"""
Migration script to add promotional period columns to credit_cards table
Run this to add:
- purchase_0_percent_until
- balance_transfer_0_percent_until
And to credit_card_transactions:
- applied_apr
- is_promotional_rate
- bank_transaction_id
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db
from app import create_app
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("Starting credit card migration...")
    
    # Add columns to credit_cards table
    print("Adding promotional period columns to credit_cards...")
    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                ALTER TABLE credit_cards 
                ADD COLUMN purchase_0_percent_until DATE
            """))
            conn.commit()
        print("  ✓ Added purchase_0_percent_until")
    except Exception as e:
        print(f"  - purchase_0_percent_until: {e}")
    
    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                ALTER TABLE credit_cards 
                ADD COLUMN balance_transfer_0_percent_until DATE
            """))
            conn.commit()
        print("  ✓ Added balance_transfer_0_percent_until")
    except Exception as e:
        print(f"  - balance_transfer_0_percent_until: {e}")
    
    # Add columns to credit_card_transactions table
    print("\nAdding tracking columns to credit_card_transactions...")
    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                ALTER TABLE credit_card_transactions 
                ADD COLUMN applied_apr DECIMAL(5, 2)
            """))
            conn.commit()
        print("  ✓ Added applied_apr")
    except Exception as e:
        print(f"  - applied_apr: {e}")
    
    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                ALTER TABLE credit_card_transactions 
                ADD COLUMN is_promotional_rate BOOLEAN DEFAULT 0
            """))
            conn.commit()
        print("  ✓ Added is_promotional_rate")
    except Exception as e:
        print(f"  - is_promotional_rate: {e}")
    
    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                ALTER TABLE credit_card_transactions 
                ADD COLUMN bank_transaction_id INTEGER
            """))
            conn.commit()
        print("  ✓ Added bank_transaction_id")
    except Exception as e:
        print(f"  - bank_transaction_id: {e}")
    
    # Create credit_card_promotions table
    print("\nCreating credit_card_promotions table...")
    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS credit_card_promotions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    credit_card_id INTEGER NOT NULL,
                    promotion_type VARCHAR(50) NOT NULL,
                    apr_rate DECIMAL(5, 2) NOT NULL,
                    start_date DATE NOT NULL,
                    end_date DATE,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (credit_card_id) REFERENCES credit_cards(id) ON DELETE CASCADE
                )
            """))
            conn.commit()
        print("  ✓ Created credit_card_promotions table")
    except Exception as e:
        print(f"  - credit_card_promotions table: {e}")
    
    print("\n✅ Migration complete!")
