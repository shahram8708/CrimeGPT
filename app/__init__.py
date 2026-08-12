import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.config import get_config
from app.extensions import cache, celery, csrf, db, init_celery, limiter, login_manager, migrate
from app.utils.file_utils import ensure_directories


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:
        pass


def _register_login(app):
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"
    login_manager.session_protection = "strong"

    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User

        if not user_id:
            return None
        try:
            uid, version = str(user_id).split(":", 1)
            user = db.session.get(User, int(uid))
        except (ValueError, TypeError):
            return None
        if user is None or not user.is_active:
            return None
        if str(user.session_version) != str(version):
            return None
        return user

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import redirect, url_for

        wants_json = (
            request.accept_mimetypes.best == "application/json"
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or request.path.startswith("/api/")
        )
        if wants_json:
            return jsonify({"error": "authentication required"}), 401
        return redirect(url_for("auth.login", next=request.path))


def _register_error_handlers(app):
    def _render_error(code, template, extra=None):
        ctx = extra or {}
        if request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
            payload = {"error": ctx.get("title") or str(code), "status": code}
            if "reference" in ctx:
                payload["reference"] = ctx["reference"]
            return jsonify(payload), code
        return render_template(template, **ctx), code

    @app.errorhandler(404)
    def not_found(err):
        return _render_error(404, "errors/404.html", {"title": "Page not found"})

    @app.errorhandler(403)
    def forbidden(err):
        return _render_error(403, "errors/403.html", {"title": "Permission denied"})

    @app.errorhandler(413)
    def too_large(err):
        return _render_error(413, "errors/413.html", {"title": "File too large"})

    @app.errorhandler(500)
    def server_error(err):
        reference = str(uuid.uuid4())
        try:
            from app.services.audit_service import write_audit

            write_audit("server_error", object_type="error", object_id=reference, meta={"path": request.path})
        except Exception:
            app.logger.exception("failed to audit server_error")
        app.logger.exception("server error %s", reference)
        return _render_error(
            500, "errors/500.html", {"title": "Something went wrong", "reference": reference}
        )


def _register_jinja(app):
    from flask_login import current_user

    from app.models import Notification
    from app.services import authz
    from app.services.i18n import get_current_lang, translate
    from app.services.registration import registration_visible
    from app.utils.formatting_utils import format_ist, nl2br
    from app.utils.security_utils import safe_next_url

    app.jinja_env.autoescape = True
    app.jinja_env.globals["t"] = translate
    app.jinja_env.globals["current_lang"] = get_current_lang
    app.jinja_env.filters["ist"] = format_ist
    app.jinja_env.filters["nl2br"] = nl2br

    @app.context_processor
    def inject_authz():
        unread = 0
        if getattr(current_user, "is_authenticated", False):
            try:
                unread = Notification.query.filter_by(
                    user_id=current_user.id, is_read=False
                ).count()
            except Exception:
                unread = 0
        authed = getattr(current_user, "is_authenticated", False)
        hide_modal = False
        if authed and getattr(current_user, "preferences", None):
            hide_modal = bool(current_user.preferences.hide_intel_modal)
        snap = None
        if authed:
            try:
                from app.services.entitlement_service import snapshot

                snap = snapshot(current_user)
            except Exception:
                snap = None
        return {
            "unread_count": unread,
            "can_create_case": authz.can_create_case(current_user) if authed else False,
            "can_manage_station_users": authz.can_manage_station_users(current_user) if authed else False,
            "can_run_legal_intel": authz.can_run_legal_intel(current_user, require_key=False) if authed else False,
            "can_generate_documents": authz.can_generate_documents(current_user) if authed else False,
            "gemini_ready": authz.gemini_ready() if authed else False,
            "entitlements": snap,
            "hide_intel_modal": hide_modal,
            "show_register": registration_visible(),
            "safe_path": safe_next_url,
        }


def prepare_runtime(app):
    from app.utils.schema import ensure_additive_schema

    ensure_directories(app)
    db.create_all()
    ensure_additive_schema()
    try:
        from app.services.docx_service import ensure_court_templates

        ensure_court_templates()
    except Exception:
        app.logger.exception("court templates")
    if app.config.get("TESTING"):
        return
    from app.models import PoliceStation
    from app.services.entitlement_service import unlock_demo_station
    from app.services.seed import seed_if_empty

    seed_if_empty(app)
    if app.config.get("ENV_NAME") == "development":
        nrp = PoliceStation.query.filter_by(code="NRP").first()
        if nrp:
            unlock_demo_station(nrp)
            db.session.commit()


ONBOARDING_ALLOWED = {
    "auth.logout",
    "auth.login",
    "dashboard.onboarding",
    "main.service_worker",
    "main.manifest",
    "main.healthz",
    "main.set_lang",
    "static",
}


def _register_onboarding_gate(app):
    from flask import redirect, url_for
    from flask_login import current_user

    @app.before_request
    def _gate_onboarding():
        if not getattr(current_user, "is_authenticated", False):
            return None
        if current_user.onboarding_completed_at:
            return None
        endpoint = request.endpoint or ""
        if endpoint in ONBOARDING_ALLOWED or endpoint.startswith("static"):
            return None
        if request.path.startswith("/static") or request.path in ("/sw.js", "/healthz"):
            return None
        if request.path.startswith("/auth/"):
            return None
        return redirect(url_for("dashboard.onboarding"))


def create_app(config_name=None):
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config.from_object(get_config(config_name))

    for key in (
        "SECRET_KEY", "MAIL_SERVER", "MAIL_USERNAME", "MAIL_PASSWORD",
        "MAIL_DEFAULT_SENDER", "GEMINI_API_KEY", "GEMINI_MODEL",
        "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND",
    ):
        val = os.environ.get(key)
        if val is not None:
            app.config[key] = val
    mail_port = os.environ.get("MAIL_PORT")
    if mail_port is not None:
        app.config["MAIL_PORT"] = int(mail_port)

    upload = Path(app.config["UPLOAD_FOLDER"])
    generated = Path(app.config["GENERATED_FOLDER"])
    root = Path(app.root_path).resolve().parent
    if not upload.is_absolute():
        app.config["UPLOAD_FOLDER"] = str(root / upload)
    if not generated.is_absolute():
        app.config["GENERATED_FOLDER"] = str(root / generated)

    uri = app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    if uri.startswith("sqlite:///instance/"):
        db_file = root / "instance" / uri.split("sqlite:///instance/", 1)[1]
        db_file.parent.mkdir(parents=True, exist_ok=True)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(db_file)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    cache.init_app(app)
    limiter.init_app(app)
    limiter.enabled = bool(app.config.get("RATE_LIMIT_ENABLED"))
    init_celery(app)

    from app import models  # noqa: F401
    from app.routes.admin import admin_bp
    from app.routes.admin_users import admin_users_bp
    from app.routes.api import api_bp
    from app.routes.auth import auth_bp
    from app.routes.cases import cases_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.diary import diary_bp
    from app.routes.downloads import downloads_bp
    from app.routes.evidence import evidence_bp
    from app.routes.jobs import jobs_bp
    from app.routes.main import main_bp
    from app.routes.profile import profile_bp
    from app.routes.documents import documents_bp
    from app.routes.results import results_bp
    from app.routes.assist import assist_bp
    from app.routes.tools import tools_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(admin_users_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(evidence_bp)
    app.register_blueprint(diary_bp)
    app.register_blueprint(downloads_bp)
    app.register_blueprint(tools_bp)
    app.register_blueprint(results_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(assist_bp)

    _register_login(app)
    _register_error_handlers(app)
    _register_jinja(app)
    _register_onboarding_gate(app)

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    with app.app_context():
        prepare_runtime(app)

    return app
