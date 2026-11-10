from extensions import db
from models.accounts import Account
from services.platform.preference_service import PreferenceService
from services.finance.settings_service import SettingsService
from utils.db_helpers import family_query


class FinancePreferenceService:
    DEFAULTS = {
        'dashboard.networth_expanded': True,
        'dashboard.account_selection_expanded': True,
        'dashboard.payday_expanded': True,
        'dashboard.summaries_expanded': True,
        'dashboard.quick_nav_expanded': True,
        'categories.collapse_all_default': False,
        'vendors.collapse_all_default': False,
        'dashboard.attention_days': 60,
    }

    @staticmethod
    def get_value(key):
        if key not in FinancePreferenceService.DEFAULTS:
            raise ValueError('Unsupported preference key.')
        return (PreferenceService._user().preferences or {}).get(
            key, FinancePreferenceService.DEFAULTS[key],
        )

    @staticmethod
    def get_page_data():
        accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
        user = PreferenceService._user()
        return {
            'preferences': {
                key: FinancePreferenceService.get_value(key)
                for key in FinancePreferenceService.DEFAULTS
            },
            'accounts': accounts,
            'default_account_id': user.default_account_id if any(
                account.id == user.default_account_id for account in accounts
            ) else None,
        }

    @staticmethod
    def update(data):
        values = {}
        for key, default in FinancePreferenceService.DEFAULTS.items():
            if not isinstance(default, bool):
                values[key] = FinancePreferenceService._attention_days(
                    data.get(key, FinancePreferenceService.get_value(key)),
                )
                continue
            value = data.get(key)
            if value not in (None, '1'):
                raise ValueError('Preference values must be checked or unchecked.')
            values[key] = value == '1'
        user = PreferenceService._user()
        SettingsService.update_default_account(data)
        user.preferences = {**(user.preferences or {}), **values}
        db.session.commit()

    @staticmethod
    def _attention_days(value):
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError('Reminder window must be a whole number from 1 to 365 days.')
        try:
            days = int(value)
        except ValueError as error:
            raise ValueError('Reminder window must be a whole number from 1 to 365 days.') from error
        if not 1 <= days <= 365:
            raise ValueError('Reminder window must be between 1 and 365 days.')
        return days

    @staticmethod
    def save_preference(data):
        if not isinstance(data, dict):
            raise ValueError('Preference data must be an object.')
        key = data.get('key')
        if not isinstance(key, str) or key not in FinancePreferenceService.DEFAULTS:
            raise ValueError('Unsupported preference key.')
        value = data.get('value')
        if key == 'dashboard.attention_days':
            value = FinancePreferenceService._attention_days(value)
        elif not isinstance(value, bool):
            raise ValueError('Preference value must be boolean.')
        user = PreferenceService._user()
        user.preferences = {**(user.preferences or {}), key: value}
        db.session.commit()
