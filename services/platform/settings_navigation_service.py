from services.platform.settings_service import SettingsService


class SettingsNavigationService:
    @staticmethod
    def get_context(user, endpoint, view_args):
        endpoint = {
            'settings.edit_tax_settings': 'settings.tax_settings',
            'auth.two_factor_setup': 'auth.account_security',
            'auth.delete_account': 'auth.account_security',
        }.get(endpoint, endpoint)
        groups = {
            'central': {
                'label': 'Central', 'endpoint': 'central.settings',
                'pages': [
                    {
                        'label': 'Appearance & starting point',
                        'endpoint': 'preferences.index', 'values': {}, 'scope': 'personal',
                        'description': 'Your colours, display mode and default workspace across the application.',
                    },
                    {
                        'label': 'Account & security',
                        'endpoint': 'auth.account_security', 'values': {}, 'scope': 'personal',
                        'description': 'Password, sign-in security, sessions and account management.',
                    },
                ],
            },
            'finance': {
                'label': 'Finance', 'endpoint': 'central.finance_settings', 'pages': [],
            },
        }
        has_household = user.family_id is not None
        owner = user.is_household_owner and has_household
        if owner:
            groups['central']['pages'].append({
                'label': 'Household & members', 'endpoint': 'family.index',
                'values': {}, 'scope': 'owner',
                'description': 'Household membership, roles and invitations across all workspaces.',
            })
        if has_household:
            groups['finance']['pages'].append({
                'label': 'Your preferences', 'endpoint': 'preferences.finance',
                'values': {}, 'scope': 'personal',
                'description': 'Your dashboard, reminders, list display and default bank account.',
            })
        if owner:
            groups['finance']['pages'].append({
                'label': 'Access & assignment', 'endpoint': 'settings.finance_access',
                'values': {}, 'scope': 'owner',
                'description': 'Member Finance permissions, transaction display names and assignment labels.',
            })
            for section, (title, _) in SettingsService.SECTIONS.items():
                groups['finance']['pages'].append({
                    'label': title, 'endpoint': 'settings.module_settings',
                    'values': {'section': section}, 'scope': 'owner',
                    'description': f'Shared {title.lower()} rules and defaults for your household.',
                })
            groups['finance']['pages'].append({
                'label': 'Tax & National Insurance', 'endpoint': 'settings.tax_settings',
                'values': {}, 'scope': 'owner',
                'description': 'Tax-year bands and rates used to estimate take-home pay.',
            })
        if has_household and user.can_access_section('vendors'):
            groups['finance']['pages'].append({
                'label': 'Vendor types', 'endpoint': 'vendors.types_index',
                'values': {}, 'scope': 'household',
                'description': 'Organise the vendor types used by your household in Finance.',
            })

        area, page = None, None
        for key, group in groups.items():
            if endpoint == group['endpoint']:
                area = key
            for candidate in group['pages']:
                if endpoint == candidate['endpoint'] and all(
                    view_args.get(name) == value for name, value in candidate['values'].items()
                ):
                    area, page = key, candidate
        if endpoint == 'settings.index':
            area = 'finance'
        return {
            'settings_groups': groups, 'settings_area': area, 'settings_page': page,
        }
