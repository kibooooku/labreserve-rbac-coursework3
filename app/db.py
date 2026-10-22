"""SQLite 持久层与可重复演示数据。

RBAC 核心恰为七张表。权限以 (operation_id, object_id) 联合主键标识，
角色权限外键直接引用该联合主键，禁止不存在的“操作×对象”授权。
"""
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
from flask import current_app, g
from werkzeug.security import generate_password_hash


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
 display_name TEXT NOT NULL, password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE TABLE IF NOT EXISTS roles (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS user_roles (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
 PRIMARY KEY(user_id,role_id)
);
CREATE TABLE IF NOT EXISTS operations (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS control_objects (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('page','menu','business'))
);
CREATE TABLE IF NOT EXISTS permissions (
 operation_id INTEGER NOT NULL REFERENCES operations(id),
 object_id INTEGER NOT NULL REFERENCES control_objects(id),
 PRIMARY KEY(operation_id,object_id)
);
CREATE TABLE IF NOT EXISTS role_permissions (
 role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
 operation_id INTEGER NOT NULL, object_id INTEGER NOT NULL,
 PRIMARY KEY(role_id,operation_id,object_id),
 FOREIGN KEY(operation_id,object_id) REFERENCES permissions(operation_id,object_id)
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 csrf_token TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS laboratories (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 location TEXT NOT NULL, manager_id INTEGER REFERENCES users(id),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS equipment_categories (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL UNIQUE,
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS equipment (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 model TEXT NOT NULL DEFAULT '', category_id INTEGER NOT NULL REFERENCES equipment_categories(id),
 laboratory_id INTEGER NOT NULL REFERENCES laboratories(id), location TEXT NOT NULL,
 lifecycle_status TEXT NOT NULL DEFAULT 'active' CHECK(lifecycle_status IN ('active','disabled','retired')),
 description TEXT NOT NULL DEFAULT '', created_by INTEGER REFERENCES users(id), created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS reservations (
 id INTEGER PRIMARY KEY, equipment_id INTEGER NOT NULL REFERENCES equipment(id),
 user_id INTEGER NOT NULL REFERENCES users(id), start_at TEXT NOT NULL, end_at TEXT NOT NULL,
 purpose TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','cancelled')),
 created_at TEXT NOT NULL, updated_at TEXT, cancelled_at TEXT, cancelled_by INTEGER REFERENCES users(id),
 CHECK(end_at > start_at), CHECK((status='cancelled') OR (cancelled_at IS NULL AND cancelled_by IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_reservation_overlap ON reservations(equipment_id,status,start_at,end_at);
CREATE TABLE IF NOT EXISTS reservation_reviews (
 id INTEGER PRIMARY KEY, reservation_id INTEGER NOT NULL UNIQUE REFERENCES reservations(id),
 reviewer_id INTEGER REFERENCES users(id), decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')),
 note TEXT NOT NULL DEFAULT '', reviewed_at TEXT
);
CREATE TABLE IF NOT EXISTS loans (
 id INTEGER PRIMARY KEY, reservation_id INTEGER NOT NULL UNIQUE REFERENCES reservations(id),
 checkout_by INTEGER REFERENCES users(id), checkout_at TEXT NOT NULL, checkout_condition TEXT NOT NULL DEFAULT '',
 returned_by INTEGER REFERENCES users(id), returned_at TEXT, return_condition TEXT,
 acceptance_result TEXT CHECK(acceptance_result IN ('passed','damaged','unknown')),
 CHECK(returned_at IS NULL OR returned_at >= checkout_at),
 CHECK((returned_at IS NULL AND returned_by IS NULL AND return_condition IS NULL AND acceptance_result IS NULL)
    OR (returned_at IS NOT NULL AND return_condition IS NOT NULL AND acceptance_result IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS equipment_maintenance (
 id INTEGER PRIMARY KEY, equipment_id INTEGER NOT NULL REFERENCES equipment(id),
 loan_id INTEGER UNIQUE REFERENCES loans(id), started_by INTEGER REFERENCES users(id), start_at TEXT NOT NULL,
 reason TEXT NOT NULL, ended_by INTEGER REFERENCES users(id), end_at TEXT, result TEXT,
 CHECK(end_at IS NULL OR end_at >= start_at),
 CHECK((end_at IS NULL AND ended_by IS NULL AND result IS NULL) OR (end_at IS NOT NULL AND result IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_open_maintenance ON equipment_maintenance(equipment_id) WHERE end_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_maintenance_equipment_time ON equipment_maintenance(equipment_id,start_at,end_at);
CREATE TABLE IF NOT EXISTS event_audit (
 id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES users(id), actor_name TEXT NOT NULL,
 source_id TEXT NOT NULL, event_type TEXT NOT NULL, object_code TEXT NOT NULL,
 operation_code TEXT NOT NULL, target_id TEXT, outcome TEXT NOT NULL,
 detail TEXT NOT NULL, created_at TEXT NOT NULL
);
"""

PAGE_NAMES = {"dashboard": "工作台", "equipment": "设备目录", "reservations": "预约管理", "loans": "借还管理", "rbac": "权限配置", "audit": "事件审计"}
BUSINESS_PAIRS = {
    "equipment": ["view", "update"],
    "reservation": ["view", "create", "approve", "reject", "cancel", "manage", "export"],
    "loan": ["view", "checkout", "return"],
    "rbac": ["view", "manage"], "audit": ["view"],
}
OPERATION_NAMES = {"view": "查看", "update": "维护", "create": "申请", "approve": "批准", "reject": "驳回", "cancel": "取消", "manage": "管理", "export": "导出", "checkout": "借出", "return": "归还"}
OBJECT_NAMES = {"equipment": "设备", "reservation": "预约", "loan": "借还", "rbac": "角色权限", "audit": "事件审计"}


def now():
    clock = current_app.config.get("NOW")
    value = clock() if callable(clock) else clock
    if value is None:
        value = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=None)


def timestamp(value=None):
    return (value or now()).isoformat(timespec="seconds")


def get_db():
    if "db" not in g:
        connection = sqlite3.connect(current_app.config["DATABASE"], timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        g.db = connection
    return g.db


def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def initialize_database(reset=False):
    db = get_db()
    if reset:
        # 显式 --reset 专用；外键按依赖顺序删除，绝不删除任意文件。
        for name in ("event_audit", "equipment_maintenance", "loans", "reservation_reviews", "reservations", "equipment", "equipment_categories", "laboratories", "sessions", "role_permissions", "permissions", "control_objects", "operations", "user_roles", "roles", "users"):
            db.execute(f"DROP TABLE IF EXISTS {name}")
    columns = {row[1] for row in db.execute("PRAGMA table_info(equipment)")}
    if columns and "lifecycle_status" not in columns:
        migrate_v1_database(db)
    db.executescript(SCHEMA)
    # 兼容本次升级过程中已生成的16表库，不清库、不回灌演示数据。
    equipment_columns = {row[1] for row in db.execute("PRAGMA table_info(equipment)")}
    for name, declaration in (("created_by", "INTEGER REFERENCES users(id)"), ("created_at", "TEXT"), ("updated_at", "TEXT")):
        if name not in equipment_columns:
            db.execute(f"ALTER TABLE equipment ADD COLUMN {name} {declaration}")
    if "updated_at" not in {row[1] for row in db.execute("PRAGMA table_info(reservations)")}:
        db.execute("ALTER TABLE reservations ADD COLUMN updated_at TEXT")
    db.execute("PRAGMA user_version=2")
    if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        _seed(db)
        db.commit()
    except Exception:
        db.rollback()
        raise


def _execute_schema(db):
    """逐条执行DDL，避免 executescript 隐式 COMMIT 打断迁移事务。"""
    for statement in SCHEMA.split(";"):
        if statement.strip():
            db.execute(statement)


def migrate_v1_database(db):
    """非破坏迁移：在独占写事务里重建三张业务表，保留所有主键和历史。

    SQLite backup API 先保存旧库快照（instance/backups 不进入提交包）。
    七张 RBAC 表、会话、审计原样保留。旧版未记录的人员/审核时间保持 NULL，
    已归还记录的旧 condition_note 是归还说明，不能伪造成借出检查。
    """
    database_path = Path(current_app.config["DATABASE"])
    backup_dir = database_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{database_path.stem}-schema-v1-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.sqlite3"
    db.execute("PRAGMA foreign_keys=OFF")
    db.execute("BEGIN IMMEDIATE")
    try:
        # 另一连接可在 RESERVED 写锁下读取一致快照，避免对活跃写事务自身 backup。
        with sqlite3.connect(database_path) as source, sqlite3.connect(backup_path) as backup:
            source.backup(backup)
        devices = [dict(row) for row in db.execute("SELECT * FROM equipment ORDER BY id")]
        requests = [dict(row) for row in db.execute("SELECT * FROM reservations ORDER BY id")]
        old_loans = [dict(row) for row in db.execute("SELECT * FROM loans ORDER BY id")]
        for table in ("loans", "reservations", "equipment"):
            db.execute(f"DROP TABLE {table}")
        _execute_schema(db)
        categories, laboratories = {}, {}
        for device in devices:
            category = device["category"]
            if category not in categories:
                categories[category] = db.execute("INSERT INTO equipment_categories(code,name,description) VALUES (?,?,?)", (f"CAT-M{len(categories)+1:03d}", category, "由旧版设备分类迁移")).lastrowid
            location = device["location"]
            if location not in laboratories:
                laboratories[location] = db.execute("INSERT INTO laboratories(code,name,location,description) VALUES (?,?,?,?)", (f"LAB-M{len(laboratories)+1:03d}", location or "未命名实验室", location, "由旧版设备位置迁移；可由管理员补充负责人和实验室名称")).lastrowid
            db.execute("INSERT INTO equipment(id,code,name,model,category_id,laboratory_id,location,lifecycle_status,description) VALUES (?,?,?,'',?,?,?,'active',?)", (device["id"], device["code"], device["name"], categories[category], laboratories[location], location, device["description"]))
        for row in requests:
            status = "approved" if row["status"] in ("borrowed", "returned") else row["status"]
            db.execute("INSERT INTO reservations(id,equipment_id,user_id,start_at,end_at,purpose,status,created_at) VALUES (?,?,?,?,?,?,?,?)", (row["id"], row["equipment_id"], row["user_id"], row["start_at"], row["end_at"], row["purpose"], status, row["created_at"]))
            if status in ("approved", "rejected") or row["reviewer_id"] is not None:
                decision = "rejected" if status == "rejected" else "approved"
                db.execute("INSERT INTO reservation_reviews(reservation_id,reviewer_id,decision,note,reviewed_at) VALUES (?,?,?,?,NULL)", (row["id"], row["reviewer_id"], decision, row["review_note"]))
        for row in old_loans:
            returned = row["status"] == "returned"
            db.execute("INSERT INTO loans(id,reservation_id,checkout_by,checkout_at,checkout_condition,returned_by,returned_at,return_condition,acceptance_result) VALUES (?,?,NULL,?,?,NULL,?,?,?)", (row["id"], row["reservation_id"], row["checkout_at"], "" if returned else row["condition_note"], row["returned_at"], row["condition_note"] if returned else None, "unknown" if returned else None))
        for device in devices:
            if device["status"] == "maintenance":
                db.execute("INSERT INTO equipment_maintenance(equipment_id,start_at,reason) VALUES (?,?,?)", (device["id"], timestamp(), "旧版维护状态迁移；原系统未记录开始时间和经办人，此处时间为迁移登记时间"))
        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"迁移后外键校验失败，已保留旧库备份：{backup_path.name}")
        db.execute("PRAGMA user_version=2")
        db.commit()
        current_app.logger.info("数据库已从12表迁移到16表，旧库备份：%s", backup_path)
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA foreign_keys=ON")


def _seed(db):
    for code, name in OPERATION_NAMES.items():
        db.execute("INSERT INTO operations(code,name) VALUES (?,?)", (code, name))
    for kind in ("page", "menu"):
        for code, name in PAGE_NAMES.items():
            db.execute("INSERT INTO control_objects(code,name,kind) VALUES (?,?,?)", (f"{kind}.{code}", f"{name}{'页面' if kind == 'page' else '菜单'}", kind))
    for code, name in OBJECT_NAMES.items():
        db.execute("INSERT INTO control_objects(code,name,kind) VALUES (?,?,'business')", (code, name))
    operation_ids = {row["code"]: row["id"] for row in db.execute("SELECT * FROM operations")}
    object_ids = {row["code"]: row["id"] for row in db.execute("SELECT * FROM control_objects")}
    supported = {f"{kind}.{page}:view" for kind in ("page", "menu") for page in PAGE_NAMES}
    supported |= {f"{obj}:{op}" for obj, ops in BUSINESS_PAIRS.items() for op in ops}
    for key in sorted(supported):
        obj, op = key.split(":")
        db.execute("INSERT INTO permissions VALUES (?,?)", (operation_ids[op], object_ids[obj]))
    base = {f"{kind}.{page}:view" for kind in ("page", "menu") for page in ("dashboard", "equipment", "reservations", "loans")}
    base |= {"equipment:view", "reservation:view", "reservation:create", "reservation:cancel", "loan:view"}
    sets = {
        "student": base,
        "teacher": base | {"reservation:approve", "reservation:reject"},
        "keeper": base | {"equipment:update", "loan:checkout", "loan:return"},
        "admin": supported,
        "auditor": {p for p in supported if p.endswith(":view")} | {"reservation:export"},
    }
    roles = [("student", "学生"), ("teacher", "指导教师"), ("keeper", "设备管理员"), ("admin", "系统管理员"), ("auditor", "审计员")]
    for code, name in roles:
        role_id = db.execute("INSERT INTO roles(code,name) VALUES (?,?)", (code, name)).lastrowid
        for key in sorted(sets[code]):
            obj, op = key.split(":")
            db.execute("INSERT INTO role_permissions VALUES (?,?,?)", (role_id, operation_ids[op], object_ids[obj]))
    role_ids = {r["code"]: r["id"] for r in db.execute("SELECT * FROM roles")}
    accounts = [("student", "张同学", ["student"]), ("teacher", "李老师", ["teacher"]), ("keeper", "王老师", ["keeper"]), ("admin", "系统管理员", ["admin"]), ("auditor", "审计员", ["auditor"]), ("multi", "陈同学（兼任助教）", ["student", "teacher"])]
    for username, name, user_roles in accounts:
        uid = db.execute("INSERT INTO users(username,display_name,password_hash) VALUES (?,?,?)", (username, name, generate_password_hash("Lab@2026!"))).lastrowid
        db.executemany("INSERT INTO user_roles VALUES (?,?)", [(uid, role_ids[role]) for role in user_roles])
    categories = [("OPT", "光学仪器"), ("ELE", "电子测量"), ("ANA", "分析仪器"), ("DEV", "开发平台"), ("DET", "检测设备")]
    for code, name in categories:
        db.execute("INSERT INTO equipment_categories(code,name,description) VALUES (?,?,?)", (code, name, f"{name}设备分类"))
    db.execute("INSERT INTO equipment_categories(code,name,active,description) VALUES ('OLD','旧式设备',0,'已停用分类，不接受新增设备和预约')")
    lab_locations = ["实验楼 A201", "实验楼 B203", "实验楼 A102", "创新工坊 C305", "实验楼 A203", "实验楼 B101", "创新工坊 C301"]
    for index, location in enumerate(lab_locations, 1):
        db.execute("INSERT INTO laboratories(code,name,location,manager_id,description) VALUES (?,?,?,?,?)", (f"LAB-{index:03d}", location + "实验室", location, 3, "课程设备存放与借还管理实验室"))
    db.execute("INSERT INTO laboratories(code,name,location,manager_id,active,description) VALUES ('LAB-OLD','旧实验室','实验楼 D101',3,0,'改造期间停止使用')")
    devices = [
        ("EQ-001", "奥林巴斯生物显微镜", "CX23", 1, 1, "光学设备柜 A-01", "适用于细胞形态观察；借用前请确认镜头洁净。"),
        ("EQ-002", "数字示波器", "DS1102Z-E", 2, 2, "电子测量台 01", "100 MHz 双通道数字示波器，配两根探头。"),
        ("EQ-003", "高精度电子天平", "BSA224S", 3, 3, "防震实验台 01", "量程 220 g，读数精度 0.1 mg。"),
        ("EQ-004", "树莓派开发套件", "Raspberry Pi 5", 4, 4, "开发套件柜 C-02", "含开发板、电源及传感器套件。"),
        ("EQ-005", "便携式光谱仪", "USB2000+", 1, 5, "光谱仪器柜 A-03", "定期标定中，维护结束后恢复预约。"),
        ("EQ-006", "热成像仪", "T120", 5, 6, "检测设备柜 B-01", "用于非接触温度测量，附充电电池。"),
        ("EQ-007", "函数信号发生器", "DG1022Z", 2, 2, "电子测量台 02", "支持正弦波、方波及任意波形。"),
        ("EQ-008", "三维扫描仪", "EinScan-SE", 5, 7, "扫描工作台 C-01", "配套转台及标定板，仅限室内使用。"),
        ("EQ-009", "奥林巴斯生物显微镜（二号机）", "CX23", 1, 1, "光学设备柜 A-02", "与一号机同型号，资产编号独立，分别预约。"),
    ]
    db.executemany("INSERT INTO equipment(code,name,model,category_id,laboratory_id,location,description) VALUES (?,?,?,?,?,?,?)", devices)
    db.execute("UPDATE equipment SET created_by=3,created_at=?,updated_at=?", (timestamp(now() - timedelta(days=20)), timestamp(now() - timedelta(days=9))))
    db.execute("INSERT INTO equipment_maintenance(equipment_id,started_by,start_at,reason) VALUES (5,3,?,'定期光谱标定')", (timestamp(now() - timedelta(days=1)),))
    db.execute("INSERT INTO equipment_maintenance(equipment_id,started_by,start_at,reason,ended_by,end_at,result) VALUES (7,3,?,'信号输出校准',3,?,'输出误差在允许范围内，设备恢复使用')", (timestamp(now() - timedelta(days=8)), timestamp(now() - timedelta(days=7))))
    anchor = (now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    samples = [(1, 1, 0, "pending", "细胞观察课程实验", None, ""), (2, 1, 2, "approved", "电子电路波形测量", 2, "已核验课程实验需求，请按时归还。"), (3, 6, 1, "pending", "材料质量测量与误差分析", None, ""), (4, 1, -4, "returned", "物联网温湿度采集验证", 2, "同意借用。"), (6, 6, 4, "rejected", "设备热分布测试", 2, "请补充实验安全方案后重新申请。"), (7, 1, 5, "cancelled", "模拟信号输出测试", None, ""), (8, 6, -1, "borrowed", "三维模型采集课程实践", 2, "同意，注意保护标定板。")]
    for eid, uid, offset, status, purpose, reviewer, note in samples:
        start = anchor + timedelta(days=offset)
        end = start + timedelta(hours=3)
        if status == "borrowed":
            start = now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
            end = start + timedelta(hours=8)
        created = min(now() - timedelta(hours=2), start - timedelta(days=1))
        workflow = "approved" if status in ("borrowed", "returned") else status
        updated = created + timedelta(minutes=30 if status == "cancelled" else 15 if reviewer else 0)
        rid = db.execute("INSERT INTO reservations(equipment_id,user_id,start_at,end_at,purpose,status,created_at,updated_at,cancelled_at,cancelled_by) VALUES (?,?,?,?,?,?,?,?,?,?)", (eid, uid, start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes"), purpose, workflow, timestamp(created), timestamp(updated), timestamp(created + timedelta(minutes=30)) if status == "cancelled" else None, uid if status == "cancelled" else None)).lastrowid
        if reviewer is not None:
            db.execute("INSERT INTO reservation_reviews(reservation_id,reviewer_id,decision,note,reviewed_at) VALUES (?,?,?,?,?)", (rid, reviewer, "rejected" if status == "rejected" else "approved", note, timestamp(created + timedelta(minutes=15))))
        if status in ("borrowed", "returned"):
            checkout = start + timedelta(minutes=5)
            returned = end - timedelta(minutes=5) if status == "returned" else None
            db.execute("INSERT INTO loans(reservation_id,checkout_by,checkout_at,checkout_condition,returned_by,returned_at,return_condition,acceptance_result) VALUES (?,3,?,'设备及附件借出检查完好。',?,?,?,?)", (rid, timestamp(checkout), 3 if returned else None, timestamp(returned) if returned else None, "归还时设备及附件完好。" if returned else None, "passed" if returned else None))
    db.execute("INSERT INTO event_audit(actor_id,actor_name,source_id,event_type,object_code,operation_code,target_id,outcome,detail,created_at) VALUES (4,'系统管理员','system.seed','initialize','equipment','view',NULL,'accepted','初始化课程演示数据；该记录由系统生成。',?)", (timestamp(),))
