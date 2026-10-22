"""事件源 → Listener → 通用授权 → 业务处理器。

调用者只发送 source_id 与业务 payload，操作和控制对象取自服务端固定表。
所有业务变更和成功审计共用事务；失败回滚后单独写审计，不记录密码/令牌。
"""
from dataclasses import dataclass, asdict
import sqlite3
from flask import g
from . import business
from .auth import require_user, require_csrf
from .db import get_db, timestamp
from .errors import DomainError, conflict
from .rbac import require_permissions


@dataclass(frozen=True)
class EventBinding:
    source_id: str
    event_type: str
    object_code: str
    operation_code: str
    handler: str


BINDINGS = (
    EventBinding("equipment.save", "submit", "equipment", "update", "save_equipment"),
    EventBinding("laboratory.save", "submit", "equipment", "update", "save_laboratory"),
    EventBinding("laboratory.set_active", "submit", "equipment", "update", "set_laboratory_active"),
    EventBinding("category.save", "submit", "equipment", "update", "save_category"),
    EventBinding("category.set_active", "submit", "equipment", "update", "set_category_active"),
    EventBinding("maintenance.start", "submit", "equipment", "update", "start_maintenance"),
    EventBinding("maintenance.end", "submit", "equipment", "update", "end_maintenance"),
    EventBinding("reservation.submit", "submit", "reservation", "create", "submit_reservation"),
    EventBinding("reservation.approve", "submit", "reservation", "approve", "approve_reservation"),
    EventBinding("reservation.reject", "submit", "reservation", "reject", "reject_reservation"),
    EventBinding("reservation.cancel", "submit", "reservation", "cancel", "cancel_reservation"),
    EventBinding("loan.checkout", "submit", "loan", "checkout", "checkout_loan"),
    EventBinding("loan.return", "submit", "loan", "return", "return_loan"),
    EventBinding("rbac.save_permissions", "submit", "rbac", "manage", "save_role_permissions"),
    EventBinding("rbac.assign_roles", "submit", "rbac", "manage", "assign_roles"),
)
_REGISTRY = {binding.source_id: binding for binding in BINDINGS}


def binding_snapshot():
    return [asdict(binding) for binding in BINDINGS]


def write_audit(source_id, binding, actor, outcome, detail, target_id=None):
    get_db().execute("INSERT INTO event_audit(actor_id,actor_name,source_id,event_type,object_code,operation_code,target_id,outcome,detail,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (
        actor["id"] if actor else None, actor["display_name"] if actor else "未登录",
        source_id[:100], binding.event_type if binding else "unknown", binding.object_code if binding else "unknown",
        binding.operation_code if binding else "unknown", str(target_id) if target_id is not None else None,
        outcome, detail[:1000], timestamp(),
    ))


def audit_rows(limit=200):
    return [dict(r) for r in get_db().execute("SELECT id,actor_name,source_id,event_type,object_code,operation_code,target_id,outcome,detail,created_at FROM event_audit ORDER BY id DESC LIMIT ?", (limit,))]


class PermissionListener:
    """一个可复用监听器覆盖所有受控按钮/表单，不复制每个业务的授权逻辑。"""

    def handle(self, source_id, payload):
        source = source_id if isinstance(source_id, str) else "[invalid]"
        binding = _REGISTRY.get(source)
        db = get_db()
        actor = None
        target_id = None
        if isinstance(payload, dict):
            for field in ("id", "reservation_id", "role_id", "user_id", "equipment_id"):
                if field in payload:
                    target_id = payload[field]
                    break
        if type(target_id) is not int:
            target_id = None
        try:
            actor = require_user()
            require_csrf()
            if binding is None:
                raise DomainError("未知事件源，不能指定任意操作或处理器")
            if not isinstance(payload, dict):
                raise DomainError("payload 必须是 JSON 对象")
            # 锁定写事务后再查权限，避免授权修改与业务提交交错。
            db.execute("BEGIN IMMEDIATE")
            require_permissions(f"{binding.object_code}:{binding.operation_code}")
            handler = getattr(business, binding.handler)
            result = handler(actor, payload)
            target_id = result.get("id", target_id) if isinstance(result, dict) else target_id
            write_audit(source, binding, actor, "accepted", "授权通过，业务操作完成", target_id)
            db.commit()
            return result
        except DomainError as error:
            db.rollback()
            write_audit(source, binding, actor, "denied" if error.status in (401, 403) else "invalid", error.message, target_id)
            raise
        except sqlite3.IntegrityError as error:
            db.rollback()
            write_audit(source, binding, actor, "invalid", "数据约束冲突，未保存任何业务修改", target_id)
            raise conflict("数据已发生变化或存在重复，请刷新后重试") from error
        except Exception:
            db.rollback()
            write_audit(source, binding, actor or getattr(g, "user", None), "invalid", "内部处理失败，业务事务已回滚", target_id)
            raise


listener = PermissionListener()


def dispatch(source_id, payload):
    return listener.handle(source_id, payload)
