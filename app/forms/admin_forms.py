from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional

from app.forms.auth_forms import validate_identifier_value


def _int_or_zero(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class InviteUserForm(FlaskForm):
    full_name = StringField(
        "Full name",
        validators=[
            DataRequired(message="Enter a name."),
            Length(min=2, max=120, message="Name must be between 2 and 120 characters."),
        ],
    )
    identifier = StringField(
        "Identifier or email",
        validators=[DataRequired(message="Enter an identifier or email."), Length(max=180)],
    )
    email = StringField(
        "Email",
        validators=[Optional(), Email(message="Enter a valid email."), Length(max=180)],
    )
    role = SelectField("Role", validators=[DataRequired()])
    station_id = SelectField("Station", coerce=_int_or_zero, validators=[Optional()])
    rank_label = StringField("Rank", validators=[Optional(), Length(max=80)])
    send_invite = BooleanField("Send invite email", default=True)

    def validate_identifier(self, field):
        value = (field.data or "").strip().lower()
        if "@" in value:
            Email(message="Enter a valid email.")(self, field)
            field.data = value
            return
        field.data = validate_identifier_value(value)

    def validate_email(self, field):
        value = (field.data or "").strip().lower()
        field.data = value or None

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators)
        ident = (self.identifier.data or "").strip().lower()
        email = (self.email.data or "").strip().lower()
        dest = email or (ident if "@" in ident else "")
        if self.send_invite.data and not dest:
            self.email.errors = list(self.email.errors) + [
                "Enter an email address to send the invite."
            ]
            return False
        return ok


class UserEditForm(FlaskForm):
    rank_label = StringField("Rank", validators=[Optional(), Length(max=80)])
    belt_no = StringField("Belt number", validators=[Optional(), Length(max=30)])
    role = SelectField("Role", validators=[DataRequired()])
    station_id = SelectField("Station", coerce=_int_or_zero, validators=[Optional()])


class StationForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(min=3, max=200)])
    code = StringField("Code", validators=[DataRequired(), Length(min=2, max=32)])
    district = StringField("District", validators=[Optional(), Length(max=120)])
    city = StringField("City", validators=[Optional(), Length(max=120)])
    state = StringField("State", validators=[Optional(), Length(max=80)])
    address = StringField("Address", validators=[Optional(), Length(max=400)])
    phone = StringField("Phone", validators=[Optional(), Length(max=40)])
    letterhead_line2 = StringField("Letterhead line 2", validators=[Optional(), Length(max=200)])
    letterhead_line3 = StringField("Letterhead line 3", validators=[Optional(), Length(max=200)])
    is_active = BooleanField("Active", default=True)
    plan_key = SelectField(
        "Plan",
        choices=[
            ("pilot", "Pilot"),
            ("station", "Station"),
            ("zone", "Zone"),
            ("commissionerate", "Commissionerate"),
        ],
        default="pilot",
    )
    monthly_gemini_allowance = StringField("Monthly Gemini allowance", validators=[Optional(), Length(max=8)])
    extra_credits = StringField("Extra credits", validators=[Optional(), Length(max=8)])
    max_users = StringField("Max users", validators=[Optional(), Length(max=6)])
    allow_all_document_types = BooleanField("All document types")
    allow_legal_review = BooleanField("Legal-cell review")
    allow_sho_queue = BooleanField("SHO queue")
    allow_station_fts = BooleanField("Station-wide search")
    allow_cctns_demo = BooleanField("CCTNS demo button")
    allow_audit_export = BooleanField("Audit export")


class SettingsForm(FlaskForm):
    site_name = StringField("Site name", validators=[Optional(), Length(max=80)])
    registration_open = BooleanField("Public registration open")
    gemini_daily_soft_limit = StringField("Daily Gemini soft limit", validators=[Optional(), Length(max=6)])
    retention_days = StringField("Retention days", validators=[Optional(), Length(max=6)])
    disclaimer_en = StringField("Disclaimer (English)", validators=[Optional()])
    disclaimer_hi = StringField("Disclaimer (Hindi)", validators=[Optional()])
    disclaimer_gu = StringField("Disclaimer (Gujarati)", validators=[Optional()])
    disclaimer_short_en = StringField("Short disclaimer (English)", validators=[Optional()])
    disclaimer_short_hi = StringField("Short disclaimer (Hindi)", validators=[Optional()])
    disclaimer_short_gu = StringField("Short disclaimer (Gujarati)", validators=[Optional()])


class EnrollmentRotateForm(FlaskForm):
    pass


class EmptyAdminForm(FlaskForm):
    pass
