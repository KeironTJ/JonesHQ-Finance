"""
Import loans
Run this script to populate the loans table with loan data
"""
import sys
import os
from datetime import date

# Add parent directory to path to import models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import create_app
from extensions import db
from models.loans import Loan

# Loan data from Excel
LOANS = [
    # Active Loans
    {
        'name': 'EE',
        'loan_value': 1068.07,
        'current_balance': 563.70,
        'annual_apr': 0.00,
        'monthly_apr': 0.00,
        'monthly_payment': 29.66,
        'start_date': date(2024, 8, 7),
        'end_date': date(2027, 8, 7),
        'term_months': 36,
        'is_active': True
    },
    {
        'name': 'JN Bank',
        'loan_value': 5800.00,
        'current_balance': 5422.87,
        'annual_apr': 10.39,
        'monthly_apr': 0.87,
        'monthly_payment': 124.36,
        'start_date': date(2025, 8, 15),
        'end_date': date(2030, 8, 15),
        'term_months': 60,
        'is_active': True
    },
    {
        'name': 'Loft Loan',
        'loan_value': 3940.00,
        'current_balance': 3602.12,
        'annual_apr': 10.39,
        'monthly_apr': 0.87,
        'monthly_payment': 84.47,
        'start_date': date(2025, 9, 1),
        'end_date': date(2030, 9, 1),
        'term_months': 60,
        'is_active': True
    },
    {
        'name': 'Creation',
        'loan_value': 7500.00,
        'current_balance': 6798.95,
        'annual_apr': 5.93,
        'monthly_apr': 0.49,
        'monthly_payment': 270.18,
        'start_date': date(2025, 10, 1),
        'end_date': date(2028, 4, 1),
        'term_months': 30,
        'is_active': True
    },
    {
        'name': 'Zopa',
        'loan_value': 3000.00,
        'current_balance': 3000.00,
        'annual_apr': 8.70,
        'monthly_apr': 0.73,
        'monthly_payment': 73.76,
        'start_date': date(2026, 1, 24),
        'end_date': date(2030, 1, 24),
        'term_months': 48,
        'is_active': True
    },
    
    # Inactive Loans (paid off)
    {
        'name': 'MoneyBarn',
        'loan_value': 7725.00,
        'current_balance': 0.00,
        'annual_apr': 17.95,
        'monthly_apr': 1.50,
        'monthly_payment': 198.00,
        'start_date': date(2023, 1, 30),
        'end_date': date(2027, 12, 30),
        'term_months': 59,
        'is_active': False
    },
    {
        'name': 'Vodafone',
        'loan_value': 1080.00,
        'current_balance': 0.00,
        'annual_apr': 0.00,
        'monthly_apr': 0.00,
        'monthly_payment': 30.00,
        'start_date': date(2022, 4, 20),
        'end_date': date(2025, 4, 20),
        'term_months': 36,
        'is_active': False
    },
    {
        'name': 'Sky',
        'loan_value': 940.00,
        'current_balance': 0.00,
        'annual_apr': 0.00,
        'monthly_apr': 0.00,
        'monthly_payment': 20.00,
        'start_date': date(2021, 10, 20),
        'end_date': date(2025, 9, 20),
        'term_months': 47,
        'is_active': False
    },
    {
        'name': 'Oakbrook',
        'loan_value': 2750.00,
        'current_balance': 0.00,
        'annual_apr': 26.90,
        'monthly_apr': 2.24,
        'monthly_payment': 94.11,
        'start_date': date(2024, 11, 1),
        'end_date': date(2028, 11, 1),
        'term_months': 48,
        'is_active': False
    },
]


def import_loans():
    """Import all loans into database"""
    print("Starting loan import...")
    print(f"Total loans to import: {len(LOANS)}")
    print("-" * 50)
    
    imported_count = 0
    skipped_count = 0
    
    for loan_data in LOANS:
        # Check if loan already exists
        existing = Loan.query.filter_by(name=loan_data['name']).first()
        
        if existing:
            print(f"⏭️  Skipped: {loan_data['name']} (already exists)")
            skipped_count += 1
            continue
        
        # Create new loan
        loan = Loan(
            name=loan_data['name'],
            loan_value=loan_data['loan_value'],
            principal=loan_data['loan_value'],  # Same as loan_value
            current_balance=loan_data['current_balance'],
            annual_apr=loan_data['annual_apr'],
            monthly_apr=loan_data['monthly_apr'],
            monthly_payment=loan_data['monthly_payment'],
            start_date=loan_data['start_date'],
            end_date=loan_data.get('end_date'),
            term_months=loan_data['term_months'],
            is_active=loan_data['is_active']
        )
        
        db.session.add(loan)
        imported_count += 1
        
        # Show status
        status_emoji = "✅" if loan_data['is_active'] else "❌"
        balance_str = f"£{loan_data['current_balance']:.2f}" if loan_data['current_balance'] > 0 else "PAID OFF"
        print(f"{status_emoji} Added: {loan_data['name']} - {balance_str} ({'Active' if loan_data['is_active'] else 'Inactive'})")
    
    # Commit all loans
    db.session.commit()
    
    print("-" * 50)
    print(f"✅ Import complete!")
    print(f"   Imported: {imported_count} loans")
    print(f"   Skipped: {skipped_count} loans")
    print(f"   Total in database: {Loan.query.count()} loans")
    
    # Show summary
    active_count = Loan.query.filter_by(is_active=True).count()
    inactive_count = Loan.query.filter_by(is_active=False).count()
    print(f"\n📊 Summary:")
    print(f"   Active loans: {active_count}")
    print(f"   Inactive loans: {inactive_count}")


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        import_loans()
