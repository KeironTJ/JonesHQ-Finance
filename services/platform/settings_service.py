from decimal import Decimal
from datetime import date

from extensions import db
from models.tax_settings import TaxSettings
from models.settings import Settings
from models.accounts import Account
from models.categories import Category
from models.vendors import Vendor
from models.users import User
from utils.db_helpers import (
    family_get,
    family_get_or_404,
    get_current_user_id,
    get_family_id,
    family_query,
)


class SettingsService:
    SECTIONS = {
        'household': ('Household & payday', {
            'payday_day': ('payday_day', 15, 'int', 'Day of month when payday occurs (adjusted for weekends)'),
        }),
        'credit-cards': ('Credit cards', {
            'default_generation_years': ('default_generation_years', 10, 'int', 'Default number of years to generate future credit card transactions'),
        }),
        'expenses': ('Work expenses', {
            'expense_reimburse_account': ('expenses.reimburse_account_id', None, 'int', 'Account where expense reimbursements are deposited'),
            'expense_payment_account': ('expenses.payment_account_id', None, 'int', 'Default account for bank-paid expenses'),
            'expense_auto_sync': ('expenses.auto_sync', True, 'boolean', 'Automatically sync expense transactions'),
            'expense_period_mode': ('expenses.period_mode', 'calendar_month', 'string', 'Expense accumulation period: calendar_month or payday_period'),
            'expense_cutoff_day': ('expenses.cutoff_day', 0, 'int', 'Day of month expenses are cut off for claiming (0 = last day of month)'),
            'expense_reimburse_day': ('expenses.reimburse_day', 0, 'int', 'Fixed reimbursement day (0 = derive from cutoff/period-end)'),
            'expense_reimburse_category': ('expenses.reimburse_category_id', None, 'int', 'Category for reimbursement/bank-expense transactions'),
            'expense_reimburse_vendor': ('expenses.reimburse_vendor_id', None, 'int', 'Vendor for reimbursement/bank-expense transactions'),
        }),
        'networth': ('Net worth', {
            'networth_start_date': ('networth.start_date', '', 'date', 'Earliest date to show on the net worth timeline'),
        }),
    }

    @staticmethod
    def get_section_data(section):
        title, fields = SettingsService.SECTIONS[section]
        result = {
            'section': section,
            'section_title': title,
            'values': {
                field: Settings.get_value(key, default)
                for field, (key, default, _, _) in fields.items()
            },
        }
        if section == 'expenses':
            result.update(
                accounts=family_query(Account).filter_by(is_active=True).order_by(Account.name).all(),
                categories=family_query(Category).order_by(Category.head_budget, Category.sub_budget).all(),
                vendors=family_query(Vendor).order_by(Vendor.name).all(),
            )
        return result

    @staticmethod
    def _integer(data, field, minimum, maximum, label):
        try:
            value = int(data.get(field))
        except (ValueError, TypeError):
            raise ValueError(f'{label} must be a whole number between {minimum} and {maximum}.')
        if not minimum <= value <= maximum:
            raise ValueError(f'{label} must be between {minimum} and {maximum}.')
        return value

    @staticmethod
    def update_section(section, data):
        if section not in SettingsService.SECTIONS:
            raise ValueError('Unknown settings section.')
        values = {}
        if section == 'household':
            values['payday_day'] = SettingsService._integer(data, 'payday_day', 1, 31, 'Payday')
        elif section == 'credit-cards':
            values['default_generation_years'] = SettingsService._integer(
                data, 'default_generation_years', 1, 50, 'Generation period',
            )
        elif section == 'networth':
            value = (data.get('networth_start_date') or '').strip()
            if value:
                try:
                    if date.fromisoformat(value).isoformat() != value:
                        raise ValueError
                except ValueError:
                    raise ValueError('Timeline start date must be a valid date (YYYY-MM-DD).')
            values['networth_start_date'] = value or None
        elif section == 'expenses':
            mode = data.get('expense_period_mode')
            if mode not in ('calendar_month', 'payday_period'):
                raise ValueError('Please select a valid expense accumulation period.')
            values['expense_period_mode'] = mode
            auto_sync = data.get('expense_auto_sync')
            if auto_sync not in (None, '1'):
                raise ValueError('Auto-sync must be checked or unchecked.')
            values['expense_auto_sync'] = auto_sync == '1'
            values['expense_cutoff_day'] = SettingsService._integer(
                data, 'expense_cutoff_day', 0, 28, 'Expense cutoff day',
            )
            values['expense_reimburse_day'] = SettingsService._integer(
                data, 'expense_reimburse_day', 0, 28, 'Reimbursement day',
            )
            for field, model, label in (
                ('expense_reimburse_account', Account, 'reimbursement account'),
                ('expense_payment_account', Account, 'payment account'),
                ('expense_reimburse_category', Category, 'reimbursement category'),
                ('expense_reimburse_vendor', Vendor, 'reimbursement vendor'),
            ):
                raw = data.get(field)
                if not raw:
                    values[field] = None
                    continue
                try:
                    record_id = int(raw)
                except (ValueError, TypeError):
                    raise ValueError(f'Please select a valid {label}.')
                record = family_get(model, record_id)
                if record is None or (model is Account and not record.is_active):
                    raise ValueError(f'Please select a {label} you can access.')
                values[field] = record.id

        # Validate the whole section before writing anything.
        for field, value in values.items():
            key, _, setting_type, description = SettingsService.SECTIONS[section][1][field]
            if value is None:
                setting = family_query(Settings).filter_by(key=key).first()
                if setting:
                    db.session.delete(setting)
            else:
                Settings.set_value(key, value, description, setting_type)
        db.session.commit()

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
