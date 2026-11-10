from flask import has_request_context, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from services.platform.landing_service import LandingService
from services.household.membership_service import HouseholdMembershipService
from services.platform.settings_navigation_service import SettingsNavigationService
from services.platform.module_registry import ModuleRegistry
from utils.db_helpers import get_family_id

from . import central_bp


@central_bp.app_context_processor
def settings_navigation():
    if not has_request_context() or not current_user.is_authenticated:
        return {}
    endpoint = request.endpoint
    if endpoint == 'preferences.index' and request.method == 'POST':
        endpoint = 'preferences.finance'
    context = SettingsNavigationService.get_context(
        current_user, endpoint, request.view_args or {},
    )
    context.update({
        'household_memberships': HouseholdMembershipService.memberships_for(current_user),
        'active_household_id': get_family_id(),
    })
    return context


@central_bp.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('auth.intro'))
    return redirect(LandingService.resolve(current_user))


@central_bp.route('/hub')
@login_required
def hub():
    return render_template(
        'central/index.html',
        modules=ModuleRegistry.modules_for(current_user),
    )


@central_bp.route('/hub/settings')
@login_required
def settings():
    return render_template('settings/overview.html')


@central_bp.route('/hub/settings/finance')
@login_required
def finance_settings():
    return render_template('settings/overview.html')
