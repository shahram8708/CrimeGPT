import uuid

from app.extensions import db
from app.models.mixins import TimestampMixin, utcnow

LIVE_DOC_TYPES = (
    "medical_letter",
    "seizure_receipt",
    "remand_pc",
    "face_identification",
    "purvani_chargesheet",
    "court_custody",
    "accused_panchanama",
    "lers_request",
)
HUB_ONLY_TYPES = ()
ALL_DOC_CARDS = LIVE_DOC_TYPES
DOC_STATUSES = ("pending", "completed", "failed", "final")


class GeneratedDocument(TimestampMixin, db.Model):
    __tablename__ = "generated_documents"
    __table_args__ = (
        db.Index("ix_gendoc_case_type_ver", "case_id", "doc_type", "version_number"),
    )

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    doc_type = db.Column(db.String(40), nullable=False)
    language = db.Column(db.String(5), default="en", nullable=False)
    version_number = db.Column(db.Integer, default=1, nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("generated_documents.id"), nullable=True)
    status = db.Column(db.String(16), default="pending", nullable=False)
    ai_used = db.Column(db.Boolean, default=False, nullable=False)
    ai_error = db.Column(db.Text)
    context_json = db.Column(db.Text)
    docx_path = db.Column(db.String(400))
    pdf_path = db.Column(db.String(400))
    is_incomplete = db.Column(db.Boolean, default=False, nullable=False)
    finalized_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    finalized_at = db.Column(db.DateTime(timezone=True))
    review_requested_at = db.Column(db.DateTime(timezone=True))
    diary_proposal = db.Column(db.Text)

    case = db.relationship("Case", backref=db.backref("generated_documents", lazy="dynamic"))
    creator = db.relationship("User", foreign_keys=[created_by_id])
    finalized_by = db.relationship("User", foreign_keys=[finalized_by_id])
    parent = db.relationship("GeneratedDocument", remote_side="GeneratedDocument.id")


class LibraryDocument(TimestampMixin, db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=True, index=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    original_filename = db.Column(db.String(240))
    stored_name = db.Column(db.String(80), nullable=False)
    stored_path = db.Column(db.String(400), nullable=False)
    mime = db.Column(db.String(80))
    size_bytes = db.Column(db.Integer, default=0, nullable=False)
    source = db.Column(db.String(16), default="upload", nullable=False)

    case = db.relationship("Case")
    uploader = db.relationship("User", foreign_keys=[uploaded_by_id])


class CompareResult(db.Model):
    __tablename__ = "compare_results"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=True)
    job_id = db.Column(db.Integer, db.ForeignKey("celery_jobs.id"), nullable=True)
    left_kind = db.Column(db.String(20), nullable=False)
    left_ref = db.Column(db.String(36), nullable=False)
    right_kind = db.Column(db.String(20), nullable=False)
    right_ref = db.Column(db.String(36), nullable=False)
    language = db.Column(db.String(8), default="en", nullable=False)
    result_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])
    case = db.relationship("Case")


class ClauseAnalysis(db.Model):
    __tablename__ = "clause_analyses"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    generated_id = db.Column(db.Integer, db.ForeignKey("generated_documents.id"), nullable=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey("celery_jobs.id"), nullable=True)
    language = db.Column(db.String(8), default="en", nullable=False)
    result_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    generated = db.relationship("GeneratedDocument")
    upload = db.relationship("LibraryDocument")
    user = db.relationship("User", foreign_keys=[user_id])


class DocumentReviewNote(db.Model):
    __tablename__ = "document_review_notes"

    id = db.Column(db.Integer, primary_key=True)
    generated_document_id = db.Column(db.Integer, db.ForeignKey("generated_documents.id"), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(32), default="reviewed_ok", nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    document = db.relationship("GeneratedDocument", backref=db.backref("review_notes", lazy="dynamic"))
    author = db.relationship("User", foreign_keys=[author_id])
