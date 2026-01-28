"""
Import loans - TEMPLATE
⚠️ WARNING: This is a template with placeholder values
Copy this file to import_loans_ACTUAL.py and fill in your real data
The _ACTUAL.py file is gitignored for security
"""
import sys
import os
from datetime import date

# Add parent directory to path to import models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Loan

# Loan data - TEMPLATE WITH PLACEHOLDER VALUES
# ⚠️ DO NOT commit real financial data to Git!
# Copy this file to import_loans_ACTUAL.py and fill in real values
LOANS = [
    # Active Loans
    {
        'name': 'Loan 1',
        'loan_value': 0.00,  # TODO: Update with original loan amount
        'current_balance': 0.00,  # TODO: Update with current balance
        'annual_apr': 0.00,  # TODO: Update with APR
        'monthly_apr': 0.00,  # TODO: Update with monthly APR
        'monthly_payment': 0.00,  # TODO: Update with monthly payment
        'start_date': date(2024, 1, 1),  # TODO: Update with start date
        'end_date': date(2027, 1, 1),  # TODO: Update with end date
        'term_months': 36,  # TODO: Update with term
        'is_active': True
    },
    # Add more loans as needed...
]


def import_loans():
    """Import all loans into database"""
    app = create_app()
    
    with app.app_context():
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
    import_loans()
