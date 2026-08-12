from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SelectField, StringField
from wtforms.validators import DataRequired, EqualTo, Length, Optional

from app.forms.auth_forms import StrongPassword


class ProfileForm(FlaskForm):
    full_name = StringField(
        "Display name",
        validators=[
            DataRequired(message="Enter your name."),
            Length(min=2, max=120, message="Name must be between 2 and 120 characters."),
        ],
    )
    rank_label = StringField("Rank", validators=[Optional(), Length(max=40)])
    belt_no = StringField("Belt number", validators=[Optional(), Length(max=30)])


class PreferencesForm(FlaskForm):
    ui_language = SelectField(
        "Interface language",
        choices=[("en", "English"), ("hi", "हिन्दी"), ("gu", "ગુજરાતી")],
    )
    document_language = SelectField(
        "Document language",
        choices=[("en", "English"), ("hi", "हिन्दी"), ("gu", "ગુજરાતી")],
    )
    offline_drafts = BooleanField("Save wizard drafts on this device")
    email_notifications = BooleanField("Email notifications")
    hide_intel_modal = BooleanField("Do not show the Legal Intelligence first-run disclaimer modal again")
    diary_oldest_first = BooleanField("Show case diary oldest first")


class SecurityForm(FlaskForm):
    current_password = PasswordField(
        "Current password",
        validators=[DataRequired(message="Enter your current password."), Length(max=128)],
    )
    new_password = PasswordField(
        "New password",
        validators=[DataRequired(message="Enter a new password."), StrongPassword(), Length(max=128)],
    )
    confirm = PasswordField(
        "Confirm new password",
        validators=[
            DataRequired(message="Confirm the new password."),
            EqualTo("new_password", message="Passwords must match."),
        ],
    )
