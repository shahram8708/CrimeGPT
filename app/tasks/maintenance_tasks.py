from datetime import timedelta
from pathlib import Path

from flask import current_app

from app.extensions import celery, db
from app.models import ApplicationSetting, Case
from app.models.evidence import EvidenceItem
from app.models.mixins import utcnow
from app.services.file_service import file_service, generated_files


def _retention_days():
    raw = ApplicationSetting.get("retention_days", "365")
    try:
        return max(int(raw), 30)
    except (TypeError, ValueError):
        return 365


def purge_tombstoned():
    cutoff = utcnow() - timedelta(days=_retention_days())
    removed = 0
    cases = Case.query.filter(Case.deleted_at.isnot(None), Case.deleted_at < cutoff).all()
    for case in cases:
        items = EvidenceItem.query.filter_by(case_id=case.id).all()
        for item in items:
            if item.stored_path:
                try:
                    file_service.delete(item.stored_path)
                except Exception:
                    current_app.logger.exception("purge evidence")
            if item.thumbnail_path:
                try:
                    file_service.delete(item.thumbnail_path)
                except Exception:
                    pass
            db.session.delete(item)
            removed += 1
        from app.models.document import GeneratedDocument

        for doc in GeneratedDocument.query.filter_by(case_id=case.id).all():
            for key in (doc.docx_path, doc.pdf_path):
                if key:
                    try:
                        generated_files.delete(key)
                    except Exception:
                        pass
            db.session.delete(doc)
            removed += 1
    db.session.commit()
    return {"ok": True, "purged": removed, "cutoff": cutoff.isoformat()}


@celery.task(name="crimegpt.purge_tombstoned")
def purge_tombstoned_task():
    return purge_tombstoned()
