from flask import render_template, request, redirect, url_for, flash
from . import settings_bp
from models.settings import Settings
from extensions import db


@settings_bp.route('/settings')
def index():
    """Display application settings"""
    # Get or create default settings
    default_generation_years = Settings.get_value('default_generation_years', 10)
    payday_day = Settings.get_value('payday_day', 15)
    
    return render_template('settings/index.html',
                         default_generation_years=default_generation_years,
                         payday_day=payday_day)


@settings_bp.route('/settings/update', methods=['POST'])
def update():
    """Update application settings"""
    try:
        # Credit Card Settings
        generation_years = int(request.form.get('default_generation_years', 10))
        
        # Payday Settings
        payday_day = int(request.form.get('payday_day', 15))
        
        # Validate
        if generation_years < 1 or generation_years > 50:
            flash('Generation period must be between 1 and 50 years!', 'danger')
            return redirect(url_for('settings.index'))
        
        if payday_day < 1 or payday_day > 31:
            flash('Payday must be between 1 and 31!', 'danger')
            return redirect(url_for('settings.index'))
        
        # Update settings
        Settings.set_value(
            'default_generation_years',
            generation_years,
            'Default number of years to generate future credit card transactions',
            'int'
        )
        
        Settings.set_value(
            'payday_day',
            payday_day,
            'Day of month when payday occurs (adjusted for weekends)',
            'int'
        )
        
        db.session.commit()
        flash(f'Settings updated successfully! Payday set to {payday_day} of each month.', 'success')
        
    except ValueError:
        db.session.rollback()
        flash('Invalid value provided!', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating settings: {str(e)}', 'danger')
    
    return redirect(url_for('settings.index'))
