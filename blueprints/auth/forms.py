"""
Authentication Forms
CSRF-protected forms for login
"""
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, ValidationError
import re


class LoginForm(FlaskForm):
    """Login form with CSRF protection"""
    email = StringField('Email', validators=[
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
    email = StringField('Email', validators=[
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
    """
    Validate password meets security requirements
    Returns: (is_valid, error_message)
    """
    from flask import current_app
    
    min_length = current_app.config.get('PASSWORD_MIN_LENGTH', 10)
    require_uppercase = current_app.config.get('PASSWORD_REQUIRE_UPPERCASE', True)
    require_lowercase = current_app.config.get('PASSWORD_REQUIRE_LOWERCASE', True)
    require_digit = current_app.config.get('PASSWORD_REQUIRE_DIGIT', True)
    require_special = current_app.config.get('PASSWORD_REQUIRE_SPECIAL', True)
    
    errors = []
    
    if len(password) < min_length:
        errors.append(f"at least {min_length} characters")
    
    if require_uppercase and not re.search(r'[A-Z]', password):
        errors.append("an uppercase letter")
    
    if require_lowercase and not re.search(r'[a-z]', password):
        errors.append("a lowercase letter")
    
    if require_digit and not re.search(r'\d', password):
        errors.append("a number")
    
    if require_special and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        errors.append("a special character (!@#$%^&*(),.?\":{}|<>)")
    
    if errors:
        return False, f"Password must contain {', '.join(errors)}"
    
    return True, None
