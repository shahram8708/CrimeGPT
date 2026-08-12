import uuid

from app.extensions import db
from app.models.mixins import TimestampMixin, utcnow


class ApplicationSetting(db.Model):
    __tablename__ = "application_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False, index=True)
    value = db.Column(db.Text)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    updated_by = db.relationship("User", foreign_keys=[updated_by_id])

    @classmethod
    def get(cls, key, default=None):
        row = cls.query.filter_by(key=key).first()
        if row is None or row.value is None:
            return default
        return row.value

    @classmethod
    def set(cls, key, value, updated_by_id=None):
        row = cls.query.filter_by(key=key).first()
        if row is None:
            row = cls(key=key, value=value, updated_by_id=updated_by_id)
            db.session.add(row)
        else:
            row.value = value
            row.updated_by_id = updated_by_id
            row.updated_at = utcnow()
        return row


class AuditLog(db.Model):
    __tablename__ = "audit_log"
    __table_args__ = (
        db.Index("ix_audit_actor_time", "actor_id", "created_at"),
        db.Index("ix_audit_action_time", "action", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    station_id = db.Column(db.Integer, db.ForeignKey("police_stations.id"), nullable=True)
    case_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.String(80), nullable=False)
    object_type = db.Column(db.String(80))
    object_id = db.Column(db.String(64))
    ip = db.Column(db.String(64))
    user_agent = db.Column(db.String(300))
    meta_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    actor = db.relationship("User", foreign_keys=[actor_id])
    station = db.relationship("PoliceStation", foreign_keys=[station_id])


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    body = db.Column(db.String(400))
    link_path = db.Column(db.String(240))
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship("User", back_populates="notifications")


class UsageCounter(db.Model):
    __tablename__ = "usage_counters"
    __table_args__ = (
        db.UniqueConstraint("station_id", "user_id", "day", name="uq_usage_station_user_day"),
    )

    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey("police_stations.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    day = db.Column(db.Date, nullable=False)
    gemini_calls = db.Column(db.Integer, default=0, nullable=False)
    doc_generations = db.Column(db.Integer, default=0, nullable=False)


class MailLog(db.Model):
    __tablename__ = "mail_log"

    id = db.Column(db.Integer, primary_key=True)
    to_address = db.Column(db.String(180), nullable=False)
    subject = db.Column(db.String(240), nullable=False)
    purpose = db.Column(db.String(40))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    sent_ok = db.Column(db.Boolean, default=False, nullable=False)
    error_class = db.Column(db.String(80))
    body = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])


class CaseIntegration(db.Model):
    __tablename__ = "case_integrations"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False, index=True)
    system = db.Column(db.String(24), nullable=False)
    ack_number = db.Column(db.String(80), nullable=False)
    payload_json = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    case = db.relationship("Case")
    created_by = db.relationship("User", foreign_keys=[created_by_id])


class ContactMessage(db.Model):
    __tablename__ = "contact_messages"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), nullable=False)
    organisation = db.Column(db.String(160))
    station_note = db.Column(db.String(160))
    message = db.Column(db.Text, nullable=False)
    ip = db.Column(db.String(64))
    user_agent = db.Column(db.String(300))
    honeypot_hit = db.Column(db.Boolean, default=False, nullable=False)
    emailed_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
