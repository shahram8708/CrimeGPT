from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
from wtforms import (
    BooleanField,
    DateField,
    DateTimeLocalField,
    SelectField,
    SelectMultipleField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, Optional

from app.models.evidence import DIARY_TYPES, EVIDENCE_TAGS


class EvidenceUploadForm(FlaskForm):
    file = FileField("File", validators=[FileRequired(message="Choose a file.")])
    caption = StringField("Caption", validators=[Optional(), Length(max=300)])
    tag = SelectField(
        "Tag",
        choices=[(t, t.replace("_", " ")) for t in EVIDENCE_TAGS],
        default="exhibit",
    )
    exhibit_no = StringField("Exhibit no.", validators=[Optional(), Length(max=20)])
    taken_at = DateTimeLocalField("Taken at", format="%Y-%m-%dT%H:%M", validators=[Optional()])
    case_item_id = SelectField("Linked item", coerce=int, validators=[Optional()])
    keep_exif = BooleanField("Keep device location (EXIF)")
    consent = BooleanField("I understand these files are stored for this case")


class DiaryEntryForm(FlaskForm):
    entry_type = SelectField(
        "Entry type",
        choices=[(t, t.replace("_", " ")) for t in DIARY_TYPES if t != "correction"],
        validators=[DataRequired()],
    )
    occurred_at = DateTimeLocalField(
        "Occurred at",
        format="%Y-%m-%dT%H:%M",
        validators=[DataRequired(message="Enter the time of the event.")],
    )
    place = StringField("Place", validators=[Optional(), Length(max=200)])
    body = TextAreaField(
        "Entry",
        validators=[
            DataRequired(message="Write the diary line."),
            Length(min=20, max=10000, message="Entry must be between 20 and 10000 characters."),
        ],
    )
    evidence_ids = SelectMultipleField("Linked exhibits", coerce=int, validators=[Optional()])


class DiaryCorrectForm(FlaskForm):
    body = TextAreaField(
        "Correction",
        validators=[DataRequired(), Length(min=20, max=10000)],
    )
    occurred_at = DateTimeLocalField(
        "Occurred at",
        format="%Y-%m-%dT%H:%M",
        validators=[DataRequired()],
    )


class DiaryExportForm(FlaskForm):
    date_from = DateField("From", validators=[DataRequired()])
    date_to = DateField("To", validators=[DataRequired()])
    language = SelectField(
        "Language",
        choices=[("en", "English"), ("hi", "हिन्दी"), ("gu", "ગુજરાતી")],
        default="en",
    )
    summarize = BooleanField("Summarize for court")


class AssignmentForm(FlaskForm):
    user_id = SelectField("Field officer", coerce=int, validators=[DataRequired()])
