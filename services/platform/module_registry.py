from services.household.membership_service import HouseholdMembershipService


_MODULES = (
    {
        'key': 'finance',
        'title': 'Finance',
        'description': 'A clear view of your money, from everyday banking and bills to borrowing and longer-term plans.',
        'icon': 'bi-wallet2',
        'home_endpoint': 'dashboard.index',
        'status': 'available',
        'requires_household': True,
        'default_destination': True,
    },
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
