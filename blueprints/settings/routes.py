from flask import render_template, request, redirect, url_for, flash
from . import settings_bp
from models.settings import Settings
from extensions import db


@settings_bp.route('/settings')
def index():
    """Display application settings"""
    # Get or create default settings
    default_generation_years = Settings.get_value('default_generation_years', 10)
    
    return render_template('settings/index.html',
                         default_generation_years=default_generation_years)


@settings_bp.route('/settings/update', methods=['POST'])
def update():
    """Update application settings"""
    try:
        # Credit Card Settings
        generation_years = int(request.form.get('default_generation_years', 10))
        
        # Validate
        if generation_years < 1 or generation_years > 50:
            flash('Generation period must be between 1 and 50 years!', 'danger')
            return redirect(url_for('settings.index'))
        
        # Update settings
        Settings.set_value(
            'default_generation_years',
            generation_years,
            'Default number of years to generate future credit card transactions',
            'int'
        )
        
        db.session.commit()
        flash(f'Settings updated successfully! Future generation will default to {generation_years} years.', 'success')
        
    except ValueError:
        db.session.rollback()
        flash('Invalid value provided!', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating settings: {str(e)}', 'danger')
    
    return redirect(url_for('settings.index'))
