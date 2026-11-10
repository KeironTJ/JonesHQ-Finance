from services.finance.settings_service import SettingsService
from services.household.membership_service import HouseholdMembershipService


class FinanceSettingsNavigationService:
    @staticmethod
    def get_group(user):
        group = {
            'label': 'Finance', 'endpoint': 'settings.overview',
            'aliases': ('settings.index',), 'pages': [],
        }
        membership = HouseholdMembershipService.get_membership(user)
        if membership is None:
            return group
        group['pages'].append({
            'label': 'Your preferences', 'endpoint': 'finance_preferences.index',
            'values': {}, 'scope': 'personal',
            'description': 'Your dashboard, reminders, list display and default bank account.',
        })
        if membership.role == 'admin':
            group['pages'].append({
                'label': 'Access & assignment', 'endpoint': 'settings.finance_access',
                'values': {}, 'scope': 'owner',
                'description': 'Member Finance permissions, transaction display names and assignment labels.',
            })
            for section, (title, _) in SettingsService.SECTIONS.items():
                group['pages'].append({
                    'label': title, 'endpoint': 'settings.module_settings',
                    'values': {'section': section}, 'scope': 'owner',
                    'description': f'Shared {title.lower()} rules and defaults for your household.',
                })
            group['pages'].append({
                'label': 'Tax & National Insurance', 'endpoint': 'settings.tax_settings',
                'aliases': ('settings.edit_tax_settings',),
                'values': {}, 'scope': 'owner',
                'description': 'Tax-year bands and rates used to estimate take-home pay.',
            })
        if user.can_access_section('vendors'):
            group['pages'].append({
                'label': 'Vendor types', 'endpoint': 'vendors.types_index',
                'values': {}, 'scope': 'household',
                'description': 'Organise the vendor types used by your household in Finance.',
            })
        return group
