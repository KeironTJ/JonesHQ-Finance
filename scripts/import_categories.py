"""
Import categories from your Excel structure
This script helps you define Head Budgets and Sub Budgets based on your data
"""

from app import create_app
from extensions import db
from models import Category

def import_categories():
    """Import your actual category structure"""
    
    app = create_app()
    
    with app.app_context():
        print("Importing your categories...")
        
        # Define your categories with GENERIC structure
        # Specific details (which loan, which card, which shop) go in foreign keys or 'item' field
        # Format: {"head_budget": "Main Category", "sub_budget": "Sub Category", "type": "income/expense"}
        
        categories_data = [
            # ============= INCOME =============
            {"head_budget": "Income", "sub_budget": "Salary", "category_type": "income"},
            {"head_budget": "Income", "sub_budget": "Expense Reimbursement", "category_type": "income"},
            {"head_budget": "Income", "sub_budget": "Benefits / Tax Credits", "category_type": "income"},
            
            # ============= SAVINGS / TRANSFERS =============
            {"head_budget": "Savings", "sub_budget": "Savings Account", "category_type": "transfer"},
            {"head_budget": "Savings", "sub_budget": "Clothing Fund", "category_type": "transfer"},
            {"head_budget": "Savings", "sub_budget": "Holiday Fund", "category_type": "transfer"},
            {"head_budget": "Savings", "sub_budget": "Christmas Fund", "category_type": "transfer"},
            {"head_budget": "Savings", "sub_budget": "General Transfer", "category_type": "transfer"},
            
            # ============= LOANS (use loan_id foreign key for specific loan) =============
            {"head_budget": "Loans", "sub_budget": "Loan Payment", "category_type": "expense"},
            {"head_budget": "Loans", "sub_budget": "Loan Credit", "category_type": "income"},
            
            # ============= FAMILY =============
            {"head_budget": "Family", "sub_budget": "Hobbies / Interests", "category_type": "expense"},
            {"head_budget": "Family", "sub_budget": "Health & Beauty", "category_type": "expense"},
            {"head_budget": "Family", "sub_budget": "Clothing", "category_type": "expense"},
            {"head_budget": "Family", "sub_budget": "Holiday", "category_type": "expense"},
            {"head_budget": "Family", "sub_budget": "Child Maintenance", "category_type": "expense"},
            {"head_budget": "Family", "sub_budget": "Education / School", "category_type": "expense"},
            {"head_budget": "Family", "sub_budget": "Events / Activities", "category_type": "expense"},
            {"head_budget": "Family", "sub_budget": "Birthday", "category_type": "expense"},
            {"head_budget": "Family", "sub_budget": "Pets", "category_type": "expense"},
            
            # ============= GENERAL =============
            {"head_budget": "General", "sub_budget": "General Spending", "category_type": "expense"},
            {"head_budget": "General", "sub_budget": "Eating Out / Takeaway", "category_type": "expense"},
            {"head_budget": "General", "sub_budget": "Subscriptions", "category_type": "expense"},
            {"head_budget": "General", "sub_budget": "Tablets / Phones", "category_type": "expense"},
            
            # ============= TRANSPORTATION =============
            {"head_budget": "Transportation", "sub_budget": "Parking", "category_type": "expense"},
            {"head_budget": "Transportation", "sub_budget": "Fuel", "category_type": "expense"},
            {"head_budget": "Transportation", "sub_budget": "Vehicle Sale / Purchase", "category_type": "expense"},
            {"head_budget": "Transportation", "sub_budget": "Vehicle Tax", "category_type": "expense"},
            {"head_budget": "Transportation", "sub_budget": "Public Transport", "category_type": "expense"},
            {"head_budget": "Transportation", "sub_budget": "Fines", "category_type": "expense"},
            
            # ============= HOUSEHOLD =============
            {"head_budget": "Household", "sub_budget": "Food / Groceries", "category_type": "expense"},
            {"head_budget": "Household", "sub_budget": "Council Tax", "category_type": "expense"},
            {"head_budget": "Household", "sub_budget": "TV License", "category_type": "expense"},
            {"head_budget": "Household", "sub_budget": "Mortgage", "category_type": "expense"},
            {"head_budget": "Household", "sub_budget": "Phone / Broadband", "category_type": "expense"},
            {"head_budget": "Household", "sub_budget": "Water", "category_type": "expense"},
            {"head_budget": "Household", "sub_budget": "Gas / Electric", "category_type": "expense"},
            
            # ============= INSURANCE =============
            {"head_budget": "Insurance", "sub_budget": "Life", "category_type": "expense"},
            {"head_budget": "Insurance", "sub_budget": "Home", "category_type": "expense"},
            {"head_budget": "Insurance", "sub_budget": "Motor", "category_type": "expense"},
            {"head_budget": "Insurance", "sub_budget": "Pet", "category_type": "expense"},
            
            # ============= CREDIT CARDS (use credit_card_id foreign key) =============
            {"head_budget": "Credit Cards", "sub_budget": "Payment", "category_type": "expense"},
            
            # ============= OTHER =============
            {"head_budget": "Other", "sub_budget": "Miscellaneous", "category_type": "expense"},
        ]
        
        # Clear existing categories
        print("\n⚠️  Clearing existing categories...")
        Category.query.delete()
        db.session.commit()
        
        # Insert categories
        print("\n📝 Inserting categories...")
        count = 0
        
        for cat_data in categories_data:
            # Check for duplicates
            existing = Category.query.filter_by(
                head_budget=cat_data["head_budget"],
                sub_budget=cat_data["sub_budget"]
            ).first()
            
            if not existing:
                category = Category(
                    name=f"{cat_data['head_budget']}" + (f" - {cat_data['sub_budget']}" if cat_data['sub_budget'] else ""),
                    head_budget=cat_data["head_budget"],
                    sub_budget=cat_data["sub_budget"],
                    category_type=cat_data["category_type"],
                    parent_id=None  # We'll set up hierarchy in next step if needed
                )
                db.session.add(category)
                count += 1
        
        db.session.commit()
        
        print(f"\n✅ Successfully imported {count} unique categories!")
        
        # Display summary by Head Budget
        print("\n" + "="*60)
        print("CATEGORY SUMMARY")
        print("="*60)
        
        head_budgets = db.session.query(Category.head_budget).distinct().all()
        
        for (head,) in head_budgets:
            subs = Category.query.filter_by(head_budget=head).all()
            print(f"\n{head} ({len(subs)} sub-categories):")
            for sub in subs:
                if sub.sub_budget:
                    print(f"  - {sub.sub_budget}")
                else:
                    print(f"  - [No sub-category]")
        
        print("\n" + "="*60)
        print(f"TOTAL: {Category.query.count()} categories")
        print("="*60)

if __name__ == "__main__":
    import_categories()
