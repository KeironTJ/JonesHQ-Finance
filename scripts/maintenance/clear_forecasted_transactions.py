"""Clear all forecasted transactions to regenerate with corrected logic"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from extensions import db
from models.transactions import Transaction

def clear_forecasted_transactions():
    """Delete all forecasted transactions"""
    app = create_app()
    
    with app.app_context():
        count = Transaction.query.filter_by(is_forecasted=True).delete()
        db.session.commit()
        print(f"Deleted {count} forecasted transactions")

if __name__ == "__main__":
    clear_forecasted_transactions()
