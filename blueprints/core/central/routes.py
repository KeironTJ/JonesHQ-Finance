from flask import current_app, flash, has_request_context, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError
from extensions import db
from services.household.household_access_service import HouseholdAccessService
from services.platform.landing_service import LandingService
from services.household.membership_service import HouseholdMembershipService
from services.platform.settings_navigation_service import SettingsNavigationService
from services.platform.module_registry import ModuleRegistry
from services.platform.module_access_service import ModuleAccessService
from utils.db_helpers import get_family_id
from utils.reauth import recent_auth_required

from . import central_bp


@central_bp.app_context_processor
def settings_navigation():
    if not has_request_context() or not current_user.is_authenticated:
        return {}
    context = SettingsNavigationService.get_context(
        current_user, request.endpoint, request.view_args or {},
    )
    active_module = ModuleRegistry.module_for_blueprint(request.blueprint)
    if active_module and not ModuleAccessService.can_access(current_user, active_module['key']):
        active_module = None
    context.update({
        'household_memberships': HouseholdMembershipService.memberships_for(current_user),
        'active_household_id': get_family_id(),
        'active_module': active_module,
        'navigation_modules': ModuleRegistry.modules_for(current_user),
        'can_open_household': ModuleAccessService.can_access(current_user, 'household'),
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
    if current_user.is_managed_child and ModuleAccessService.can_access(current_user, 'household'):
        from services.household.my_day_service import MyDayService
        return render_template('household/my_day.html', **MyDayService.page_data())
    return render_template(
        'central/index.html',
        modules=ModuleRegistry.modules_for(current_user),
    )


@central_bp.route('/hub/settings')
@login_required
def settings():
    return render_template('central/settings.html')


@central_bp.route('/hub/setup')
@login_required
def household_setup():
    from services.household.setup_service import HouseholdSetupService
    return render_template('central/setup.html', **HouseholdSetupService.page_data())


@central_bp.route('/hub/settings/children/new')
@login_required
def new_managed_child():
    HouseholdAccessService.require_owner()
    return render_template('central/child_form.html', submitted={})


@central_bp.route('/hub/settings/access')
@login_required
def household_access():
    return render_template('central/access.html', **HouseholdAccessService.get_page_data())


@central_bp.route('/hub/settings/access/members/<int:member_id>', methods=['POST'])
@login_required
@recent_auth_required
def update_module_access(member_id):
    try:
        HouseholdAccessService.update_modules(member_id, {'modules': request.form.getlist('modules')})
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Invalid module access.', 'danger')
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to update household module access')
        flash('Unable to update module access. No changes were saved.', 'danger')
    else:
        flash('Module access saved for this household.', 'success')
    return redirect(url_for('central.household_access'))


@central_bp.route('/hub/settings/children/create', methods=['POST'])
@login_required
@recent_auth_required
def create_managed_child():
    HouseholdAccessService.require_owner()
    try:
        HouseholdAccessService.create_child(dict(request.form))
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Invalid child-account details.', 'danger')
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to create managed child account')
        flash('Unable to create the child account. No changes were saved.', 'danger')
    else:
        flash('Managed child account created. You are its designated guardian.', 'success')
        return redirect(url_for('family.index'))
    return render_template(
        'central/child_form.html',
        submitted={key: request.form.get(key, '') for key in ('name', 'email')},
    )


@central_bp.route('/account/children')
@login_required
def managed_children():
    children = HouseholdAccessService.managed_children()
    return render_template(
        'central/children.html', children=children,
        guardians={child.id: HouseholdAccessService.guardians_for(child) for child in children},
    )


@central_bp.route('/account/children/<int:child_id>', methods=['POST'])
@login_required
@recent_auth_required
def update_managed_child(child_id):
    try:
        HouseholdAccessService.update_child(child_id, dict(request.form))
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Invalid child-account change.', 'danger')
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to update managed child account')
        flash('Unable to update the child account. No changes were saved.', 'danger')
    else:
        flash('Child-account management updated. Household module grants are unchanged.', 'success')
    return redirect(url_for('central.managed_children'))
