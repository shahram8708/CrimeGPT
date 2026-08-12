import time

from flask import current_app

from app.extensions import celery, db
from app.models import Notification, User
from app.models.ai import LegalSuggestion
from app.models.mixins import utcnow
from app.services.gemini_service import GeminiError, RetryableGeminiError
from app.services.intel_service import (
    find_cache,
    increment_gemini_calls,
    prepare_prompt_bundle,
    quota_reached,
    record_interaction,
    save_completed,
)
from app.utils.formatting_utils import sanitize_error


def _job(job_uuid):
    from app.models import CeleryJob

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


def _fail(job, user, message, error_class=None, title=None):
    _mark(job, status="failed", message=message, error=message, finished=True)
    if user:
        db.session.add(
            Notification(
                user_id=user.id,
                title=title or "Job failed",
                body=message,
                link_path=f"/jobs/{job.uuid}?stay=1",
            )
        )
        db.session.commit()


def run_legal_intel(job_uuid, suggestion_id=None, user_id=None):
    job = _job(job_uuid)
    if job is None:
        return {"ok": False}
    user = db.session.get(User, int(user_id)) if user_id else None
    if user is None:
        user = db.session.get(User, job.user_id)
    try:
        _mark(job, status="processing", progress=10, message="Queued for legal mapping")
        sugg = db.session.get(LegalSuggestion, int(suggestion_id)) if suggestion_id else None
        if sugg is None:
            raise RuntimeError("Suggestion row missing")
        _mark(job, progress=25, message="Loading the narrative")
        cached = find_cache(sugg.station_id, sugg.narrative_hash)
        if cached and cached.id != sugg.id and cached.result_json:
            import json

            data = json.loads(cached.result_json)
            sugg.result_json = cached.result_json
            sugg.overall_confidence = cached.overall_confidence
            record_interaction(user, sugg, job, success=True, cached=True)
            save_completed(user, sugg, job, data, cached=True)
            db.session.commit()
            _mark(job, status="completed", progress=100, message="Completed", finished=True)
            return {"ok": True, "cached": True}

        if quota_reached(user, sugg.case):
            record_interaction(user, sugg, job, success=False, error_class="quota")
            db.session.commit()
            _fail(job, user, "Station AI quota reached for today.")
            return {"ok": False, "error": "quota"}

        _mark(job, progress=50, message="Reading the incident narrative")
        from app.services import gemini_service

        narrative, facts = prepare_prompt_bundle(sugg.case, sugg.narrative_snapshot)
        delays = (0, 3, 6)
        last_err = None
        result = None
        for attempt, wait in enumerate(delays):
            if wait and not current_app.config.get("TESTING"):
                time.sleep(wait)
            try:
                result = gemini_service.legal_intel(
                    narrative,
                    language=sugg.language,
                    focus=sugg.focus,
                    use_search=bool(sugg.use_search),
                    case_facts=facts,
                )
                last_err = None
                break
            except RetryableGeminiError as exc:
                last_err = exc
                current_app.logger.warning("legal_intel attempt %d failed with retryable error: %s", attempt + 1, exc)
                if attempt == len(delays) - 1:
                    raise
            except GeminiError:
                raise
        if result is None and last_err:
            raise last_err

        _mark(job, progress=75, message="Storing structured suggestions")
        increment_gemini_calls(user, sugg.case)
        record_interaction(user, sugg, job, success=True, result=result, cached=False)
        save_completed(user, sugg, job, result["normalized"], cached=False)
        db.session.commit()
        _mark(job, status="completed", progress=100, message="Completed", finished=True)
        return {"ok": True}
    except GeminiError as exc:
        current_app.logger.exception("legal_intel parse or model error")
        db.session.rollback()
        job = _job(job_uuid)
        user = db.session.get(User, job.user_id) if job else user
        sugg = db.session.get(LegalSuggestion, int(suggestion_id)) if suggestion_id else None
        if job:
            record_interaction(user, sugg, job, success=False, error_class=type(exc).__name__)
            db.session.commit()
            _fail(job, user, f"AI legal analysis error: {sanitize_error(exc)}. Please try again.")
        return {"ok": False, "error": sanitize_error(exc)}
    except Exception as exc:
        current_app.logger.exception("legal_intel failed")
        db.session.rollback()
        job = _job(job_uuid)
        user = db.session.get(User, job.user_id) if job else user
        sugg = db.session.get(LegalSuggestion, int(suggestion_id)) if suggestion_id else None
        if job:
            record_interaction(user, sugg, job, success=False, error_class=type(exc).__name__)
            db.session.commit()
            _fail(job, user, f"Task processing failed: {sanitize_error(exc)}")
        return {"ok": False, "error": sanitize_error(exc)}


@celery.task(
    name="crimegpt.legal_intel",
    autoretry_for=(RetryableGeminiError,),
    retry_backoff=5,
    retry_backoff_max=60,
    max_retries=3,
    soft_time_limit=180,
    time_limit=240,
)
def legal_intel_task(job_uuid, suggestion_id=None, user_id=None):
    return run_legal_intel(job_uuid, suggestion_id=suggestion_id, user_id=user_id)


def _load_side(kind, ref):
    import json

    from app.models.document import GeneratedDocument, LibraryDocument
    from app.services.compare_service import extract_file_text, extract_generated_text
    from app.services.document_service import parse_ctx
    from app.services.file_service import file_service

    if kind == "generated":
        row = GeneratedDocument.query.filter_by(uuid=ref).first()
        if row is None:
            return None, "", None
        ctx = parse_ctx(row)
        return row, extract_generated_text(ctx), ctx
    row = LibraryDocument.query.filter_by(uuid=ref).first()
    if row is None:
        return None, "", None
    data = file_service.get(row.stored_path) or b""
    return row, extract_file_text(data, row.mime, row.original_filename), None


def run_compare_documents(job_uuid, compare_id=None, user_id=None):
    import json

    from app.models.document import CompareResult
    from app.services.compare_service import deterministic_compare
    from app.services.gemini_service import GeminiError, gemini_configured
    from app.services.intel_service import increment_gemini_calls

    job = _job(job_uuid)
    if job is None:
        return {"ok": False}
    row = db.session.get(CompareResult, int(compare_id)) if compare_id else None
    user = db.session.get(User, job.user_id)
    if row is None:
        _fail(job, user, "Compare row missing")
        return {"ok": False}
    try:
        _mark(job, status="processing", progress=20, message="Loading both papers")
        _, left_text, left_ctx = _load_side(row.left_kind, row.left_ref)
        _, right_text, right_ctx = _load_side(row.right_kind, row.right_ref)
        det = deterministic_compare(left_ctx or {}, right_ctx or {})
        from app.services.compare_service import compute_text_diff
        text_diff = compute_text_diff(left_text, right_text)
        ai = None
        if gemini_configured() and (left_text or right_text):
            _mark(job, progress=60, message="Reading both texts")
            try:
                from app.services import gemini_service

                ai = gemini_service.compare_documents(left_text, right_text, language=row.language)
                increment_gemini_calls(user, None)
            except (GeminiError, Exception) as exc:
                current_app.logger.warning("ai compare_documents error: %s", exc)
                ai = None
        payload = {
            "deterministic": det,
            "text_diff": text_diff,
            "ai": ai,
            "disclaimer": det.get("disclaimer") if det else "",
        }
        row.result_json = json.dumps(payload, ensure_ascii=False)
        job.result_ref_table = "compare_results"
        job.result_ref_id = row.id
        db.session.add(
            Notification(
                user_id=user.id,
                title="Compare ready",
                body="Structured document compare is ready.",
                link_path=f"/results/compare/{row.uuid}",
            )
        )
        db.session.commit()
        _mark(job, status="completed", progress=100, message="Done", finished=True)
        return {"ok": True}
    except Exception as exc:
        current_app.logger.exception("compare failed")
        _fail(job, user, sanitize_error(exc))
        return {"ok": False}


def run_identify_clauses(job_uuid, analysis_id=None, user_id=None):
    import json

    from app.models.document import ClauseAnalysis
    from app.services.compare_service import deterministic_identify, extract_file_text, extract_generated_text
    from app.services.document_service import parse_ctx
    from app.services.file_service import file_service
    from app.services.gemini_service import GeminiError, gemini_configured
    from app.services.intel_service import increment_gemini_calls

    job = _job(job_uuid)
    if job is None:
        return {"ok": False}
    row = db.session.get(ClauseAnalysis, int(analysis_id)) if analysis_id else None
    user = db.session.get(User, job.user_id)
    if row is None:
        _fail(job, user, "Identify row missing")
        return {"ok": False}
    try:
        _mark(job, status="processing", progress=25, message="Reading the paper")
        text = ""
        ctx = None
        dtype = None
        if row.generated_id:
            ctx = parse_ctx(row.generated)
            dtype = row.generated.doc_type if row.generated else None
            text = extract_generated_text(ctx)
        elif row.document_id and row.upload:
            data = file_service.get(row.upload.stored_path) or b""
            text = extract_file_text(data, row.upload.mime, row.upload.original_filename)
        det = deterministic_identify(ctx or {}, dtype) if ctx is not None else {"blocks": [], "flags": {}}
        ai = None
        if gemini_configured() and text:
            _mark(job, progress=60, message="Mapping fields")
            try:
                from app.services import gemini_service

                ai = gemini_service.identify_clauses(text, language=row.language, case_json=ctx)
                increment_gemini_calls(user, None)
            except (GeminiError, Exception):
                ai = None
        payload = {"deterministic": det, "ai": ai, "disclaimer": det.get("disclaimer")}
        row.result_json = json.dumps(payload, ensure_ascii=False)
        job.result_ref_table = "clause_analyses"
        job.result_ref_id = row.id
        db.session.add(
            Notification(
                user_id=user.id,
                title="Clause map ready",
                body="Field and defect map is ready.",
                link_path=f"/results/identify/{row.uuid}",
            )
        )
        db.session.commit()
        _mark(job, status="completed", progress=100, message="Done", finished=True)
        return {"ok": True}
    except Exception as exc:
        current_app.logger.exception("identify failed")
        _fail(job, user, sanitize_error(exc))
        return {"ok": False}


@celery.task(name="crimegpt.compare_documents", soft_time_limit=90, time_limit=120)
def compare_documents_task(job_uuid, compare_id=None, user_id=None):
    return run_compare_documents(job_uuid, compare_id=compare_id, user_id=user_id)


@celery.task(name="crimegpt.identify_clauses", soft_time_limit=90, time_limit=120)
def identify_clauses_task(job_uuid, analysis_id=None, user_id=None):
    return run_identify_clauses(job_uuid, analysis_id=analysis_id, user_id=user_id)


def run_qa_turn(job_uuid, thread_id=None, user_id=None):
    import json
    import time

    from app.models.ai import QaMessage, QaThread
    from app.services.intel_service import increment_gemini_calls
    from app.services.qa_service import redacted_case_brief, save_thread_result

    job = _job(job_uuid)
    if job is None:
        return {"ok": False}
    user = db.session.get(User, job.user_id)
    thread = db.session.get(QaThread, int(thread_id)) if thread_id else None
    if thread is None:
        _fail(job, user, "Thread missing", title="Q&A failed")
        return {"ok": False}
    try:
        _mark(job, status="processing", progress=20, message="Reading the notebook")
        rows = thread.messages.order_by(QaMessage.id.asc()).all()
        payload = [{"role": m.role, "body": m.body} for m in rows]
        brief = redacted_case_brief(thread.case) if thread.case_id else ""
        from app.services import gemini_service

        last = None
        result = None
        for attempt, wait in enumerate((0, 8)):
            if wait and not current_app.config.get("TESTING"):
                time.sleep(wait)
            try:
                result = gemini_service.qa_turn(payload, case_brief=brief, language="en", use_search=True)
                last = None
                break
            except RetryableGeminiError as exc:
                last = exc
                if attempt:
                    raise
            except GeminiError:
                raise
        if result is None and last:
            raise last
        _mark(job, progress=80, message="Storing the answer")
        increment_gemini_calls(user, thread.case)
        assistant = QaMessage(
            thread_id=thread.id,
            role="assistant",
            body=result.get("answer") or "",
            job_id=job.id,
            refusal=bool(result.get("refusal")),
            citations_json=json.dumps(result.get("citations") or [], ensure_ascii=False),
            followups_json=json.dumps(result.get("suggested_followups") or [], ensure_ascii=False),
        )
        db.session.add(assistant)
        save_thread_result(user, thread)
        job.result_ref_table = "qa_threads"
        job.result_ref_id = thread.id
        db.session.add(
            Notification(
                user_id=user.id,
                title="Q&A reply ready",
                body=thread.title or "Notebook reply",
                link_path=f"/tools/qa/{thread.uuid}",
            )
        )
        db.session.commit()
        _mark(job, status="completed", progress=100, message="Completed", finished=True)
        return {"ok": True}
    except GeminiError:
        current_app.logger.exception("qa_turn model error")
        db.session.rollback()
        job = _job(job_uuid)
        user = db.session.get(User, job.user_id) if job else user
        if job:
            _fail(job, user, "The model returned unreadable output. Nothing was applied.", title="Q&A failed")
        return {"ok": False}
    except Exception as exc:
        current_app.logger.exception("qa_turn failed")
        db.session.rollback()
        job = _job(job_uuid)
        user = db.session.get(User, job.user_id) if job else user
        if job:
            _fail(job, user, sanitize_error(exc), title="Q&A failed")
        return {"ok": False}


@celery.task(
    name="crimegpt.qa_turn",
    autoretry_for=(RetryableGeminiError,),
    retry_backoff=8,
    max_retries=1,
    soft_time_limit=70,
    time_limit=90,
)
def qa_turn_task(job_uuid, thread_id=None, user_id=None):
    return run_qa_turn(job_uuid, thread_id=thread_id, user_id=user_id)


def run_analyze_document(job_uuid, analysis_id=None, user_id=None):
    import json

    from app.models.ai import DocumentAnalysis
    from app.services.analysis_service import parsed_analysis, prepare_source, save_analysis_result
    from app.services.intel_service import compact_case_facts, increment_gemini_calls
    from app.services.playbook_service import case_graph

    job = _job(job_uuid)
    if job is None:
        return {"ok": False}
    user = db.session.get(User, job.user_id)
    row = db.session.get(DocumentAnalysis, int(analysis_id)) if analysis_id else None
    if row is None or row.document is None:
        _fail(job, user, "Analysis row missing", title="Analyse failed")
        return {"ok": False}
    try:
        _mark(job, status="processing", progress=20, message="Opening the file")
        src = prepare_source(row.document)
        facts = None
        if row.case_id and row.case:
            try:
                facts = case_graph(row.case)
            except Exception:
                facts = compact_case_facts(row.case)
        _mark(job, progress=55, message="Reading the paper")
        from app.services import gemini_service

        result = gemini_service.analyze_document(
            text=src.get("text") or "",
            image_bytes=src.get("bytes"),
            mime=src.get("mime"),
            case_json=facts,
            language=row.language or "en",
        )
        increment_gemini_calls(user, row.case)
        row.result_json = json.dumps(
            {
                "document_type": result.get("document_type"),
                "language": result.get("language"),
                "summary": result.get("summary"),
                "extracted_fields": result.get("extracted_fields"),
                "flags": result.get("flags"),
                "raw_limitations": result.get("raw_limitations"),
                "overall_confidence": result.get("overall_confidence"),
                "disclaimer": result.get("disclaimer"),
            },
            ensure_ascii=False,
        )
        row.document_type = result.get("document_type")
        row.summary = result.get("summary")
        row.language = result.get("language") or row.language
        row.overall_confidence = result.get("overall_confidence")
        save_analysis_result(user, row)
        job.result_ref_table = "document_analyses"
        job.result_ref_id = row.id
        db.session.add(
            Notification(
                user_id=user.id,
                title="Document analysis ready",
                body="Extracted fields are suggestions until you apply them.",
                link_path=f"/results/analysis/{row.uuid}",
            )
        )
        db.session.commit()
        _mark(job, status="completed", progress=100, message="Completed", finished=True)
        return {"ok": True}
    except GeminiError:
        current_app.logger.exception("analyze parse error")
        db.session.rollback()
        job = _job(job_uuid)
        user = db.session.get(User, job.user_id) if job else user
        if job:
            _fail(job, user, "The model returned unreadable output. Nothing was applied.", title="Analyse failed")
        return {"ok": False}
    except Exception as exc:
        current_app.logger.exception("analyze failed")
        db.session.rollback()
        job = _job(job_uuid)
        user = db.session.get(User, job.user_id) if job else user
        if job:
            _fail(job, user, sanitize_error(exc), title="Analyse failed")
        return {"ok": False}


@celery.task(name="crimegpt.analyze_document", soft_time_limit=160, time_limit=180)
def analyze_document_task(job_uuid, analysis_id=None, user_id=None):
    return run_analyze_document(job_uuid, analysis_id=analysis_id, user_id=user_id)


def run_translate(job_uuid, translate_id=None, user_id=None):
    import json

    from app.models.ai import SavedResult, TranslateResult
    from app.services.intel_service import increment_gemini_calls

    job = _job(job_uuid)
    if job is None:
        return {"ok": False}
    user = db.session.get(User, job.user_id)
    row = db.session.get(TranslateResult, int(translate_id)) if translate_id else None
    if row is None:
        _fail(job, user, "Translate row missing", title="Explain failed")
        return {"ok": False}
    try:
        _mark(job, status="processing", progress=30, message="Reading the text")
        from app.services import gemini_service

        result = gemini_service.translate(row.source_text, target_lang=row.target_lang, mode=row.mode)
        increment_gemini_calls(user, row.case)
        row.detected_language = result.get("detected_language")
        row.output_text = result.get("output_text")
        row.notes = result.get("notes")
        row.result_json = json.dumps(
            {
                "detected_language": row.detected_language,
                "output_text": row.output_text,
                "notes": row.notes,
                "disclaimer": result.get("disclaimer"),
            },
            ensure_ascii=False,
        )
        if not SavedResult.query.filter_by(user_id=user.id, ref_table="translate_results", ref_id=row.id).first():
            db.session.add(
                SavedResult(
                    user_id=user.id,
                    case_id=row.case_id,
                    result_type="translate",
                    ref_table="translate_results",
                    ref_id=row.id,
                    title=f"{row.mode} → {row.target_lang}"[:200],
                )
            )
        job.result_ref_table = "translate_results"
        job.result_ref_id = row.id
        db.session.add(
            Notification(
                user_id=user.id,
                title="Explain / translate ready",
                body="Plain-language output is ready for review.",
                link_path=f"/results/translate/{row.uuid}",
            )
        )
        db.session.commit()
        _mark(job, status="completed", progress=100, message="Completed", finished=True)
        return {"ok": True}
    except GeminiError:
        current_app.logger.exception("translate parse error")
        db.session.rollback()
        job = _job(job_uuid)
        user = db.session.get(User, job.user_id) if job else user
        if job:
            _fail(job, user, "The model returned unreadable output. Nothing was applied.", title="Explain failed")
        return {"ok": False}
    except Exception as exc:
        current_app.logger.exception("translate failed")
        db.session.rollback()
        job = _job(job_uuid)
        if job:
            _fail(job, db.session.get(User, job.user_id), sanitize_error(exc), title="Explain failed")
        return {"ok": False}


@celery.task(name="crimegpt.translate", soft_time_limit=90, time_limit=120)
def translate_task(job_uuid, translate_id=None, user_id=None):
    return run_translate(job_uuid, translate_id=translate_id, user_id=user_id)


def run_generate_checklist(job_uuid, checklist_id=None, user_id=None):
    from app.models.ai import LegalChecklist, LegalChecklistItem, SavedResult
    from app.services.intel_service import increment_gemini_calls
    from app.services.playbook_service import case_graph, map_deep_link

    job = _job(job_uuid)
    if job is None:
        return {"ok": False}
    user = db.session.get(User, job.user_id)
    row = db.session.get(LegalChecklist, int(checklist_id)) if checklist_id else None
    if row is None or row.case is None:
        _fail(job, user, "Checklist row missing", title="Checklist failed")
        return {"ok": False}
    try:
        _mark(job, status="processing", progress=30, message="Reading the case pool")
        graph = case_graph(row.case)
        from app.services import gemini_service

        result = gemini_service.generate_checklist(graph, category=row.case.category, language="en")
        increment_gemini_calls(user, row.case)
        row.title = result.get("title") or row.title
        LegalChecklistItem.query.filter_by(checklist_id=row.id).delete()
        for idx, item in enumerate(result.get("items") or []):
            href = map_deep_link(row.case, item.get("suggested_deep_link"))
            db.session.add(
                LegalChecklistItem(
                    checklist_id=row.id,
                    sort_order=idx,
                    label=item.get("label") or "Item",
                    why_text=item.get("why"),
                    severity=item.get("severity") or "medium",
                    deep_link=href,
                )
            )
        if not SavedResult.query.filter_by(user_id=user.id, ref_table="legal_checklists", ref_id=row.id).first():
            db.session.add(
                SavedResult(
                    user_id=user.id,
                    case_id=row.case_id,
                    result_type="checklist",
                    ref_table="legal_checklists",
                    ref_id=row.id,
                    title=(row.title or "Checklist")[:200],
                )
            )
        job.result_ref_table = "legal_checklists"
        job.result_ref_id = row.id
        db.session.add(
            Notification(
                user_id=user.id,
                title="Checklist ready",
                body="Tick items as you complete them. This is not a conviction score.",
                link_path=f"/cases/{row.case.uuid}/checklist",
            )
        )
        db.session.commit()
        _mark(job, status="completed", progress=100, message="Completed", finished=True)
        return {"ok": True}
    except GeminiError:
        current_app.logger.exception("checklist parse error")
        db.session.rollback()
        job = _job(job_uuid)
        if job:
            _fail(job, db.session.get(User, job.user_id), "The model returned unreadable output. Nothing was applied.", title="Checklist failed")
        return {"ok": False}
    except Exception as exc:
        current_app.logger.exception("checklist failed")
        db.session.rollback()
        job = _job(job_uuid)
        if job:
            _fail(job, db.session.get(User, job.user_id), sanitize_error(exc), title="Checklist failed")
        return {"ok": False}


@celery.task(name="crimegpt.generate_checklist", soft_time_limit=80, time_limit=110)
def generate_checklist_task(job_uuid, checklist_id=None, user_id=None):
    return run_generate_checklist(job_uuid, checklist_id=checklist_id, user_id=user_id)


def run_gap_analysis(job_uuid, gap_id=None, user_id=None):
    import json

    from app.models.ai import GapResult, SavedResult
    from app.services.gemini_service import GeminiError, gemini_configured
    from app.services.intel_service import increment_gemini_calls
    from app.services.playbook_service import case_graph, deterministic_gaps, load_playbook, map_deep_link, merge_gap_cards

    job = _job(job_uuid)
    if job is None:
        return {"ok": False}
    user = db.session.get(User, job.user_id)
    row = db.session.get(GapResult, int(gap_id)) if gap_id else None
    if row is None or row.case is None:
        _fail(job, user, "Gap row missing", title="Gap analysis failed")
        return {"ok": False}
    try:
        _mark(job, status="processing", progress=20, message="Loading the playbook")
        playbook = load_playbook(row.case.category)
        det = deterministic_gaps(row.case, playbook)
        model_cards = []
        limitations = []
        used_model = False
        if gemini_configured():
            _mark(job, progress=55, message="Comparing facts to the playbook")
            try:
                from app.services import gemini_service

                result = gemini_service.gap_analysis(case_graph(row.case), playbook, language="en")
                model_cards = result.get("cards") or []
                limitations = result.get("limitations") or []
                increment_gemini_calls(user, row.case)
                used_model = True
            except (GeminiError, Exception):
                limitations.append("Gemini cards were skipped. Deterministic playbook cards remain.")
        cards = merge_gap_cards(det, model_cards)
        for card in cards:
            href = map_deep_link(row.case, card.get("deep_link"))
            card["href"] = href
        payload = {
            "cards": cards,
            "limitations": limitations,
            "disclaimer": "AI-generated legal information may contain errors and should be verified against authoritative legal sources. This platform does not provide legal advice. For matters with significant legal consequences, please consult a qualified legal professional.",
            "used_model": used_model,
        }
        row.result_json = json.dumps(payload, ensure_ascii=False)
        if not SavedResult.query.filter_by(user_id=user.id, ref_table="gap_results", ref_id=row.id).first():
            db.session.add(
                SavedResult(
                    user_id=user.id,
                    case_id=row.case_id,
                    result_type="gap",
                    ref_table="gap_results",
                    ref_id=row.id,
                    title=f"Gaps - {row.case.display_cr}"[:200],
                )
            )
        job.result_ref_table = "gap_results"
        job.result_ref_id = row.id
        db.session.add(
            Notification(
                user_id=user.id,
                title="Gap analysis ready",
                body="Operational gaps only. Accept a card to put it on the checklist.",
                link_path=f"/cases/{row.case.uuid}/gaps",
            )
        )
        db.session.commit()
        _mark(job, status="completed", progress=100, message="Completed", finished=True)
        return {"ok": True}
    except Exception as exc:
        current_app.logger.exception("gap failed")
        db.session.rollback()
        job = _job(job_uuid)
        if job:
            _fail(job, db.session.get(User, job.user_id), sanitize_error(exc), title="Gap analysis failed")
        return {"ok": False}


@celery.task(name="crimegpt.gap_analysis", soft_time_limit=90, time_limit=120)
def gap_analysis_task(job_uuid, gap_id=None, user_id=None):
    return run_gap_analysis(job_uuid, gap_id=gap_id, user_id=user_id)
