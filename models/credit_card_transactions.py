from extensions import db
from datetime import datetime


class CreditCardTransaction(db.Model):
    __tablename__ = 'credit_card_transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    credit_card_id = db.Column(db.Integer, db.ForeignKey('credit_cards.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    
    # Transaction Details
    date = db.Column(db.Date, nullable=False)
    day_name = db.Column(db.String(10))
    week = db.Column(db.String(7))  # 51-2025
    month = db.Column(db.String(7))  # 2025-12
    
    # Categories (denormalized for quick access)
    head_budget = db.Column(db.String(100))  # Main category
    sub_budget = db.Column(db.String(100))   # Sub category
    item = db.Column(db.String(255))  # Merchant/description
    
    # Transaction Type and Amount
    transaction_type = db.Column(db.String(50), nullable=False)  
    # Types: 'Purchase', 'Balance Transfer', 'Payment', 'Interest', 'Reward', 'Fee'
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    # Negative = reduces balance (payment, reward)
    # Positive = increases balance (purchase, interest, fee)
    
    # Interest Tracking (for Interest transactions)
    applied_apr = db.Column(db.Numeric(5, 2))  # APR used for this interest charge
    is_promotional_rate = db.Column(db.Boolean, default=False)  # Was 0% rate applied?
    
    # Payment Status
    is_paid = db.Column(db.Boolean, default=False)  # Has this been reconciled?
    
    # Balances After Transaction
    balance = db.Column(db.Numeric(10, 2))  # Card balance after transaction
    credit_available = db.Column(db.Numeric(10, 2))  # Available credit after
    
    # Link to Bank Account Transaction (for payments)
    bank_transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True)
    
    # Audit Fields
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    bank_transaction = db.relationship('Transaction', foreign_keys=[bank_transaction_id])
    
    @staticmethod
    def recalculate_card_balance(credit_card_id):
        """Recalculate balance for a credit card based on all transactions"""
        from models.credit_cards import CreditCard
        
        card = CreditCard.query.get(credit_card_id)
        if not card:
            return
        
        # Get all transactions ordered by date
        transactions = CreditCardTransaction.query.filter_by(
            credit_card_id=credit_card_id
        ).order_by(CreditCardTransaction.date.asc()).all()
        
        running_balance = 0.0
        for txn in transactions:
            # Purchases, Interest, Fees increase balance (positive amount)
            # Payments, Rewards decrease balance (negative amount)
            running_balance += float(txn.amount)
            txn.balance = round(running_balance, 2)
            txn.credit_available = round(float(card.credit_limit) - running_balance, 2)
        
        # Update card's current balance
        card.current_balance = round(running_balance, 2)
        card.available_credit = round(float(card.credit_limit) - running_balance, 2)
        
        db.session.commit()
    
    def __repr__(self):
        return f'<CreditCardTransaction {self.date}: {self.item} - £{self.amount}>'
