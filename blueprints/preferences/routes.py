from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

from . import preferences_bp
from extensions import db
from services.platform.preference_service import PreferenceService


@preferences_bp.route('', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            PreferenceService.update(request.form)
            flash('Your preferences have been saved.', 'success')
            return redirect(url_for('preferences.index'))
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Invalid preference value.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Unable to save personal preferences')
            flash('Unable to save your preferences. Please try again.', 'danger')
    context = PreferenceService.get_page_data()
    if request.method == 'POST':
        context['preferences'] = {
            key: (
                request.form.get(key) == '1' if isinstance(default, bool)
                else request.form.get(key, context['preferences'][key])
            )
            for key, default in PreferenceService.DEFAULTS.items()
        }
    return render_template('preferences/index.html', **context)


@preferences_bp.route('/save', methods=['POST'])
def save_preference():
    try:
        PreferenceService.save_preference(request.get_json())
    except (ValueError, TypeError) as error:
        db.session.rollback()
        return jsonify(success=False, error=str(error) or 'Invalid preference value.'), 400
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to save a personal preference')
        return jsonify(success=False, error='Unable to save your preference. Please try again.'), 500
    return jsonify(success=True)
