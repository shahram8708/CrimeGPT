import re

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    HiddenField,
    PasswordField,
    RadioField,
    SelectField,
    StringField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, ValidationError

from app.utils.security_utils import is_strong_password, password_errors

IDENTIFIER_RE = re.compile(r"^[a-z0-9._-]{4,64}$")
MOBILE_RE = re.compile(r"^[6-9][0-9]{9}$")


def _looks_like_email(value):
    return bool(value) and "@" in value


def validate_identifier_value(value):
    value = (value or "").strip().lower()
    if _looks_like_email(value):
        if len(value) > 160 or " " in value:
            raise ValidationError("Enter a valid email or station identifier.")
        return value
    if not IDENTIFIER_RE.match(value):
        raise ValidationError(
            "Identifier must be 4–64 characters: lowercase letters, digits, dot, underscore, or hyphen."
        )
    return value


class MustAccept:
    def __init__(self, message):
        self.message = message

    def __call__(self, form, field):
        if not field.data:
            raise ValidationError(self.message)


class StrongPassword:
    def __call__(self, form, field):
        errs = password_errors(field.data or "")
        if errs:
            raise ValidationError(errs[0])
        if not is_strong_password(field.data or ""):
            raise ValidationError("Choose a stronger password.")


class LoginForm(FlaskForm):
    identifier = StringField(
        "Identifier",
        validators=[DataRequired(message="Enter your station identifier."), Length(max=160)],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(message="Enter your password."), Length(max=128)],
    )
    remember = BooleanField("Remember me")
    next = HiddenField()


class RegisterForm(FlaskForm):
    full_name = StringField(
        "Full name",
        validators=[
            DataRequired(message="Enter your name."),
            Length(min=2, max=120, message="Name must be between 2 and 120 characters."),
        ],
    )
    identifier = StringField(
        "Identifier",
        validators=[DataRequired(message="Enter an identifier."), Length(max=160)],
    )
    email = StringField("Email", validators=[Optional(), Email(message="Enter a valid email."), Length(max=180)])
    mobile = StringField("Mobile", validators=[Optional(), Length(max=20)])
    password = PasswordField(
        "Password",
        validators=[DataRequired(message="Enter a password."), StrongPassword(), Length(max=128)],
    )
    confirm = PasswordField(
        "Confirm password",
        validators=[
            DataRequired(message="Confirm your password."),
            EqualTo("password", message="Passwords must match."),
        ],
    )
    station_id = SelectField("Station", coerce=int, validators=[DataRequired(message="Choose a station.")])
    role = SelectField(
        "Requested role",
        choices=[("writer", "Writer"), ("constable", "Constable")],
        default="writer",
        validators=[DataRequired()],
    )
    enrollment_code = StringField("Enrollment code", validators=[Optional(), Length(max=80)])
    language = SelectField(
        "Language",
        choices=[("en", "English"), ("hi", "हिन्दी"), ("gu", "ગુજરાતી")],
        default="en",
    )
    understand = BooleanField(
        "I understand CrimeGPT does not provide legal advice",
        validators=[MustAccept("You must acknowledge that CrimeGPT does not provide legal advice.")],
    )
    accept_terms = BooleanField(
        "I accept the Terms",
        validators=[MustAccept("You must accept the Terms.")],
    )

    def validate_identifier(self, field):
        field.data = validate_identifier_value(field.data)

    def validate_mobile(self, field):
        value = (field.data or "").strip()
        if not value:
            field.data = ""
            return
        digits = re.sub(r"\D", "", value)
        if digits.startswith("91") and len(digits) == 12:
            digits = digits[2:]
        if not MOBILE_RE.match(digits):
            raise ValidationError("Enter an Indian mobile number starting with 6–9, or leave blank.")
        field.data = digits

    def validate_email(self, field):
        ident = (self.identifier.data or "").strip().lower()
        if not _looks_like_email(ident) and not (field.data or "").strip():
            raise ValidationError("Email is required when the identifier is not an email address.")


class ForgotPasswordForm(FlaskForm):
    identifier = StringField(
        "Identifier",
        validators=[DataRequired(message="Enter your identifier."), Length(max=160)],
    )


class ResetPasswordForm(FlaskForm):
    password = PasswordField(
        "New password",
        validators=[DataRequired(message="Enter a password."), StrongPassword(), Length(max=128)],
    )
    confirm = PasswordField(
        "Confirm password",
        validators=[
            DataRequired(message="Confirm your password."),
            EqualTo("password", message="Passwords must match."),
        ],
    )


class ResendVerifyForm(FlaskForm):
    identifier = StringField(
        "Identifier or email",
        validators=[DataRequired(message="Enter your identifier or email."), Length(max=180)],
    )


class InviteAcceptForm(FlaskForm):
    full_name = StringField(
        "Full name",
        validators=[
            DataRequired(message="Enter your name."),
            Length(min=2, max=120, message="Name must be between 2 and 120 characters."),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(message="Enter a password."), StrongPassword(), Length(max=128)],
    )
    confirm = PasswordField(
        "Confirm password",
        validators=[
            DataRequired(message="Confirm your password."),
            EqualTo("password", message="Passwords must match."),
        ],
    )
    understand = BooleanField(
        "I understand CrimeGPT does not provide legal advice",
        validators=[MustAccept("You must acknowledge the disclaimer.")],
    )


class OnboardingForm(FlaskForm):
    step = HiddenField(default="1")
    ui_language = RadioField(
        "Language",
        choices=[("en", "English"), ("hi", "हिन्दी"), ("gu", "ગુજરાતી")],
        default="en",
    )
    understand = BooleanField("I understand")
    offline_drafts = RadioField(
        "Offline drafts",
        choices=[
            ("0", "Do not save drafts on this device"),
            ("1", "On this device save wizard drafts locally"),
        ],
        default="0",
    )
    action = HiddenField(default="continue")
