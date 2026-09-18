from decimal import Decimal

from extensions import db
from models.tax_settings import TaxSettings
from utils.db_helpers import family_get_or_404


class SettingsService:
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
