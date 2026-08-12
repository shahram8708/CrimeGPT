import json

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db, limiter
from app.forms.case_forms import parse_local_dt
from app.forms.evidence_forms import AssignmentForm, EvidenceUploadForm
from app.models import User
from app.models.evidence import CaseAssignment, EvidenceItem, ProposedDiaryItem
from app.models.mixins import utcnow
from app.services.audit_service import write_audit
from app.services.authz import (
    can_assign_case_user,
    can_delete_evidence,
    can_upload_evidence,
    require_case,
)
from app.services.file_service import file_service
from app.services.i18n import translate
from app.services.task_service import enqueue_job
from app.tasks.document_tasks import run_process_evidence
from app.utils.file_utils import validate_upload

evidence_bp = Blueprint("evidence", __name__)


def _case(uuid, perm="view"):
    from app.models import Case

    case = Case.query.filter_by(uuid=uuid).first()
    return require_case(current_user, case, perm)


def _audit(action, case, extra=None):
    write_audit(
        action,
        object_type="evidence",
        object_id=case.uuid,
        actor=current_user,
        station_id=case.station_id,
        case_id=case.id,
        meta=extra,
    )


def _int0(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@evidence_bp.route("/cases/<uuid>/evidence", methods=["GET", "POST"])
@login_required
def gallery(uuid):
    case = _case(uuid, "view")
    form = EvidenceUploadForm()
    form.case_item_id.choices = [(0, "-")] + [(i.id, i.description[:60]) for i in case.live_items()]
    form.case_item_id.coerce = _int0
    prefs = current_user.preferences
    need_consent = not (prefs and prefs.evidence_consent_at)
    if form.validate_on_submit():
        require_case(current_user, case, "upload")
        if need_consent and not form.consent.data:
            form.consent.errors = list(form.consent.errors) + [
                "Acknowledge that files are stored for this case."
            ]
        else:
            upload = request.files.get("file")
            data = upload.read() if upload else b""
            meta, err = validate_upload(upload.filename if upload else "", data)
            if err:
                form.file.errors = list(form.file.errors) + [err]
            else:
                station_uuid = case.station.uuid if case.station else "platform"
                key = f"{station_uuid}/{case.uuid}/{meta['stored_name']}"
                file_service.put(data, key)
                item = EvidenceItem(
                    case_id=case.id,
                    uploaded_by_id=current_user.id,
                    case_item_id=form.case_item_id.data or None,
                    original_filename=meta["display_name"],
                    stored_name=meta["stored_name"],
                    stored_path=key,
                    mime=meta["mime"],
                    size_bytes=meta["size"],
                    caption=(form.caption.data or "").strip() or None,
                    tag=form.tag.data,
                    exhibit_no=(form.exhibit_no.data or "").strip() or None,
                    taken_at=parse_local_dt(form.taken_at.data) if form.taken_at.data else None,
                    keep_exif=bool(form.keep_exif.data),
                )
                if item.case_item_id == 0:
                    item.case_item_id = None
                db.session.add(item)
                db.session.flush()
                body = _suggested_body(item)
                kind = "seizure" if item.tag == "property" else "evidence_note"
                db.session.add(
                    ProposedDiaryItem(
                        case_id=case.id,
                        evidence_id=item.id,
                        suggested_type=kind,
                        suggested_body=body,
                        created_by_id=current_user.id,
                    )
                )
                if prefs and not prefs.evidence_consent_at:
                    prefs.evidence_consent_at = utcnow()
                db.session.commit()
                enqueue_job(
                    current_user,
                    "crimegpt.process_evidence",
                    run_process_evidence,
                    extra={"evidence_id": item.id},
                    case_id=case.id,
                )
                _audit("evidence.uploaded", case, {"tag": item.tag, "size": item.size_bytes})
                flash(translate("flash.evidence_uploaded"), "success")
                return redirect(url_for("evidence.gallery", uuid=case.uuid))
    tag = request.args.get("tag") or ""
    q = case.evidence_items.filter(EvidenceItem.deleted_at.is_(None))
    if tag:
        q = q.filter(EvidenceItem.tag == tag)
    items = q.order_by(EvidenceItem.created_at.desc()).all()
    proposals = case.diary_proposals.filter(
        ProposedDiaryItem.accepted_at.is_(None), ProposedDiaryItem.dismissed_at.is_(None)
    ).all()
    assign_form = AssignmentForm()
    officers = User.query.filter(
        User.station_id == case.station_id,
        User.is_active.is_(True),
        User.role.in_(("constable", "writer")),
    ).order_by(User.full_name).all()
    assign_form.user_id.choices = [(u.id, f"{u.full_name} ({u.role})") for u in officers]
    return render_template(
        "cases/evidence.html",
        case=case,
        form=form,
        items=items,
        tag=tag,
        proposals=proposals,
        need_consent=need_consent,
        can_upload=can_upload_evidence(current_user, case),
        can_assign=can_assign_case_user(current_user, case),
        assign_form=assign_form,
        assignees=case.assignments.all(),
    )


def _suggested_body(item):
    bits = []
    if item.exhibit_no:
        bits.append(f"Exhibit {item.exhibit_no}")
    bits.append(item.caption or item.original_filename or "file")
    if item.tag:
        bits.append(f"({item.tag})")
    bits.append("uploaded.")
    return " ".join(bits)


@evidence_bp.route("/cases/<uuid>/evidence/<eid>")
@login_required
def detail(uuid, eid):
    case = _case(uuid, "view")
    item = EvidenceItem.query.filter_by(uuid=eid, case_id=case.id, deleted_at=None).first()
    if item is None:
        abort(404)
    from app.services.authz import can_run_legal_intel, gemini_ready

    return render_template(
        "cases/evidence_detail.html",
        case=case,
        item=item,
        can_delete=can_delete_evidence(current_user, case),
        can_analyse=can_run_legal_intel(current_user, require_key=False),
        gemini_ok=gemini_ready(),
    )


@evidence_bp.route("/cases/<uuid>/evidence/<eid>/analyse", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def send_analyser(uuid, eid):
    from app.forms.tool_forms import EmptyPostForm
    from app.models.document import LibraryDocument
    from app.services.analysis_service import enqueue_analyze
    from app.services.authz import can_run_legal_intel, gemini_ready

    case = _case(uuid, "view")
    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    if not EmptyPostForm().validate_on_submit():
        abort(400)
    item = EvidenceItem.query.filter_by(uuid=eid, case_id=case.id, deleted_at=None).first()
    if item is None:
        abort(404)
    if not gemini_ready():
        flash(translate("intel.missing_key"), "danger")
        return redirect(url_for("evidence.detail", uuid=case.uuid, eid=item.uuid))
    row = LibraryDocument(
        case_id=case.id,
        uploaded_by_id=current_user.id,
        original_filename=item.original_filename,
        stored_name=item.stored_name,
        stored_path=item.stored_path,
        mime=item.mime,
        size_bytes=item.size_bytes,
        source="evidence",
    )
    db.session.add(row)
    db.session.commit()
    try:
        job, _ = enqueue_analyze(current_user, row, case=case, language="en")
    except RuntimeError as exc:
        flash(translate("intel.quota") if str(exc) == "quota" else translate("intel.missing_key"), "warning")
        return redirect(url_for("evidence.detail", uuid=case.uuid, eid=item.uuid))
    _audit("evidence.sent_to_analyser", case, {"evidence": item.uuid})
    return redirect(url_for("jobs.progress", job_uuid=job.uuid))


@evidence_bp.route("/cases/<uuid>/evidence/<eid>/delete", methods=["POST"])
@login_required
def delete_item(uuid, eid):
    case = _case(uuid, "delete_evidence")
    item = EvidenceItem.query.filter_by(uuid=eid, case_id=case.id, deleted_at=None).first()
    if item is None:
        abort(404)
    item.deleted_at = utcnow()
    db.session.commit()
    _audit("evidence.deleted", case, {"evidence": item.uuid})
    flash(translate("flash.evidence_deleted"), "info")
    return redirect(url_for("evidence.gallery", uuid=case.uuid))


@evidence_bp.route("/cases/<uuid>/evidence/proposals/<int:pid>/accept", methods=["POST"])
@login_required
def accept_proposal(uuid, pid):
    case = _case(uuid, "diary")
    prop = ProposedDiaryItem.query.filter_by(id=pid, case_id=case.id).first()
    if prop is None or prop.accepted_at or prop.dismissed_at:
        abort(404)
    from app.models.evidence import CaseDiaryEntry
    from app.services.authz import can_add_diary
    from app.services.case_service import rebuild_fts

    kind = prop.suggested_type or "evidence_note"
    if not can_add_diary(current_user, case, kind):
        abort(403)
    signed = current_user.role in ("io", "sho", "super_admin")
    entry = CaseDiaryEntry(
        case_id=case.id,
        author_id=current_user.id,
        entry_type=kind,
        occurred_at=utcnow(),
        body=prop.suggested_body,
        status="signed" if signed else "draft",
        evidence_json=json.dumps([prop.evidence.uuid]) if prop.evidence else None,
    )
    db.session.add(entry)
    prop.accepted_at = utcnow()
    db.session.commit()
    rebuild_fts(case)
    write_audit("diary.added", object_type="diary", object_id=entry.uuid, case_id=case.id)
    flash(translate("flash.diary_added"), "success")
    return redirect(url_for("evidence.gallery", uuid=case.uuid))


@evidence_bp.route("/cases/<uuid>/evidence/proposals/<int:pid>/dismiss", methods=["POST"])
@login_required
def dismiss_proposal(uuid, pid):
    case = _case(uuid, "diary")
    prop = ProposedDiaryItem.query.filter_by(id=pid, case_id=case.id).first()
    if prop is None:
        abort(404)
    prop.dismissed_at = utcnow()
    db.session.commit()
    return redirect(url_for("evidence.gallery", uuid=case.uuid))


@evidence_bp.route("/cases/<uuid>/assignments", methods=["POST"])
@login_required
def assign(uuid):
    case = _case(uuid, "assign")
    form = AssignmentForm()
    officers = User.query.filter(
        User.station_id == case.station_id,
        User.is_active.is_(True),
        User.role.in_(("constable", "writer")),
    ).all()
    form.user_id.choices = [(u.id, u.full_name) for u in officers]
    if not form.validate_on_submit():
        flash(translate("form.fix"), "danger")
        return redirect(url_for("evidence.gallery", uuid=case.uuid))
    existing = CaseAssignment.query.filter_by(case_id=case.id, user_id=form.user_id.data).first()
    if existing is None:
        target = db.session.get(User, form.user_id.data)
        if target is None or target.station_id != case.station_id:
            abort(404)
        db.session.add(
            CaseAssignment(
                case_id=case.id,
                user_id=target.id,
                assigned_by_id=current_user.id,
                role_on_case=target.role,
            )
        )
        db.session.commit()
        write_audit("case.assigned", object_type="case", object_id=case.uuid, case_id=case.id, meta={"user": target.identifier})
        flash(translate("flash.assigned"), "success")
    return redirect(url_for("evidence.gallery", uuid=case.uuid))


@evidence_bp.route("/cases/<uuid>/assignments/<aid>/remove", methods=["POST"])
@login_required
def unassign(uuid, aid):
    case = _case(uuid, "assign")
    row = CaseAssignment.query.filter_by(uuid=aid, case_id=case.id).first()
    if row is None:
        abort(404)
    db.session.delete(row)
    db.session.commit()
    write_audit("case.unassigned", object_type="case", object_id=case.uuid, case_id=case.id)
    flash(translate("flash.unassigned"), "info")
    return redirect(url_for("evidence.gallery", uuid=case.uuid))
