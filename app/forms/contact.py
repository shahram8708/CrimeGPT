from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional


class ContactForm(FlaskForm):
    name = StringField(
        "Name",
        validators=[
            DataRequired(message="Enter your name."),
            Length(min=2, max=120, message="Name must be between 2 and 120 characters."),
        ],
    )
    email = StringField(
        "Email",
        validators=[
            DataRequired(message="Enter your email."),
            Email(message="Enter a valid email address."),
            Length(max=180),
        ],
    )
    organisation = StringField("Organisation", validators=[Optional(), Length(max=160)])
    station_note = StringField("Station or unit", validators=[Optional(), Length(max=160)])
    message = TextAreaField(
        "Message",
        validators=[
            DataRequired(message="Enter a message."),
            Length(min=20, max=2000, message="Message must be between 20 and 2000 characters."),
        ],
    )
    website = StringField("Website", validators=[Optional(), Length(max=200)])
