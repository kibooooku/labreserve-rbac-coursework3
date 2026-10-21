"""登录认证只负责身份；角色与权限在 rbac 模块即时查询。"""
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlsplit
from flask import current_app, g, request
from werkzeug.security import check_password_hash, generate_password_hash
from .db import get_db, now, timestamp
from .errors import DomainError

# 未知账号也执行一次密码哈希检查，避免明显的耗时差异。
_DUMMY_HASH = generate_password_hash("unavailable-account")


def token_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def same_origin():
    origin = request.headers.get("Origin")
    if origin:
        try:
            parsed = urlsplit(origin)
            expected = urlsplit(request.host_url)
        except ValueError as error:
            raise DomainError("请求来源格式无效，请从本站页面操作", 403, "CSRF_FAILED") from error
        if (parsed.scheme, parsed.netloc) != (expected.scheme, expected.netloc):
            raise DomainError("请求来源不匹配，请从本站页面操作", 403, "CSRF_FAILED")


def login(username, password):
    same_origin()
    if not isinstance(username, str) or not isinstance(password, str) or len(username) > 80 or len(password) > 256:
        raise DomainError("请输入有效的用户名和密码", 400, "INVALID_INPUT")
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username=? AND active=1", (username.strip(),)).fetchone()
    valid = check_password_hash(user["password_hash"] if user else _DUMMY_HASH, password)
    if not user or not valid:
        raise DomainError("用户名或密码错误", 401, "INVALID_CREDENTIALS")
    # 登录时轮换随机令牌，浏览器只得到原始令牌；数据库仅存 SHA-256 摘要。
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    old = request.cookies.get(current_app.config["SESSION_COOKIE_NAME"], "")
    db.execute("BEGIN IMMEDIATE")
    try:
        if old:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(old),))
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (timestamp(),))
        db.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at) VALUES (?,?,?,?)", (token_hash(token), user["id"], csrf, timestamp(now() + timedelta(hours=current_app.config["SESSION_HOURS"]))))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return user, token, csrf


def require_user():
    if getattr(g, "user", None) is not None:
        return g.user
    token = request.cookies.get(current_app.config["SESSION_COOKIE_NAME"], "")
    if not token or len(token) > 200:
        raise DomainError("请先登录", 401, "AUTH_REQUIRED")
    row = get_db().execute("SELECT u.*,s.csrf_token,s.token_hash FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1", (token_hash(token), timestamp())).fetchone()
    if row is None:
        raise DomainError("登录已失效，请重新登录", 401, "AUTH_REQUIRED")
    g.user = row
    return row


def require_csrf():
    user = require_user()
    same_origin()
    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied or not secrets.compare_digest(supplied, user["csrf_token"]):
        raise DomainError("安全令牌失效，请刷新页面后重试", 403, "CSRF_FAILED")


def public_user(user):
    roles = get_db().execute("SELECT r.id,r.code,r.name FROM roles r JOIN user_roles ur ON ur.role_id=r.id WHERE ur.user_id=? ORDER BY r.id", (user["id"],)).fetchall()
    return {"id": user["id"], "username": user["username"], "display_name": user["display_name"], "roles": [dict(r) for r in roles]}
