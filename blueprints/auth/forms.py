"""
Authentication Forms
CSRF-protected forms for login
"""
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, ValidationError
from services.platform.auth_service import AuthService


class LoginForm(FlaskForm):
    """Login form with CSRF protection"""
    email = StringField('Email', filters=[lambda value: value.strip().lower() if value else value], validators=[
        DataRequired(message='Email is required'),
        Email(message='Invalid email address')
    ])
    password = PasswordField('Password', validators=[
        DataRequired(message='Password is required')
    ])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Sign In')


class RegisterForm(FlaskForm):
    """Household registration form"""
    household_name = StringField('Household Name', validators=[
        DataRequired(message='Household name is required'),
        Length(min=2, max=100, message='Household name must be between 2 and 100 characters')
    ])
    name = StringField('Your Name', validators=[
        DataRequired(message='Your name is required'),
        Length(min=2, max=100, message='Name must be between 2 and 100 characters')
    ])
    email = StringField('Email', filters=[lambda value: value.strip().lower() if value else value], validators=[
        DataRequired(message='Email is required'),
        Email(message='Invalid email address')
    ])
    password = PasswordField('Password', validators=[
        DataRequired(message='Password is required'),
        Length(min=10, message='Password must be at least 10 characters')
    ])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(message='Please confirm your password')
    ])
    submit = SubmitField('Create Household')

    def validate_confirm_password(self, field):
        if field.data != self.password.data:
            raise ValidationError('Passwords must match')


def validate_password_strength(password):
    return AuthService.validate_password_strength(password)
