"""
Sample data population script for JonesHQ Finance
Demonstrates the correct order for populating tables with foreign key dependencies
"""

from app import create_app
from extensions import db
from models import (
    Account, Category, CreditCard, Loan, Vehicle, Pension, Mortgage,
    Income, NetWorth, ChildcareRecord,
    Transaction, Balance, Budget, CreditCardTransaction, LoanPayment,
    MortgagePayment, PensionSnapshot, FuelRecord, Trip, Expense, PlannedTransaction
)
from datetime import datetime, date, timedelta

def populate_sample_data():
    """Populate database with sample data in correct order"""
    
    app = create_app()
    
    with app.app_context():
        # Clear existing data (optional - comment out if you want to keep existing data)
        print("Clearing existing data...")
        db.drop_all()
        db.create_all()
        
        print("\n=== STEP 1: Categories (no dependencies) ===")
        # Create categories with hierarchical structure
        categories_data = [
            # Head budgets (parent categories)
            {"name": "Income", "head_budget": "Income", "sub_budget": None, "category_type": "income", "parent_id": None},
            {"name": "Housing", "head_budget": "Housing", "sub_budget": None, "category_type": "expense", "parent_id": None},
            {"name": "Transport", "head_budget": "Transport", "sub_budget": None, "category_type": "expense", "parent_id": None},
            {"name": "Food & Groceries", "head_budget": "Food & Groceries", "sub_budget": None, "category_type": "expense", "parent_id": None},
            {"name": "Utilities", "head_budget": "Utilities", "sub_budget": None, "category_type": "expense", "parent_id": None},
            {"name": "Childcare", "head_budget": "Childcare", "sub_budget": None, "category_type": "expense", "parent_id": None},
        ]
        
        categories = []
        for cat_data in categories_data:
            cat = Category(**cat_data)
            db.session.add(cat)
            categories.append(cat)
        db.session.commit()
        
        # Add sub-categories
        housing = Category.query.filter_by(head_budget="Housing").first()
        transport = Category.query.filter_by(head_budget="Transport").first()
        utilities = Category.query.filter_by(head_budget="Utilities").first()
        
        sub_categories = [
            {"name": "Mortgage", "head_budget": "Housing", "sub_budget": "Mortgage", "category_type": "expense", "parent_id": housing.id},
            {"name": "Council Tax", "head_budget": "Housing", "sub_budget": "Council Tax", "category_type": "expense", "parent_id": housing.id},
            {"name": "Home Insurance", "head_budget": "Housing", "sub_budget": "Home Insurance", "category_type": "expense", "parent_id": housing.id},
            {"name": "Fuel", "head_budget": "Transport", "sub_budget": "Fuel", "category_type": "expense", "parent_id": transport.id},
            {"name": "Car Insurance", "head_budget": "Transport", "sub_budget": "Car Insurance", "category_type": "expense", "parent_id": transport.id},
            {"name": "Electricity", "head_budget": "Utilities", "sub_budget": "Electricity", "category_type": "expense", "parent_id": utilities.id},
            {"name": "Gas", "head_budget": "Utilities", "sub_budget": "Gas", "category_type": "expense", "parent_id": utilities.id},
            {"name": "Water", "head_budget": "Utilities", "sub_budget": "Water", "category_type": "expense", "parent_id": utilities.id},
        ]
        
        for sub_cat in sub_categories:
            db.session.add(Category(**sub_cat))
        db.session.commit()
        print(f"✓ Created {Category.query.count()} categories")
        
        print("\n=== STEP 2: Master Tables (no dependencies) ===")
        
        # Accounts
        accounts_data = [
            {"name": "Joint Account", "account_type": "current", "balance": 2500.00, "is_active": True},
            {"name": "Second Bank Account", "account_type": "savings", "balance": 5000.00, "is_active": True},
            {"name": "Emergency Fund", "account_type": "savings", "balance": 10000.00, "is_active": True},
        ]
        for acc_data in accounts_data:
            db.session.add(Account(**acc_data))
        db.session.commit()
        print(f"✓ Created {Account.query.count()} accounts")
        
        # Credit Cards
        credit_cards_data = [
            {
                "card_name": "Main Credit Card",
                "annual_apr": 19.9,
                "monthly_apr": 1.66,
                "credit_limit": 5000.00,
                "current_balance": 1200.50,
                "available_credit": 3799.50,
                "set_payment": 150.00,
                "statement_date": 15
            }
        ]
        for cc_data in credit_cards_data:
            db.session.add(CreditCard(**cc_data))
        db.session.commit()
        print(f"✓ Created {CreditCard.query.count()} credit cards")
        
        # Loans
        loans_data = [
            {
                "name": "Car Loan",
                "loan_value": 15000.00,
                "current_balance": 8500.00,
                "annual_apr": 5.9,
                "monthly_apr": 0.49,
                "monthly_payment": 350.00,
                "calculated_payment": 348.75,
                "term_months": 48,
                "start_date": date(2024, 1, 1)
            }
        ]
        for loan_data in loans_data:
            db.session.add(Loan(**loan_data))
        db.session.commit()
        print(f"✓ Created {Loan.query.count()} loans")
        
        # Vehicles
        vehicles_data = [
            {
                "name": "Family Car",
                "make": "Toyota",
                "model": "RAV4",
                "year": 2020,
                "registration": "MV15LZJ",
                "tank_size": 60.0,
                "fuel_type": "Petrol",
                "is_active": True
            }
        ]
        for veh_data in vehicles_data:
            db.session.add(Vehicle(**veh_data))
        db.session.commit()
        print(f"✓ Created {Vehicle.query.count()} vehicles")
        
        # Pensions
        pensions_data = [
            {
                "provider": "Company Pension Scheme",
                "pension_type": "workplace",
                "current_value": 45000.00,
                "contribution_rate": 8.0,
                "employer_contribution": 5.0,
                "is_active": True
            }
        ]
        for pen_data in pensions_data:
            db.session.add(Pension(**pen_data))
        db.session.commit()
        print(f"✓ Created {Pension.query.count()} pensions")
        
        # Mortgage
        mortgage_data = {
            "property_address": "123 Sample Street, City, AB1 2CD",
            "original_amount": 200000.00,
            "current_balance": 185000.00,
            "annual_interest_rate": 3.5,
            "monthly_interest_rate": 0.292,
            "fixed_payment": 850.00,
            "optional_payment": 100.00,
            "property_valuation": 275000.00,
            "equity_amount": 90000.00,
            "equity_percent": 32.73,
            "start_date": date(2020, 6, 1)
        }
        db.session.add(Mortgage(**mortgage_data))
        db.session.commit()
        print(f"✓ Created {Mortgage.query.count()} mortgage(s)")
        
        # Income records
        income_data = [
            {
                "pay_date": date(2026, 1, 15),
                "gross_annual_income": 45000.00,
                "employer_pension_percent": 5.0,
                "employee_pension_percent": 8.0,
                "tax_code": "1257L",
                "gross_pay": 3750.00,
                "employer_pension": 187.50,
                "employee_pension": 300.00,
                "income_tax": 625.00,
                "national_insurance": 350.00,
                "take_home": 2475.00
            }
        ]
        for inc_data in income_data:
            db.session.add(Income(**inc_data))
        db.session.commit()
        print(f"✓ Created {Income.query.count()} income record(s)")
        
        # Net Worth snapshots
        networth_data = [
            {
                "date": date(2026, 1, 1),
                "year_month": "2026-01",
                "cash": 2500.00,
                "savings": 15000.00,
                "house_value": 275000.00,
                "pensions_value": 45000.00,
                "total_assets": 337500.00,
                "credit_cards": 1200.50,
                "loans": 8500.00,
                "mortgage": 185000.00,
                "total_liabilities": 194700.50,
                "net_worth": 142799.50
            }
        ]
        for nw_data in networth_data:
            db.session.add(NetWorth(**nw_data))
        db.session.commit()
        print(f"✓ Created {NetWorth.query.count()} net worth snapshot(s)")
        
        # Childcare records
        childcare_data = [
            {
                "date": date(2026, 1, 20),
                "child_name": "Child 1",
                "day_name": "Monday",
                "year_month": "2026-01",
                "service_type": "Nursery",
                "cost": 45.00,
                "year_group": "Pre-school",
                "provider": "Little Stars Nursery"
            }
        ]
        for cc_data in childcare_data:
            db.session.add(ChildcareRecord(**cc_data))
        db.session.commit()
        print(f"✓ Created {ChildcareRecord.query.count()} childcare record(s)")
        
        print("\n=== STEP 3: Dependent Tables (require foreign keys) ===")
        
        # Get IDs for foreign keys
        joint_account = Account.query.filter_by(name="Joint Account").first()
        food_category = Category.query.filter_by(head_budget="Food & Groceries").first()
        fuel_category = Category.query.filter_by(sub_budget="Fuel").first()
        main_cc = CreditCard.query.first()
        car_loan = Loan.query.first()
        family_car = Vehicle.query.first()
        pension = Pension.query.first()
        mortgage = Mortgage.query.first()
        
        # Transactions
        transactions_data = [
            {
                "account_id": joint_account.id,
                "category_id": food_category.id,
                "amount": -85.50,
                "transaction_date": date(2026, 1, 20),
                "description": "Weekly grocery shopping",
                "item": "Tesco",
                "payment_type": "Debit Card",
                "is_paid": True,
                "year_month": "2026-01"
            },
            {
                "account_id": joint_account.id,
                "category_id": fuel_category.id,
                "amount": -65.00,
                "transaction_date": date(2026, 1, 22),
                "description": "Fuel purchase",
                "item": "Shell",
                "payment_type": "Debit Card",
                "is_paid": True,
                "year_month": "2026-01"
            }
        ]
        for trans_data in transactions_data:
            db.session.add(Transaction(**trans_data))
        db.session.commit()
        print(f"✓ Created {Transaction.query.count()} transaction(s)")
        
        # Balances
        balance_data = {
            "account_id": joint_account.id,
            "balance_date": date(2026, 1, 25),
            "balance": 2349.50
        }
        db.session.add(Balance(**balance_data))
        db.session.commit()
        print(f"✓ Created {Balance.query.count()} balance record(s)")
        
        # Budgets
        budget_data = {
            "category_id": food_category.id,
            "month": date(2026, 1, 1),
            "budgeted_amount": 400.00,
            "actual_amount": 85.50
        }
        db.session.add(Budget(**budget_data))
        db.session.commit()
        print(f"✓ Created {Budget.query.count()} budget(s)")
        
        # Credit Card Transactions
        cc_trans_data = {
            "credit_card_id": main_cc.id,
            "category_id": food_category.id,
            "date": date(2026, 1, 21),
            "item": "Restaurant",
            "transaction_type": "Purchase",
            "amount": 45.00,
            "balance": 1245.50,
            "credit_available": 3754.50
        }
        db.session.add(CreditCardTransaction(**cc_trans_data))
        db.session.commit()
        print(f"✓ Created {CreditCardTransaction.query.count()} credit card transaction(s)")
        
        # Loan Payments
        loan_payment_data = {
            "loan_id": car_loan.id,
            "date": date(2026, 1, 15),
            "period": "2026-01",
            "opening_balance": 8850.00,
            "payment_amount": 350.00,
            "interest_charge": 43.37,
            "amount_paid_off": 306.63,
            "closing_balance": 8543.37
        }
        db.session.add(LoanPayment(**loan_payment_data))
        db.session.commit()
        print(f"✓ Created {LoanPayment.query.count()} loan payment(s)")
        
        # Mortgage Payments
        mortgage_payment_data = {
            "mortgage_id": mortgage.id,
            "date": date(2026, 1, 1),
            "period": "2026-01",
            "mortgage_balance": 185000.00,
            "fixed_payment": 850.00,
            "optional_payment": 100.00,
            "interest_charge": 540.33,
            "equity_paid": 409.67,
            "property_valuation": 275000.00,
            "equity_amount": 90409.67,
            "equity_percent": 32.88
        }
        db.session.add(MortgagePayment(**mortgage_payment_data))
        db.session.commit()
        print(f"✓ Created {MortgagePayment.query.count()} mortgage payment(s)")
        
        # Pension Snapshots
        pension_snapshot_data = {
            "pension_id": pension.id,
            "review_date": date(2026, 1, 1),
            "value": 45000.00,
            "growth_percent": 8.5
        }
        db.session.add(PensionSnapshot(**pension_snapshot_data))
        db.session.commit()
        print(f"✓ Created {PensionSnapshot.query.count()} pension snapshot(s)")
        
        # Fuel Records
        fuel_record_data = {
            "vehicle_id": family_car.id,
            "date": date(2026, 1, 22),
            "price_per_litre": 1.45,
            "litres": 44.83,
            "mileage": 25340,
            "cost": 65.00,
            "gallons": 9.86,
            "actual_miles": 385,
            "mpg": 39.05,
            "price_per_mile": 0.169
        }
        db.session.add(FuelRecord(**fuel_record_data))
        db.session.commit()
        print(f"✓ Created {FuelRecord.query.count()} fuel record(s)")
        
        # Expenses
        expense_data = {
            "date": date(2026, 1, 18),
            "description": "Client meeting travel",
            "expense_type": "Mileage",
            "covered_miles": 45.0,
            "rate_per_mile": 0.45,
            "total_cost": 20.25,
            "paid_for": "Personal",
            "submitted": True,
            "reimbursed": False
        }
        db.session.add(Expense(**expense_data))
        db.session.commit()
        print(f"✓ Created {Expense.query.count()} expense(s)")
        
        # Planned Transactions
        planned_data = {
            "category_id": food_category.id,
            "planned_date": date(2026, 2, 1),
            "description": "Monthly grocery budget",
            "amount": 400.00,
            "frequency": "monthly"
        }
        db.session.add(PlannedTransaction(**planned_data))
        db.session.commit()
        print(f"✓ Created {PlannedTransaction.query.count()} planned transaction(s)")
        
        print("\n=== STEP 4: Complex Dependencies ===")
        
        # Trips (depends on Vehicle AND FuelRecord)
        fuel_record = FuelRecord.query.first()
        trip_data = {
            "vehicle_id": family_car.id,
            "fuel_record_id": fuel_record.id,
            "date": date(2026, 1, 22),
            "personal_miles": 35.0,
            "business_miles": 10.0,
            "total_miles": 45.0,
            "journey_description": "Commute and errands",
            "approx_mpg": 39.0,
            "trip_cost": 1.95
        }
        db.session.add(Trip(**trip_data))
        db.session.commit()
        print(f"✓ Created {Trip.query.count()} trip(s)")
        
        print("\n" + "="*60)
        print("✅ Sample data population complete!")
        print("="*60)
        print("\nSummary:")
        print(f"  Categories: {Category.query.count()}")
        print(f"  Accounts: {Account.query.count()}")
        print(f"  Credit Cards: {CreditCard.query.count()}")
        print(f"  Loans: {Loan.query.count()}")
        print(f"  Vehicles: {Vehicle.query.count()}")
        print(f"  Pensions: {Pension.query.count()}")
        print(f"  Mortgages: {Mortgage.query.count()}")
        print(f"  Transactions: {Transaction.query.count()}")
        print(f"  Income: {Income.query.count()}")
        print(f"  Net Worth: {NetWorth.query.count()}")
        print(f"  Childcare: {ChildcareRecord.query.count()}")
        print(f"  Fuel Records: {FuelRecord.query.count()}")
        print(f"  Trips: {Trip.query.count()}")
        print(f"  Loan Payments: {LoanPayment.query.count()}")
        print(f"  Mortgage Payments: {MortgagePayment.query.count()}")
        print(f"  Pension Snapshots: {PensionSnapshot.query.count()}")
        print(f"  Credit Card Transactions: {CreditCardTransaction.query.count()}")
        print(f"  Expenses: {Expense.query.count()}")
        print(f"  Budgets: {Budget.query.count()}")
        print(f"  Balances: {Balance.query.count()}")
        print(f"  Planned Transactions: {PlannedTransaction.query.count()}")

if __name__ == "__main__":
    populate_sample_data()
