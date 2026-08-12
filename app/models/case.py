import uuid
from decimal import Decimal

from app.extensions import db
from app.models.mixins import TimestampMixin, utcnow

CASE_STATUSES = ("draft", "open", "in_court", "closed", "archived")
CASE_CATEGORIES = (
    "hurt",
    "theft",
    "house_trespass",
    "intimidation",
    "accident",
    "ndps_adjacent",
    "other",
)
PARTY_ROLES = ("complainant", "injured", "accused", "witness", "panch", "surety", "other")
STATUTE_FAMILIES = ("BNS", "BNSS", "BSA", "IPC", "CrPC", "IEA", "OTHER")
SECTION_STATUSES = ("suggested", "confirmed", "rejected")
SECTION_SOURCES = ("officer", "legal", "gemini")
CATEGORY_LABELS = {
    "hurt": "Hurt",
    "theft": "Theft",
    "house_trespass": "House-trespass",
    "intimidation": "Intimidation",
    "accident": "Accident",
    "ndps_adjacent": "NDPS-adjacent",
    "other": "Other",
}


class Case(TimestampMixin, db.Model):
    __tablename__ = "cases"
    __table_args__ = (
        db.Index("ix_cases_assigned_io_id", "assigned_io_id"),
        db.Index("ix_cases_incident_at", "incident_at"),
        db.Index("ix_cases_status", "status"),
        db.Index("ix_cases_station_id", "station_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    station_id = db.Column(db.Integer, db.ForeignKey("police_stations.id"), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    assigned_io_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    assigned_legal_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    year = db.Column(db.Integer, nullable=False)
    cr_number = db.Column(db.String(40))
    gd_number = db.Column(db.String(40))
    incident_at = db.Column(db.DateTime(timezone=True), nullable=False)
    place_of_occurrence = db.Column(db.String(300), nullable=False)
    category = db.Column(db.String(40), nullable=False, default="other")
    narrative = db.Column(db.Text)
    narrative_language = db.Column(db.String(5))
    status = db.Column(db.String(24), nullable=False, default="draft")
    is_locked = db.Column(db.Boolean, default=False, nullable=False)
    locked_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    locked_at = db.Column(db.DateTime(timezone=True))
    deleted_at = db.Column(db.DateTime(timezone=True))

    station = db.relationship("PoliceStation", backref="cases")
    creator = db.relationship("User", foreign_keys=[created_by_id])
    assigned_io = db.relationship("User", foreign_keys=[assigned_io_id])
    assigned_legal = db.relationship("User", foreign_keys=[assigned_legal_id])
    locked_by = db.relationship("User", foreign_keys=[locked_by_id])
    parties = db.relationship("CaseParty", back_populates="case", lazy="dynamic")
    items = db.relationship("CaseItem", back_populates="case", lazy="dynamic")
    arrests = db.relationship("CaseArrest", back_populates="case", lazy="dynamic")
    medical = db.relationship("CaseMedical", back_populates="case", uselist=False)
    sections = db.relationship("CaseSection", back_populates="case", lazy="dynamic")

    @property
    def category_label(self):
        return CATEGORY_LABELS.get(self.category, self.category)

    @property
    def display_cr(self):
        return self.cr_number or "Draft"

    def live_parties(self, role=None):
        q = self.parties.filter(CaseParty.deleted_at.is_(None))
        if role:
            q = q.filter(CaseParty.role == role)
        return q.order_by(CaseParty.sort_order, CaseParty.id).all()

    def live_items(self):
        return self.items.filter(CaseItem.deleted_at.is_(None)).order_by(CaseItem.id).all()

    def live_arrests(self):
        return self.arrests.filter(CaseArrest.deleted_at.is_(None)).all()


class CaseParty(TimestampMixin, db.Model):
    __tablename__ = "case_parties"
    __table_args__ = (db.Index("ix_case_parties_case_role", "case_id", "role"),)

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False, index=True)
    role = db.Column(db.String(24), nullable=False)
    full_name = db.Column(db.String(160), nullable=False)
    guardian_name = db.Column(db.String(160))
    relation = db.Column(db.String(80))
    age = db.Column(db.Integer)
    gender = db.Column(db.String(24))
    address = db.Column(db.Text)
    phone = db.Column(db.String(15))
    id_type = db.Column(db.String(40))
    id_number = db.Column(db.String(80))
    alias = db.Column(db.String(120))
    is_juvenile = db.Column(db.Boolean, default=False, nullable=False)
    notes = db.Column(db.Text)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    deleted_at = db.Column(db.DateTime(timezone=True))

    case = db.relationship("Case", back_populates="parties")

    @property
    def initials(self):
        parts = [p for p in (self.full_name or "").split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()


class CaseItem(TimestampMixin, db.Model):
    __tablename__ = "case_items"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False, index=True)
    description = db.Column(db.String(500), nullable=False)
    quantity = db.Column(db.String(40))
    unit = db.Column(db.String(20))
    estimated_value = db.Column(db.Numeric(12, 2))
    serial_or_marking = db.Column(db.String(120))
    seized_from_party_id = db.Column(db.Integer, db.ForeignKey("case_parties.id"), nullable=True)
    place = db.Column(db.String(200))
    seized_at = db.Column(db.DateTime(timezone=True))
    exhibit_no = db.Column(db.String(20))
    notes = db.Column(db.Text)
    deleted_at = db.Column(db.DateTime(timezone=True))

    case = db.relationship("Case", back_populates="items")
    seized_from = db.relationship("CaseParty", foreign_keys=[seized_from_party_id])


class CaseArrest(TimestampMixin, db.Model):
    __tablename__ = "case_arrests"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False, index=True)
    accused_id = db.Column(db.Integer, db.ForeignKey("case_parties.id"), nullable=False)
    arrest_at = db.Column(db.DateTime(timezone=True), nullable=False)
    place = db.Column(db.String(200), nullable=False)
    rights_informed = db.Column(db.Boolean, default=False, nullable=False)
    grounds_brief = db.Column(db.Text)
    produced_before = db.Column(db.String(160))
    relative_informed = db.Column(db.Boolean, default=False, nullable=False)
    relative_name = db.Column(db.String(160))
    deleted_at = db.Column(db.DateTime(timezone=True))

    case = db.relationship("Case", back_populates="arrests")
    accused = db.relationship("CaseParty", foreign_keys=[accused_id])


class CaseMedical(TimestampMixin, db.Model):
    __tablename__ = "case_medical"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False, unique=True)
    injured_party_id = db.Column(db.Integer, db.ForeignKey("case_parties.id"), nullable=True)
    hospital_name = db.Column(db.String(200))
    department = db.Column(db.String(120))
    mlc_no = db.Column(db.String(80))
    history_reported = db.Column(db.Text)
    requested_exam = db.Column(db.Text)
    escorting_officer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    case = db.relationship("Case", back_populates="medical")
    injured_party = db.relationship("CaseParty", foreign_keys=[injured_party_id])
    escorting_officer = db.relationship("User", foreign_keys=[escorting_officer_id])


class CaseSection(db.Model):
    __tablename__ = "case_sections"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False, index=True)
    statute_family = db.Column(db.String(16), nullable=False)
    code = db.Column(db.String(40), nullable=False)
    title = db.Column(db.String(240))
    rationale = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="suggested")
    source = db.Column(db.String(20), nullable=False, default="officer")
    confidence = db.Column(db.Integer)
    suggestion_id = db.Column(db.Integer)
    confirmed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    confirmed_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    case = db.relationship("Case", back_populates="sections")
    confirmed_by = db.relationship("User", foreign_keys=[confirmed_by_id])
