import uuid

from app.extensions import db
from app.models.mixins import utcnow

JOB_STATUSES = ("queued", "processing", "completed", "failed")


class CeleryJob(db.Model):
    __tablename__ = "celery_jobs"
    __table_args__ = (
        db.Index("ix_celery_jobs_user_created", "user_id", "created_at"),
        db.Index("ix_celery_jobs_status", "status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    case_id = db.Column(db.Integer, nullable=True)
    task_name = db.Column(db.String(120), nullable=False)
    celery_task_id = db.Column(db.String(120))
    status = db.Column(db.String(24), nullable=False, default="queued")
    progress = db.Column(db.Integer, default=0, nullable=False)
    progress_message = db.Column(db.String(240))
    result_ref_table = db.Column(db.String(80))
    result_ref_id = db.Column(db.Integer)
    error_message = db.Column(db.String(400))
    is_starred = db.Column(db.Boolean, default=False, nullable=False)
    payload_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    started_at = db.Column(db.DateTime(timezone=True))
    finished_at = db.Column(db.DateTime(timezone=True))

    user = db.relationship("User", back_populates="jobs")

    def to_poll_dict(self):
        return {
            "status": self.status,
            "progress": self.progress or 0,
            "message": self.progress_message or "",
            "redirect": None,
            "error": self.error_message if self.status == "failed" else None,
        }
