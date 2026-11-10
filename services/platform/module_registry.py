from flask import current_app

from blueprints.finance import MODULE as FINANCE_MODULE
from services.household.membership_service import HouseholdMembershipService


_MODULES = (
    FINANCE_MODULE,
    {
        'key': 'household',
        'title': 'Household Hub',
        'description': 'Organise household life with shared meals, activities and tasks.',
        'icon': 'bi-house-heart',
        'home_endpoint': None,
        'status': 'planned',
        'requires_household': True,
        'default_destination': False,
    },
)

_CENTRAL_DESTINATION = ('Central Hub', 'central.hub')


class ModuleRegistry:
    """Canonical catalog of platform modules and their entry points."""

    @staticmethod
    def register_modules(app):
        registered_modules = {}
        for module in _MODULES:
            if module['status'] == 'available':
                previous_blueprints = set(app.blueprints)
                module['register_blueprints'](app)
                for name in set(app.blueprints) - previous_blueprints:
                    registered_modules[name] = module
        app.extensions['platform_modules'] = registered_modules

    @staticmethod
    def module_for_blueprint(name):
        return current_app.extensions['platform_modules'].get(name)

    @staticmethod
    def settings_groups_for(user):
        return {
            module['key']: module['settings_group'](user)
            for module in _MODULES if module['status'] == 'available'
        }

    @staticmethod
    def has_active_household(user):
        return HouseholdMembershipService.get_membership(user) is not None

    @staticmethod
    def modules_for(user):
        has_household = ModuleRegistry.has_active_household(user)
        modules = []
        for definition in _MODULES:
            module = definition.copy()
            module['can_open'] = (
                module['status'] == 'available'
                and (not module['requires_household'] or has_household)
            )
            modules.append(module)
        return modules

    @staticmethod
    def default_destinations():
        destinations = {'central': _CENTRAL_DESTINATION}
        destinations.update({
            module['key']: (module['title'], module['home_endpoint'])
            for module in _MODULES
            if module['default_destination']
        })
        return destinations
