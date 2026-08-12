import json

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db, limiter
from app.forms.tool_forms import EmptyPostForm, GapAcceptForm
from app.models.ai import GapResult, LegalChecklist, LegalChecklistItem
from app.models.mixins import utcnow
from app.services.authz import can_run_legal_intel, gemini_ready, require_case
from app.services.i18n import translate
from app.services.intel_service import quota_reached
from app.services.playbook_service import map_deep_link
from app.services.task_service import enqueue_job

assist_bp = Blueprint("assist", __name__)


def _case(uuid, perm="view"):
    from app.models import Case

    case = Case.query.filter_by(uuid=uuid).first()
    return require_case(current_user, case, perm)


@assist_bp.route("/cases/<uuid>/checklist")
@login_required
def checklist(uuid):
    case = _case(uuid, "view")
    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    rows = (
        LegalChecklist.query.filter_by(case_id=case.id)
        .order_by(LegalChecklist.created_at.desc())
        .all()
    )
    current = rows[0] if rows else None
    return render_template(
        "cases/checklist.html",
        case=case,
        current=current,
        history=rows[1:],
        form=EmptyPostForm(),
        gemini_ok=gemini_ready(),
        quota=quota_reached(current_user, case),
    )


@assist_bp.route("/cases/<uuid>/checklist/generate", methods=["POST"])
@login_required
@limiter.limit("30 per hour", methods=["POST"])
def checklist_generate(uuid):
    from app.tasks.ai_tasks import run_generate_checklist

    case = _case(uuid, "view")
    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    if not EmptyPostForm().validate_on_submit():
        abort(400)
    if not gemini_ready():
        flash(translate("intel.missing_key"), "danger")
        return redirect(url_for("assist.checklist", uuid=case.uuid))
    if quota_reached(current_user, case):
        flash(translate("intel.quota"), "warning")
        return redirect(url_for("assist.checklist", uuid=case.uuid))
    row = LegalChecklist(
        case_id=case.id,
        created_by_id=current_user.id,
        title=f"Checklist - {case.display_cr}",
    )
    db.session.add(row)
    db.session.commit()
    job = enqueue_job(
        current_user,
        "crimegpt.generate_checklist",
        run_generate_checklist,
        extra={"checklist_id": row.id, "user_id": current_user.id},
        case_id=case.id,
    )
    row.job_id = job.id
    db.session.commit()
    return redirect(url_for("jobs.progress", job_uuid=job.uuid))


@assist_bp.route("/cases/<uuid>/checklist/<int:item_id>/toggle", methods=["POST"])
@login_required
def checklist_toggle(uuid, item_id):
    case = _case(uuid, "view")
    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    if not EmptyPostForm().validate_on_submit():
        abort(400)
    item = db.session.get(LegalChecklistItem, item_id)
    if item is None or item.checklist.case_id != case.id:
        abort(404)
    item.is_done = not bool(item.is_done)
    item.done_by_id = current_user.id if item.is_done else None
    item.done_at = utcnow() if item.is_done else None
    db.session.commit()
    return redirect(url_for("assist.checklist", uuid=case.uuid))


@assist_bp.route("/cases/<uuid>/gaps")
@login_required
def gaps(uuid):
    case = _case(uuid, "view")
    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    row = (
        GapResult.query.filter_by(case_id=case.id)
        .order_by(GapResult.created_at.desc())
        .first()
    )
    data = {}
    if row and row.result_json:
        try:
            data = json.loads(row.result_json)
        except (TypeError, ValueError):
            data = {}
    return render_template(
        "cases/gaps.html",
        case=case,
        row=row,
        data=data,
        form=EmptyPostForm(),
        accept_form=GapAcceptForm(),
        gemini_ok=gemini_ready(),
        quota=quota_reached(current_user, case),
    )


@assist_bp.route("/cases/<uuid>/gaps/run", methods=["POST"])
@login_required
@limiter.limit("30 per hour", methods=["POST"])
def gaps_run(uuid):
    from app.tasks.ai_tasks import run_gap_analysis

    case = _case(uuid, "view")
    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    if not EmptyPostForm().validate_on_submit():
        abort(400)
    if quota_reached(current_user, case):
        flash(translate("intel.quota"), "warning")
        return redirect(url_for("assist.gaps", uuid=case.uuid))
    row = GapResult(case_id=case.id, user_id=current_user.id)
    db.session.add(row)
    db.session.commit()
    job = enqueue_job(
        current_user,
        "crimegpt.gap_analysis",
        run_gap_analysis,
        extra={"gap_id": row.id, "user_id": current_user.id},
        case_id=case.id,
    )
    row.job_id = job.id
    db.session.commit()
    return redirect(url_for("jobs.progress", job_uuid=job.uuid))


@assist_bp.route("/cases/<uuid>/gaps/accept", methods=["POST"])
@login_required
def gaps_accept(uuid):
    case = _case(uuid, "view")
    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    form = GapAcceptForm()
    if not form.validate_on_submit():
        flash(translate("form.fix"), "danger")
        return redirect(url_for("assist.gaps", uuid=case.uuid))
    cl = (
        LegalChecklist.query.filter_by(case_id=case.id)
        .order_by(LegalChecklist.created_at.desc())
        .first()
    )
    if cl is None:
        cl = LegalChecklist(
            case_id=case.id,
            created_by_id=current_user.id,
            title=f"Checklist - {case.display_cr}",
        )
        db.session.add(cl)
        db.session.flush()
    href = map_deep_link(case, form.deep_link.data) if form.deep_link.data else None
    db.session.add(
        LegalChecklistItem(
            checklist_id=cl.id,
            sort_order=len(cl.items or []) + 1,
            label=(form.label.data or "Gap")[:300],
            why_text=form.why.data or "",
            severity=form.severity.data or "medium",
            deep_link=href,
        )
    )
    db.session.commit()
    flash(translate("flash.gap_accepted"), "success")
    return redirect(url_for("assist.checklist", uuid=case.uuid))
