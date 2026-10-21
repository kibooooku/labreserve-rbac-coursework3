"""SQLite 持久层与可重复演示数据。

RBAC 核心恰为七张表。权限以 (operation_id, object_id) 联合主键标识，
角色权限外键直接引用该联合主键，禁止不存在的“操作×对象”授权。
"""
import sqlite3
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
CREATE TABLE IF NOT EXISTS equipment (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 category TEXT NOT NULL, location TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('available','maintenance')), description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS reservations (
 id INTEGER PRIMARY KEY, equipment_id INTEGER NOT NULL REFERENCES equipment(id),
 user_id INTEGER NOT NULL REFERENCES users(id), start_at TEXT NOT NULL, end_at TEXT NOT NULL,
 purpose TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','cancelled','borrowed','returned')),
 reviewer_id INTEGER REFERENCES users(id), review_note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
 CHECK(end_at > start_at)
);
CREATE INDEX IF NOT EXISTS idx_reservation_overlap ON reservations(equipment_id,status,start_at,end_at);
CREATE TABLE IF NOT EXISTS loans (
 id INTEGER PRIMARY KEY, reservation_id INTEGER NOT NULL UNIQUE REFERENCES reservations(id),
 checkout_at TEXT NOT NULL, returned_at TEXT,
 status TEXT NOT NULL CHECK(status IN ('borrowed','returned')), condition_note TEXT NOT NULL DEFAULT ''
);
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
        for name in ("event_audit", "loans", "reservations", "equipment", "sessions", "role_permissions", "permissions", "control_objects", "operations", "user_roles", "roles", "users"):
            db.execute(f"DROP TABLE IF EXISTS {name}")
    db.executescript(SCHEMA)
    if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        _seed(db)
        db.commit()
    except Exception:
        db.rollback()
        raise


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
    devices = [
        ("EQ-001", "奥林巴斯生物显微镜", "光学仪器", "实验楼 A201", "available", "适用于细胞形态观察；借用前请确认镜头洁净。"),
        ("EQ-002", "数字示波器", "电子测量", "实验楼 B203", "available", "100 MHz 双通道数字示波器，配两根探头。"),
        ("EQ-003", "高精度电子天平", "分析仪器", "实验楼 A102", "available", "量程 220 g，读数精度 0.1 mg。"),
        ("EQ-004", "树莓派开发套件", "开发平台", "创新工坊 C305", "available", "含开发板、电源及传感器套件。"),
        ("EQ-005", "便携式光谱仪", "光学仪器", "实验楼 A203", "maintenance", "定期标定中，维护结束后恢复预约。"),
        ("EQ-006", "热成像仪", "检测设备", "实验楼 B101", "available", "用于非接触温度测量，附充电电池。"),
        ("EQ-007", "函数信号发生器", "电子测量", "实验楼 B203", "available", "支持正弦波、方波及任意波形。"),
        ("EQ-008", "三维扫描仪", "检测设备", "创新工坊 C301", "available", "配套转台及标定板，仅限室内使用。"),
    ]
    db.executemany("INSERT INTO equipment(code,name,category,location,status,description) VALUES (?,?,?,?,?,?)", devices)
    anchor = (now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    samples = [(1, 1, 0, "pending", "细胞观察课程实验", None, ""), (2, 1, 2, "approved", "电子电路波形测量", 2, "已核验课程实验需求，请按时归还。"), (3, 6, 1, "pending", "材料质量测量与误差分析", None, ""), (4, 1, -4, "returned", "物联网温湿度采集验证", 2, "同意借用。"), (6, 6, 4, "rejected", "设备热分布测试", 2, "请补充实验安全方案后重新申请。"), (7, 1, 5, "cancelled", "模拟信号输出测试", None, ""), (8, 6, -1, "borrowed", "三维模型采集课程实践", 2, "同意，注意保护标定板。")]
    for eid, uid, offset, status, purpose, reviewer, note in samples:
        start = anchor + timedelta(days=offset)
        end = start + timedelta(hours=3)
        if status == "borrowed":
            start = now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
            end = start + timedelta(hours=8)
        created = min(now() - timedelta(hours=2), start - timedelta(days=1))
        rid = db.execute("INSERT INTO reservations(equipment_id,user_id,start_at,end_at,purpose,status,reviewer_id,review_note,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (eid, uid, start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes"), purpose, status, reviewer, note, timestamp(created))).lastrowid
        if status in ("borrowed", "returned"):
            checkout = start + timedelta(minutes=5)
            returned = end - timedelta(minutes=5) if status == "returned" else None
            db.execute("INSERT INTO loans(reservation_id,checkout_at,returned_at,status,condition_note) VALUES (?,?,?,?,?)", (rid, timestamp(checkout), timestamp(returned) if returned else None, status, "设备及附件检查完好。"))
    db.execute("INSERT INTO event_audit(actor_id,actor_name,source_id,event_type,object_code,operation_code,target_id,outcome,detail,created_at) VALUES (4,'系统管理员','system.seed','initialize','equipment','view',NULL,'accepted','初始化课程演示数据；该记录由系统生成。',?)", (timestamp(),))
