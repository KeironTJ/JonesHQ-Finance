from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.exc import SQLAlchemyError

from . import finance_preferences_bp
from extensions import db
from services.finance.preference_service import FinancePreferenceService
from services.platform.module_registry import ModuleRegistry


@finance_preferences_bp.route('', methods=['POST'])
@finance_preferences_bp.route('/finance', methods=['GET', 'POST'])
def index():
    if not ModuleRegistry.has_active_household(current_user):
        flash('Join a household before managing Finance preferences.', 'info')
        return redirect(url_for('preferences.index'))
    if request.method == 'POST':
        try:
            FinancePreferenceService.update(request.form)
            flash('Your Finance preferences have been saved.', 'success')
            return redirect(url_for('finance_preferences.index'))
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Invalid preference value.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Unable to save personal preferences')
            flash('Unable to save your preferences. Please try again.', 'danger')
    context = FinancePreferenceService.get_page_data()
    if request.method == 'POST':
        context['preferences'] = {
            key: (
                request.form.get(key) == '1' if isinstance(default, bool)
                else request.form.get(key, context['preferences'][key])
            )
            for key, default in FinancePreferenceService.DEFAULTS.items()
        }
    return render_template('preferences/finance.html', **context)


@finance_preferences_bp.route('/save', methods=['POST'])
def save_preference():
    try:
        FinancePreferenceService.save_preference(request.get_json())
    except (ValueError, TypeError) as error:
        db.session.rollback()
        return jsonify(success=False, error=str(error) or 'Invalid preference value.'), 400
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to save a personal preference')
        return jsonify(success=False, error='Unable to save your preference. Please try again.'), 500
    return jsonify(success=True)
