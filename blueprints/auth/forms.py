"""
Authentication Forms
CSRF-protected forms for login
"""
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, HiddenField, IntegerField
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional, ValidationError
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


class HouseholdInviteForm(FlaskForm):
    """Site-admin form for issuing a one-time household invite"""
    email = StringField('Restrict to email (optional)', filters=[lambda value: value.strip().lower() if value else value],
                        validators=[Optional(), Email(message='Invalid email address'), Length(max=120)])
    note = StringField('Note (optional)', validators=[Optional(), Length(max=200)])
    days = IntegerField('Expires after (days)', default=7, validators=[
        DataRequired(message='Expiry is required'),
        NumberRange(min=1, max=30, message='Expiry must be between 1 and 30 days')
    ])
    submit = SubmitField('Create invite link')


def validate_password_strength(password):
    return AuthService.validate_password_strength(password)
