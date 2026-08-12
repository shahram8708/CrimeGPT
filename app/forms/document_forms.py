from flask_wtf import FlaskForm
from wtforms import BooleanField, HiddenField, IntegerField, SelectField, SelectMultipleField, StringField, TextAreaField
from wtforms.validators import Optional


class GenerateDocumentForm(FlaskForm):
    doc_type = HiddenField()
    language = SelectField(
        "Language",
        choices=[("en", "English"), ("hi", "हिन्दी"), ("gu", "ગુજરાતી")],
        default="en",
    )
    use_ai = BooleanField("Draft paragraphs with Gemini")
    allow_incomplete = BooleanField("Allow incomplete draft")
    juvenile_ack = BooleanField("I understand this is a juvenile and remand custody rules must be verified")
    accused_ids = SelectMultipleField("Accused", coerce=int, validators=[Optional()])
    combined = SelectField(
        "Files",
        choices=[("combined", "Single combined file"), ("split", "One file per accused")],
        default="combined",
    )
    custody_hours_sought = StringField("Hours of police custody sought", validators=[Optional()])
    court_name = StringField("Court", validators=[Optional()])
    grounds = TextAreaField("Grounds", validators=[Optional()])
    investigation_gist = TextAreaField("Investigation gist", validators=[Optional()])
    production_at = StringField("Production date and time", validators=[Optional()])
    description = TextAreaField("Description of person", validators=[Optional()])
    date_from = StringField("Records from", validators=[Optional()])
    date_to = StringField("Records to", validators=[Optional()])
    request_target = StringField("Addressee", validators=[Optional()])


class SaveDocumentForm(FlaskForm):
    history_line = TextAreaField(validators=[Optional()])
    request_line = TextAreaField(validators=[Optional()])
    grounds = TextAreaField(validators=[Optional()])
    prayer = TextAreaField(validators=[Optional()])
    identifiers = TextAreaField(validators=[Optional()])
    gist = TextAreaField(validators=[Optional()])


class DiaryAcceptForm(FlaskForm):
    body = TextAreaField(validators=[Optional()])


class LibraryUploadForm(FlaskForm):
    case_id = SelectField("Case", coerce=int, validators=[Optional()])
    run_identify = BooleanField("Run clause identifier after upload")
    consent = BooleanField("I understand these files are stored")


class CompareForm(FlaskForm):
    left_generated = SelectField("Left generated paper", coerce=int, validators=[Optional()])
    right_generated = SelectField("Right generated paper", coerce=int, validators=[Optional()])
    language = SelectField(
        "Language",
        choices=[("en", "English"), ("hi", "हिन्दी"), ("gu", "ગુજરાતી")],
        default="en",
    )
    case_id = SelectField("Filter by case", coerce=int, validators=[Optional()])


class ReviewForm(FlaskForm):
    body = TextAreaField("Comment", validators=[Optional()])
    status = SelectField(
        "Status",
        choices=[("reviewed_ok", "Reviewed - in order"), ("changes_requested", "Changes requested")],
        default="reviewed_ok",
    )
