"""
Test Tax/NI calculation against actual payslip values
"""
import sys
import os
from decimal import Decimal
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from services.income_service import IncomeService

app = create_app()

with app.app_context():
    print("=" * 80)
    print("TAX & NI CALCULATION COMPARISON")
    print("=" * 80)
    
    # Your actual payslip data
    gross_annual = Decimal('61328.40')
    employer_pension_pct = Decimal('3')
    employee_pension_pct = Decimal('6')
    tax_code = '1257L'
    
    print(f"\nINPUTS:")
    print(f"  Gross Annual: £{gross_annual:,.2f}")
    print(f"  Employer Pension: {employer_pension_pct}%")
    print(f"  Employee Pension: {employee_pension_pct}%")
    print(f"  Tax Code: {tax_code}")
    
    # Calculate using my code
    gross_monthly = gross_annual / 12
    
    # Auto-enrolment uses QUALIFYING EARNINGS
    # For 2024/25 onwards: between £6,240 and £50,270 annually
    lower_threshold_annual = Decimal('6240')
    upper_threshold_annual = Decimal('50270')
    
    qualifying_earnings_annual = gross_annual
    if qualifying_earnings_annual > upper_threshold_annual:
        qualifying_earnings_annual = upper_threshold_annual
    if qualifying_earnings_annual > lower_threshold_annual:
        qualifying_earnings_annual = qualifying_earnings_annual - lower_threshold_annual
    else:
        qualifying_earnings_annual = Decimal('0')
    
    qualifying_earnings_monthly = qualifying_earnings_annual / 12
    
    print(f"  Qualifying Earnings (annual): £{qualifying_earnings_annual:,.2f}")
    print(f"  Qualifying Earnings (monthly): £{qualifying_earnings_monthly:,.2f}")
    
    employer_pension = qualifying_earnings_monthly * (employer_pension_pct / 100)
    employee_pension = qualifying_earnings_monthly * (employee_pension_pct / 100)
    adjusted_annual = gross_annual - (employee_pension * 12)
    
    print(f"\n  Gross Monthly: £{gross_monthly:,.2f}")
    print(f"  Employer Pension (monthly): £{employer_pension:,.2f}")
    print(f"  Employee Pension (monthly): £{employee_pension:,.2f}")
    print(f"  Adjusted Annual (after employee pension): £{adjusted_annual:,.2f}")
    
    # Calculate tax and NI
    # IMPORTANT: NI is calculated on GROSS earnings, not adjusted
    calcs = IncomeService.calculate_tax_and_ni(
        gross_annual,  # NI uses gross
        tax_code,
        employee_pension * 12,  # Tax relief for pension
        date(2026, 2, 15)
    )
    
    monthly_tax = calcs['tax'] / 12
    monthly_ni = calcs['ni'] / 12
    take_home = gross_monthly - employee_pension - monthly_tax - monthly_ni
    
    print(f"\n" + "=" * 80)
    print("MY CALCULATION RESULTS:")
    print("=" * 80)
    print(f"  Monthly Tax:         £{monthly_tax:,.2f}")
    print(f"  Monthly NI:          £{monthly_ni:,.2f}")
    print(f"  Monthly Take Home:   £{take_home:,.2f}")
    print(f"  Annual Tax:          £{calcs['tax']:,.2f}")
    print(f"  Annual NI:           £{calcs['ni']:,.2f}")
    
    print(f"\n" + "=" * 80)
    print("YOUR ACTUAL PAYSLIP VALUES:")
    print("=" * 80)
    actual_emp_pension = Decimal('153.32')
    actual_employee_pension = Decimal('245.31')
    actual_tax = Decimal('996.47')
    actual_ni = Decimal('269.71')
    actual_take_home = Decimal('3599.21')
    
    print(f"  Employer Pension:    £{actual_emp_pension:,.2f}")
    print(f"  Employee Pension:    £{actual_employee_pension:,.2f}")
    print(f"  Monthly Tax:         £{actual_tax:,.2f}")
    print(f"  Monthly NI:          £{actual_ni:,.2f}")
    print(f"  Monthly Take Home:   £{actual_take_home:,.2f}")
    
    print(f"\n" + "=" * 80)
    print("DIFFERENCES:")
    print("=" * 80)
    print(f"  Employee Pension:    £{employee_pension - actual_employee_pension:,.2f} {'HIGHER' if employee_pension > actual_employee_pension else 'LOWER'}")
    print(f"  Tax:                 £{monthly_tax - actual_tax:,.2f} {'HIGHER' if monthly_tax > actual_tax else 'LOWER'}")
    print(f"  NI:                  £{monthly_ni - actual_ni:,.2f} {'HIGHER' if monthly_ni > actual_ni else 'LOWER'}")
    print(f"  Take Home:           £{take_home - actual_take_home:,.2f} {'HIGHER' if take_home > actual_take_home else 'LOWER'}")
    
    print(f"\n" + "=" * 80)
    print("ANALYSIS:")
    print("=" * 80)
    
    # Check what percentage the actual employee pension is
    actual_emp_pension_pct = (actual_employee_pension / gross_monthly) * 100
    print(f"  Actual employee pension %: {actual_emp_pension_pct:.2f}% (you specified {employee_pension_pct}%)")
    
    # Check annual amounts
    print(f"\n  Employee pension annual (actual): £{actual_employee_pension * 12:,.2f}")
    print(f"  Employee pension annual (my calc): £{employee_pension * 12:,.2f}")
    
    # Recalculate with actual employee pension amount
    print(f"\n" + "=" * 80)
    print("RECALCULATING WITH ACTUAL EMPLOYEE PENSION AMOUNT:")
    print("=" * 80)
    
    actual_adjusted_annual = gross_annual - (actual_employee_pension * 12)
    print(f"  Adjusted Annual: £{actual_adjusted_annual:,.2f}")
    
    calcs2 = IncomeService.calculate_tax_and_ni(
        actual_adjusted_annual,
        tax_code,
        actual_employee_pension * 12,
        date(2026, 2, 15)
    )
    
    monthly_tax2 = calcs2['tax'] / 12
    monthly_ni2 = calcs2['ni'] / 12
    
    print(f"  Monthly Tax:  £{monthly_tax2:,.2f} (actual: £{actual_tax:,.2f}, diff: £{monthly_tax2 - actual_tax:,.2f})")
    print(f"  Monthly NI:   £{monthly_ni2:,.2f} (actual: £{actual_ni:,.2f}, diff: £{monthly_ni2 - actual_ni:,.2f})")
