"""通用 RBAC：不包含设备预约、归还、自审等任何业务判断。

多角色权限求并集；每次请求读取数据库，保存授权后现有会话立即生效。
"""
from .auth import require_user
from .db import get_db
from .errors import DomainError


def permissions_for(user_id):
    rows = get_db().execute("""SELECT DISTINCT co.code AS object_code,o.code AS operation_code
        FROM user_roles ur JOIN role_permissions rp ON rp.role_id=ur.role_id
        JOIN control_objects co ON co.id=rp.object_id JOIN operations o ON o.id=rp.operation_id
        WHERE ur.user_id=? ORDER BY co.code,o.code""", (user_id,)).fetchall()
    return {f"{r['object_code']}:{r['operation_code']}" for r in rows}


def require_permissions(*keys):
    user = require_user()
    permissions = permissions_for(user["id"])
    if any(key not in permissions for key in keys):
        raise DomainError("当前角色没有该操作权限", 403, "FORBIDDEN")
    return user


def full_scope(user_id):
    permissions = permissions_for(user_id)
    return bool(permissions & {"reservation:approve", "reservation:reject", "reservation:manage", "loan:checkout", "loan:return", "audit:view"})


def snapshot():
    db = get_db()
    roles = [dict(r) for r in db.execute("SELECT * FROM roles ORDER BY id")]
    users = []
    for row in db.execute("SELECT id,username,display_name FROM users WHERE active=1 ORDER BY id"):
        user = dict(row)
        user["role_ids"] = [r[0] for r in db.execute("SELECT role_id FROM user_roles WHERE user_id=? ORDER BY role_id", (row["id"],))]
        users.append(user)
    objects = [dict(r) for r in db.execute("SELECT * FROM control_objects ORDER BY id")]
    operations = [dict(r) for r in db.execute("SELECT * FROM operations ORDER BY id")]
    permissions = [dict(r) for r in db.execute("SELECT co.code AS object_code,o.code AS operation_code FROM permissions p JOIN control_objects co ON co.id=p.object_id JOIN operations o ON o.id=p.operation_id ORDER BY co.id,o.id")]
    role_permissions = {}
    for role in roles:
        rows = db.execute("SELECT co.code || ':' || o.code AS permission FROM role_permissions rp JOIN control_objects co ON co.id=rp.object_id JOIN operations o ON o.id=rp.operation_id WHERE rp.role_id=? ORDER BY co.code,o.code", (role["id"],))
        role_permissions[str(role["id"])] = [r[0] for r in rows]
    return {"roles": roles, "users": users, "objects": objects, "operations": operations, "permissions": permissions, "role_permissions": role_permissions}
