"""实验室业务服务。

这里处理状态、时段、设备占用及归属；事件监听器先做通用 RBAC 授权，
随后在 BEGIN IMMEDIATE 事务中调用服务。服务不信任客户端身份或状态。
"""
import re
from datetime import datetime
from .db import get_db, now, timestamp
from .errors import DomainError, conflict
from .rbac import permissions_for, full_scope


RESERVATION_SELECT = """SELECT r.id,r.equipment_id,e.name AS equipment_name,e.code AS equipment_code,
    r.user_id,u.display_name AS applicant_name,r.start_at,r.end_at,r.purpose,r.status,
    reviewer.display_name AS reviewer_name,r.review_note,r.created_at
    FROM reservations r JOIN equipment e ON e.id=r.equipment_id JOIN users u ON u.id=r.user_id
    LEFT JOIN users reviewer ON reviewer.id=r.reviewer_id"""
LOAN_SELECT = """SELECT l.id,l.reservation_id,e.name AS equipment_name,u.display_name AS applicant_name,
    l.checkout_at,l.returned_at,l.status,l.condition_note FROM loans l
    JOIN reservations r ON r.id=l.reservation_id JOIN equipment e ON e.id=r.equipment_id JOIN users u ON u.id=r.user_id"""


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
    row = get_db().execute("SELECT * FROM equipment WHERE id=?", (integer(eid, "设备编号"),)).fetchone()
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
    row = get_db().execute("""SELECT id FROM reservations WHERE equipment_id=? AND id<>?
        AND status IN ('pending','approved','borrowed') AND start_at < ? AND end_at > ? LIMIT 1""", (eid, exclude_id, end, start)).fetchone()
    if row:
        raise conflict("该时段设备已有待审批、已批准或借用中的预约")


def save_equipment(actor, payload):
    db = get_db()
    eid = payload.get("id")
    if eid is not None:
        equipment_by_id(eid)
    values = [text_field(payload, "code", "设备编号", 40), text_field(payload, "name", "设备名称", 100), text_field(payload, "category", "设备分类", 60), text_field(payload, "location", "存放位置", 100), text_field(payload, "status", "设备状态", 30), text_field(payload, "description", "设备说明", 1000, False)]
    if values[4] not in ("available", "maintenance"):
        raise DomainError("设备状态必须为 available 或 maintenance")
    if eid is not None and values[4] == "maintenance":
        active = db.execute("SELECT 1 FROM reservations WHERE equipment_id=? AND (status='borrowed' OR (status IN ('pending','approved') AND end_at>?)) LIMIT 1", (eid, timestamp())).fetchone()
        if active:
            raise conflict("设备存在有效预约或正在借用，不能设为维护中")
    duplicate = db.execute("SELECT id FROM equipment WHERE code=? AND id<>?", (values[0], eid or 0)).fetchone()
    if duplicate:
        raise conflict("设备编号已存在")
    if eid is None:
        eid = db.execute("INSERT INTO equipment(code,name,category,location,status,description) VALUES (?,?,?,?,?,?)", values).lastrowid
    else:
        db.execute("UPDATE equipment SET code=?,name=?,category=?,location=?,status=?,description=? WHERE id=?", values + [eid])
    return dict(equipment_by_id(eid))


def submit_reservation(actor, payload):
    equipment = equipment_by_id(payload.get("equipment_id"))
    if equipment["status"] != "available":
        raise conflict("设备处于维护状态，暂不能预约")
    start = minute_datetime(payload.get("start_at"), "开始时间")
    end = minute_datetime(payload.get("end_at"), "结束时间")
    if start < now():
        raise DomainError("开始时间不能早于当前时间")
    if end <= start:
        raise DomainError("结束时间必须晚于开始时间")
    purpose = text_field(payload, "purpose", "借用用途", 1000)
    start_text, end_text = start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes")
    check_overlap(equipment["id"], start_text, end_text)
    rid = get_db().execute("INSERT INTO reservations(equipment_id,user_id,start_at,end_at,purpose,status,created_at) VALUES (?,?,?,?,?,'pending',?)", (equipment["id"], actor["id"], start_text, end_text, purpose, timestamp())).lastrowid
    return reservation_record(rid)


def review_reservation(actor, payload, approve):
    row = reservation_by_id(payload.get("id"))
    if row["user_id"] == actor["id"]:
        raise DomainError("不能审批本人提交的预约，请由另一位教师处理", 403, "SELF_REVIEW_FORBIDDEN")
    if row["status"] != "pending":
        raise conflict("只有待审批预约可以批准或驳回")
    note = text_field(payload, "note", "审批意见", 1000, required=not approve)
    if approve:
        if equipment_by_id(row["equipment_id"])["status"] != "available":
            raise conflict("设备处于维护状态，不能批准预约")
        if minute_datetime(row["end_at"], "结束时间") <= now():
            raise conflict("预约已过期，不能批准")
        check_overlap(row["equipment_id"], row["start_at"], row["end_at"], row["id"])
    get_db().execute("UPDATE reservations SET status=?,reviewer_id=?,review_note=? WHERE id=?", ("approved" if approve else "rejected", actor["id"], note, row["id"]))
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
    get_db().execute("UPDATE reservations SET status='cancelled' WHERE id=?", (row["id"],))
    return reservation_record(row["id"])


def checkout_loan(actor, payload):
    row = reservation_by_id(payload.get("reservation_id"))
    if row["status"] != "approved":
        raise conflict("只有已批准的预约可以办理借出")
    if minute_datetime(row["end_at"], "结束时间") <= now():
        raise conflict("预约已过期，不能办理借出")
    if equipment_by_id(row["equipment_id"])["status"] != "available":
        raise conflict("设备处于维护状态，不能办理借出")
    active = get_db().execute("SELECT 1 FROM loans l JOIN reservations r ON r.id=l.reservation_id WHERE r.equipment_id=? AND l.status='borrowed' LIMIT 1", (row["equipment_id"],)).fetchone()
    if active:
        raise conflict("该实体设备尚未归还，不能再次借出")
    note = text_field(payload, "condition_note", "设备状态说明", 1000, False)
    lid = get_db().execute("INSERT INTO loans(reservation_id,checkout_at,status,condition_note) VALUES (?,?,'borrowed',?)", (row["id"], timestamp(), note)).lastrowid
    get_db().execute("UPDATE reservations SET status='borrowed' WHERE id=?", (row["id"],))
    return loan_record(lid)


def return_loan(actor, payload):
    lid = integer(payload.get("id"), "借用记录编号")
    row = get_db().execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()
    if row is None:
        raise DomainError("借用记录不存在", 404, "NOT_FOUND")
    if row["status"] != "borrowed":
        raise conflict("该设备已归还，不能重复办理")
    note = text_field(payload, "condition_note", "归还检查说明", 1000)
    get_db().execute("UPDATE loans SET status='returned',returned_at=?,condition_note=? WHERE id=?", (timestamp(), note, lid))
    get_db().execute("UPDATE reservations SET status='returned' WHERE id=?", (row["reservation_id"],))
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
