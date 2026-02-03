"""
Update pension settings - specifically dates of birth
Run this to set your actual dates of birth for accurate retirement calculations
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from extensions import db
from models.settings import Settings


def update_pension_settings():
    """Update pension settings with actual values"""
    app = create_app()
    with app.app_context():
        print("\n=== Update Pension Settings ===\n")
        
        # Dates of Birth
        print("1. Update Dates of Birth")
        keiron_dob = input("Enter Keiron's date of birth (YYYY-MM-DD) [press Enter to skip]: ").strip()
        if keiron_dob:
            Settings.set_value('keiron_date_of_birth', keiron_dob, setting_type='string')
            print(f"✓ Updated Keiron's DOB to {keiron_dob}")
        
        emma_dob = input("Enter Emma's date of birth (YYYY-MM-DD) [press Enter to skip]: ").strip()
        if emma_dob:
            Settings.set_value('emma_date_of_birth', emma_dob, setting_type='string')
            print(f"✓ Updated Emma's DOB to {emma_dob}")
        
        # Retirement Ages
        print("\n2. Update Retirement Ages")
        keiron_ret = input("Enter Keiron's retirement age [current: 65, press Enter to skip]: ").strip()
        if keiron_ret:
            Settings.set_value('keiron_retirement_age', keiron_ret, setting_type='int')
            print(f"✓ Updated Keiron's retirement age to {keiron_ret}")
        
        emma_ret = input("Enter Emma's retirement age [current: 65, press Enter to skip]: ").strip()
        if emma_ret:
            Settings.set_value('emma_retirement_age', emma_ret, setting_type='int')
            print(f"✓ Updated Emma's retirement age to {emma_ret}")
        
        # Government Pensions
        print("\n3. Update Government Pension Amounts")
        keiron_gov = input("Enter Keiron's annual government pension [current: £8,122.40, press Enter to skip]: ").strip()
        if keiron_gov:
            Settings.set_value('government_pension_annual_keiron', keiron_gov, setting_type='float')
            print(f"✓ Updated Keiron's government pension to £{keiron_gov}")
        
        emma_gov = input("Enter Emma's annual government pension [current: £8,122.40, press Enter to skip]: ").strip()
        if emma_gov:
            Settings.set_value('government_pension_annual_emma', emma_gov, setting_type='float')
            print(f"✓ Updated Emma's government pension to £{emma_gov}")
        
        # Growth Rates
        print("\n4. Update Growth Rates (as decimal, e.g., 0.0012 for 0.12%)")
        default_growth = input("Enter default monthly growth rate [current: 0.0012, press Enter to skip]: ").strip()
        if default_growth:
            Settings.set_value('pension_default_monthly_growth_rate', default_growth, setting_type='float')
            print(f"✓ Updated default growth rate to {default_growth}")
        
        db.session.commit()
        
        print("\n✓ All settings updated successfully!")
        print("\nCurrent Settings:")
        print(f"  Keiron DOB: {Settings.get_value('keiron_date_of_birth')}")
        print(f"  Emma DOB: {Settings.get_value('emma_date_of_birth')}")
        print(f"  Keiron Retirement Age: {Settings.get_value('keiron_retirement_age')}")
        print(f"  Emma Retirement Age: {Settings.get_value('emma_retirement_age')}")
        print(f"  Default Growth Rate: {Settings.get_value('pension_default_monthly_growth_rate')}")


if __name__ == '__main__':
    update_pension_settings()
