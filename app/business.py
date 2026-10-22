"""实验室业务服务。

这里处理状态、时段、设备占用及归属；事件监听器先做通用 RBAC 授权，
随后在 BEGIN IMMEDIATE 事务中调用服务。服务不信任客户端身份或状态。
"""
import re
from datetime import datetime
from .db import get_db, now, timestamp
from .errors import DomainError, conflict
from .rbac import permissions_for, full_scope


EQUIPMENT_SELECT = """SELECT e.*,c.name AS category,c.name AS category_name,c.active AS category_active,
    lab.name AS laboratory_name,lab.active AS laboratory_active,
    CASE WHEN e.lifecycle_status<>'active' THEN e.lifecycle_status
         WHEN c.active=0 OR lab.active=0 THEN 'disabled'
         WHEN EXISTS(SELECT 1 FROM equipment_maintenance m WHERE m.equipment_id=e.id AND m.end_at IS NULL) THEN 'maintenance'
         ELSE 'available' END AS status,
    (SELECT id FROM equipment_maintenance m WHERE m.equipment_id=e.id AND m.end_at IS NULL) AS maintenance_id
    FROM equipment e JOIN equipment_categories c ON c.id=e.category_id JOIN laboratories lab ON lab.id=e.laboratory_id"""
RESERVATION_SELECT = """SELECT r.id,r.equipment_id,e.name AS equipment_name,e.code AS equipment_code,
    r.user_id,u.display_name AS applicant_name,r.start_at,r.end_at,r.purpose,r.status AS workflow_status,
    CASE WHEN l.id IS NULL THEN r.status WHEN l.returned_at IS NULL THEN 'borrowed' ELSE 'returned' END AS status,
    rev.id AS review_id,rev.reviewer_id,rev.decision AS review_decision,rev.reviewed_at,
    reviewer.display_name AS reviewer_name,COALESCE(rev.note,'') AS review_note,r.created_at,r.updated_at,r.cancelled_at,r.cancelled_by
    FROM reservations r JOIN equipment e ON e.id=r.equipment_id JOIN users u ON u.id=r.user_id
    LEFT JOIN reservation_reviews rev ON rev.reservation_id=r.id LEFT JOIN users reviewer ON reviewer.id=rev.reviewer_id
    LEFT JOIN loans l ON l.reservation_id=r.id"""
LOAN_SELECT = """SELECT l.*,e.id AS equipment_id,e.code AS equipment_code,e.name AS equipment_name,
    r.user_id,u.display_name AS applicant_name,checked.display_name AS checkout_by_name,
    returned.display_name AS returned_by_name,
    CASE WHEN l.returned_at IS NULL THEN 'borrowed' ELSE 'returned' END AS status,
    COALESCE(l.return_condition,l.checkout_condition) AS condition_note,
    (SELECT id FROM equipment_maintenance m WHERE m.loan_id=l.id) AS maintenance_id
    FROM loans l JOIN reservations r ON r.id=l.reservation_id JOIN equipment e ON e.id=r.equipment_id
    JOIN users u ON u.id=r.user_id LEFT JOIN users checked ON checked.id=l.checkout_by LEFT JOIN users returned ON returned.id=l.returned_by"""
MAINTENANCE_SELECT = """SELECT m.*,e.name AS equipment_name,e.code AS equipment_code,
    starter.display_name AS started_by_name,ender.display_name AS ended_by_name,
    CASE WHEN m.end_at IS NULL THEN 'open' ELSE 'closed' END AS status
    FROM equipment_maintenance m JOIN equipment e ON e.id=m.equipment_id
    LEFT JOIN users starter ON starter.id=m.started_by LEFT JOIN users ender ON ender.id=m.ended_by"""


def integer(value, label="编号"):
    if type(value) is not int or value < 1:
        raise DomainError(f"{label}必须是正整数")
    return value


def text_field(payload, key, label, maximum=200, required=True):
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise DomainError(f"{label}必须是文本")
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        raise DomainError(f"{label}不能为空且不能超过 {maximum} 字")
    if "\x00" in value:
        raise DomainError(f"{label}含无效字符")
    return value


def minute_datetime(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::00)?", value):
        raise DomainError(f"{label}需为本地日期时间，精确到分钟")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise DomainError(f"{label}不是有效日期时间") from error
    return parsed


def equipment_by_id(eid):
    row = get_db().execute(EQUIPMENT_SELECT + " WHERE e.id=?", (integer(eid, "设备编号"),)).fetchone()
    if row is None:
        raise DomainError("设备不存在", 404, "NOT_FOUND")
    return row


def reservation_by_id(rid):
    row = get_db().execute("SELECT * FROM reservations WHERE id=?", (integer(rid, "预约编号"),)).fetchone()
    if row is None:
        raise DomainError("预约不存在", 404, "NOT_FOUND")
    return row


def reservation_record(rid):
    return dict(get_db().execute(RESERVATION_SELECT + " WHERE r.id=?", (rid,)).fetchone())


def loan_record(lid):
    return dict(get_db().execute(LOAN_SELECT + " WHERE l.id=?", (lid,)).fetchone())


def reservations_for(user_id):
    if full_scope(user_id):
        rows = get_db().execute(RESERVATION_SELECT + " ORDER BY r.id DESC")
    else:
        rows = get_db().execute(RESERVATION_SELECT + " WHERE r.user_id=? ORDER BY r.id DESC", (user_id,))
    return [dict(r) for r in rows]


def loans_for(user_id):
    if full_scope(user_id):
        rows = get_db().execute(LOAN_SELECT + " ORDER BY l.id DESC")
    else:
        rows = get_db().execute(LOAN_SELECT + " WHERE r.user_id=? ORDER BY l.id DESC", (user_id,))
    return [dict(r) for r in rows]


def check_overlap(eid, start, end, exclude_id=0):
    # 半开区间 [start,end)：前一条结束时刻等于后一条开始时刻允许预约。
    row = get_db().execute("""SELECT r.id FROM reservations r WHERE r.equipment_id=? AND r.id<>?
        AND r.status IN ('pending','approved') AND r.start_at < ? AND r.end_at > ?
        AND NOT EXISTS(SELECT 1 FROM loans l WHERE l.reservation_id=r.id AND l.returned_at IS NOT NULL)
        LIMIT 1""", (eid, exclude_id, end, start)).fetchone()
    if row:
        raise conflict("该时段设备已有待审批、已批准或借用中的预约")


def _has_live_business(filter_sql, params):
    """filter_sql 只来自下方固定代码，不接收任何客户端 SQL。"""
    return get_db().execute("""SELECT 1 FROM reservations r JOIN equipment e ON e.id=r.equipment_id
        WHERE (""" + filter_sql + """) AND (
          (r.status IN ('pending','approved') AND r.end_at>? AND
           NOT EXISTS(SELECT 1 FROM loans closed WHERE closed.reservation_id=r.id AND closed.returned_at IS NOT NULL))
          OR EXISTS(SELECT 1 FROM loans active WHERE active.reservation_id=r.id AND active.returned_at IS NULL)) LIMIT 1""", (*params, timestamp())).fetchone() is not None


def _catalog_record(table, identity, label):
    # 表名由调用点固定，不从请求体取值。
    row = get_db().execute(f"SELECT * FROM {table} WHERE id=?", (integer(identity, label + "编号"),)).fetchone()
    if row is None:
        raise DomainError(label + "不存在", 404, "NOT_FOUND")
    return row


def equipment_metadata():
    db = get_db()
    laboratories = [dict(r) for r in db.execute("SELECT lab.*,u.display_name AS manager_name FROM laboratories lab LEFT JOIN users u ON u.id=lab.manager_id ORDER BY lab.id")]
    categories = [dict(r) for r in db.execute("SELECT * FROM equipment_categories ORDER BY id")]
    for row in laboratories + categories:
        row["active"] = bool(row["active"])
    managers = [dict(r) for r in db.execute("SELECT id,username,display_name FROM users WHERE active=1 ORDER BY id")]
    return {"laboratories": laboratories, "categories": categories, "managers": managers}


def save_laboratory(actor, payload):
    db = get_db()
    identity = payload.get("id")
    if identity is not None:
        _catalog_record("laboratories", identity, "实验室")
    manager_id = payload.get("manager_id")
    if manager_id is not None:
        integer(manager_id, "负责人编号")
        if not db.execute("SELECT 1 FROM users WHERE id=? AND active=1", (manager_id,)).fetchone():
            raise DomainError("实验室负责人不存在或已停用")
    values = [text_field(payload, "code", "实验室编号", 40), text_field(payload, "name", "实验室名称", 100), text_field(payload, "location", "实验室位置", 150), manager_id, text_field(payload, "description", "实验室说明", 1000, False)]
    if db.execute("SELECT 1 FROM laboratories WHERE code=? AND id<>?", (values[0], identity or 0)).fetchone():
        raise conflict("实验室编号已存在")
    if identity is None:
        identity = db.execute("INSERT INTO laboratories(code,name,location,manager_id,description) VALUES (?,?,?,?,?)", values).lastrowid
    else:
        db.execute("UPDATE laboratories SET code=?,name=?,location=?,manager_id=?,description=? WHERE id=?", values + [identity])
    return next(r for r in equipment_metadata()["laboratories"] if r["id"] == identity)


def save_category(actor, payload):
    db = get_db()
    identity = payload.get("id")
    if identity is not None:
        _catalog_record("equipment_categories", identity, "分类")
    values = [text_field(payload, "code", "分类编号", 40), text_field(payload, "name", "分类名称", 80), text_field(payload, "description", "分类说明", 1000, False)]
    if db.execute("SELECT 1 FROM equipment_categories WHERE (code=? OR name=?) AND id<>?", (values[0], values[1], identity or 0)).fetchone():
        raise conflict("分类编号或名称已存在")
    if identity is None:
        identity = db.execute("INSERT INTO equipment_categories(code,name,description) VALUES (?,?,?)", values).lastrowid
    else:
        db.execute("UPDATE equipment_categories SET code=?,name=?,description=? WHERE id=?", values + [identity])
    row = dict(_catalog_record("equipment_categories", identity, "分类"))
    row["active"] = bool(row["active"])
    return row


def _set_catalog_active(table, column, label, payload):
    identity = integer(payload.get("id"), label + "编号")
    _catalog_record(table, identity, label)
    active = payload.get("active")
    if type(active) is not bool:
        raise DomainError("启用状态必须是布尔值")
    if not active and _has_live_business(f"e.{column}=?", (identity,)):
        raise conflict(label + "仍有关联有效预约或未归还设备，请先处理业务")
    get_db().execute(f"UPDATE {table} SET active=? WHERE id=?", (int(active), identity))
    row = dict(_catalog_record(table, identity, label))
    row["active"] = active
    return row


def set_laboratory_active(actor, payload):
    return _set_catalog_active("laboratories", "laboratory_id", "实验室", payload)


def set_category_active(actor, payload):
    return _set_catalog_active("equipment_categories", "category_id", "分类", payload)


def save_equipment(actor, payload):
    db = get_db()
    eid = payload.get("id")
    original = equipment_by_id(eid) if eid is not None else None
    category_id = payload.get("category_id")
    if category_id is None and isinstance(payload.get("category"), str):
        category = db.execute("SELECT id FROM equipment_categories WHERE name=?", (payload["category"].strip(),)).fetchone()
        if category:
            category_id = category[0]
    laboratory_id = payload.get("laboratory_id", original["laboratory_id"] if original else None)
    if laboratory_id is None:  # 旧版页面没有实验室字段，兼容首个启用实验室。
        laboratory = db.execute("SELECT id FROM laboratories WHERE active=1 ORDER BY id LIMIT 1").fetchone()
        laboratory_id = laboratory[0] if laboratory else None
    category = _catalog_record("equipment_categories", category_id, "分类")
    laboratory = _catalog_record("laboratories", laboratory_id, "实验室")
    if not category["active"] or not laboratory["active"]:
        raise conflict("设备所属分类和实验室必须启用")
    legacy_status = payload.get("status")
    lifecycle = payload.get("lifecycle_status", "active" if legacy_status in (None, "available", "maintenance") else legacy_status)
    if lifecycle not in ("active", "disabled", "retired"):
        raise DomainError("设备生命周期必须为 active、disabled 或 retired")
    if original and original["lifecycle_status"] == "retired" and lifecycle != "retired":
        raise conflict("已报废设备不能重新启用，请为新实体建立独立资产编号")
    if original and lifecycle != "active" and _has_live_business("e.id=?", (eid,)):
        raise conflict("设备仍有有效预约或尚未归还，不能停用或报废")
    code = text_field(payload, "code", "资产编号", 40)
    if db.execute("SELECT 1 FROM equipment WHERE code=? AND id<>?", (code, eid or 0)).fetchone():
        raise conflict("资产编号已存在，每台实体设备必须使用独立编号")
    values = [code, text_field(payload, "name", "设备名称", 100), text_field(payload, "model", "设备型号", 120, False), category_id, laboratory_id, text_field(payload, "location", "存放位置", 150), lifecycle, text_field(payload, "description", "设备说明", 1000, False)]
    if eid is None:
        eid = db.execute("INSERT INTO equipment(code,name,model,category_id,laboratory_id,location,lifecycle_status,description,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", values + [actor["id"], timestamp(), timestamp()]).lastrowid
    else:
        db.execute("UPDATE equipment SET code=?,name=?,model=?,category_id=?,laboratory_id=?,location=?,lifecycle_status=?,description=?,updated_at=? WHERE id=?", values + [timestamp(), eid])
    if legacy_status == "maintenance" and equipment_by_id(eid)["maintenance_id"] is None:
        start_maintenance(actor, {"equipment_id": eid, "reason": payload.get("description") or "由兼容设备表单登记维护"})
    return dict(equipment_by_id(eid))


def maintenance_rows():
    return [dict(r) for r in get_db().execute(MAINTENANCE_SELECT + " ORDER BY m.id DESC")]


def maintenance_record(identity):
    row = get_db().execute(MAINTENANCE_SELECT + " WHERE m.id=?", (integer(identity, "维护编号"),)).fetchone()
    if row is None:
        raise DomainError("维护记录不存在", 404, "NOT_FOUND")
    return dict(row)


def start_maintenance(actor, payload):
    equipment = equipment_by_id(payload.get("equipment_id"))
    if equipment["status"] != "available":
        raise conflict("仅可用设备可以开始维护，请先检查设备及所属实验室、分类状态")
    if _has_live_business("e.id=?", (equipment["id"],)):
        raise conflict("设备有有效预约或尚未归还，不能开始维护")
    reason = text_field(payload, "reason", "维护原因", 1000)
    identity = get_db().execute("INSERT INTO equipment_maintenance(equipment_id,started_by,start_at,reason) VALUES (?,?,?,?)", (equipment["id"], actor["id"], timestamp(), reason)).lastrowid
    return maintenance_record(identity)


def end_maintenance(actor, payload):
    row = maintenance_record(payload.get("id"))
    if row["end_at"] is not None:
        raise conflict("维护已经结束，不能重复完成")
    result = text_field(payload, "result", "维护结果", 1000)
    get_db().execute("UPDATE equipment_maintenance SET ended_by=?,end_at=?,result=? WHERE id=?", (actor["id"], timestamp(), result, row["id"]))
    return maintenance_record(row["id"])


def submit_reservation(actor, payload):
    equipment = equipment_by_id(payload.get("equipment_id"))
    if equipment["status"] != "available":
        raise conflict("设备正在维护、停用或已报废，或所属实验室/分类已停用，暂不能预约")
    start = minute_datetime(payload.get("start_at"), "开始时间")
    end = minute_datetime(payload.get("end_at"), "结束时间")
    if start < now():
        raise DomainError("开始时间不能早于当前时间")
    if end <= start:
        raise DomainError("结束时间必须晚于开始时间")
    purpose = text_field(payload, "purpose", "借用用途", 1000)
    start_text, end_text = start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes")
    check_overlap(equipment["id"], start_text, end_text)
    rid = get_db().execute("INSERT INTO reservations(equipment_id,user_id,start_at,end_at,purpose,status,created_at,updated_at) VALUES (?,?,?,?,?,'pending',?,?)", (equipment["id"], actor["id"], start_text, end_text, purpose, timestamp(), timestamp())).lastrowid
    return reservation_record(rid)


def review_reservation(actor, payload, approve):
    row = reservation_by_id(payload.get("id"))
    if row["user_id"] == actor["id"]:
        raise DomainError("不能审批本人提交的预约，请由另一位教师处理", 403, "SELF_REVIEW_FORBIDDEN")
    if row["status"] != "pending":
        raise conflict("只有待审批预约可以批准或驳回")
    if get_db().execute("SELECT 1 FROM reservation_reviews WHERE reservation_id=?", (row["id"],)).fetchone():
        raise conflict("该申请已产生终审记录，驳回后应重新提交新的申请")
    note = text_field(payload, "note", "审批意见", 1000, required=not approve)
    if approve:
        if equipment_by_id(row["equipment_id"])["status"] != "available":
            raise conflict("设备或所属实验室、分类不可用，不能批准预约")
        if minute_datetime(row["end_at"], "结束时间") <= now():
            raise conflict("预约已过期，不能批准")
        check_overlap(row["equipment_id"], row["start_at"], row["end_at"], row["id"])
    decision = "approved" if approve else "rejected"
    get_db().execute("INSERT INTO reservation_reviews(reservation_id,reviewer_id,decision,note,reviewed_at) VALUES (?,?,?,?,?)", (row["id"], actor["id"], decision, note, timestamp()))
    get_db().execute("UPDATE reservations SET status=?,updated_at=? WHERE id=?", (decision, timestamp(), row["id"]))
    return reservation_record(row["id"])


def approve_reservation(actor, payload):
    return review_reservation(actor, payload, True)


def reject_reservation(actor, payload):
    return review_reservation(actor, payload, False)


def cancel_reservation(actor, payload):
    row = reservation_by_id(payload.get("id"))
    if row["user_id"] != actor["id"] and "reservation:manage" not in permissions_for(actor["id"]):
        raise DomainError("只能取消本人的预约", 403, "OWNERSHIP_FORBIDDEN")
    if row["status"] not in ("pending", "approved"):
        raise conflict("只有待审批或已批准的预约可以取消")
    if get_db().execute("SELECT 1 FROM loans WHERE reservation_id=?", (row["id"],)).fetchone():
        raise conflict("预约已产生借还记录，不能取消")
    get_db().execute("UPDATE reservations SET status='cancelled',cancelled_at=?,cancelled_by=?,updated_at=? WHERE id=?", (timestamp(), actor["id"], timestamp(), row["id"]))
    return reservation_record(row["id"])


def checkout_loan(actor, payload):
    row = reservation_by_id(payload.get("reservation_id"))
    if row["status"] != "approved":
        raise conflict("只有已批准的预约可以办理借出")
    if get_db().execute("SELECT 1 FROM loans WHERE reservation_id=?", (row["id"],)).fetchone():
        raise conflict("该预约已办理过借出，不能重复领用；再次借用请重新预约")
    if minute_datetime(row["end_at"], "结束时间") <= now():
        raise conflict("预约已过期，不能办理借出")
    if equipment_by_id(row["equipment_id"])["status"] != "available":
        raise conflict("设备或所属实验室、分类不可用，不能办理借出")
    active = get_db().execute("SELECT 1 FROM loans l JOIN reservations r ON r.id=l.reservation_id WHERE r.equipment_id=? AND l.returned_at IS NULL LIMIT 1", (row["equipment_id"],)).fetchone()
    if active:
        raise conflict("该实体设备尚未归还，不能再次借出")
    key = "checkout_condition" if "checkout_condition" in payload else "condition_note"
    note = text_field(payload, key, "借出检查说明", 1000, False)
    lid = get_db().execute("INSERT INTO loans(reservation_id,checkout_by,checkout_at,checkout_condition) VALUES (?,?,?,?)", (row["id"], actor["id"], timestamp(), note)).lastrowid
    return loan_record(lid)


def return_loan(actor, payload):
    lid = integer(payload.get("id"), "借用记录编号")
    row = get_db().execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()
    if row is None:
        raise DomainError("借用记录不存在", 404, "NOT_FOUND")
    if row["returned_at"] is not None:
        raise conflict("该设备已归还，不能重复办理")
    key = "return_condition" if "return_condition" in payload else "condition_note"
    note = text_field(payload, key, "归还检查说明", 1000)
    result = payload.get("acceptance_result", "passed")
    if result not in ("passed", "damaged"):
        raise DomainError("归还验收结果必须为 passed 或 damaged")
    get_db().execute("UPDATE loans SET returned_by=?,returned_at=?,return_condition=?,acceptance_result=? WHERE id=?", (actor["id"], timestamp(), note, result, lid))
    if result == "damaged":
        # 异常验收优先保护实体设备。自动维护不因其他未来预约而跳过；相关预约
        # 保持原申请历史，但在恢复可用前不能批准/借出。手工维护仍检查预约冲突。
        reservation = reservation_by_id(row["reservation_id"])
        open_record = get_db().execute("SELECT id FROM equipment_maintenance WHERE equipment_id=? AND end_at IS NULL", (reservation["equipment_id"],)).fetchone()
        if open_record is None:
            get_db().execute("INSERT INTO equipment_maintenance(equipment_id,loan_id,started_by,start_at,reason) VALUES (?,?,?,?,?)", (reservation["equipment_id"], lid, actor["id"], timestamp(), "归还验收异常：" + note))
    return loan_record(lid)


def save_role_permissions(actor, payload):
    db = get_db()
    role_id = integer(payload.get("role_id"), "角色编号")
    role = db.execute("SELECT * FROM roles WHERE id=?", (role_id,)).fetchone()
    if role is None:
        raise DomainError("角色不存在")
    keys = payload.get("permissions")
    if not isinstance(keys, list) or len(keys) > 100 or any(not isinstance(k, str) for k in keys):
        raise DomainError("权限必须为受支持权限名称的数组")
    if len(set(keys)) != len(keys):
        raise DomainError("权限列表不能重复")
    supported = {f"{r['object_code']}:{r['operation_code']}": (r["operation_id"], r["object_id"]) for r in db.execute("SELECT p.*,co.code AS object_code,o.code AS operation_code FROM permissions p JOIN control_objects co ON co.id=p.object_id JOIN operations o ON o.id=p.operation_id")}
    if any(key not in supported for key in keys):
        raise DomainError("包含未定义的操作与控制对象组合")
    protected = {"rbac:view", "rbac:manage", "page.rbac:view", "menu.rbac:view"}
    if role["code"] == "admin" and not protected.issubset(keys):
        raise DomainError("管理员保护：必须保留权限配置页面、菜单的查看权及 rbac:view、rbac:manage，避免管理入口被锁死", 409, "ADMIN_PROTECTED")
    db.execute("DELETE FROM role_permissions WHERE role_id=?", (role_id,))
    db.executemany("INSERT INTO role_permissions(role_id,operation_id,object_id) VALUES (?,?,?)", [(role_id, *supported[key]) for key in keys])
    return {"message": "角色权限已保存，现有登录会话立即生效"}


def assign_roles(actor, payload):
    db = get_db()
    uid = integer(payload.get("user_id"), "用户编号")
    if not db.execute("SELECT 1 FROM users WHERE id=? AND active=1", (uid,)).fetchone():
        raise DomainError("用户不存在或已停用")
    role_ids = payload.get("role_ids")
    if not isinstance(role_ids, list) or not role_ids or len(role_ids) > 100:
        raise DomainError("每个用户至少应有一个角色")
    for rid in role_ids:
        integer(rid, "角色编号")
    if len(set(role_ids)) != len(role_ids):
        raise DomainError("角色编号不能重复")
    known = {r[0] for r in db.execute("SELECT id FROM roles")}
    if not set(role_ids).issubset(known):
        raise DomainError("包含不存在的角色")
    admin_id = db.execute("SELECT id FROM roles WHERE code='admin'").fetchone()[0]
    if admin_id not in role_ids:
        remaining = db.execute("SELECT 1 FROM user_roles ur JOIN users u ON u.id=ur.user_id WHERE ur.role_id=? AND u.active=1 AND u.id<>? LIMIT 1", (admin_id, uid)).fetchone()
        if remaining is None:
            raise DomainError("管理员保护：必须保留至少一个有效系统管理员账号", 409, "ADMIN_PROTECTED")
    db.execute("DELETE FROM user_roles WHERE user_id=?", (uid,))
    db.executemany("INSERT INTO user_roles(user_id,role_id) VALUES (?,?)", [(uid, rid) for rid in role_ids])
    return {"message": "用户角色已更新，当前会话立即按新角色授权"}
