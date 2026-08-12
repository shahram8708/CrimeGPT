import time

from flask import current_app

from app.extensions import celery, db
from app.models import CeleryJob, Notification
from app.models.mixins import utcnow
from app.services.audit_service import write_audit
from app.utils.file_utils import ensure_directories
from app.utils.formatting_utils import sanitize_error


def _load_job(job_uuid):
    return CeleryJob.query.filter_by(uuid=job_uuid).first()


def _update(job, status=None, progress=None, message=None, error=None, finished=False):
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


def run_system_ping(job_uuid):
    job = _load_job(job_uuid)
    if job is None:
        return {"ok": False, "error": "job not found"}
    try:
        _update(job, status="processing", progress=10, message="Starting system check")
        time.sleep(0.35)

        db.session.execute(db.text("SELECT 1"))
        _update(job, progress=25, message="Checking database")
        time.sleep(0.35)

        ensure_directories(current_app._get_current_object())
        _update(job, progress=50, message="Checking storage folders")
        time.sleep(0.35)

        write_audit(
            "job.ping_check",
            object_type="celery_job",
            object_id=job.uuid,
            actor=job.user,
            station_id=job.user.station_id if job.user else None,
            meta={"task": "crimegpt.system_ping"},
        )
        _update(job, progress=75, message="Writing audit")

        note = Notification(
            user_id=job.user_id,
            title="System ping completed",
            body="The platform health check finished successfully.",
            link_path=f"/jobs/{job.uuid}",
        )
        db.session.add(note)
        _update(job, status="completed", progress=100, message="System check completed", finished=True)
        return {"ok": True, "job": job_uuid}
    except Exception as exc:
        current_app.logger.exception("system ping failed")
        db.session.rollback()
        job = _load_job(job_uuid)
        if job:
            _update(
                job,
                status="failed",
                message="System check failed",
                error=sanitize_error(exc),
                finished=True,
            )
            note = Notification(
                user_id=job.user_id,
                title="System ping failed",
                body="The platform health check did not finish. Open the job page for details.",
                link_path=f"/jobs/{job.uuid}",
            )
            db.session.add(note)
            db.session.commit()
        return {"ok": False, "error": sanitize_error(exc)}


@celery.task(name="crimegpt.system_ping", bind=True)
def system_ping(self, job_uuid):
    return run_system_ping(job_uuid)
