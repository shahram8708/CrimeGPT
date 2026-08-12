from io import BytesIO

from flask import current_app

from app.extensions import celery, db
from app.models import CeleryJob, Notification
from app.models.evidence import DiaryExport, EvidenceItem
from app.models.mixins import utcnow
from app.services.file_service import file_service
from app.utils.formatting_utils import sanitize_error


def _job(job_uuid):
    return CeleryJob.query.filter_by(uuid=job_uuid).first()


def _mark(job, status=None, progress=None, message=None, error=None, finished=False):
    if status:
        job.status = status
    if progress is not None:
        job.progress = progress
    if message is not None:
        job.progress_message = message
    if error is not None:
        job.error_message = error
    if status == "processing" and job.started_at is None:
        job.started_at = utcnow()
    if finished:
        job.finished_at = utcnow()
    db.session.commit()


def _pdf_glyph():
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (400, 280), (11, 31, 58))
    draw = ImageDraw.Draw(img)
    draw.rectangle([120, 40, 280, 240], fill=(247, 244, 238), outline=(196, 163, 90), width=3)
    draw.polygon([(220, 40), (280, 40), (280, 100)], fill=(196, 163, 90))
    draw.text((155, 130), "PDF", fill=(11, 31, 58))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def run_process_evidence(job_uuid, evidence_id=None):
    job = _job(job_uuid)
    if job is None:
        return {"ok": False}
    try:
        _mark(job, status="processing", progress=10, message="Queued for processing")
        item = db.session.get(EvidenceItem, int(evidence_id))
        if item is None or item.deleted_at:
            raise RuntimeError("Evidence row missing")
        raw = file_service.get(item.stored_path)
        if raw is None:
            raise RuntimeError("File purged or not yet ready")
        _mark(job, progress=50, message="Processing file")
        mime = item.mime or ""
        if mime.startswith("image/"):
            from PIL import Image

            src = Image.open(BytesIO(raw))
            src.load()
            if not item.keep_exif:
                cleaned = Image.new(src.mode, src.size)
                cleaned.putdata(list(src.getdata()))
                out = BytesIO()
                fmt = "JPEG" if "jpeg" in mime else "PNG"
                if fmt == "JPEG" and cleaned.mode not in ("RGB", "L"):
                    cleaned = cleaned.convert("RGB")
                cleaned.save(out, format=fmt)
                file_service.put(out.getvalue(), item.stored_path)
                src = cleaned
            thumb = src.copy()
            if thumb.mode not in ("RGB", "L"):
                thumb = thumb.convert("RGB")
            thumb.thumbnail((400, 400))
            tbuf = BytesIO()
            thumb.save(tbuf, format="JPEG", quality=82)
            tkey = item.stored_path.rsplit(".", 1)[0] + "_thumb.jpg"
            file_service.put(tbuf.getvalue(), tkey)
            item.thumbnail_path = tkey
        else:
            tkey = item.stored_path.rsplit(".", 1)[0] + "_thumb.jpg"
            file_service.put(_pdf_glyph(), tkey)
            item.thumbnail_path = tkey
        db.session.commit()
        _mark(job, status="completed", progress=100, message="Processing complete", finished=True)
        return {"ok": True}
    except Exception as exc:
        current_app.logger.exception("process_evidence failed")
        db.session.rollback()
        job = _job(job_uuid)
        if job:
            _mark(
                job,
                status="failed",
                message="Could not process the file",
                error=sanitize_error(exc),
                finished=True,
            )
            note = Notification(
                user_id=job.user_id,
                title="Evidence processing failed",
                body="The original file is still stored. Open the exhibit for details.",
                link_path="/cases",
            )
            db.session.add(note)
            db.session.commit()
        return {"ok": False, "error": sanitize_error(exc)}


def run_export_diary(job_uuid, export_id=None):
    job = _job(job_uuid)
    if job is None:
        return {"ok": False}
    try:
        _mark(job, status="processing", progress=10, message="Queued for diary extract")
        exp = db.session.get(DiaryExport, int(export_id))
        if exp is None:
            raise RuntimeError("Export row missing")
        _mark(job, progress=25, message="Loading diary entries")
        from app.services.docx_service import _entries, render_diary_docx
        from app.services.pdf_service import render_diary_pdf

        if getattr(exp, "summarize", False):
            _mark(job, progress=40, message="Summarizing for court")
            try:
                from app.services.gemini_service import GeminiError, gemini_configured
                from app.services.intel_service import increment_gemini_calls

                if gemini_configured():
                    from app.services import gemini_service

                    bits = []
                    for entry in _entries(exp):
                        bits.append(f"{entry.occurred_at} [{entry.entry_type}] {entry.body}")
                    result = gemini_service.summarize_diary("\n".join(bits), language=exp.language or "en")
                    exp.summary_text = result.get("summary") or ""
                    exp.summarize_error = None
                    from app.models import User

                    increment_gemini_calls(db.session.get(User, job.user_id), exp.case)
                else:
                    exp.summarize_error = "Gemini is not configured. Extract has full entries only."
            except Exception:
                current_app.logger.exception("diary summarize failed")
                exp.summarize_error = "Summary failed. Extract still has every full entry."
                exp.summary_text = None
        _mark(job, progress=75, message="Rendering extract")
        docx_key, pdf_key = render_diary_docx(exp), None
        pdf_key = render_diary_pdf(exp)
        exp.docx_path = docx_key
        exp.pdf_path = pdf_key
        job.result_ref_table = "diary_exports"
        job.result_ref_id = exp.id
        db.session.commit()
        done_msg = "Diary extract ready"
        if getattr(exp, "summarize", False) and exp.summarize_error:
            done_msg = "Diary extract ready without summary"
        _mark(job, status="completed", progress=100, message=done_msg, finished=True)
        note = Notification(
            user_id=job.user_id,
            title="Diary extract ready",
            body="DOCX and PDF are ready to download.",
            link_path=f"/cases/{exp.case.uuid}/diary/exports/{exp.uuid}",
        )
        db.session.add(note)
        db.session.commit()
        return {"ok": True}
    except Exception as exc:
        current_app.logger.exception("export_diary failed")
        db.session.rollback()
        job = _job(job_uuid)
        if job:
            _mark(
                job,
                status="failed",
                message="Diary extract failed",
                error=sanitize_error(exc),
                finished=True,
            )
        return {"ok": False, "error": sanitize_error(exc)}


@celery.task(name="crimegpt.process_evidence")
def process_evidence_task(job_uuid, evidence_id=None):
    return run_process_evidence(job_uuid, evidence_id=evidence_id)


@celery.task(name="crimegpt.export_diary")
def export_diary_task(job_uuid, export_id=None):
    return run_export_diary(job_uuid, export_id=export_id)


def run_generate_document(job_uuid, document_id=None, user_id=None):
    import json
    import time

    from app.models import User
    from app.models.document import GeneratedDocument
    from app.services.document_service import build_context, increment_doc_generations
    from app.services.gemini_service import GeminiError, RetryableGeminiError
    from app.services.intel_service import increment_gemini_calls

    job = _job(job_uuid)
    if job is None:
        return {"ok": False}
    user = db.session.get(User, int(user_id)) if user_id else db.session.get(User, job.user_id)
    row = db.session.get(GeneratedDocument, int(document_id)) if document_id else None
    if row is None:
        _mark(job, status="failed", message="Document row missing", error="Document row missing", finished=True)
        return {"ok": False}
    try:
        _mark(job, status="processing", progress=10, message="Queued")
        opts = {}
        if row.context_json:
            try:
                opts = json.loads(row.context_json)
            except (TypeError, ValueError):
                opts = {}
        _mark(job, progress=25, message="Loading the case pool")
        use_ai = bool(opts.get("use_ai"))
        ai_block = opts.get("edited_ai") or {}
        ai_error = None
        if use_ai and not ai_block:
            _mark(job, progress=50, message="Drafting narrative paragraphs")
            delays = (0, 10, 40)
            drafted = None
            last = None
            from app.services import gemini_service

            for attempt, wait in enumerate(delays):
                if wait and not current_app.config.get("TESTING"):
                    time.sleep(wait)
                try:
                    drafted = gemini_service.draft_document_paragraphs(
                        row.doc_type,
                        {"gist": (row.case.narrative or "")[:1200], "cr": row.case.display_cr},
                        language=row.language,
                    )
                    last = None
                    break
                except RetryableGeminiError as exc:
                    last = exc
                    if attempt == len(delays) - 1:
                        break
                except GeminiError as exc:
                    last = exc
                    break
            if drafted:
                ai_block = drafted.get("paragraphs") or {}
                increment_gemini_calls(user, row.case)
            else:
                use_ai = False
                ai_error = "Narrative draft failed; generated from template fields only."
                if last:
                    ai_error = f"Narrative draft failed: {last}; generated from template fields only."
                    current_app.logger.warning("AI draft failed for doc %s: %s", row.uuid, last)
        _mark(job, progress=75, message="Building DOCX and PDF")
        options = {
            "language": row.language,
            "accused_ids": opts.get("accused_ids") or [],
            "custody_hours_sought": opts.get("custody_hours_sought") or "",
            "court_name": opts.get("court_name") or "",
            "grounds": opts.get("grounds") or "",
            "investigation_gist": opts.get("investigation_gist") or "",
            "production_at": opts.get("production_at") or "",
            "description": opts.get("description") or "",
            "date_from": opts.get("date_from") or "",
            "date_to": opts.get("date_to") or "",
            "request_target": opts.get("request_target") or "",
            "is_incomplete": row.is_incomplete,
            "ai": ai_block,
        }
        ctx = build_context(row.case, row.doc_type, user, options)
        from app.services.docx_service import render_court_docx
        from app.services.pdf_service import render_court_pdf

        docx_key = render_court_docx(row, ctx)
        pdf_key = render_court_pdf(row, ctx)
        row.docx_path = docx_key
        row.pdf_path = pdf_key
        row.ai_used = bool(use_ai and ai_block)
        row.ai_error = ai_error
        ctx["ai"] = ai_block
        row.context_json = json.dumps(ctx, ensure_ascii=False)
        row.status = "completed"
        job.result_ref_table = "generated_documents"
        job.result_ref_id = row.id
        increment_doc_generations(user, row.case)
        db.session.add(
            Notification(
                user_id=user.id,
                title="Document ready",
                body=f"{row.doc_type} v{row.version_number} is ready to preview.",
                link_path=f"/cases/{row.case.uuid}/documents/{row.uuid}",
            )
        )
        from app.services.audit_service import write_audit

        write_audit(
            "document.generated",
            object_type="generated_document",
            object_id=row.uuid,
            actor=user,
            station_id=row.case.station_id,
            case_id=row.case_id,
            meta={"type": row.doc_type, "ai": row.ai_used},
        )
        db.session.commit()
        _mark(job, status="completed", progress=100, message="Done", finished=True)
        return {"ok": True}
    except Exception as exc:
        current_app.logger.exception("generate_document failed")
        db.session.rollback()
        job = _job(job_uuid)
        row = db.session.get(GeneratedDocument, int(document_id)) if document_id else None
        if row:
            row.status = "failed"
            row.ai_error = sanitize_error(exc)
            db.session.commit()
        if job:
            _mark(job, status="failed", message=sanitize_error(exc), error=sanitize_error(exc), finished=True)
            db.session.add(
                Notification(
                    user_id=job.user_id,
                    title="Document generation failed",
                    body=sanitize_error(exc),
                    link_path=f"/jobs/{job.uuid}?stay=1",
                )
            )
            db.session.commit()
        return {"ok": False, "error": sanitize_error(exc)}


@celery.task(
    name="crimegpt.generate_document",
    autoretry_for=(),
    soft_time_limit=120,
    time_limit=180,
)
def generate_document_task(job_uuid, document_id=None, user_id=None):
    return run_generate_document(job_uuid, document_id=document_id, user_id=user_id)
