import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateTimeLocalField,
    HiddenField,
    IntegerField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError

from app.models.case import CASE_CATEGORIES, CASE_STATUSES, CATEGORY_LABELS, PARTY_ROLES, STATUTE_FAMILIES

IST = ZoneInfo("Asia/Kolkata")
CR_RE = re.compile(r"^[A-Za-z0-9/\-]{0,40}$")
MOBILE_RE = re.compile(r"^[6-9][0-9]{9}$")

CATEGORY_CHOICES = [(k, CATEGORY_LABELS[k]) for k in CASE_CATEGORIES]
ROLE_CHOICES = [(r, r.replace("_", " ").title()) for r in PARTY_ROLES]
GENDER_CHOICES = [("", "-"), ("male", "Male"), ("female", "Female"), ("other", "Other"), ("unknown", "Unknown")]
ID_CHOICES = [
    ("", "-"),
    ("aadhaar", "Aadhaar"),
    ("voter", "Voter ID"),
    ("pan", "PAN"),
    ("passport", "Passport"),
    ("driving_licence", "Driving licence"),
    ("other", "Other"),
]
LANG_CHOICES = [("en", "English"), ("hi", "हिन्दी"), ("gu", "ગુજરાતી")]
STATUTE_CHOICES = [(s, s) for s in STATUTE_FAMILIES]


def parse_local_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                dt = None
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(timezone.utc)


def to_local_input(dt):
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime("%Y-%m-%dT%H:%M")


class NotFuture:
    def __call__(self, form, field):
        dt = parse_local_dt(field.data)
        if dt is None:
            return
        if dt > datetime.now(timezone.utc) + timedelta(minutes=10):
            raise ValidationError("Incident time cannot be in the future.")


class IndianMobile:
    def __call__(self, form, field):
        value = (field.data or "").strip()
        if not value:
            return
        digits = re.sub(r"\D", "", value)
        if digits.startswith("91") and len(digits) == 12:
            digits = digits[2:]
        if not MOBILE_RE.match(digits):
            raise ValidationError("Enter an Indian mobile starting with 6–9, or leave blank.")
        field.data = digits


class CaseWizardForm(FlaskForm):
    step = HiddenField(default="1")
    case_uuid = HiddenField()
    action = HiddenField(default="next")
    station_id = SelectField("Station", coerce=int, validators=[Optional()])
    year = IntegerField("Year", validators=[DataRequired(), NumberRange(min=2000, max=2100)])
    cr_number = StringField("FIR / CR number", validators=[Optional(), Length(max=40)])
    gd_number = StringField("GD number", validators=[Optional(), Length(max=40)])
    incident_at = DateTimeLocalField(
        "Incident date and time",
        format="%Y-%m-%dT%H:%M",
        validators=[DataRequired(message="Enter the incident date and time."), NotFuture()],
    )
    place_of_occurrence = StringField(
        "Place of occurrence",
        validators=[
            DataRequired(message="Enter the place of occurrence."),
            Length(min=5, max=300, message="Place must be between 5 and 300 characters."),
        ],
    )
    category = SelectField("Category", choices=CATEGORY_CHOICES, validators=[DataRequired()])
    assigned_io_id = SelectField("Assigned IO", coerce=int, validators=[Optional()])
    complainant_name = StringField("Full name", validators=[Optional(), Length(max=160)])
    guardian_name = StringField("Guardian name", validators=[Optional(), Length(max=160)])
    relation = StringField("Relation", validators=[Optional(), Length(max=80)])
    age = IntegerField("Age", validators=[Optional(), NumberRange(min=0, max=120)])
    gender = SelectField("Gender", choices=GENDER_CHOICES, validators=[Optional()])
    address = TextAreaField("Address", validators=[Optional(), Length(max=800)])
    phone = StringField("Phone", validators=[Optional(), IndianMobile(), Length(max=15)])
    id_type = SelectField("ID type", choices=ID_CHOICES, validators=[Optional()])
    id_number = StringField("ID number", validators=[Optional(), Length(max=80)])
    narrative = TextAreaField("Narrative", validators=[Optional(), Length(max=20000)])
    narrative_language = SelectField("Narrative language", choices=LANG_CHOICES, default="en")

    def validate_cr_number(self, field):
        value = (field.data or "").strip()
        if value and not CR_RE.match(value):
            raise ValidationError("Use letters, digits, slash or hyphen only.")
        field.data = value or None

    def complainant_started(self):
        return any(
            [
                (self.complainant_name.data or "").strip(),
                (self.guardian_name.data or "").strip(),
                (self.relation.data or "").strip(),
                self.age.data not in (None, ""),
                (self.address.data or "").strip(),
                (self.phone.data or "").strip(),
                (self.id_number.data or "").strip(),
            ]
        )


class CaseEditForm(FlaskForm):
    updated_at = HiddenField()
    year = IntegerField("Year", validators=[DataRequired(), NumberRange(min=2000, max=2100)])
    cr_number = StringField("FIR / CR number", validators=[Optional(), Length(max=40)])
    gd_number = StringField("GD number", validators=[Optional(), Length(max=40)])
    incident_at = DateTimeLocalField(
        "Incident date and time",
        format="%Y-%m-%dT%H:%M",
        validators=[DataRequired(), NotFuture()],
    )
    place_of_occurrence = StringField(
        "Place of occurrence",
        validators=[DataRequired(), Length(min=5, max=300)],
    )
    category = SelectField("Category", choices=CATEGORY_CHOICES, validators=[DataRequired()])
    assigned_io_id = SelectField("Assigned IO", coerce=int, validators=[Optional()])
    assigned_legal_id = SelectField("Assigned legal", coerce=int, validators=[Optional()])
    narrative = TextAreaField("Narrative", validators=[Optional(), Length(max=20000)])
    narrative_language = SelectField("Narrative language", choices=LANG_CHOICES)
    status = SelectField("Status", choices=[(s, s.replace("_", " ")) for s in CASE_STATUSES])

    def validate_cr_number(self, field):
        value = (field.data or "").strip()
        if value and not CR_RE.match(value):
            raise ValidationError("Use letters, digits, slash or hyphen only.")
        field.data = value or None


class PartyForm(FlaskForm):
    role = SelectField("Role", choices=ROLE_CHOICES, validators=[DataRequired()])
    full_name = StringField("Full name", validators=[DataRequired(), Length(min=2, max=160)])
    guardian_name = StringField("Guardian name", validators=[Optional(), Length(max=160)])
    relation = StringField("Relation", validators=[Optional(), Length(max=80)])
    age = IntegerField("Age", validators=[Optional(), NumberRange(min=0, max=120)])
    gender = SelectField("Gender", choices=GENDER_CHOICES, validators=[Optional()])
    address = TextAreaField("Address", validators=[Optional(), Length(max=800)])
    phone = StringField("Phone", validators=[Optional(), IndianMobile(), Length(max=15)])
    id_type = SelectField("ID type", choices=ID_CHOICES, validators=[Optional()])
    id_number = StringField("ID number", validators=[Optional(), Length(max=80)])
    alias = StringField("Alias", validators=[Optional(), Length(max=120)])
    is_juvenile = BooleanField("Juvenile")
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=2000)])


class ItemForm(FlaskForm):
    description = StringField(
        "Description",
        validators=[DataRequired(), Length(min=3, max=500)],
    )
    quantity = StringField("Quantity", validators=[Optional(), Length(max=40)])
    unit = StringField("Unit", validators=[Optional(), Length(max=20)])
    estimated_value = StringField("Estimated value", validators=[Optional(), Length(max=20)])
    serial_or_marking = StringField("Serial or marking", validators=[Optional(), Length(max=120)])
    seized_from_party_id = SelectField("Seized from", coerce=int, validators=[Optional()])
    place = StringField("Place", validators=[Optional(), Length(max=200)])
    seized_at = DateTimeLocalField("Seized at", format="%Y-%m-%dT%H:%M", validators=[Optional()])
    exhibit_no = StringField("Exhibit no.", validators=[Optional(), Length(max=20)])
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=2000)])


class ArrestBlockForm(FlaskForm):
    accused_id = HiddenField(validators=[DataRequired()])
    arrest_at = DateTimeLocalField("Arrested at", format="%Y-%m-%dT%H:%M", validators=[Optional()])
    place = StringField("Place", validators=[Optional(), Length(max=200)])
    rights_informed = BooleanField("Rights informed")
    grounds_brief = TextAreaField("Grounds", validators=[Optional(), Length(max=2000)])
    produced_before = StringField("Produced before", validators=[Optional(), Length(max=160)])
    relative_informed = BooleanField("Relative informed")
    relative_name = StringField("Relative name", validators=[Optional(), Length(max=160)])


class MedicalForm(FlaskForm):
    injured_party_id = SelectField("Injured / complainant", coerce=int, validators=[Optional()])
    hospital_name = StringField("Hospital", validators=[Optional(), Length(max=200)])
    department = StringField("Department", validators=[Optional(), Length(max=120)])
    mlc_no = StringField("MLC no.", validators=[Optional(), Length(max=80)])
    history_reported = TextAreaField("History reported", validators=[Optional(), Length(max=4000)])
    requested_exam = TextAreaField("Requested examination", validators=[Optional(), Length(max=2000)])
    escorting_officer_id = SelectField("Escorting officer", coerce=int, validators=[Optional()])


class SectionManualForm(FlaskForm):
    statute_family = SelectField("Statute", choices=STATUTE_CHOICES, validators=[DataRequired()])
    code = StringField("Section / provision", validators=[DataRequired(), Length(max=40)])
    title = StringField("Title", validators=[Optional(), Length(max=240)])
    rationale = TextAreaField("Rationale", validators=[Optional(), Length(max=2000)])


class SectionRemoveForm(FlaskForm):
    reason = StringField("Reason", validators=[DataRequired(), Length(min=3, max=240)])
