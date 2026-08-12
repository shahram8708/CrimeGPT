import threading

import json

from flask import current_app

from app.extensions import db
from app.models import CeleryJob
from app.services.audit_service import write_audit
from app.utils.formatting_utils import sanitize_error

SAFE_PAYLOAD_KEYS = (
    "suggestion_id",
    "user_id",
    "document_id",
    "export_id",
    "compare_id",
    "analysis_id",
    "thread_id",
    "translate_id",
    "checklist_id",
    "gap_id",
    "evidence_id",
    "use_ai",
    "language",
)


def _broker_needs_fallback(broker):
    broker = (broker or "").strip().lower()
    return (not broker) or broker.startswith("memory://") or broker.startswith("cache+")


def _run_in_thread(app, runner, job_uuid, extra):
    with app.app_context():
        runner(job_uuid, **extra)


def enqueue_job(user, task_name, runner, extra=None, case_id=None):
    extra = extra or {}
    safe = {k: extra[k] for k in SAFE_PAYLOAD_KEYS if k in extra}
    job = CeleryJob(
        user_id=user.id,
        case_id=case_id,
        task_name=task_name,
        status="queued",
        progress=0,
        progress_message="Queued",
        payload_json=json.dumps(safe, default=str) if safe else None,
    )
    db.session.add(job)
    db.session.commit()
    write_audit(
        "job.enqueued",
        object_type="celery_job",
        object_id=job.uuid,
        actor=user,
        station_id=user.station_id,
        case_id=case_id,
        meta={"task": task_name},
    )
    broker = current_app.config.get("CELERY_BROKER_URL", "memory://")
    launched = False
    if not _broker_needs_fallback(broker):
        try:
            from app.tasks.ai_tasks import (
                analyze_document_task,
                compare_documents_task,
                gap_analysis_task,
                generate_checklist_task,
                identify_clauses_task,
                legal_intel_task,
                qa_turn_task,
                translate_task,
            )
            from app.tasks.document_tasks import export_diary_task, generate_document_task, process_evidence_task
            from app.tasks.system_tasks import system_ping

            celery_map = {
                "crimegpt.system_ping": system_ping,
                "crimegpt.process_evidence": process_evidence_task,
                "crimegpt.export_diary": export_diary_task,
                "crimegpt.legal_intel": legal_intel_task,
                "crimegpt.generate_document": generate_document_task,
                "crimegpt.compare_documents": compare_documents_task,
                "crimegpt.identify_clauses": identify_clauses_task,
                "crimegpt.qa_turn": qa_turn_task,
                "crimegpt.analyze_document": analyze_document_task,
                "crimegpt.translate": translate_task,
                "crimegpt.generate_checklist": generate_checklist_task,
                "crimegpt.gap_analysis": gap_analysis_task,
            }
            task = celery_map.get(task_name)
            if task is not None:
                async_result = task.apply_async(args=[job.uuid], kwargs=extra)
                job.celery_task_id = async_result.id
                db.session.commit()
                launched = True
        except Exception as exc:
            current_app.logger.warning("celery apply_async failed: %s", sanitize_error(exc))
            launched = False
    if not launched:
        env_name = current_app.config.get("ENV_NAME", "development")
        if env_name == "production":
            job.status = "failed"
            job.error_message = "Background worker unavailable"
            job.progress_message = "Could not reach the job broker"
            db.session.commit()
        else:
            app_obj = current_app._get_current_object()
            thread = threading.Thread(
                target=_run_in_thread,
                args=(app_obj, runner, job.uuid, extra),
                daemon=True,
                name=f"job-{job.uuid[:8]}",
            )
            thread.start()
            if current_app.config.get("TESTING"):
                thread.join(timeout=30)
    return job


def celery_runners():
    from app.tasks.ai_tasks import (
        analyze_document_task,
        compare_documents_task,
        gap_analysis_task,
        generate_checklist_task,
        identify_clauses_task,
        legal_intel_task,
        qa_turn_task,
        run_analyze_document,
        run_compare_documents,
        run_gap_analysis,
        run_generate_checklist,
        run_identify_clauses,
        run_legal_intel,
        run_qa_turn,
        run_translate,
        translate_task,
    )
    from app.tasks.document_tasks import (
        export_diary_task,
        generate_document_task,
        process_evidence_task,
        run_export_diary,
        run_generate_document,
        run_process_evidence,
    )
    from app.tasks.system_tasks import run_system_ping, system_ping

    return {
        "crimegpt.system_ping": (system_ping, run_system_ping),
        "crimegpt.process_evidence": (process_evidence_task, run_process_evidence),
        "crimegpt.export_diary": (export_diary_task, run_export_diary),
        "crimegpt.legal_intel": (legal_intel_task, run_legal_intel),
        "crimegpt.generate_document": (generate_document_task, run_generate_document),
        "crimegpt.compare_documents": (compare_documents_task, run_compare_documents),
        "crimegpt.identify_clauses": (identify_clauses_task, run_identify_clauses),
        "crimegpt.qa_turn": (qa_turn_task, run_qa_turn),
        "crimegpt.analyze_document": (analyze_document_task, run_analyze_document),
        "crimegpt.translate": (translate_task, run_translate),
        "crimegpt.generate_checklist": (generate_checklist_task, run_generate_checklist),
        "crimegpt.gap_analysis": (gap_analysis_task, run_gap_analysis),
    }


def retry_failed_job(user, job):
    if job is None or job.status != "failed":
        raise RuntimeError("not_failed")
    extra = {}
    if job.payload_json:
        try:
            extra = json.loads(job.payload_json) or {}
        except (TypeError, ValueError):
            extra = {}
    extra.setdefault("user_id", user.id)
    pair = celery_runners().get(job.task_name)
    if pair is None:
        raise RuntimeError("unknown_task")
    _, runner = pair
    return enqueue_job(user, job.task_name, runner, extra=extra, case_id=job.case_id)


def enqueue_system_ping(user):
    from app.tasks.system_tasks import run_system_ping

    return enqueue_job(user, "crimegpt.system_ping", run_system_ping)
