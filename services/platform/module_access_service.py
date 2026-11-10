from flask import abort, request
from flask_login import current_user

from services.household.membership_service import HouseholdMembershipService


class ModuleAccessService:
    MODULE_LABELS = {'finance': 'Finance', 'household': 'Household Hub'}

    @staticmethod
    def can_access(user, module_key, family_id=None):
        if not user or not user.is_authenticated or not user.is_active:
            return False
        if user.is_managed_child and module_key != 'household':
            return False
        membership = HouseholdMembershipService.get_membership(user, family_id)
        return (
            membership is not None
            and isinstance(membership.allowed_modules, list)
            and module_key in membership.allowed_modules
        )

    @staticmethod
    def enforce_request():
        if request.endpoint in ('static', 'auth.health'):
            return
        if not current_user.is_authenticated:
            return
        if current_user.is_managed_child:
            if (
                request.blueprint == 'site_admin'
                or (request.blueprint or '').startswith('admin')
                or request.endpoint in (
                    'family.join', 'auth.register', 'auth.delete_account',
                    'central.household_access', 'central.update_module_access',
                    'central.create_managed_child', 'central.managed_children',
                    'central.update_managed_child',
                    'central.new_managed_child', 'central.household_setup',
                )
            ):
                abort(403, description='Your guardian manages this action.')
        from services.platform.module_registry import ModuleRegistry
        module = ModuleRegistry.module_for_blueprint(request.blueprint)
        module_key = module['key'] if module else None
        if request.endpoint in (
            'auth.export_data', 'family.create_assignment_label',
            'family.delete_assignment_label', 'family.update_member',
        ):
            module_key = 'finance'
        if module_key is None:
            return
        # Preserve the existing detached-account help/redirect pages, not Finance data access.
        if (
            not current_user.is_managed_child
            and not HouseholdMembershipService.get_membership(current_user)
            and request.endpoint in (
                'settings.overview', 'finance_preferences.index', 'auth.export_data',
            )
        ):
            return
        if not ModuleAccessService.can_access(current_user, module_key):
            abort(403, description='This module is not enabled for your account in this household.')
