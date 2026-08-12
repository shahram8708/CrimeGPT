import uuid

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models.mixins import TimestampMixin, utcnow

ALLOWED_ROLES = ("constable", "writer", "io", "sho", "legal", "admin", "super_admin")

ROLE_LABELS = {
    "constable": "Constable",
    "writer": "Writer",
    "io": "Investigating Officer",
    "sho": "Station House Officer",
    "legal": "Legal Cell",
    "admin": "Station Admin",
    "super_admin": "Super Admin",
}


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    full_name = db.Column(db.String(160), nullable=False)
    identifier = db.Column(db.String(160), unique=True, nullable=False, index=True)
    email = db.Column(db.String(180), unique=True, nullable=True, index=True)
    mobile = db.Column(db.String(20))
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(32), nullable=False, default="writer")
    rank_label = db.Column(db.String(80))
    belt_no = db.Column(db.String(40))
    station_id = db.Column(db.Integer, db.ForeignKey("police_stations.id"), nullable=True)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    email_verified_at = db.Column(db.DateTime(timezone=True))
    last_login_at = db.Column(db.DateTime(timezone=True))
    failed_login_count = db.Column(db.Integer, default=0, nullable=False)
    lock_until = db.Column(db.DateTime(timezone=True))
    session_version = db.Column(db.Integer, default=1, nullable=False)
    onboarding_completed_at = db.Column(db.DateTime(timezone=True))
    disclaimer_accepted_at = db.Column(db.DateTime(timezone=True))
    invited_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    station = db.relationship("PoliceStation", back_populates="users")
    invited_by = db.relationship(
        "User", remote_side="User.id", foreign_keys="User.invited_by_id"
    )
    preferences = db.relationship(
        "UserPreference", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    jobs = db.relationship("CeleryJob", back_populates="user", lazy="dynamic")
    notifications = db.relationship("Notification", back_populates="user", lazy="dynamic")
    auth_tokens = db.relationship("AuthToken", back_populates="user", lazy="dynamic")

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        if not raw or not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw)

    def get_id(self):
        return f"{self.id}:{self.session_version}"

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)

    @property
    def is_super_admin(self):
        return self.role == "super_admin"

    @property
    def is_locked(self):
        if not self.lock_until:
            return False
        lock = self.lock_until
        if lock.tzinfo is None:
            lock = lock.replace(tzinfo=__import__("datetime").timezone.utc)
        return lock > utcnow()

    def __repr__(self):
        return f"<User {self.identifier}>"


class UserPreference(TimestampMixin, db.Model):
    __tablename__ = "user_preferences"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    ui_language = db.Column(db.String(8), default="en", nullable=False)
    document_language = db.Column(db.String(8), default="gu", nullable=False)
    offline_drafts = db.Column(db.Boolean, default=False, nullable=False)
    email_notifications = db.Column(db.Boolean, default=True, nullable=False)
    hide_intel_modal = db.Column(db.Boolean, default=False, nullable=False)
    diary_oldest_first = db.Column(db.Boolean, default=True, nullable=False)
    evidence_consent_at = db.Column(db.DateTime(timezone=True))

    user = db.relationship("User", back_populates="preferences")


class AuthToken(db.Model):
    __tablename__ = "auth_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    purpose = db.Column(db.String(32), nullable=False)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship("User", back_populates="auth_tokens")
