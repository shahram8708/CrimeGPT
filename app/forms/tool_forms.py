from flask_wtf import FlaskForm
from wtforms import BooleanField, HiddenField, SelectField, SelectMultipleField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class LegalIntelForm(FlaskForm):
    narrative = TextAreaField(
        "Narrative",
        validators=[
            DataRequired(message="Paste or write the incident narrative."),
            Length(min=50, max=20000, message="Narrative must be between 50 and 20000 characters."),
        ],
    )
    language = SelectField(
        "Language",
        choices=[("en", "English"), ("hi", "हिन्दी"), ("gu", "ગુજરાતી")],
        default="en",
    )
    focus = SelectField(
        "Focus",
        choices=[
            ("charging", "Charging"),
            ("remand", "Remand procedure"),
            ("evidence", "Evidence"),
        ],
        default="charging",
    )
    use_search = BooleanField("Use web grounding for publicly reported judgments", default=True)
    case_id = SelectField("Link a case (optional)", coerce=int, validators=[Optional()])
    ack = HiddenField()
    hide_again = HiddenField()


class SuggestIntelForm(FlaskForm):
    focus = SelectField(
        "Focus",
        choices=[
            ("charging", "Charging"),
            ("remand", "Remand procedure"),
            ("evidence", "Evidence"),
        ],
        default="charging",
    )
    use_search = BooleanField("Use web grounding for publicly reported judgments", default=True)
    ack = HiddenField()
    hide_again = HiddenField()


class ApplyIntelForm(FlaskForm):
    selected = SelectMultipleField("Sections", choices=[], validators=[Optional()])


class LinkCaseForm(FlaskForm):
    case_id = SelectField("Case", coerce=int, validators=[DataRequired()])


class QaForm(FlaskForm):
    body = TextAreaField(
        "Question",
        validators=[
            DataRequired(message="Write a question."),
            Length(min=5, max=4000, message="Question must be between 5 and 4000 characters."),
        ],
    )
    case_id = SelectField("Case", coerce=int, validators=[Optional()])
    language = SelectField(
        "Language",
        choices=[("en", "English"), ("hi", "हिन्दी"), ("gu", "ગુજરાતી")],
        default="en",
    )


class AnalyzeForm(FlaskForm):
    case_id = SelectField("Case", coerce=int, validators=[Optional()])
    language = SelectField(
        "Language hint",
        choices=[("en", "English"), ("hi", "हिन्दी"), ("gu", "ગુજરાતી")],
        default="en",
    )
    consent = BooleanField("I understand these files are stored")


class ExplainForm(FlaskForm):
    source_text = TextAreaField(
        "Text",
        validators=[
            DataRequired(message="Paste the text."),
            Length(min=8, max=12000, message="Text must be between 8 and 12000 characters."),
        ],
    )
    target_lang = SelectField(
        "Target language",
        choices=[("en", "English"), ("hi", "हिन्दी"), ("gu", "ગુજરાતી")],
        default="en",
    )
    mode = SelectField(
        "Mode",
        choices=[("explain", "Explain in plain language"), ("translate", "Translate")],
        default="explain",
    )
    case_id = SelectField("Case", coerce=int, validators=[Optional()])


class ApplyFieldForm(FlaskForm):
    field_key = HiddenField(validators=[DataRequired()])
    field_value = HiddenField(validators=[DataRequired()])
    party_id = SelectField("Party", coerce=int, validators=[Optional()])
    confirm = BooleanField("I confirm this date should replace the incident date")


class EmptyPostForm(FlaskForm):
    pass


class GapAcceptForm(FlaskForm):
    label = HiddenField(validators=[DataRequired()])
    why = HiddenField()
    severity = HiddenField()
    deep_link = HiddenField()
