import json

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db, limiter
from app.forms.document_forms import DiaryAcceptForm, GenerateDocumentForm, SaveDocumentForm
from app.models import Case, CaseDiaryEntry, Notification, User
from app.models.document import ALL_DOC_CARDS, GeneratedDocument, LIVE_DOC_TYPES
from app.models.mixins import utcnow
from app.services.audit_service import write_audit
from app.services.authz import can_finalize_or_lock, can_generate_documents, gemini_ready, require_case
from app.services.case_service import list_for
from app.services.document_service import (
    DOC_TITLES as TITLES,
    enqueue_generate,
    last_for,
    parse_ctx,
    preflight,
)
from app.services.gemini_service import gemini_configured
from app.services.i18n import translate
from app.services.intel_service import quota_reached

documents_bp = Blueprint("documents", __name__)


def _case(uuid, perm="view"):
    case = Case.query.filter_by(uuid=uuid).first()
    return require_case(current_user, case, perm)


def _doc(case, did):
    row = GeneratedDocument.query.filter_by(uuid=did, case_id=case.id).first()
    if row is None:
        abort(404)
    return row


@documents_bp.route("/documents")
@login_required
def cross_list():
    if not can_generate_documents(current_user):
        abort(403)
    allowed = {c.id: c for c in list_for(current_user, {})}
    q = GeneratedDocument.query.filter(GeneratedDocument.case_id.in_(list(allowed) or [-1]))
    dtype = (request.args.get("type") or "").strip()
    if dtype:
        q = q.filter(GeneratedDocument.doc_type == dtype)
    status = (request.args.get("status") or "").strip()
    if status:
        q = q.filter(GeneratedDocument.status == status)
    rows = q.order_by(GeneratedDocument.created_at.desc()).limit(80).all()
    return render_template("documents/list.html", rows=rows, cases=allowed, titles=TITLES)


@documents_bp.route("/cases/<uuid>/documents")
@login_required
def hub(uuid):
    case = _case(uuid, "view")
    from app.services.entitlement_service import doc_type_allowed

    cards = []
    for key in ALL_DOC_CARDS:
        live = key in LIVE_DOC_TYPES
        allowed = doc_type_allowed(current_user, case, key) if live else False
        pf = preflight(case, key) if live and allowed else {"ready": False, "missing": [], "warnings": []}
        last = last_for(case, key) if live else None
        cards.append(
            {
                "key": key,
                "title": TITLES.get(key, key),
                "live": live and allowed,
                "gated": live and not allowed,
                "ready": pf["ready"] if live and allowed else False,
                "missing": len(pf["missing"]) if live and allowed else 0,
                "last": last,
            }
        )
    return render_template(
        "documents/hub.html",
        case=case,
        cards=cards,
        can_generate=can_generate_documents(current_user, case)
        and (not case.is_locked or current_user.role == "super_admin"),
    )


@documents_bp.route("/cases/<uuid>/documents/generate", methods=["GET", "POST"])
@login_required
@limiter.limit("30 per hour", methods=["POST"])
def generate(uuid):
    case = _case(uuid, "generate")
    dtype = (request.values.get("type") or request.values.get("doc_type") or "").strip()
    if dtype not in LIVE_DOC_TYPES:
        abort(404)
    from app.services.entitlement_service import doc_type_allowed

    if not doc_type_allowed(current_user, case, dtype):
        flash(translate("adm.doc_gated"), "warning")
        return redirect(url_for("documents.hub", uuid=case.uuid))
    form = GenerateDocumentForm()
    form.doc_type.data = dtype
    accused = case.live_parties("accused")
    form.accused_ids.choices = [(p.id, p.full_name) for p in accused]
    if request.method == "GET":
        if current_user.preferences:
            form.language.data = current_user.preferences.document_language or "en"
        form.use_ai.data = dtype == "remand_pc" and gemini_configured()
        if not gemini_configured():
            form.use_ai.data = False
        if accused:
            form.accused_ids.data = [p.id for p in accused]
        court = next(((a.produced_before or "") for a in case.live_arrests() if a.produced_before), "")
        form.court_name.data = court
    pf = preflight(
        case,
        dtype,
        {
            "custody_hours_sought": form.custody_hours_sought.data or request.form.get("custody_hours_sought"),
            "court_name": form.court_name.data or request.form.get("court_name"),
            "production_at": form.production_at.data or request.form.get("production_at"),
            "date_from": form.date_from.data or request.form.get("date_from"),
        },
    )
    juveniles = any(p.is_juvenile for p in accused) and dtype == "remand_pc"
    if form.validate_on_submit():
        if juveniles and not form.juvenile_ack.data:
            flash(translate("doc.juvenile_gate"), "danger")
            return render_template(
                "documents/generate.html",
                case=case,
                form=form,
                dtype=dtype,
                title=TITLES.get(dtype),
                pf=pf,
                juveniles=juveniles,
                gemini_ok=gemini_configured(),
                quota=quota_reached(current_user, case),
            )
        ready = pf["ready"]
        if dtype == "remand_pc":
            ready = ready or bool(form.custody_hours_sought.data and (form.court_name.data or pf["ready"]))
            pf = preflight(
                case,
                dtype,
                {
                    "custody_hours_sought": form.custody_hours_sought.data,
                    "court_name": form.court_name.data,
                },
            )
            ready = pf["ready"]
        if not pf["ready"] and not form.allow_incomplete.data:
            flash(translate("doc.need_fields"), "warning")
        else:
            use_ai = bool(form.use_ai.data) and gemini_configured()
            try:
                job, _ = enqueue_generate(
                    current_user,
                    case,
                    dtype,
                    {
                        "language": form.language.data or "en",
                        "use_ai": use_ai,
                        "is_incomplete": (not pf["ready"]) and bool(form.allow_incomplete.data),
                        "accused_ids": form.accused_ids.data or [],
                        "combined": form.combined.data != "split",
                        "custody_hours_sought": form.custody_hours_sought.data or "",
                        "court_name": form.court_name.data or "",
                        "grounds": form.grounds.data or "",
                        "investigation_gist": form.investigation_gist.data or "",
                        "production_at": form.production_at.data or "",
                        "description": form.description.data or "",
                        "date_from": form.date_from.data or "",
                        "date_to": form.date_to.data or "",
                        "request_target": form.request_target.data or "",
                    },
                )
            except RuntimeError as exc:
                code = str(exc)
                if code == "plan":
                    flash(translate("adm.doc_gated"), "warning")
                    return redirect(url_for("documents.hub", uuid=case.uuid))
                flash(translate("intel.quota"), "warning")
                return redirect(url_for("documents.generate", uuid=case.uuid, type=dtype))
            return redirect(url_for("jobs.progress", job_uuid=job.uuid))
    return render_template(
        "documents/generate.html",
        case=case,
        form=form,
        dtype=dtype,
        title=TITLES.get(dtype),
        pf=pf,
        juveniles=juveniles,
        gemini_ok=gemini_configured(),
        quota=quota_reached(current_user, case),
    )


@documents_bp.route("/cases/<uuid>/documents/<did>")
@login_required
def preview(uuid, did):
    case = _case(uuid, "view")
    doc = _doc(case, did)
    if doc.status == "pending":
        if doc.creator and doc.created_by_id == current_user.id:
            from app.models import CeleryJob

            job = CeleryJob.query.filter_by(
                case_id=case.id, task_name="crimegpt.generate_document"
            ).order_by(CeleryJob.id.desc()).first()
            if job:
                return redirect(url_for("jobs.progress", job_uuid=job.uuid))
        return render_template("documents/preview.html", case=case, doc=doc, ctx={}, pending=True)
    ctx = parse_ctx(doc)
    from app.forms.document_forms import ReviewForm
    from app.models.document import ClauseAnalysis, DocumentReviewNote

    notes = DocumentReviewNote.query.filter_by(generated_document_id=doc.id).order_by(DocumentReviewNote.created_at.asc()).all()
    last_id = (
        ClauseAnalysis.query.filter_by(generated_id=doc.id).order_by(ClauseAnalysis.id.desc()).first()
    )
    return render_template(
        "documents/preview.html",
        case=case,
        doc=doc,
        ctx=ctx,
        pending=False,
        save_form=SaveDocumentForm(),
        review_form=ReviewForm(),
        notes=notes,
        last_identify=last_id,
        can_review=current_user.role in ("legal", "sho", "admin", "super_admin"),
        can_finalize=can_finalize_or_lock(current_user, case) and doc.status != "final",
        can_edit=can_generate_documents(current_user, case)
        and doc.status != "final"
        and (not case.is_locked or current_user.role == "super_admin"),
        titles=TITLES,
    )


@documents_bp.route("/cases/<uuid>/documents/<did>/save", methods=["POST"])
@login_required
def save(uuid, did):
    case = _case(uuid, "generate")
    doc = _doc(case, did)
    if doc.status == "final":
        abort(403)
    form = SaveDocumentForm()
    if not form.validate_on_submit():
        flash(translate("form.fix"), "danger")
        return redirect(url_for("documents.preview", uuid=case.uuid, did=doc.uuid))
    ctx = parse_ctx(doc)
    ai = dict(ctx.get("ai") or {})
    if form.history_line.data:
        ai["history_line"] = form.history_line.data.strip()
    if form.request_line.data:
        ai["request_line"] = form.request_line.data.strip()
    if form.prayer.data:
        ai["prayer"] = form.prayer.data.strip()
    if form.identifiers.data:
        ai["identifiers"] = form.identifiers.data.strip()
    if form.gist.data:
        ai["gist"] = form.gist.data.strip()
    grounds = form.grounds.data.strip() if form.grounds.data else ctx.get("grounds") or ""
    job, _ = enqueue_generate(
        current_user,
        case,
        doc.doc_type,
        {
            "language": doc.language,
            "use_ai": False,
            "is_incomplete": doc.is_incomplete,
            "accused_ids": [a.get("id") for a in (ctx.get("accused") or []) if a.get("id")],
            "custody_hours_sought": ctx.get("custody_hours") or "",
            "court_name": ctx.get("court_name") or "",
            "grounds": grounds,
            "parent_id": doc.id,
            "edited_ai": ai,
        },
    )
    return redirect(url_for("jobs.progress", job_uuid=job.uuid))


@documents_bp.route("/cases/<uuid>/documents/<did>/finalize", methods=["POST"])
@login_required
def finalize(uuid, did):
    case = _case(uuid, "view")
    doc = _doc(case, did)
    if not can_finalize_or_lock(current_user, case):
        abort(403)
    if doc.status not in ("completed", "final"):
        abort(403)
    doc.status = "final"
    doc.finalized_by_id = current_user.id
    doc.finalized_at = utcnow()
    db.session.commit()
    write_audit(
        "document.finalized",
        object_type="generated_document",
        object_id=doc.uuid,
        case_id=case.id,
        meta={"type": doc.doc_type},
    )
    flash(translate("flash.doc_final"), "success")
    return redirect(url_for("documents.preview", uuid=case.uuid, did=doc.uuid))


@documents_bp.route("/cases/<uuid>/documents/<did>/review", methods=["POST"])
@login_required
def review(uuid, did):
    case = _case(uuid, "view")
    doc = _doc(case, did)
    doc.review_requested_at = utcnow()
    legal = User.query.filter_by(station_id=case.station_id, role="legal", is_active=True).all()
    for u in legal:
        db.session.add(
            Notification(
                user_id=u.id,
                title="Document review requested",
                body=f"{TITLES.get(doc.doc_type)} for {case.display_cr}",
                link_path=f"/cases/{case.uuid}/documents/{doc.uuid}",
            )
        )
    db.session.commit()
    flash(translate("flash.doc_review"), "info")
    return redirect(url_for("documents.preview", uuid=case.uuid, did=doc.uuid))


@documents_bp.route("/cases/<uuid>/documents/<did>/regenerate", methods=["POST"])
@login_required
def regenerate(uuid, did):
    case = _case(uuid, "generate")
    doc = _doc(case, did)
    ctx = parse_ctx(doc)
    if not gemini_configured():
        flash(translate("intel.missing_key"), "danger")
        return redirect(url_for("documents.preview", uuid=case.uuid, did=doc.uuid))
    job, _ = enqueue_generate(
        current_user,
        case,
        doc.doc_type,
        {
            "language": doc.language,
            "use_ai": True,
            "is_incomplete": doc.is_incomplete,
            "accused_ids": [a.get("id") for a in (ctx.get("accused") or []) if a.get("id")],
            "custody_hours_sought": ctx.get("custody_hours") or "",
            "court_name": ctx.get("court_name") or "",
            "grounds": ctx.get("grounds") or "",
            "parent_id": doc.id,
        },
    )
    return redirect(url_for("jobs.progress", job_uuid=job.uuid))


@documents_bp.route("/cases/<uuid>/documents/<did>/versions")
@login_required
def versions(uuid, did):
    case = _case(uuid, "view")
    doc = _doc(case, did)
    rows = (
        GeneratedDocument.query.filter_by(case_id=case.id, doc_type=doc.doc_type)
        .order_by(GeneratedDocument.version_number.desc())
        .all()
    )
    return render_template("documents/versions.html", case=case, doc=doc, rows=rows, titles=TITLES)


@documents_bp.route("/cases/<uuid>/documents/<did>/diary", methods=["POST"])
@login_required
def propose_diary(uuid, did):
    case = _case(uuid, "diary")
    doc = _doc(case, did)
    title = TITLES.get(doc.doc_type, doc.doc_type)
    body = (
        f"Generated {title} (version {doc.version_number}) in {doc.language}. "
        f"Draft assistance only. Officer remains responsible."
    )
    doc.diary_proposal = body
    db.session.commit()
    flash(translate("flash.doc_diary_proposed"), "info")
    return redirect(url_for("documents.preview", uuid=case.uuid, did=doc.uuid))


@documents_bp.route("/cases/<uuid>/documents/<did>/diary-accept", methods=["POST"])
@login_required
def accept_diary(uuid, did):
    case = _case(uuid, "diary")
    doc = _doc(case, did)
    text = (request.form.get("body") or doc.diary_proposal or "").strip()
    if len(text) < 20:
        flash(translate("form.fix"), "danger")
        return redirect(url_for("documents.preview", uuid=case.uuid, did=doc.uuid))
    signed = current_user.role in ("io", "sho", "super_admin")
    db.session.add(
        CaseDiaryEntry(
            case_id=case.id,
            author_id=current_user.id,
            entry_type="court",
            occurred_at=utcnow(),
            body=text,
            status="signed" if signed else "draft",
        )
    )
    doc.diary_proposal = None
    db.session.commit()
    from app.services.case_service import rebuild_fts

    rebuild_fts(case)
    flash(translate("flash.diary_added"), "success")
    return redirect(url_for("documents.preview", uuid=case.uuid, did=doc.uuid))


@documents_bp.route("/documents/upload", methods=["GET", "POST"])
@login_required
@limiter.limit("30 per hour", methods=["POST"])
def upload():
    from app.forms.document_forms import LibraryUploadForm
    from app.models.document import LibraryDocument
    from app.services.file_service import file_service
    from app.utils.file_utils import validate_upload

    if not can_generate_documents(current_user):
        abort(403)
    form = LibraryUploadForm()
    cases = list_for(current_user, {})
    form.case_id.choices = [(0, "-")] + [(c.id, c.display_cr) for c in cases]
    prefs = current_user.preferences
    need_consent = not (prefs and prefs.evidence_consent_at)
    if form.validate_on_submit():
        if need_consent and not form.consent.data:
            form.consent.errors = list(form.consent.errors) + ["Acknowledge that files are stored."]
        else:
            upload = request.files.get("file")
            data = upload.read() if upload else b""
            meta, err = validate_upload(upload.filename if upload else "", data, allow_docx=True)
            if err:
                flash(err, "danger")
            else:
                case_id = form.case_id.data or None
                if case_id == 0:
                    case_id = None
                if case_id:
                    case = db.session.get(Case, case_id)
                    if case is None:
                        abort(404)
                    require_case(current_user, case, "view")
                key = f"library/{current_user.uuid if hasattr(current_user, 'uuid') else current_user.id}/{meta['stored_name']}"
                file_service.put(data, key)
                row = LibraryDocument(
                    case_id=case_id,
                    uploaded_by_id=current_user.id,
                    original_filename=meta["display_name"],
                    stored_name=meta["stored_name"],
                    stored_path=key,
                    mime=meta["mime"],
                    size_bytes=meta["size"],
                    source="upload",
                )
                if prefs and not prefs.evidence_consent_at:
                    prefs.evidence_consent_at = utcnow()
                db.session.add(row)
                db.session.commit()
                write_audit("library.uploaded", object_type="library_document", object_id=row.uuid, case_id=case_id)
                if form.run_identify.data:
                    job = _enqueue_identify(current_user, generated=None, upload=row, case_id=case_id)
                    return redirect(url_for("jobs.progress", job_uuid=job.uuid))
                return redirect(url_for("documents.upload_detail", uid=row.uuid))
    return render_template("documents/upload.html", form=form, need_consent=need_consent)


@documents_bp.route("/documents/file/<uid>")
@login_required
def upload_detail(uid):
    from app.models.document import ClauseAnalysis, LibraryDocument

    row = LibraryDocument.query.filter_by(uuid=uid).first()
    if row is None:
        abort(404)
    if current_user.role not in ("super_admin", "admin"):
        if row.uploaded_by_id != current_user.id:
            if not row.case_id:
                abort(404)
            require_case(current_user, row.case, "view")
    last = (
        ClauseAnalysis.query.filter_by(document_id=row.id)
        .order_by(ClauseAnalysis.id.desc())
        .first()
    )
    return render_template("documents/upload_detail.html", item=row, last=last)


@documents_bp.route("/cases/<uuid>/documents/<did>/identify", methods=["POST"])
@login_required
def identify_generated(uuid, did):
    case = _case(uuid, "view")
    doc = _doc(case, did)
    if not can_generate_documents(current_user, case):
        abort(403)
    job = _enqueue_identify(current_user, generated=doc, upload=None, case_id=case.id)
    return redirect(url_for("jobs.progress", job_uuid=job.uuid))


@documents_bp.route("/documents/file/<uid>/identify", methods=["POST"])
@login_required
def identify_upload(uid):
    from app.models.document import LibraryDocument

    row = LibraryDocument.query.filter_by(uuid=uid).first()
    if row is None:
        abort(404)
    if not can_generate_documents(current_user):
        abort(403)
    if not gemini_configured():
        flash(translate("intel.missing_key"), "danger")
        return redirect(url_for("documents.upload_detail", uid=row.uuid))
    job = _enqueue_identify(current_user, generated=None, upload=row, case_id=row.case_id)
    return redirect(url_for("jobs.progress", job_uuid=job.uuid))


@documents_bp.route("/cases/<uuid>/documents/<did>/review-comment", methods=["POST"])
@login_required
def review_comment(uuid, did):
    from app.forms.document_forms import ReviewForm
    from app.models.document import DocumentReviewNote

    case = _case(uuid, "view")
    doc = _doc(case, did)
    if current_user.role not in ("legal", "sho", "admin", "super_admin"):
        abort(403)
    form = ReviewForm()
    if not form.validate_on_submit() or len((form.body.data or "").strip()) < 10:
        flash(translate("form.fix"), "danger")
        return redirect(url_for("documents.preview", uuid=case.uuid, did=doc.uuid))
    db.session.add(
        DocumentReviewNote(
            generated_document_id=doc.id,
            author_id=current_user.id,
            body=form.body.data.strip()[:4000],
            status=form.status.data or "reviewed_ok",
        )
    )
    for uid in {case.assigned_io_id, doc.created_by_id}:
        if uid and uid != current_user.id:
            db.session.add(
                Notification(
                    user_id=uid,
                    title="Document review comment",
                    body=f"{TITLES.get(doc.doc_type)} - {form.status.data}",
                    link_path=f"/cases/{case.uuid}/documents/{doc.uuid}",
                )
            )
    db.session.commit()
    write_audit("document.review_commented", object_type="generated_document", object_id=doc.uuid, case_id=case.id)
    flash(translate("flash.doc_review_saved"), "success")
    return redirect(url_for("documents.preview", uuid=case.uuid, did=doc.uuid))


def _enqueue_identify(user, generated=None, upload=None, case_id=None):
    from app.models.document import ClauseAnalysis
    from app.services.task_service import enqueue_job
    from app.tasks.ai_tasks import run_identify_clauses

    row = ClauseAnalysis(
        generated_id=generated.id if generated else None,
        document_id=upload.id if upload else None,
        case_id=case_id,
        user_id=user.id,
        language=(generated.language if generated else "en"),
    )
    db.session.add(row)
    db.session.commit()
    job = enqueue_job(
        user,
        "crimegpt.identify_clauses",
        run_identify_clauses,
        extra={"analysis_id": row.id, "user_id": user.id},
        case_id=case_id,
    )
    row.job_id = job.id
    db.session.commit()
    return job
