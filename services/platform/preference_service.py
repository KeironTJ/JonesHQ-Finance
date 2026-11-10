from extensions import db
from models.users import User
from services.platform.landing_service import LandingService
from utils.db_helpers import get_current_user_id


class PreferenceService:
    PALETTES = {
        'blue': ('Blue', 'Classic, confident and clear'),
        'graphite': ('Graphite', 'Refined black and charcoal'),
        'green': ('Green', 'Calm, grounded and natural'),
        'pink': ('Pink', 'Warm rose with a softer edge'),
        'sky': ('Light blue', 'Fresh, airy and focused'),
        'purple': ('Purple', 'Rich, thoughtful and distinctive'),
    }
    APPEARANCE_DEFAULTS = {'mode': 'light', 'palette': 'blue'}
    MODES = ('light', 'dark', 'auto')

    @staticmethod
    def update_workspace(data):
        if not hasattr(data, 'get'):
            raise ValueError('Workspace preferences must be an object.')
        workspace = data.get('default_workspace')
        if not isinstance(workspace, str) or workspace not in LandingService.WORKSPACES:
            raise ValueError('Choose Central Hub or Finance as your default workspace.')
        user = PreferenceService._user()
        user.preferences = {**(user.preferences or {}), 'default_workspace': workspace}
        db.session.commit()

    @staticmethod
    def appearance_for(user):
        preferences = (user.preferences or {}) if user.is_authenticated else {}
        return {
            key: preferences.get(f'appearance.{key}', default)
            for key, default in PreferenceService.APPEARANCE_DEFAULTS.items()
        }

    @staticmethod
    def update_appearance(data):
        if not hasattr(data, 'get'):
            raise ValueError('Appearance data must be an object.')
        values = {}
        for key, options in [('mode', PreferenceService.MODES), ('palette', PreferenceService.PALETTES)]:
            value = data.get(key)
            if not isinstance(value, str) or value not in options:
                raise ValueError(f'Choose a supported appearance {key}.')
            values[f'appearance.{key}'] = value
        user = PreferenceService._user()
        user.preferences = {**(user.preferences or {}), **values}
        db.session.commit()

    @staticmethod
    def _user():
        user_id = get_current_user_id()
        user = db.session.get(User, user_id) if user_id else None
        if user is None:
            raise ValueError('Unable to identify the current user.')
        return user
