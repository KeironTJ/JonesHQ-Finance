"""Site admin (service operator) forms."""
from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional


class HouseholdInviteForm(FlaskForm):
    """Issue a one-time household invite"""
    email = StringField('Restrict to email (optional)', filters=[lambda value: value.strip().lower() if value else value],
                        validators=[Optional(), Email(message='Invalid email address'), Length(max=120)])
    note = StringField('Note (optional)', validators=[Optional(), Length(max=200)])
    days = IntegerField('Expires after (days)', default=7, validators=[
        DataRequired(message='Expiry is required'),
        NumberRange(min=1, max=30, message='Expiry must be between 1 and 30 days')
    ])
    submit = SubmitField('Create invite link')


class SiteSettingsForm(FlaskForm):
    """Service-wide switches"""
    household_signups_paused = BooleanField('Pause new household sign-ups')
    signups_paused_message = StringField('Message shown on the sign-up page (optional)',
                                         validators=[Optional(), Length(max=300)])
    announcement = TextAreaField('Announcement shown to everyone (leave blank for none)',
                                 validators=[Optional(), Length(max=500)])
    announcement_level = SelectField('Announcement style', choices=[
        ('info', 'Information (blue)'),
        ('warning', 'Warning (amber)'),
        ('danger', 'Urgent (red)'),
    ])
    submit = SubmitField('Save settings')
