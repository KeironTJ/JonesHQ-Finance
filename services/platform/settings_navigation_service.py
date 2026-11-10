from services.platform.module_registry import ModuleRegistry


class SettingsNavigationService:
    @staticmethod
    def get_context(user, endpoint, view_args):
        endpoint = {
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
        }
        has_household = ModuleRegistry.has_active_household(user)
        owner = user.is_household_owner and has_household
        if owner:
            groups['central']['pages'].append({
                'label': 'Household & members', 'endpoint': 'family.index',
                'values': {}, 'scope': 'owner',
                'description': 'Household membership, roles and invitations across all workspaces.',
            })
        groups.update(ModuleRegistry.settings_groups_for(user))

        area, page = None, None
        for key, group in groups.items():
            if endpoint == group['endpoint'] or endpoint in group.get('aliases', ()):
                area = key
            for candidate in group['pages']:
                if (endpoint == candidate['endpoint'] or endpoint in candidate.get('aliases', ())) and all(
                    view_args.get(name) == value for name, value in candidate['values'].items()
                ):
                    area, page = key, candidate
        return {
            'settings_groups': groups, 'settings_area': area, 'settings_page': page,
        }
