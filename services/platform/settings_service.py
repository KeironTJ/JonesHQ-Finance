from decimal import Decimal

from extensions import db
from models.tax_settings import TaxSettings
from models.settings import Settings
from models.accounts import Account
from models.users import User
from utils.db_helpers import (
    family_get,
    family_get_or_404,
    get_current_user_id,
    get_family_id,
)


class SettingsService:
    @staticmethod
    def get_default_account(accounts):
        user_id = get_current_user_id()
        user = db.session.get(User, user_id) if user_id else None
        if user:
            for account in accounts:
                if account.id == user.default_account_id:
                    return account
        return accounts[0] if accounts else None

    @staticmethod
    def update_default_account(data):
        user_id = get_current_user_id()
        user = db.session.get(User, user_id) if user_id else None
        if not user:
            raise ValueError('Unable to identify the current user.')

        account_id = data.get('default_account_id')
        if not account_id:
            user.default_account_id = None
            return None

        account = family_get(Account, int(account_id))
        if not account or not account.is_active:
            raise ValueError('Please select an active account you can access.')
        user.default_account_id = account.id
        return account

    @staticmethod
    def clear_networth_start_date():
        setting = Settings.query.filter_by(
            key='networth.start_date',
            family_id=get_family_id(),
        ).first()
        if setting:
            db.session.delete(setting)
        return setting

    @staticmethod
    def update_tax_settings(tax_settings_id, form_data):
        tax_year = family_get_or_404(TaxSettings, tax_settings_id)
        tax_year.personal_allowance = Decimal(form_data['personal_allowance'])
        tax_year.basic_rate_limit = Decimal(form_data['basic_rate_limit'])
        tax_year.higher_rate_limit = Decimal(form_data['higher_rate_limit'])
        tax_year.basic_rate = Decimal(form_data['basic_rate']) / 100
        tax_year.higher_rate = Decimal(form_data['higher_rate']) / 100
        tax_year.additional_rate = Decimal(form_data['additional_rate']) / 100
        tax_year.ni_threshold = Decimal(form_data['ni_threshold'])
        tax_year.ni_upper_earnings = Decimal(form_data['ni_upper_earnings'])
        tax_year.ni_basic_rate = Decimal(form_data['ni_basic_rate']) / 100
        tax_year.ni_additional_rate = Decimal(form_data['ni_additional_rate']) / 100
        tax_year.notes = form_data.get('notes', '')
        tax_year.is_active = form_data.get('is_active') == 'on'
        db.session.commit()
        return tax_year
