"""
Add default pension settings to the database
Run this once to initialize pension-related settings
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from extensions import db
from models.settings import Settings


def add_pension_settings():
    """Add default pension settings"""
    app = create_app()
    with app.app_context():
        settings_to_add = [
            # Growth rates
            {
                'key': 'pension_default_monthly_growth_rate',
                'value': '0.0012',  # 0.12% per month
                'description': 'Default monthly growth rate for pension projections',
                'setting_type': 'float'
            },
            {
                'key': 'pension_optimistic_monthly_growth_rate',
                'value': '0.005',  # 0.5% per month (optimistic scenario)
                'description': 'Optimistic monthly growth rate for pension projections',
                'setting_type': 'float'
            },
            {
                'key': 'pension_pessimistic_monthly_growth_rate',
                'value': '0.0005',  # 0.05% per month (pessimistic scenario)
                'description': 'Pessimistic monthly growth rate for pension projections',
                'setting_type': 'float'
            },
            
            # Retirement ages
            {
                'key': 'default_retirement_age',
                'value': '65',
                'description': 'Default retirement age',
                'setting_type': 'int'
            },
            {
                'key': 'keiron_retirement_age',
                'value': '65',
                'description': "Keiron's planned retirement age",
                'setting_type': 'int'
            },
            {
                'key': 'emma_retirement_age',
                'value': '65',
                'description': "Emma's planned retirement age",
                'setting_type': 'int'
            },
            {
                'key': 'keiron_date_of_birth',
                'value': '1990-01-01',  # UPDATE THIS
                'description': "Keiron's date of birth for retirement calculations",
                'setting_type': 'string'
            },
            {
                'key': 'emma_date_of_birth',
                'value': '1990-01-01',  # UPDATE THIS
                'description': "Emma's date of birth for retirement calculations",
                'setting_type': 'string'
            },
            
            # Annuity calculations
            {
                'key': 'annuity_conversion_rate',
                'value': '0.05',  # 5% - £100k pension pot = £5k annual income
                'description': 'Annual annuity conversion rate (pot value to annual income)',
                'setting_type': 'float'
            },
            
            # Government pension
            {
                'key': 'government_pension_annual_keiron',
                'value': '8122.40',
                'description': "Keiron's expected annual government pension",
                'setting_type': 'float'
            },
            {
                'key': 'government_pension_annual_emma',
                'value': '8122.40',
                'description': "Emma's expected annual government pension",
                'setting_type': 'float'
            },
            
            # Projection settings
            {
                'key': 'auto_regenerate_projections',
                'value': 'true',
                'description': 'Automatically regenerate projections when snapshots are updated',
                'setting_type': 'boolean'
            },
        ]
        
        for setting_data in settings_to_add:
            existing = Settings.query.filter_by(key=setting_data['key']).first()
            if not existing:
                Settings.set_value(
                    key=setting_data['key'],
                    value=setting_data['value'],
                    description=setting_data['description'],
                    setting_type=setting_data['setting_type']
                )
                print(f"Added setting: {setting_data['key']}")
            else:
                print(f"Setting already exists: {setting_data['key']}")
        
        db.session.commit()
        print("\n✓ Pension settings initialized successfully!")


if __name__ == '__main__':
    add_pension_settings()
