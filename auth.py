"""
auth.py
登录/登出路由 + Flask-Login 配置 + 全站保护
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user

from models.user import get_user_by_username, init_db

auth_bp = Blueprint("auth", __name__)
_login_manager = LoginManager()


def init_auth(app):
    """在 app.py 中调用：init_auth(app)"""

    # ── Flask-Login 初始化 ──
    _login_manager.init_app(app)
    _login_manager.login_view = "auth.login_page"
    _login_manager.login_message = "请先登录"

    @_login_manager.user_loader
    def load_user(user_id: str):
        from models.user import get_user_by_id
        return get_user_by_id(int(user_id))

    # ── 初始化数据库 ──
    with app.app_context():
        init_db()

    # ── 全站保护 ──
    @app.before_request
    def _require_login():
        # 允许的公开端点
        public = {"auth.login_page", "auth.login_action", "static"}
        if request.endpoint in public:
            return None
        if not current_user.is_authenticated:
            return _login_manager.unauthorized()


# ── 路由 ───────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET"])
def login_page():
    """显示登录页面"""
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    return render_template("login.html")


@auth_bp.route("/login", methods=["POST"])
def login_action():
    """处理登录表单"""
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        return render_template("login.html", error="请输入用户名和密码")

    user = get_user_by_username(username)
    if user is None or not user.check_password(password):
        return render_template("login.html", error="用户名或密码错误")

    login_user(user)
    return redirect(url_for("index"))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login_page"))
