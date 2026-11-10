from services.platform.module_registry import ModuleRegistry


class SettingsNavigationService:
    @staticmethod
    def get_context(user, endpoint, view_args):
        endpoint = {
            'auth.two_factor_setup': 'auth.account_security',
            'auth.delete_account': 'auth.account_security',
            'central.create_managed_child': 'central.new_managed_child',
        }.get(endpoint, endpoint)
        groups = {
            'central': {
                'label': 'Central', 'endpoint': 'central.settings',
                'pages': [
                    {
                        'label': 'Appearance & starting point',
                        'endpoint': 'preferences.index', 'values': {}, 'scope': 'personal',
                        'category': 'account',
                        'description': (
                            'Your colours, display mode and My day starting point.'
                            if user.is_managed_child else
                            'Your colours, display mode and default workspace across the application.'
                        ),
                    },
                    {
                        'label': 'Account & security',
                        'endpoint': 'auth.account_security', 'values': {}, 'scope': 'personal',
                        'category': 'account',
                        'description': 'Password, sign-in security, sessions and account management.',
                    },
                ],
            },
        }
        has_household = ModuleRegistry.has_active_household(user)
        owner = user.is_household_owner and has_household
        if not user.is_managed_child:
            groups['central']['pages'].append({
                'label': 'Children you supervise', 'endpoint': 'central.managed_children',
                'values': {}, 'scope': 'guardian', 'category': 'people',
                'description': 'Manage child status and designated guardianship for accounts you supervise.',
            })
        if owner:
            groups['central']['pages'].append({
                'label': 'Household & people', 'endpoint': 'family.index',
                'values': {}, 'scope': 'owner', 'category': 'people',
                'description': 'Household membership, roles and invitations across all workspaces.',
            })
            groups['central']['pages'].append({
                'label': 'Member access', 'endpoint': 'central.household_access',
                'values': {}, 'scope': 'owner', 'category': 'people',
                'description': 'Control module access for adults and managed children in this household.',
            })
            groups['central']['pages'].extend([
                {
                    'label': 'Add child', 'endpoint': 'central.new_managed_child',
                    'values': {}, 'scope': 'owner', 'category': 'people',
                    'description': 'Create a child sign-in with Household Hub access and Finance blocked.',
                },
                {
                    'label': 'Household setup', 'endpoint': 'central.household_setup',
                    'values': {}, 'scope': 'owner', 'category': 'people',
                    'description': 'A guided checklist for people, access, jobs and rewards.',
                },
            ])
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
