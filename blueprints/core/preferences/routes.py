from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.exc import SQLAlchemyError

from . import preferences_bp
from extensions import db
from services.platform.preference_service import PreferenceService
from services.platform.landing_service import LandingService
from services.platform.module_registry import ModuleRegistry


@preferences_bp.route('', methods=['GET'])
def index():
    return render_template(
        'preferences/index.html',
        default_workspace=LandingService.workspace_for(current_user),
        workspaces=ModuleRegistry.destinations_for(current_user),
    )


@preferences_bp.route('/workspace', methods=['POST'])
def workspace():
    try:
        PreferenceService.update_workspace(request.form)
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Invalid workspace choice.', 'danger')
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to save default workspace')
        flash('Unable to save your default workspace. Please try again.', 'danger')
    else:
        flash('Your default workspace has been saved.', 'success')
    return redirect(url_for('preferences.index', _anchor='workspace-card'))


@preferences_bp.route('/appearance', methods=['POST'])
def appearance():
    try:
        data = request.get_json() if request.is_json else request.form
        PreferenceService.update_appearance(data)
    except (ValueError, TypeError) as error:
        db.session.rollback()
        message = str(error) or 'Invalid appearance choice.'
        if request.is_json:
            return jsonify(success=False, error=message), 400
        flash(message, 'danger')
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to save appearance preferences')
        message = 'Unable to save your appearance. Please try again.'
        if request.is_json:
            return jsonify(success=False, error=message), 500
        flash(message, 'danger')
    else:
        if request.is_json:
            return jsonify(success=True)
        flash('Your appearance has been saved to your account.', 'success')
    return redirect(url_for('preferences.index', _anchor='appearance-card'))
