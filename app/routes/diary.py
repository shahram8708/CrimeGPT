import json
from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.case_forms import parse_local_dt, to_local_input
from app.forms.evidence_forms import DiaryCorrectForm, DiaryEntryForm, DiaryExportForm
from app.models.evidence import CaseDiaryEntry, DiaryExport, EvidenceItem
from app.models.mixins import utcnow
from app.services.audit_service import write_audit
from app.services.authz import can_add_diary, can_correct_diary, can_export_diary, can_sign_diary, require_case
from app.services.case_service import rebuild_fts
from app.services.i18n import translate
from app.services.task_service import enqueue_job
from app.tasks.document_tasks import run_export_diary

diary_bp = Blueprint("diary", __name__)


def _case(uuid, perm="view"):
    from app.models import Case

    case = Case.query.filter_by(uuid=uuid).first()
    return require_case(current_user, case, perm)


@diary_bp.route("/cases/<uuid>/diary")
@login_required
def timeline(uuid):
    case = _case(uuid, "view")
    prefs = current_user.preferences
    oldest = True if not prefs else bool(prefs.diary_oldest_first)
    order = request.args.get("order")
    if order in ("old", "new"):
        oldest = order == "old"
        if prefs:
            prefs.diary_oldest_first = oldest
            db.session.commit()
    q = case.diary_entries.order_by(
        CaseDiaryEntry.occurred_at.asc() if oldest else CaseDiaryEntry.occurred_at.desc()
    )
    entries = q.all()
    corrected_ids = {e.corrects_entry_id for e in entries if e.corrects_entry_id}
    export_form = DiaryExportForm()
    if prefs:
        export_form.language.data = prefs.document_language or "en"
    return render_template(
        "cases/diary.html",
        case=case,
        entries=entries,
        corrected_ids=corrected_ids,
        oldest=oldest,
        export_form=export_form,
        can_add=can_add_diary(current_user, case),
        can_sign=can_sign_diary(current_user, case),
        can_export=can_export_diary(current_user, case),
    )


@diary_bp.route("/cases/<uuid>/diary/new", methods=["GET", "POST"])
@login_required
def diary_new(uuid):
    case = _case(uuid, "diary")
    form = DiaryEntryForm()
    types = form.entry_type.choices
    if current_user.role == "constable":
        form.entry_type.choices = [("evidence_note", "evidence note")]
    exhibits = EvidenceItem.query.filter_by(case_id=case.id, deleted_at=None).all()
    form.evidence_ids.choices = [(e.id, e.original_filename or e.stored_name) for e in exhibits]
    if request.method == "GET":
        form.occurred_at.data = datetime.now()
    posted_type = request.form.get("entry_type") if request.method == "POST" else None
    if posted_type and not can_add_diary(current_user, case, posted_type):
        abort(403)
    if form.validate_on_submit():
        kind = form.entry_type.data
        if not can_add_diary(current_user, case, kind):
            abort(403)
        signed = current_user.role in ("io", "sho", "super_admin")
        entry = CaseDiaryEntry(
            case_id=case.id,
            author_id=current_user.id,
            entry_type=kind,
            occurred_at=parse_local_dt(form.occurred_at.data),
            place=(form.place.data or "").strip() or None,
            body=form.body.data.strip(),
            status="signed" if signed else "draft",
            evidence_json=json.dumps(form.evidence_ids.data) if form.evidence_ids.data else None,
        )
        db.session.add(entry)
        db.session.commit()
        rebuild_fts(case)
        write_audit("diary.added", object_type="diary", object_id=entry.uuid, case_id=case.id)
        flash(translate("flash.diary_added"), "success")
        return redirect(url_for("diary.timeline", uuid=case.uuid))
    return render_template("cases/diary_form.html", case=case, form=form)


@diary_bp.route("/cases/<uuid>/diary/<eid>")
@login_required
def diary_entry(uuid, eid):
    case = _case(uuid, "view")
    entry = CaseDiaryEntry.query.filter_by(uuid=eid, case_id=case.id).first()
    if entry is None:
        abort(404)
    form = DiaryCorrectForm()
    form.occurred_at.data = datetime.now()
    return render_template(
        "cases/diary_entry.html",
        case=case,
        entry=entry,
        form=form,
        can_sign=can_sign_diary(current_user, case) and entry.status == "draft",
        can_correct=can_correct_diary(current_user, case, entry),
    )


@diary_bp.route("/cases/<uuid>/diary/<eid>/correct", methods=["POST"])
@login_required
def diary_correct(uuid, eid):
    case = _case(uuid, "diary")
    entry = CaseDiaryEntry.query.filter_by(uuid=eid, case_id=case.id).first()
    if entry is None:
        abort(404)
    if not can_correct_diary(current_user, case, entry):
        abort(403)
    form = DiaryCorrectForm()
    if not form.validate_on_submit():
        flash(translate("form.fix"), "danger")
        return redirect(url_for("diary.diary_entry", uuid=case.uuid, eid=entry.uuid))
    corr = CaseDiaryEntry(
        case_id=case.id,
        author_id=current_user.id,
        entry_type="correction",
        occurred_at=parse_local_dt(form.occurred_at.data) or utcnow(),
        body=form.body.data.strip(),
        status="signed" if current_user.role in ("io", "sho", "super_admin") else "draft",
        corrects_entry_id=entry.id,
    )
    db.session.add(corr)
    db.session.commit()
    rebuild_fts(case)
    write_audit("diary.corrected", object_type="diary", object_id=corr.uuid, case_id=case.id)
    flash(translate("flash.diary_corrected"), "success")
    return redirect(url_for("diary.timeline", uuid=case.uuid))


@diary_bp.route("/cases/<uuid>/diary/<eid>/sign", methods=["POST"])
@login_required
def diary_sign(uuid, eid):
    case = _case(uuid, "sign")
    entry = CaseDiaryEntry.query.filter_by(uuid=eid, case_id=case.id).first()
    if entry is None:
        abort(404)
    entry.status = "signed"
    db.session.commit()
    write_audit("diary.signed", object_type="diary", object_id=entry.uuid, case_id=case.id)
    flash(translate("flash.diary_signed"), "success")
    return redirect(url_for("diary.timeline", uuid=case.uuid))


@diary_bp.route("/cases/<uuid>/diary/export", methods=["POST"])
@login_required
def diary_export(uuid):
    case = _case(uuid, "export")
    form = DiaryExportForm()
    if not form.validate_on_submit():
        flash(translate("form.fix"), "danger")
        return redirect(url_for("diary.timeline", uuid=case.uuid))
    if form.date_to.data < form.date_from.data:
        flash(translate("flash.bad_range"), "danger")
        return redirect(url_for("diary.timeline", uuid=case.uuid))
    from datetime import datetime, time, timezone

    start = datetime.combine(form.date_from.data, time.min, tzinfo=timezone.utc)
    end = datetime.combine(form.date_to.data, time.max, tzinfo=timezone.utc)
    count = 0
    for e in case.diary_entries.all():
        at = e.occurred_at
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if start <= at <= end:
            count += 1
    if count == 0:
        flash(translate("flash.no_diary_range"), "warning")
        return redirect(url_for("diary.timeline", uuid=case.uuid))
    exp = DiaryExport(
        case_id=case.id,
        user_id=current_user.id,
        date_from=form.date_from.data,
        date_to=form.date_to.data,
        language=form.language.data or "en",
        summarize=bool(form.summarize.data),
    )
    db.session.add(exp)
    db.session.commit()
    job = enqueue_job(
        current_user,
        "crimegpt.export_diary",
        run_export_diary,
        extra={"export_id": exp.id},
        case_id=case.id,
    )
    exp.job_id = job.id
    db.session.commit()
    write_audit("diary.exported", object_type="diary_export", object_id=exp.uuid, case_id=case.id)
    return redirect(url_for("jobs.progress", job_uuid=job.uuid))


@diary_bp.route("/cases/<uuid>/diary/exports/<export_uuid>")
@login_required
def diary_export_result(uuid, export_uuid):
    case = _case(uuid, "export")
    exp = DiaryExport.query.filter_by(uuid=export_uuid, case_id=case.id).first()
    if exp is None:
        abort(404)
    return render_template("cases/diary_export_result.html", case=case, exp=exp)
