"""应用工厂：HTTP、事件授权与业务服务保持独立。"""
from pathlib import Path
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .errors import DomainError


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.json.ensure_ascii = False
    app.config.from_mapping(
        DATABASE=str(Path(app.instance_path) / "labreserve.sqlite3"),
        MAX_CONTENT_LENGTH=128 * 1024,
        SESSION_COOKIE_NAME="labreserve_session",
        SESSION_HOURS=12,
        COOKIE_SECURE=False,  # 本地 HTTP 演示；部署 HTTPS 时设为 True。
    )
    if config:
        app.config.update(config)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    from . import db
    app.teardown_appcontext(db.close_db)
    with app.app_context():
        db.initialize_database()
    from .routes import bp
    app.register_blueprint(bp)

    @app.errorhandler(DomainError)
    def domain_error(error):
        return jsonify(ok=False, error={"code": error.code, "message": error.message}), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        messages = {400: "请求格式错误", 404: "地址不存在", 405: "请求方法不支持", 413: "请求内容过大"}
        return jsonify(ok=False, error={"code": "HTTP_ERROR", "message": messages.get(error.code, "请求失败")}), error.code

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.exception("请求处理失败")
        return jsonify(ok=False, error={"code": "INTERNAL_ERROR", "message": "服务器处理失败，请稍后重试"}), 500

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    return app
