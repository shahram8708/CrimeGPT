from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import or_
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.forms.admin_forms import InviteUserForm, UserEditForm
from app.models import ALLOWED_ROLES, MailLog, Notification, PoliceStation, User, UserPreference
from app.models.mixins import utcnow
from app.services.account_mail import send_invite_email, send_reset_email
from app.services.audit_service import write_audit
from app.services.authz import (
    can_assign_role,
    can_invite,
    can_manage_station_users,
    can_manage_user,
    invite_role_choices,
)
from app.services.i18n import translate
from app.services.token_service import issue_token
from app.utils.security_utils import generate_url_token

admin_users_bp = Blueprint("admin_users", __name__)


def _require_manager():
    if not can_manage_station_users(current_user):
        abort(403)


def _scoped_users():
    q = User.query
    if current_user.role == "sho":
        q = q.filter(User.station_id == current_user.station_id)
    return q


def _get_user(uuid):
    user = User.query.filter_by(uuid=uuid).first()
    if user is None:
        abort(404)
    if current_user.role == "sho" and user.station_id != current_user.station_id:
        abort(404)
    if not can_manage_user(current_user, user):
        if current_user.role == "sho":
            abort(404)
        abort(403)
    return user


def _station_choices():
    rows = PoliceStation.query.filter_by(is_active=True).order_by(PoliceStation.name).all()
    return [(s.id, f"{s.name} ({s.code})") for s in rows]


@admin_users_bp.route("/admin/users")
@login_required
def users_list():
    _require_manager()
    q = _scoped_users()
    term = (request.args.get("q") or "").strip()
    if term:
        like = f"%{term}%"
        q = q.filter(or_(User.full_name.ilike(like), User.identifier.ilike(like)))
    role = (request.args.get("role") or "").strip()
    if role:
        q = q.filter(User.role == role)
    active = request.args.get("active")
    if active == "1":
        q = q.filter(User.is_active.is_(True))
    elif active == "0":
        q = q.filter(User.is_active.is_(False))
    station = request.args.get("station")
    if station and current_user.role in ("admin", "super_admin"):
        q = q.filter(User.station_id == int(station))
    page = max(int(request.args.get("page") or 1), 1)
    per = 20
    total = q.count()
    pages = max((total + per - 1) // per, 1)
    users = q.order_by(User.full_name).offset((page - 1) * per).limit(per).all()
    stations = PoliceStation.query.order_by(PoliceStation.name).all()
    return render_template(
        "admin/users.html",
        users=users,
        page=page,
        pages=pages,
        total=total,
        stations=stations,
        filters=request.args,
        roles=ALLOWED_ROLES,
    )


@admin_users_bp.route("/admin/users/new", methods=["GET", "POST"])
@login_required
def users_new():
    _require_manager()
    form = InviteUserForm()
    roles = invite_role_choices(current_user)
    form.role.choices = [(r, r.replace("_", " ")) for r in roles]
    stations = _station_choices()
    if current_user.role == "sho":
        form.station_id.choices = [
            (s, n) for s, n in stations if s == current_user.station_id
        ] or stations
        if current_user.station_id:
            form.station_id.data = current_user.station_id
    else:
        form.station_id.choices = [(0, "No station")] + stations
    if form.validate_on_submit():
        ident = form.identifier.data.strip().lower()
        email = (form.email.data or "").strip().lower() or None
        if not email and "@" in ident:
            email = ident
        station_id = form.station_id.data
        if current_user.role == "sho":
            station_id = current_user.station_id
        if station_id == 0:
            station_id = None
        role = form.role.data
        if role == "super_admin":
            station_id = None
        if not can_invite(current_user, role=role, station_id=station_id):
            abort(403)
        if User.query.filter_by(identifier=ident).first():
            form.identifier.errors = list(form.identifier.errors) + ["This identifier is not available."]
        elif email and User.query.filter_by(email=email).first():
            form.identifier.errors = list(form.identifier.errors) + ["This identifier is not available."]
        else:
            placeholder = generate_url_token()[0]
            user = User(
                full_name=form.full_name.data.strip(),
                identifier=ident,
                email=email,
                role=role,
                station_id=station_id,
                rank_label=(form.rank_label.data or "").strip() or None,
                is_active=False,
                invited_by_id=current_user.id,
                password_hash=generate_password_hash(placeholder),
            )
            db.session.add(user)
            db.session.flush()
            db.session.add(UserPreference(user=user))
            db.session.commit()
            raw, _ = issue_token(user, "invite", 24 * 7)
            mailed = False
            if form.send_invite.data:
                mailed = bool(send_invite_email(user, raw, current_user))
            write_audit(
                "account.invited",
                object_type="user",
                object_id=user.id,
                actor=current_user,
                station_id=station_id,
                meta={"role": role, "emailed": mailed},
            )
            if form.send_invite.data and mailed:
                flash(translate("flash.invite_sent"), "success")
            elif form.send_invite.data:
                flash(translate("flash.invite_mail_failed"), "warning")
            else:
                flash(translate("flash.invited"), "success")
            return redirect(url_for("admin_users.users_list"))
    return render_template("admin/user_form.html", form=form, mode="invite", target=None)


@admin_users_bp.route("/admin/users/<uuid>", methods=["GET", "POST"])
@login_required
def users_edit(uuid):
    _require_manager()
    user = _get_user(uuid)
    form = UserEditForm(obj=user)
    allowed = [r for r in ALLOWED_ROLES if can_assign_role(current_user, r)]
    if user.role not in allowed:
        allowed.append(user.role)
    form.role.choices = [(r, r.replace("_", " ")) for r in allowed]
    form.station_id.choices = [(0, "No station")] + _station_choices()
    if request.method == "GET":
        form.station_id.data = user.station_id or 0
    if form.validate_on_submit():
        if not can_assign_role(current_user, form.role.data):
            abort(403)
        user.rank_label = (form.rank_label.data or "").strip() or None
        user.belt_no = (form.belt_no.data or "").strip() or None
        user.role = form.role.data
        if current_user.role in ("admin", "super_admin") and "station_id" in request.form:
            sid = form.station_id.data
            user.station_id = None if not sid else sid
        if user.role == "super_admin":
            user.station_id = None
        db.session.commit()
        write_audit(
            "profile.updated",
            object_type="user",
            object_id=user.id,
            actor=current_user,
            station_id=user.station_id,
            meta={"admin_edit": True},
        )
        flash(translate("flash.user_saved"), "success")
        return redirect(url_for("admin_users.users_edit", uuid=user.uuid))
    return render_template("admin/user_form.html", form=form, mode="edit", target=user)


@admin_users_bp.route("/admin/users/<uuid>/activate", methods=["POST"])
@login_required
def users_activate(uuid):
    _require_manager()
    user = _get_user(uuid)
    user.is_active = True
    if not user.email_verified_at:
        user.email_verified_at = utcnow()
    db.session.add(
        Notification(
            user_id=user.id,
            title="Account approved",
            body="Your CrimeGPT account is active. Sign in to continue.",
            link_path="/auth/login",
        )
    )
    db.session.commit()
    write_audit(
        "account.activated",
        object_type="user",
        object_id=user.id,
        actor=current_user,
        station_id=user.station_id,
    )
    flash(translate("flash.user_activated"), "success")
    return redirect(url_for("admin_users.users_edit", uuid=user.uuid))


@admin_users_bp.route("/admin/users/<uuid>/deactivate", methods=["POST"])
@login_required
def users_deactivate(uuid):
    _require_manager()
    user = _get_user(uuid)
    if user.role == "super_admin":
        active_supers = User.query.filter_by(role="super_admin", is_active=True).count()
        if active_supers <= 1:
            flash(translate("flash.last_super"), "danger")
            return redirect(url_for("admin_users.users_edit", uuid=user.uuid))
    user.is_active = False
    user.session_version = (user.session_version or 1) + 1
    db.session.commit()
    write_audit(
        "account.deactivated",
        object_type="user",
        object_id=user.id,
        actor=current_user,
        station_id=user.station_id,
    )
    flash(translate("flash.user_deactivated"), "info")
    return redirect(url_for("admin_users.users_edit", uuid=user.uuid))


@admin_users_bp.route("/admin/users/<uuid>/invite", methods=["POST"])
@login_required
def users_resend_invite(uuid):
    _require_manager()
    user = _get_user(uuid)
    dest = user.email or (user.identifier if "@" in (user.identifier or "") else None)
    if dest:
        raw, _ = issue_token(user, "invite", 24 * 7)
        mailed = bool(send_invite_email(user, raw, current_user))
        if mailed:
            flash(translate("flash.invite_resent"), "success")
        else:
            flash(translate("flash.invite_mail_failed"), "warning")
    else:
        flash(translate("flash.no_email"), "warning")
    return redirect(url_for("admin_users.users_edit", uuid=user.uuid))


@admin_users_bp.route("/admin/users/<uuid>/reset", methods=["POST"])
@login_required
def users_send_reset(uuid):
    _require_manager()
    user = _get_user(uuid)
    dest = user.email or (user.identifier if "@" in user.identifier else None)
    if dest:
        raw, _ = issue_token(user, "reset", 1)
        send_reset_email(user, raw)
        flash(translate("flash.reset_queued"), "success")
    else:
        flash(translate("flash.no_email"), "warning")
    return redirect(url_for("admin_users.users_edit", uuid=user.uuid))


@admin_users_bp.route("/dev/mail-log")
@login_required
def mail_log():
    if current_app.config.get("ENV_NAME") == "production":
        abort(404)
    if current_user.role != "super_admin":
        abort(403)
    rows = MailLog.query.order_by(MailLog.created_at.desc()).limit(80).all()
    return render_template("admin/mail_log.html", rows=rows)
