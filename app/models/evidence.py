import uuid

from app.extensions import db
from app.models.mixins import TimestampMixin, utcnow

EVIDENCE_TAGS = ("exhibit", "scene", "injury", "property", "document", "other")
DIARY_TYPES = (
    "complaint",
    "visit",
    "witness",
    "seizure",
    "medical",
    "arrest",
    "court",
    "other",
    "evidence_note",
    "correction",
)


class EvidenceItem(TimestampMixin, db.Model):
    __tablename__ = "evidence_items"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False, index=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    case_item_id = db.Column(db.Integer, db.ForeignKey("case_items.id"), nullable=True)
    original_filename = db.Column(db.String(240))
    stored_name = db.Column(db.String(80), nullable=False)
    stored_path = db.Column(db.String(400), nullable=False)
    mime = db.Column(db.String(80))
    size_bytes = db.Column(db.Integer, default=0, nullable=False)
    caption = db.Column(db.String(300))
    tag = db.Column(db.String(40))
    exhibit_no = db.Column(db.String(20))
    taken_at = db.Column(db.DateTime(timezone=True))
    taken_by_label = db.Column(db.String(160))
    keep_exif = db.Column(db.Boolean, default=False, nullable=False)
    thumbnail_path = db.Column(db.String(400))
    deleted_at = db.Column(db.DateTime(timezone=True))

    case = db.relationship("Case", backref=db.backref("evidence_items", lazy="dynamic"))
    uploader = db.relationship("User", foreign_keys=[uploaded_by_id])
    case_item = db.relationship("CaseItem", foreign_keys=[case_item_id])


class CaseDiaryEntry(TimestampMixin, db.Model):
    __tablename__ = "case_diary_entries"
    __table_args__ = (db.Index("ix_diary_case_occurred", "case_id", "occurred_at"),)

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    entry_type = db.Column(db.String(30), nullable=False)
    occurred_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    place = db.Column(db.String(200))
    body = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="draft")
    corrects_entry_id = db.Column(db.Integer, db.ForeignKey("case_diary_entries.id"), nullable=True)
    generated_document_id = db.Column(db.Integer)
    evidence_json = db.Column(db.Text)

    case = db.relationship("Case", backref=db.backref("diary_entries", lazy="dynamic"))
    author = db.relationship("User", foreign_keys=[author_id])
    corrects = db.relationship("CaseDiaryEntry", remote_side="CaseDiaryEntry.id")


class CaseAssignment(db.Model):
    __tablename__ = "case_assignments"
    __table_args__ = (db.UniqueConstraint("case_id", "user_id", name="uq_case_assignment_user"),)

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    assigned_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    role_on_case = db.Column(db.String(32), default="constable", nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    case = db.relationship("Case", backref=db.backref("assignments", lazy="dynamic"))
    user = db.relationship("User", foreign_keys=[user_id])
    assigned_by = db.relationship("User", foreign_keys=[assigned_by_id])


class ProposedDiaryItem(db.Model):
    __tablename__ = "proposed_diary_items"

    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False, index=True)
    evidence_id = db.Column(db.Integer, db.ForeignKey("evidence_items.id"), nullable=False)
    suggested_type = db.Column(db.String(30), default="evidence_note", nullable=False)
    suggested_body = db.Column(db.Text, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    accepted_at = db.Column(db.DateTime(timezone=True))
    dismissed_at = db.Column(db.DateTime(timezone=True))

    case = db.relationship("Case", backref=db.backref("diary_proposals", lazy="dynamic"))
    evidence = db.relationship("EvidenceItem", foreign_keys=[evidence_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])


class DiaryExport(db.Model):
    __tablename__ = "diary_exports"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey("celery_jobs.id"), nullable=True)
    date_from = db.Column(db.Date, nullable=False)
    date_to = db.Column(db.Date, nullable=False)
    language = db.Column(db.String(8), default="en", nullable=False)
    summarize = db.Column(db.Boolean, default=False, nullable=False)
    summary_text = db.Column(db.Text)
    summarize_error = db.Column(db.Text)
    docx_path = db.Column(db.String(400))
    pdf_path = db.Column(db.String(400))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    case = db.relationship("Case")
    user = db.relationship("User", foreign_keys=[user_id])
    job = db.relationship("CeleryJob", foreign_keys=[job_id])
