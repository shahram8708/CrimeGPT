import csv
import io
import json
from datetime import datetime

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db, limiter
from app.forms.admin_forms import EmptyAdminForm, EnrollmentRotateForm, SettingsForm, StationForm
from app.models import ApplicationSetting, AuditLog, Case, CeleryJob, PoliceStation, UsageCounter, User
from app.models.mixins import utcnow
from app.services.audit_service import write_audit
from app.services.authz import can_manage_station_users, is_admin, is_sho, is_super_admin
from app.services.entitlement_service import (
    PLAN_DEFAULTS,
    audit_export_allowed,
    drop_letterhead,
    folder_bytes,
    snapshot,
)
from app.services.file_service import file_service
from app.services.i18n import translate
from app.services.intel_service import today_gemini_calls
from app.utils.file_utils import sniff_mime
from app.utils.security_utils import generate_url_token, hash_password_token

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

KNOWN_SETTINGS = (
    "registration_open",
    "enrollment_code_hash",
    "gemini_daily_soft_limit",
    "retention_days",
    "disclaimer_en",
    "disclaimer_hi",
    "disclaimer_gu",
    "disclaimer_short_en",
    "disclaimer_short_hi",
    "disclaimer_short_gu",
    "site_name",
)


def _gate(need="manager"):
    if not current_user.is_authenticated:
        abort(403)
    if is_super_admin(current_user) or is_admin(current_user):
        return
    if need == "manager" and can_manage_station_users(current_user):
        return
    if need == "sho" and is_sho(current_user):
        return
    abort(403)


def _platform():
    return is_super_admin(current_user) or is_admin(current_user)


def _int(raw, default=0):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


@admin_bp.route("")
@login_required
def home():
    _gate("manager")
    today = utcnow().date()
    if _platform():
        stations = PoliceStation.query.count()
        users = User.query.count()
        awaiting = User.query.filter_by(is_active=False).count()
        open_cases = Case.query.filter(Case.deleted_at.is_(None), Case.status.in_(("draft", "open"))).count()
        failed = CeleryJob.query.filter(CeleryJob.status == "failed", CeleryJob.created_at >= datetime.combine(today, datetime.min.time())).count()
        gemini = today_gemini_calls(platform=True)
    else:
        sid = current_user.station_id
        stations = 1 if sid else 0
        users = User.query.filter_by(station_id=sid).count() if sid else 0
        awaiting = User.query.filter_by(station_id=sid, is_active=False).count() if sid else 0
        open_cases = Case.query.filter_by(station_id=sid, deleted_at=None).filter(Case.status.in_(("draft", "open"))).count() if sid else 0
        failed = 0
        gemini = today_gemini_calls(station_id=sid)
    return render_template(
        "admin/index.html",
        counts={
            "stations": stations,
            "users": users,
            "awaiting": awaiting,
            "open_cases": open_cases,
            "failed_today": failed,
            "gemini_today": gemini,
            "uploads": folder_bytes(current_app.config["UPLOAD_FOLDER"]),
            "generated": folder_bytes(current_app.config["GENERATED_FOLDER"]),
        },
        snap=snapshot(current_user),
        platform=_platform(),
    )


@admin_bp.route("/stations")
@login_required
def stations():
    _gate("manager")
    if not _platform():
        abort(403)
    rows = PoliceStation.query.order_by(PoliceStation.name).all()
    cards = []
    for s in rows:
        cards.append(
            {
                "station": s,
                "users": User.query.filter_by(station_id=s.id).count(),
                "cases": Case.query.filter_by(station_id=s.id, deleted_at=None).count(),
            }
        )
    return render_template("admin/stations.html", cards=cards)


@admin_bp.route("/stations/new", methods=["GET", "POST"])
@login_required
def station_new():
    _gate("manager")
    if not _platform():
        abort(403)
    form = StationForm()
    if request.method == "GET":
        form.state.data = "Gujarat"
        form.is_active.data = True
    if form.validate_on_submit():
        code = (form.code.data or "").strip().upper()
        if PoliceStation.query.filter_by(code=code).first():
            form.code.errors = list(form.code.errors) + ["That station code is taken."]
        else:
            station = PoliceStation(code=code)
            _apply_station(station, form)
            db.session.add(station)
            db.session.commit()
            write_audit("station.created", object_type="police_station", object_id=station.uuid, meta={"code": code})
            flash(translate("flash.station_saved"), "success")
            return redirect(url_for("admin.station_edit", uuid=station.uuid))
    return render_template("admin/station_form.html", form=form, station=None)


@admin_bp.route("/stations/<uuid>", methods=["GET", "POST"])
@login_required
def station_edit(uuid):
    _gate("manager")
    if not _platform():
        abort(403)
    station = PoliceStation.query.filter_by(uuid=uuid).first()
    if station is None:
        abort(404)
    form = StationForm(obj=station)
    if request.method == "GET":
        form.monthly_gemini_allowance.data = str(station.monthly_gemini_allowance or 40)
        form.extra_credits.data = str(station.extra_credits or 0)
        form.max_users.data = str(station.max_users or 8)
    if form.validate_on_submit():
        code = (form.code.data or "").strip().upper()
        taken = PoliceStation.query.filter(PoliceStation.code == code, PoliceStation.id != station.id).first()
        if taken:
            form.code.errors = list(form.code.errors) + ["That station code is taken."]
        else:
            _apply_station(station, form)
            upload = request.files.get("logo")
            if upload and upload.filename:
                data = upload.read()
                if sniff_mime(data) != "image/png":
                    flash(translate("adm.logo_png"), "danger")
                else:
                    key = f"stations/{station.uuid}/logo.png"
                    file_service.put(data, key)
                    station.logo_path = key
            db.session.commit()
            drop_letterhead(station.id)
            write_audit("station.updated", object_type="police_station", object_id=station.uuid, meta={"code": station.code})
            flash(translate("flash.station_saved"), "success")
            return redirect(url_for("admin.station_edit", uuid=station.uuid))
    return render_template("admin/station_form.html", form=form, station=station)


def _apply_station(station, form):
    station.name = form.name.data.strip()
    station.code = (form.code.data or "").strip().upper()
    station.district = (form.district.data or "").strip() or None
    station.city = (form.city.data or "").strip() or None
    station.state = (form.state.data or "").strip() or "Gujarat"
    station.address = (form.address.data or "").strip() or None
    station.phone = (form.phone.data or "").strip() or None
    station.letterhead_line2 = (form.letterhead_line2.data or "").strip() or None
    station.letterhead_line3 = (form.letterhead_line3.data or "").strip() or None
    station.is_active = bool(form.is_active.data)
    plan = form.plan_key.data or "pilot"
    station.plan_key = plan
    defaults = PLAN_DEFAULTS.get(plan) or PLAN_DEFAULTS["pilot"]
    station.monthly_gemini_allowance = _int(form.monthly_gemini_allowance.data, defaults["monthly_gemini_allowance"])
    station.extra_credits = _int(form.extra_credits.data, 0)
    station.max_users = _int(form.max_users.data, defaults["max_users"])
    station.allow_all_document_types = bool(form.allow_all_document_types.data)
    station.allow_legal_review = bool(form.allow_legal_review.data)
    station.allow_sho_queue = bool(form.allow_sho_queue.data)
    station.allow_station_fts = bool(form.allow_station_fts.data)
    station.allow_cctns_demo = bool(form.allow_cctns_demo.data)
    station.allow_audit_export = bool(form.allow_audit_export.data)


@admin_bp.route("/stations/<uuid>/logo")
@login_required
def station_logo(uuid):
    _gate("manager")
    station = PoliceStation.query.filter_by(uuid=uuid).first()
    if station is None or not station.logo_path:
        abort(404)
    if not _platform() and current_user.station_id != station.id:
        abort(404)
    data = file_service.get(station.logo_path)
    if not data:
        abort(404)
    return send_file(io.BytesIO(data), mimetype="image/png", download_name="logo.png")


@admin_bp.route("/audit")
@login_required
def audit():
    _gate("manager")
    q = AuditLog.query
    if not _platform():
        q = q.filter(AuditLog.station_id == current_user.station_id)
    action = (request.args.get("action") or "").strip()
    if action:
        q = q.filter(AuditLog.action == action)
    actor = (request.args.get("actor") or "").strip()
    if actor:
        owner = User.query.filter((User.identifier == actor.lower()) | (User.uuid == actor)).first()
        q = q.filter(AuditLog.actor_id == (owner.id if owner else -1))
    case_u = (request.args.get("case") or "").strip()
    if case_u:
        case = Case.query.filter_by(uuid=case_u).first()
        q = q.filter(AuditLog.case_id == (case.id if case else -1))
    station_q = (request.args.get("station") or "").strip()
    if station_q and _platform():
        st = PoliceStation.query.filter_by(code=station_q.upper()).first()
        q = q.filter(AuditLog.station_id == (st.id if st else -1))
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    if date_from:
        q = q.filter(AuditLog.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
    if date_to:
        q = q.filter(AuditLog.created_at <= datetime.strptime(date_to, "%Y-%m-%d"))
    page = max(_int(request.args.get("page"), 1), 1)
    per = 30
    total = q.count()
    pages = max((total + per - 1) // per, 1)
    rows = q.order_by(AuditLog.created_at.desc()).offset((page - 1) * per).limit(per).all()
    return render_template(
        "admin/audit.html",
        rows=rows,
        page=page,
        pages=pages,
        total=total,
        filters=request.args,
        can_export=audit_export_allowed(current_user),
    )


@admin_bp.route("/audit/export")
@login_required
def audit_export():
    _gate("manager")
    if not audit_export_allowed(current_user):
        abort(403)
    q = AuditLog.query
    if not _platform():
        q = q.filter(AuditLog.station_id == current_user.station_id)
    rows = q.order_by(AuditLog.created_at.desc()).limit(2000).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["time", "actor", "action", "object_type", "object_id", "ip"])
    for r in rows:
        writer.writerow(
            [
                r.created_at.isoformat() if r.created_at else "",
                r.actor.identifier if r.actor else "",
                r.action,
                r.object_type or "",
                r.object_id or "",
                r.ip or "",
            ]
        )
    write_audit("audit.exported", object_type="audit_log", meta={"n": len(rows)})
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit.csv"},
    )


@admin_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    _gate("manager")
    if not _platform():
        abort(403)
    form = SettingsForm()
    rotate = EnrollmentRotateForm()
    if request.method == "GET":
        form.site_name.data = ApplicationSetting.get("site_name", "CrimeGPT")
        form.registration_open.data = str(ApplicationSetting.get("registration_open", "false")).lower() in ("1", "true", "yes")
        form.gemini_daily_soft_limit.data = ApplicationSetting.get("gemini_daily_soft_limit", "40")
        form.retention_days.data = ApplicationSetting.get("retention_days", "365")
        form.disclaimer_en.data = ApplicationSetting.get("disclaimer_en", "")
        form.disclaimer_hi.data = ApplicationSetting.get("disclaimer_hi", "")
        form.disclaimer_gu.data = ApplicationSetting.get("disclaimer_gu", "")
        form.disclaimer_short_en.data = ApplicationSetting.get("disclaimer_short_en", "")
        form.disclaimer_short_hi.data = ApplicationSetting.get("disclaimer_short_hi", "")
        form.disclaimer_short_gu.data = ApplicationSetting.get("disclaimer_short_gu", "")
    if form.validate_on_submit() and request.form.get("intent") != "rotate":
        mapping = {
            "site_name": form.site_name.data or "CrimeGPT",
            "registration_open": "true" if form.registration_open.data else "false",
            "gemini_daily_soft_limit": str(_int(form.gemini_daily_soft_limit.data, 40)),
            "retention_days": str(max(_int(form.retention_days.data, 365), 30)),
            "disclaimer_en": form.disclaimer_en.data or "",
            "disclaimer_hi": form.disclaimer_hi.data or "",
            "disclaimer_gu": form.disclaimer_gu.data or "",
            "disclaimer_short_en": form.disclaimer_short_en.data or "",
            "disclaimer_short_hi": form.disclaimer_short_hi.data or "",
            "disclaimer_short_gu": form.disclaimer_short_gu.data or "",
        }
        for key, value in mapping.items():
            if key not in KNOWN_SETTINGS:
                continue
            ApplicationSetting.set(key, value, updated_by_id=current_user.id)
        db.session.commit()
        write_audit("settings.updated", object_type="application_settings", meta={"keys": list(mapping)})
        flash(translate("flash.settings_saved"), "success")
        return redirect(url_for("admin.settings"))
    enroll = ApplicationSetting.query.filter_by(key="enrollment_code_hash").first()
    return render_template(
        "admin/settings.html",
        form=form,
        rotate=rotate,
        enroll_at=enroll.updated_at if enroll else None,
        shown_code=None,
    )


@admin_bp.route("/settings/enrollment", methods=["POST"])
@login_required
def settings_enroll():
    _gate("manager")
    if not _platform():
        abort(403)
    form = EnrollmentRotateForm()
    if not form.validate_on_submit():
        abort(400)
    raw, _ = generate_url_token()
    code = f"NRP-{raw[:8].upper()}"
    ApplicationSetting.set("enrollment_code_hash", hash_password_token(code), updated_by_id=current_user.id)
    db.session.commit()
    write_audit("settings.updated", object_type="application_settings", meta={"keys": ["enrollment_code_hash"]})
    flash(translate("flash.enroll_once"), "success")
    settings_form = SettingsForm()
    enroll = ApplicationSetting.query.filter_by(key="enrollment_code_hash").first()
    return render_template(
        "admin/settings.html",
        form=settings_form,
        rotate=form,
        enroll_at=enroll.updated_at if enroll else None,
        shown_code=code,
    )


@admin_bp.route("/jobs")
@login_required
def jobs():
    _gate("manager")
    if not _platform():
        abort(403)
    q = CeleryJob.query
    status = (request.args.get("status") or "").strip()
    if status:
        q = q.filter(CeleryJob.status == status)
    task = (request.args.get("task") or "").strip()
    if task:
        q = q.filter(CeleryJob.task_name.contains(task))
    user_q = (request.args.get("user") or "").strip()
    if user_q:
        owner = User.query.filter((User.identifier == user_q.lower()) | (User.uuid == user_q)).first()
        q = q.filter(CeleryJob.user_id == (owner.id if owner else -1))
    page = max(_int(request.args.get("page"), 1), 1)
    per = 30
    total = q.count()
    pages = max((total + per - 1) // per, 1)
    rows = q.order_by(CeleryJob.created_at.desc()).offset((page - 1) * per).limit(per).all()
    return render_template("admin/jobs.html", rows=rows, page=page, pages=pages, total=total, filters=request.args)


@admin_bp.route("/jobs/<job_uuid>")
@login_required
def job_detail(job_uuid):
    _gate("manager")
    if not _platform():
        abort(403)
    job = CeleryJob.query.filter_by(uuid=job_uuid).first()
    if job is None:
        abort(404)
    payload = {}
    if job.payload_json:
        try:
            payload = json.loads(job.payload_json)
        except (TypeError, ValueError):
            payload = {}
    return render_template("admin/job_detail.html", job=job, payload=payload, form=EmptyAdminForm())


@admin_bp.route("/jobs/<job_uuid>/retry", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def job_retry(job_uuid):
    from app.services.task_service import retry_failed_job

    _gate("manager")
    if not _platform():
        abort(403)
    if not EmptyAdminForm().validate_on_submit():
        abort(400)
    job = CeleryJob.query.filter_by(uuid=job_uuid).first()
    if job is None:
        abort(404)
    try:
        new_job = retry_failed_job(current_user, job)
    except RuntimeError as exc:
        flash(translate("adm.retry_bad"), "danger")
        return redirect(url_for("admin.job_detail", job_uuid=job.uuid))
    write_audit("job.retried", object_type="celery_job", object_id=job.uuid, meta={"new": new_job.uuid})
    flash(translate("flash.job_retried"), "success")
    return redirect(url_for("jobs.progress", job_uuid=new_job.uuid))


@admin_bp.route("/usage")
@login_required
def usage():
    _gate("manager")
    q = UsageCounter.query
    if not _platform():
        q = q.filter(UsageCounter.station_id == current_user.station_id)
    rows = q.order_by(UsageCounter.day.desc()).limit(90).all()
    stations = {s.id: s for s in PoliceStation.query.all()}
    return render_template(
        "admin/usage.html",
        rows=rows,
        stations=stations,
        snap=snapshot(current_user),
        platform=_platform(),
    )


@admin_bp.route("/usage/export")
@login_required
def usage_export():
    _gate("manager")
    if not _platform():
        abort(403)
    rows = UsageCounter.query.order_by(UsageCounter.day.desc()).limit(2000).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["day", "station_id", "user_id", "gemini_calls", "doc_generations"])
    for r in rows:
        writer.writerow([r.day.isoformat(), r.station_id, r.user_id or "", r.gemini_calls, r.doc_generations])
    write_audit("usage.exported", object_type="usage_counters", meta={"n": len(rows)})
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=usage.csv"},
    )
