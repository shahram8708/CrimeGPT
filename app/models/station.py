import uuid

from app.extensions import db
from app.models.mixins import TimestampMixin


class PoliceStation(TimestampMixin, db.Model):
    __tablename__ = "police_stations"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(200), nullable=False)
    code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    district = db.Column(db.String(120))
    city = db.Column(db.String(120))
    state = db.Column(db.String(80), default="Gujarat")
    address = db.Column(db.String(400))
    phone = db.Column(db.String(40))
    letterhead_line2 = db.Column(db.String(200))
    letterhead_line3 = db.Column(db.String(200))
    logo_path = db.Column(db.String(400))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    plan_key = db.Column(db.String(32), default="pilot", nullable=False)
    monthly_gemini_allowance = db.Column(db.Integer, default=40, nullable=False)
    extra_credits = db.Column(db.Integer, default=0, nullable=False)
    max_users = db.Column(db.Integer, default=8, nullable=False)
    evidence_quota_bytes = db.Column(db.BigInteger, default=2147483648, nullable=False)
    allow_all_document_types = db.Column(db.Boolean, default=False, nullable=False)
    allow_legal_review = db.Column(db.Boolean, default=False, nullable=False)
    allow_sho_queue = db.Column(db.Boolean, default=False, nullable=False)
    allow_station_fts = db.Column(db.Boolean, default=False, nullable=False)
    allow_cctns_demo = db.Column(db.Boolean, default=False, nullable=False)
    allow_audit_export = db.Column(db.Boolean, default=False, nullable=False)

    users = db.relationship("User", back_populates="station", lazy="dynamic")

    def __repr__(self):
        return f"<PoliceStation {self.code}>"
