"""
Authentication Forms
CSRF-protected forms for login
"""
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, HiddenField
from wtforms.validators import DataRequired, Email, Length, Optional, ValidationError
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
    invite_token = HiddenField()
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


class TwoFactorCodeForm(FlaskForm):
    """Authenticator app or recovery code"""
    code = StringField('Authentication code', validators=[
        DataRequired(message='Enter the code from your authenticator app'),
        Length(max=40)
    ])
    submit = SubmitField('Verify')


class PasswordConfirmForm(FlaskForm):
    """Re-enter password (and optionally a code) before a sensitive change"""
    password = PasswordField('Current password', validators=[DataRequired(message='Password is required')])
    code = StringField('Authentication code', validators=[Optional(), Length(max=40)])
    submit = SubmitField('Confirm')


class ReauthenticateForm(FlaskForm):
    """Confirm the current password before a sensitive action"""
    password = PasswordField('Password', validators=[DataRequired(message='Password is required')])
    submit = SubmitField('Confirm')


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Current password', validators=[DataRequired(message='Current password is required')])
    new_password = PasswordField('New password', validators=[
        DataRequired(message='New password is required'),
        Length(max=200),
    ])
    confirm_password = PasswordField('Confirm new password', validators=[DataRequired(message='Please confirm your new password')])
    submit = SubmitField('Change password')


class ForgotPasswordForm(FlaskForm):
    email = StringField('Email', filters=[lambda value: value.strip().lower() if value else value], validators=[
        DataRequired(message='Email is required'),
        Email(message='Invalid email address'),
        Length(max=120),
    ])
    submit = SubmitField('Email me a reset link')


class DeleteAccountForm(FlaskForm):
    password = PasswordField('Current password', validators=[DataRequired(), Length(max=200)])
    confirmation = StringField('Type DELETE MY ACCOUNT', validators=[DataRequired(), Length(max=40)])
    submit = SubmitField('Permanently delete my account')


class ResetPasswordForm(FlaskForm):
    new_password = PasswordField('New password', validators=[
        DataRequired(message='New password is required'),
        Length(max=200),
    ])
    confirm_password = PasswordField('Confirm new password', validators=[DataRequired(message='Please confirm your new password')])
    submit = SubmitField('Set new password')


def validate_password_strength(password):
    return AuthService.validate_password_strength(password)
