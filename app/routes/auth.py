from datetime import timedelta

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func

from app.extensions import db, limiter
from app.forms.auth_forms import (
    ForgotPasswordForm,
    InviteAcceptForm,
    LoginForm,
    RegisterForm,
    ResendVerifyForm,
    ResetPasswordForm,
)
from app.models import Notification, PoliceStation, User, UserPreference
from app.models.mixins import utcnow
from app.services.audit_service import write_audit
from app.services.i18n import translate
from app.services.account_mail import send_reset_email, send_verify_email
from app.services.registration import (
    enrollment_matches,
    enrollment_required,
    mail_gateway_configured,
    registration_visible,
)
from app.services.token_service import issue_token, load_token, mark_used, token_is_valid
from app.utils.security_utils import safe_next_url

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

GENERIC_ERROR = "Incorrect identifier or password"
LOCK_AFTER = 8
LOCK_MINUTES = 15


def _after_login_target(user, next_value=None):
    if not user.onboarding_completed_at:
        return url_for("dashboard.onboarding")
    return safe_next_url(next_value, fallback=url_for("dashboard.index"))


def _login_session(user, remember=False):
    session.permanent = True
    login_user(user, remember=bool(remember))


def _user_by_identifier(ident):
    ident = (ident or "").strip().lower()
    if not ident:
        return None
    user = User.query.filter_by(identifier=ident).first()
    if user:
        return user
    return User.query.filter(func.lower(User.email) == ident).first()


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per 15 minutes", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(_after_login_target(current_user))
    form = LoginForm()
    if request.method == "GET":
        form.next.data = request.args.get("next") or ""
    if form.validate_on_submit():
        ident = (form.identifier.data or "").strip().lower()
        user = _user_by_identifier(ident)
        next_url = form.next.data or request.args.get("next")

        if user and user.is_locked:
            flash("Too many attempts. Try again later.", "danger")
            write_audit(
                "auth.login_failed",
                object_type="user",
                object_id=user.id,
                actor=None,
                station_id=user.station_id,
                meta={"reason": "locked"},
            )
            return render_template(
                "auth/login.html", form=form, show_register=registration_visible()
            )

        if user is None or not user.check_password(form.password.data):
            if user:
                user.failed_login_count = (user.failed_login_count or 0) + 1
                if user.failed_login_count >= LOCK_AFTER:
                    user.lock_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
                db.session.commit()
                write_audit(
                    "auth.login_failed",
                    object_type="user",
                    object_id=user.id,
                    actor=None,
                    station_id=user.station_id,
                    meta={"reason": "bad_password"},
                )
            else:
                write_audit("auth.login_failed", object_type="user", meta={"reason": "unknown"})
            flash(GENERIC_ERROR, "danger")
            return render_template(
                "auth/login.html", form=form, show_register=registration_visible()
            )

        if user.station_id and user.role != "super_admin":
            station = user.station
            if station is not None and not station.is_active:
                flash("This account cannot sign in. Contact your SHO.", "warning")
                return render_template(
                    "auth/login.html", form=form, show_register=registration_visible()
                )
        if not user.is_active:
            if user.last_login_at:
                flash("This account cannot sign in. Contact your SHO.", "warning")
            else:
                flash("This account is awaiting approval.", "warning")
            return render_template(
                "auth/login.html", form=form, show_register=registration_visible()
            )

        user.failed_login_count = 0
        user.lock_until = None
        user.last_login_at = utcnow()
        db.session.commit()
        _login_session(user, remember=form.remember.data)
        write_audit("auth.login", object_type="user", object_id=user.id, actor=user)
        flash(translate("flash.signed_in"), "success")
        return redirect(_after_login_target(user, next_url))
    return render_template("auth/login.html", form=form, show_register=registration_visible())


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    actor = current_user
    write_audit("auth.logout", object_type="user", object_id=actor.id, actor=actor)
    logout_user()
    flash(translate("flash.signed_out"), "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def register():
    if not registration_visible():
        abort(404)
    form = RegisterForm()
    stations = PoliceStation.query.filter_by(is_active=True).order_by(PoliceStation.name).all()
    form.station_id.choices = [(s.id, f"{s.name} ({s.code})") for s in stations]
    need_code = enrollment_required()
    if form.validate_on_submit():
        def _err(field, message):
            field.errors = list(field.errors) + [message]

        if need_code and not enrollment_matches(form.enrollment_code.data):
            _err(form.enrollment_code, "Enrollment code is not valid.")
        ident = (form.identifier.data or "").strip().lower()
        if User.query.filter_by(identifier=ident).first():
            _err(form.identifier, "This identifier is not available.")
        email = (form.email.data or "").strip().lower() or (ident if "@" in ident else None)
        if email and User.query.filter(func.lower(User.email) == email).first():
            _err(form.email, "This identifier is not available.")
        if form.role.data not in ("constable", "writer"):
            _err(form.role, "That role must be assigned by invite.")
        if form.errors:
            return render_template("auth/register.html", form=form, need_code=need_code)

        user = User(
            full_name=form.full_name.data.strip(),
            identifier=ident,
            email=email,
            mobile=form.mobile.data or None,
            role=form.role.data,
            station_id=form.station_id.data,
            is_active=False,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()
        db.session.add(
            UserPreference(
                user=user,
                ui_language=form.language.data or "en",
                document_language="gu",
            )
        )
        db.session.commit()
        raw, _ = issue_token(user, "verify", 24)
        if email:
            send_verify_email(user, raw)
        write_audit(
            "account.registered",
            object_type="user",
            object_id=user.id,
            actor=None,
            station_id=user.station_id,
        )
        if mail_gateway_configured() and email:
            flash(translate("flash.check_email"), "success")
        else:
            flash(translate("flash.awaiting_sho"), "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form, need_code=need_code)


@auth_bp.route("/verify-email/<token>", methods=["GET"])
def verify_email(token):
    row = load_token(token, "verify")
    if row is None or row.used_at:
        return render_template(
            "auth/verify.html",
            state="invalid",
            form=ResendVerifyForm(),
        )
    if not token_is_valid(row):
        return render_template(
            "auth/verify.html",
            state="expired",
            form=ResendVerifyForm(),
        )
    user = db.session.get(User, row.user_id)
    if user is None:
        return render_template("auth/verify.html", state="invalid", form=ResendVerifyForm())
    user.email_verified_at = utcnow()
    activated = False
    if mail_gateway_configured():
        user.is_active = True
        activated = True
    mark_used(row)
    write_audit(
        "account.verified",
        object_type="user",
        object_id=user.id,
        actor=user,
        station_id=user.station_id,
        meta={"activated": activated},
    )
    if activated:
        flash(translate("flash.email_verified_active"), "success")
    else:
        flash(translate("flash.email_verified_pending"), "info")
    return render_template("auth/verify.html", state="ok", activated=activated, form=None)


@auth_bp.route("/resend-verification", methods=["POST"])
@limiter.limit("5 per 15 minutes")
def resend_verification():
    form = ResendVerifyForm()
    if form.validate_on_submit():
        user = _user_by_identifier(form.identifier.data)
        if user and not user.email_verified_at:
            dest = user.email or (user.identifier if "@" in user.identifier else None)
            if dest:
                raw, _ = issue_token(user, "verify", 24)
                send_verify_email(user, raw)
    flash(translate("flash.verify_resent"), "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per 15 minutes", methods=["POST"])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = _user_by_identifier(form.identifier.data)
        if user and user.password_hash:
            dest = user.email or (user.identifier if "@" in (user.identifier or "") else None)
            if dest:
                raw, _ = issue_token(user, "reset", 1)
                send_reset_email(user, raw)
            write_audit(
                "auth.reset_requested",
                object_type="user",
                object_id=user.id,
                actor=None,
                station_id=user.station_id,
            )
        flash(translate("flash.reset_sent"), "info")
        return redirect(url_for("auth.forgot_password"))
    return render_template("auth/forgot.html", form=form)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    row = load_token(token, "reset")
    if row is None or row.used_at:
        return render_template("auth/reset.html", form=None, state="invalid")
    if not token_is_valid(row):
        return render_template("auth/reset.html", form=None, state="expired")
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user = db.session.get(User, row.user_id)
        if user is None:
            return render_template("auth/reset.html", form=None, state="invalid")
        user.set_password(form.password.data)
        user.session_version = (user.session_version or 1) + 1
        user.failed_login_count = 0
        user.lock_until = None
        mark_used(row)
        write_audit(
            "auth.password_change",
            object_type="user",
            object_id=user.id,
            actor=user,
            station_id=user.station_id,
            meta={"via": "reset"},
        )
        flash(translate("flash.password_changed"), "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", form=form, state="ok")


@auth_bp.route("/invite/<token>", methods=["GET", "POST"])
def accept_invite(token):
    row = load_token(token, "invite")
    if row is None or row.used_at or not token_is_valid(row):
        return render_template("auth/invite.html", form=None, state="invalid", user=None)
    user = db.session.get(User, row.user_id)
    if user is None:
        return render_template("auth/invite.html", form=None, state="invalid", user=None)
    form = InviteAcceptForm(obj=user)
    if form.validate_on_submit():
        user.full_name = form.full_name.data.strip()
        user.set_password(form.password.data)
        user.is_active = True
        if user.email:
            user.email_verified_at = utcnow()
        user.disclaimer_accepted_at = utcnow()
        if not user.preferences:
            db.session.add(UserPreference(user=user))
        mark_used(row)
        write_audit(
            "account.invite_accepted",
            object_type="user",
            object_id=user.id,
            actor=user,
            station_id=user.station_id,
        )
        if user.invited_by_id:
            note = Notification(
                user_id=user.invited_by_id,
                title="Invite accepted",
                body=f"{user.full_name} accepted their CrimeGPT invite.",
                link_path="/admin/users",
            )
            db.session.add(note)
            db.session.commit()
        flash(translate("flash.invite_accepted"), "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/invite.html", form=form, state="ok", user=user)
