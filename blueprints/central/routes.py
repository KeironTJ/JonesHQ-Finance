from flask import has_request_context, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from services.platform.landing_service import LandingService
from services.platform.settings_navigation_service import SettingsNavigationService

from . import central_bp


@central_bp.app_context_processor
def settings_navigation():
    if not has_request_context() or not current_user.is_authenticated:
        return {}
    endpoint = request.endpoint
    if endpoint == 'preferences.index' and request.method == 'POST':
        endpoint = 'preferences.finance'
    return SettingsNavigationService.get_context(
        current_user, endpoint, request.view_args or {},
    )


@central_bp.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('auth.intro'))
    return redirect(LandingService.resolve(current_user))


@central_bp.route('/hub')
@login_required
def hub():
    return render_template('central/index.html')


@central_bp.route('/hub/settings')
@login_required
def settings():
    return render_template('settings/overview.html')


@central_bp.route('/hub/settings/finance')
@login_required
def finance_settings():
    return render_template('settings/overview.html')
