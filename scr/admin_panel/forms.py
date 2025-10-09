from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired

class LoginForm(FlaskForm):
    username = StringField("Логин", validators=[DataRequired()])
    password = PasswordField("Пароль", validators=[DataRequired()])
    submit = SubmitField("Войти")

class TwoFAForm(FlaskForm):
    code = StringField("Код из приложения", validators=[DataRequired()])
    submit = SubmitField("Подтвердить")
