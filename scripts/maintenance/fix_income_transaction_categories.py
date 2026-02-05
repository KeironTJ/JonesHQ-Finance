"""
Fix income transaction categories
Updates income transactions to use the category from their recurring income template
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from models.transactions import Transaction
from models.income import Income
from models.recurring_income import RecurringIncome
from models.categories import Category
from extensions import db

app = create_app()

with app.app_context():
    print("=" * 80)
    print("Fixing income transaction categories")
    print("=" * 80)
    
    # Get all income records that have a linked transaction and recurring income
    incomes = Income.query.filter(
        Income.transaction_id != None,
        Income.recurring_income_id != None
    ).all()
    
    print(f"\nFound {len(incomes)} income records with linked transactions and recurring income")
    
    if len(incomes) == 0:
        print("Nothing to update!")
        sys.exit(0)
    
    # Get or create default "Salary" category for fallback
    salary_category = Category.query.filter_by(name='Salary', category_type='Income').first()
    if not salary_category:
        salary_category = Category(name='Salary', category_type='Income')
        db.session.add(salary_category)
        db.session.flush()
        print(f"Created default 'Salary' category (ID: {salary_category.id})")
    
    updated_count = 0
    changed_count = 0
    no_category_count = 0
    
    print("\nUpdating transactions...")
    for income in incomes:
        transaction = Transaction.query.get(income.transaction_id)
        if not transaction:
            continue
        
        # Get the recurring income template
        recurring = RecurringIncome.query.get(income.recurring_income_id)
        if not recurring:
            continue
        
        old_category_id = transaction.category_id
        
        # Determine new category
        if recurring.category_id:
            new_category_id = recurring.category_id
            category = Category.query.get(new_category_id)
            category_name = f"{category.head_budget} > {category.sub_budget}" if category else "Unknown"
        else:
            new_category_id = salary_category.id
            category_name = "Salary (default)"
        
        # Update transaction
        transaction.category_id = new_category_id
        
        updated_count += 1
        
        # Track changes
        if old_category_id is None:
            no_category_count += 1
            print(f"  {transaction.transaction_date} | {transaction.description[:40]:40} | None -> {category_name}")
        elif old_category_id != new_category_id:
            old_cat = Category.query.get(old_category_id)
            old_cat_name = f"{old_cat.head_budget} > {old_cat.sub_budget}" if old_cat else "Unknown"
            changed_count += 1
            print(f"  {transaction.transaction_date} | {transaction.description[:40]:40} | {old_cat_name} -> {category_name}")
    
    # Commit all changes
    db.session.commit()
    
    print("\n" + "=" * 80)
    print(f"✅ Successfully updated {updated_count} income transactions")
    print(f"   {no_category_count} transactions had no category (now set)")
    print(f"   {changed_count} transactions had their category changed")
    print(f"   {updated_count - no_category_count - changed_count} transactions were already correct")
    print("=" * 80)
    
    # Show summary by category
    print("\nIncome transactions by category:")
    from sqlalchemy import func
    
    # Get all income transaction IDs
    income_txn_ids = [i.transaction_id for i in incomes if i.transaction_id]
    
    if income_txn_ids:
        category_counts = db.session.query(
            Category.head_budget,
            Category.sub_budget,
            func.count(Transaction.id)
        ).join(
            Transaction, Transaction.category_id == Category.id
        ).filter(
            Transaction.id.in_(income_txn_ids)
        ).group_by(
            Category.head_budget,
            Category.sub_budget
        ).order_by(
            func.count(Transaction.id).desc()
        ).all()
        
        for head, sub, count in category_counts:
            print(f"  {head} > {sub}: {count} transactions")
