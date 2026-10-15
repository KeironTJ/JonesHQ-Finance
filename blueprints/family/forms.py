from flask_wtf import FlaskForm
from wtforms import HiddenField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


class DeleteHouseholdForm(FlaskForm):
    family_id = HiddenField(validators=[DataRequired(message='Reload the household deletion review before confirming.')])
    password = PasswordField('Current password', validators=[DataRequired(), Length(max=200)])
    confirmation = StringField('Type DELETE THIS HOUSEHOLD', validators=[DataRequired(), Length(max=40)])
    submit = SubmitField('Permanently delete this household')
