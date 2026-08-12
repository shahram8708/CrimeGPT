from flask_wtf import FlaskForm
from wtforms import BooleanField, HiddenField, PasswordField, StringField
from wtforms.validators import DataRequired, Length


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
