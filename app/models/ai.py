import uuid

from app.extensions import db
from app.models.mixins import utcnow


class LegalSuggestion(db.Model):
    __tablename__ = "legal_suggestions"
    __table_args__ = (db.Index("ix_legal_suggestions_hash", "narrative_hash"),)

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    job_id = db.Column(db.Integer, db.ForeignKey("celery_jobs.id"), nullable=True)
    station_id = db.Column(db.Integer, db.ForeignKey("police_stations.id"), nullable=True, index=True)
    narrative_hash = db.Column(db.String(64), nullable=False, index=True)
    narrative_snapshot = db.Column(db.Text, nullable=False)
    language = db.Column(db.String(8), default="en", nullable=False)
    focus = db.Column(db.String(32), default="charging", nullable=False)
    use_search = db.Column(db.Boolean, default=True, nullable=False)
    result_json = db.Column(db.Text)
    overall_confidence = db.Column(db.Integer)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    case = db.relationship("Case")
    user = db.relationship("User", foreign_keys=[user_id])
    job = db.relationship("CeleryJob", foreign_keys=[job_id])
    station = db.relationship("PoliceStation", foreign_keys=[station_id])


class AiInteraction(db.Model):
    __tablename__ = "ai_interactions"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=True)
    job_id = db.Column(db.Integer, db.ForeignKey("celery_jobs.id"), nullable=True)
    purpose = db.Column(db.String(40), nullable=False, default="legal_intel")
    model = db.Column(db.String(80), default="gemini-2.5-flash", nullable=False)
    prompt_chars = db.Column(db.Integer, default=0)
    response_chars = db.Column(db.Integer, default=0)
    input_tokens = db.Column(db.Integer)
    output_tokens = db.Column(db.Integer)
    latency_ms = db.Column(db.Integer)
    success = db.Column(db.Boolean, default=False, nullable=False)
    error_class = db.Column(db.String(80))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    user = db.relationship("User", foreign_keys=[user_id])
    case = db.relationship("Case", foreign_keys=[case_id])


class SavedResult(db.Model):
    __tablename__ = "saved_results"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=True)
    result_type = db.Column(db.String(24), default="intel", nullable=False)
    ref_table = db.Column(db.String(40), default="legal_suggestions", nullable=False)
    ref_id = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200))
    is_starred = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])
    case = db.relationship("Case", foreign_keys=[case_id])


class QaThread(db.Model):
    __tablename__ = "qa_threads"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=True, index=True)
    title = db.Column(db.String(200), nullable=False, default="Question")
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])
    case = db.relationship("Case")
    messages = db.relationship("QaMessage", back_populates="thread", lazy="dynamic", order_by="QaMessage.id")


class QaMessage(db.Model):
    __tablename__ = "qa_messages"

    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.Integer, db.ForeignKey("qa_threads.id"), nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False)
    body = db.Column(db.Text, nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey("celery_jobs.id"), nullable=True)
    refusal = db.Column(db.Boolean, default=False, nullable=False)
    citations_json = db.Column(db.Text)
    followups_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    thread = db.relationship("QaThread", back_populates="messages")


class DocumentAnalysis(db.Model):
    __tablename__ = "document_analyses"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=True, index=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    job_id = db.Column(db.Integer, db.ForeignKey("celery_jobs.id"), nullable=True)
    result_json = db.Column(db.Text)
    document_type = db.Column(db.String(40))
    summary = db.Column(db.Text)
    language = db.Column(db.String(16), default="en")
    overall_confidence = db.Column(db.Integer)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    document = db.relationship("LibraryDocument")
    case = db.relationship("Case")
    user = db.relationship("User", foreign_keys=[user_id])


class TranslateResult(db.Model):
    __tablename__ = "translate_results"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=True)
    job_id = db.Column(db.Integer, db.ForeignKey("celery_jobs.id"), nullable=True)
    mode = db.Column(db.String(16), default="explain", nullable=False)
    source_text = db.Column(db.Text, nullable=False)
    target_lang = db.Column(db.String(8), default="en", nullable=False)
    detected_language = db.Column(db.String(16))
    output_text = db.Column(db.Text)
    notes = db.Column(db.Text)
    result_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])
    case = db.relationship("Case")


class LegalChecklist(db.Model):
    __tablename__ = "legal_checklists"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False, index=True)
    job_id = db.Column(db.Integer, db.ForeignKey("celery_jobs.id"), nullable=True)
    title = db.Column(db.String(200), default="Case checklist")
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    case = db.relationship("Case")
    creator = db.relationship("User", foreign_keys=[created_by_id])
    items = db.relationship("LegalChecklistItem", back_populates="checklist", order_by="LegalChecklistItem.sort_order")


class LegalChecklistItem(db.Model):
    __tablename__ = "legal_checklist_items"

    id = db.Column(db.Integer, primary_key=True)
    checklist_id = db.Column(db.Integer, db.ForeignKey("legal_checklists.id"), nullable=False, index=True)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    label = db.Column(db.String(300), nullable=False)
    why_text = db.Column(db.Text)
    severity = db.Column(db.String(16), default="medium")
    deep_link = db.Column(db.String(240))
    is_done = db.Column(db.Boolean, default=False, nullable=False)
    done_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    done_at = db.Column(db.DateTime(timezone=True))

    checklist = db.relationship("LegalChecklist", back_populates="items")
    done_by = db.relationship("User", foreign_keys=[done_by_id])


class GapResult(db.Model):
    __tablename__ = "gap_results"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey("celery_jobs.id"), nullable=True)
    result_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    case = db.relationship("Case")
    user = db.relationship("User", foreign_keys=[user_id])
