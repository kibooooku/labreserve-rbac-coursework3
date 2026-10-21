"""薄 HTTP 适配层：参数 → 认证/授权 → 查询或事件派发。"""
import csv
import io
from flask import Blueprint, current_app, jsonify, make_response, render_template, request
from . import auth, business, rbac
from .db import get_db
from .errors import DomainError
from .events import audit_rows, binding_snapshot, dispatch

bp = Blueprint("main", __name__)


def success(data):
    return jsonify(ok=True, data=data)


def json_object():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise DomainError("请求体必须是 JSON 对象")
    return payload


def identity(user, csrf):
    return {"user": auth.public_user(user), "permissions": sorted(rbac.permissions_for(user["id"])), "csrf_token": csrf}


@bp.get("/")
def index():
    return render_template("index.html")


@bp.post("/api/login")
def login():
    payload = json_object()
    user, token, csrf = auth.login(payload.get("username"), payload.get("password"))
    response = success(identity(user, csrf))
    response.set_cookie(current_app.config["SESSION_COOKIE_NAME"], token,
                        max_age=current_app.config["SESSION_HOURS"] * 3600,
                        httponly=True, secure=current_app.config["COOKIE_SECURE"], samesite="Strict", path="/")
    return response


@bp.get("/api/me")
def me():
    user = auth.require_user()
    return success(identity(user, user["csrf_token"]))


@bp.post("/api/logout")
def logout():
    auth.require_csrf()
    user = auth.require_user()
    get_db().execute("DELETE FROM sessions WHERE token_hash=?", (user["token_hash"],))
    response = success({})
    response.delete_cookie(current_app.config["SESSION_COOKIE_NAME"], path="/", samesite="Strict")
    return response


@bp.get("/api/dashboard")
def dashboard():
    user = rbac.require_permissions("page.dashboard:view")
    rows = business.reservations_for(user["id"])
    return success({
        "equipment_count": get_db().execute("SELECT COUNT(*) FROM equipment").fetchone()[0],
        "pending_count": sum(r["status"] == "pending" for r in rows),
        "approved_count": sum(r["status"] == "approved" for r in rows),
        "borrowed_count": sum(r["status"] == "borrowed" for r in rows),
        "my_reservation_count": get_db().execute("SELECT COUNT(*) FROM reservations WHERE user_id=?", (user["id"],)).fetchone()[0],
        "permission_count": len(rbac.permissions_for(user["id"])),
    })


@bp.get("/api/equipment")
def equipment():
    rbac.require_permissions("page.equipment:view", "equipment:view")
    return success([dict(r) for r in get_db().execute("SELECT * FROM equipment ORDER BY code")])


@bp.get("/api/reservations")
def reservations():
    user = rbac.require_permissions("page.reservations:view", "reservation:view")
    return success(business.reservations_for(user["id"]))


@bp.get("/api/loans")
def loans():
    user = rbac.require_permissions("page.loans:view", "loan:view")
    return success(business.loans_for(user["id"]))


@bp.get("/api/audit")
def audit():
    rbac.require_permissions("page.audit:view", "audit:view")
    return success(audit_rows())


@bp.get("/api/events")
def event_registry():
    rbac.require_permissions("page.audit:view", "audit:view")
    return success({"bindings": binding_snapshot(), "recent": audit_rows()})


@bp.get("/api/rbac")
def rbac_configuration():
    rbac.require_permissions("page.rbac:view", "rbac:view")
    return success(rbac.snapshot())


@bp.post("/api/events")
def events():
    envelope = request.get_json(silent=True)
    if not isinstance(envelope, dict):
        envelope = {}
    # object/operation/handler 即使出现在请求中也不会进入授权决策。
    return success(dispatch(envelope.get("source_id"), envelope.get("payload")))


def csv_safe(value):
    value = "" if value is None else str(value)
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


@bp.get("/api/export/reservations")
def export_reservations():
    user = rbac.require_permissions("page.reservations:view", "reservation:export")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    fields = [("id", "预约编号"), ("equipment_code", "设备编号"), ("equipment_name", "设备名称"), ("applicant_name", "申请人"), ("start_at", "开始时间"), ("end_at", "结束时间"), ("purpose", "借用用途"), ("status", "状态"), ("reviewer_name", "审批人"), ("review_note", "审批意见")]
    writer.writerow([label for _, label in fields])
    for row in business.reservations_for(user["id"]):
        writer.writerow([csv_safe(row[key]) for key, _ in fields])
    response = make_response("\ufeff" + buffer.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = 'attachment; filename="labreserve-reservations.csv"'
    return response
