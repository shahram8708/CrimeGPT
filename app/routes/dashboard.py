from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app.extensions import db
from app.forms.auth_forms import OnboardingForm
from app.models import CeleryJob, Notification, PoliceStation, User
from app.models.mixins import utcnow
from app.services.audit_service import write_audit
from app.services.authz import can_create_case, can_manage_station_users
from app.services.case_service import counts_for_dashboard, list_for
from app.services.i18n import translate
from app.services.intel_service import quota_reached
from app.services.task_service import enqueue_system_ping
from app.utils.formatting_utils import greeting_for_hour

dashboard_bp = Blueprint("dashboard", __name__)
IST = ZoneInfo("Asia/Kolkata")


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


@dashboard_bp.route("/dashboard", strict_slashes=False)
@login_required
def index():
    hour = datetime.now(IST).hour
    greeting = greeting_for_hour(hour)
    counts = counts_for_dashboard(current_user)
    recent_cases = list_for(current_user, {})[:5]
    running = (
        CeleryJob.query.filter(
            CeleryJob.user_id == current_user.id,
            CeleryJob.status.in_(("queued", "processing")),
        )
        .order_by(CeleryJob.created_at.desc())
        .limit(8)
        .all()
    )
    pending_jobs = CeleryJob.query.filter(
        CeleryJob.user_id == current_user.id,
        CeleryJob.status.in_(("queued", "processing")),
    ).count()
    platform = None
    if current_user.role == "super_admin":
        today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        platform = {
            "stations": PoliceStation.query.count(),
            "users": User.query.count(),
            "awaiting": User.query.filter_by(is_active=False).count(),
            "failed_today": CeleryJob.query.filter(
                CeleryJob.status == "failed", CeleryJob.created_at >= today
            ).count(),
        }
    show_queue = current_user.role in ("sho", "admin", "super_admin")
    return render_template(
        "dashboard/home.html",
        greeting=greeting,
        open_cases=counts["open_cases"],
        documents_week=counts["documents_this_week"],
        pending_jobs=pending_jobs,
        needing_sections=counts["items_needing_sections"],
        recent_cases=recent_cases,
        running_jobs=running,
        queue_rows=counts["incomplete_queue"],
        remand_rows=counts.get("remand_clock") or [],
        show_queue=show_queue,
        platform=platform,
        can_new=can_create_case(current_user),
        show_users=can_manage_station_users(current_user),
        quota=quota_reached(current_user) and current_user.role in ("sho", "admin", "super_admin"),
    )


@dashboard_bp.route("/dashboard/ping", methods=["POST"])
@login_required
def ping():
    job = enqueue_system_ping(current_user)
    return redirect(url_for("jobs.progress", job_uuid=job.uuid))


@dashboard_bp.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    if current_user.onboarding_completed_at:
        return redirect(url_for("dashboard.index"))
    form = OnboardingForm()
    if current_user.preferences:
        if request.method == "GET":
            form.ui_language.data = current_user.preferences.ui_language or "en"
            form.offline_drafts.data = "1" if current_user.preferences.offline_drafts else "0"
    step = int(request.values.get("step") or form.step.data or 1)
    if step not in (1, 2, 3):
        step = 1
    form.step.data = str(step)
    if form.validate_on_submit():
        action = form.action.data or request.form.get("action") or "continue"
        if current_user.preferences and form.ui_language.data:
            current_user.preferences.ui_language = form.ui_language.data
        if step == 1:
            db.session.commit()
            return redirect(url_for("dashboard.onboarding", step=2))
        if step == 2:
            if not form.understand.data:
                flash(translate("flash.need_disclaimer"), "danger")
                return render_template("dashboard/onboarding.html", form=form, step=2)
            current_user.disclaimer_accepted_at = utcnow()
            db.session.commit()
            if action == "skip":
                return _finish_onboarding(form)
            return redirect(url_for("dashboard.onboarding", step=3))
        if step == 3:
            return _finish_onboarding(form)
    else:
        step = int(request.args.get("step") or 1)
        if step not in (1, 2, 3):
            step = 1
        if step == 3 and not current_user.disclaimer_accepted_at:
            step = 2
        form.step.data = str(step)
    return render_template("dashboard/onboarding.html", form=form, step=step)


def _finish_onboarding(form):
    if current_user.preferences:
        current_user.preferences.offline_drafts = form.offline_drafts.data == "1"
        if form.ui_language.data:
            current_user.preferences.ui_language = form.ui_language.data
    if not current_user.disclaimer_accepted_at:
        current_user.disclaimer_accepted_at = utcnow()
    current_user.onboarding_completed_at = utcnow()
    db.session.commit()
    write_audit(
        "onboarding.completed",
        object_type="user",
        object_id=current_user.id,
        actor=current_user,
        station_id=current_user.station_id,
    )
    flash(translate("flash.onboarded"), "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/notifications")
@login_required
def notifications():
    rows = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )
    return render_template("dashboard/notifications.html", notes=rows)


@dashboard_bp.route("/notifications/read/<int:note_id>", methods=["POST"])
@login_required
def notification_read(note_id):
    note = Notification.query.filter_by(id=note_id, user_id=current_user.id).first()
    if note:
        note.is_read = True
        db.session.commit()
    return redirect(request.referrer or url_for("dashboard.notifications"))


@dashboard_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def notification_read_all():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update(
        {"is_read": True}, synchronize_session=False
    )
    db.session.commit()
    return redirect(url_for("dashboard.notifications"))


@dashboard_bp.route("/history")
@login_required
def history():
    q = CeleryJob.query
    if current_user.role == "super_admin" and request.args.get("user"):
        ident = request.args.get("user").strip().lower()
        owner = User.query.filter(
            (func.lower(User.identifier) == ident) | (User.uuid == ident)
        ).first()
        if owner:
            q = q.filter(CeleryJob.user_id == owner.id)
        else:
            q = q.filter(CeleryJob.user_id == -1)
    else:
        q = q.filter(CeleryJob.user_id == current_user.id)
    task = (request.args.get("task") or "").strip()
    kind = (request.args.get("type") or "").strip()
    type_map = {
        "intel": "crimegpt.legal_intel",
        "qa": "crimegpt.qa_turn",
        "analysis": "crimegpt.analyze_document",
        "translate": "crimegpt.translate",
        "checklist": "crimegpt.generate_checklist",
        "gap": "crimegpt.gap_analysis",
    }
    if kind in type_map:
        q = q.filter(CeleryJob.task_name == type_map[kind])
    elif task:
        q = q.filter(CeleryJob.task_name.contains(task))
    status = (request.args.get("status") or "").strip()
    if status:
        q = q.filter(CeleryJob.status == status)
    date_from = _parse_date(request.args.get("date_from"))
    date_to = _parse_date(request.args.get("date_to"))
    if date_from:
        q = q.filter(CeleryJob.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.filter(CeleryJob.created_at <= datetime.combine(date_to, datetime.max.time()))
    case_q = (request.args.get("case") or "").strip()
    case_map = {}
    if case_q:
        from app.models import Case

        matches = Case.query.filter(Case.cr_number.ilike(f"%{case_q}%")).all()
        ids = [c.id for c in matches]
        q = q.filter(CeleryJob.case_id.in_(ids or [-1]))
    star = request.args.get("star")
    if star == "1":
        q = q.filter(CeleryJob.is_starred.is_(True))
    page = max(int(request.args.get("page") or 1), 1)
    per = 20
    total = q.count()
    pages = max((total + per - 1) // per, 1)
    jobs = q.order_by(CeleryJob.created_at.desc()).offset((page - 1) * per).limit(per).all()
    ids = [j.case_id for j in jobs if j.case_id]
    if ids:
        from app.models import Case

        for c in Case.query.filter(Case.id.in_(ids)).all():
            case_map[c.id] = c
    from app.models.ai import LegalSuggestion, SavedResult

    saved_q = SavedResult.query
    if kind:
        saved_q = saved_q.filter(SavedResult.result_type == kind)
    if current_user.role not in ("super_admin", "admin"):
        saved_q = saved_q.filter(SavedResult.user_id == current_user.id)
    if star == "1":
        saved_q = saved_q.filter(SavedResult.is_starred.is_(True))
    if date_from:
        saved_q = saved_q.filter(SavedResult.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        saved_q = saved_q.filter(SavedResult.created_at <= datetime.combine(date_to, datetime.max.time()))
    saved = saved_q.order_by(SavedResult.created_at.desc()).limit(30).all()
    sugg_uuids = {}
    sids = [r.ref_id for r in saved if r.ref_table == "legal_suggestions"]
    if sids:
        for s in LegalSuggestion.query.filter(LegalSuggestion.id.in_(sids)).all():
            sugg_uuids[s.id] = s.uuid
    saved_links = {}
    for row in saved:
        saved_links[row.id] = _saved_href(row, sugg_uuids)
    return render_template(
        "dashboard/history.html",
        jobs=jobs,
        page=page,
        pages=pages,
        total=total,
        filters=request.args,
        case_map=case_map,
        saved=saved,
        sugg_uuids=sugg_uuids,
        saved_links=saved_links,
    )


def _saved_href(row, sugg_uuids):
    from flask import url_for

    if row.ref_table == "legal_suggestions" and sugg_uuids.get(row.ref_id):
        return url_for("results.legal_intel", rid=sugg_uuids[row.ref_id])
    if row.ref_table == "qa_threads":
        from app.models.ai import QaThread

        th = db.session.get(QaThread, row.ref_id)
        return url_for("tools.qa_thread", tid=th.uuid) if th else None
    if row.ref_table == "document_analyses":
        from app.models.ai import DocumentAnalysis

        an = db.session.get(DocumentAnalysis, row.ref_id)
        return url_for("results.analysis", rid=an.uuid) if an else None
    if row.ref_table == "translate_results":
        from app.models.ai import TranslateResult

        tr = db.session.get(TranslateResult, row.ref_id)
        return url_for("results.translate", rid=tr.uuid) if tr else None
    if row.ref_table == "legal_checklists":
        from app.models.ai import LegalChecklist

        cl = db.session.get(LegalChecklist, row.ref_id)
        return url_for("assist.checklist", uuid=cl.case.uuid) if cl and cl.case else None
    if row.ref_table == "gap_results":
        from app.models.ai import GapResult

        gp = db.session.get(GapResult, row.ref_id)
        return url_for("assist.gaps", uuid=gp.case.uuid) if gp and gp.case else None
    return None


@dashboard_bp.route("/history/<job_uuid>/star", methods=["POST"])
@login_required
def star_job(job_uuid):
    job = CeleryJob.query.filter_by(uuid=job_uuid).first()
    if job is None:
        abort(404)
    if current_user.role not in ("super_admin", "admin") and job.user_id != current_user.id:
        abort(404)
    job.is_starred = not bool(job.is_starred)
    db.session.commit()
    return redirect(request.referrer or url_for("dashboard.history"))
