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
    # CREDIT CARD CONVENTION (negative balance = you owe money):
    # Positive = reduces what you owe (payment, reward)
    # Negative = increases what you owe (purchase, interest, fee)
    
    # Interest Tracking (for Interest transactions)
    applied_apr = db.Column(db.Numeric(5, 2))  # APR used for this interest charge
    is_promotional_rate = db.Column(db.Boolean, default=False)  # Was 0% rate applied?
    
    # Payment Status
    is_paid = db.Column(db.Boolean, default=False)  # Has this been reconciled?
    is_fixed = db.Column(db.Boolean, default=False)  # Is this transaction locked from regeneration?
    
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
    def recalculate_card_balance(credit_card_id, commit=True):
        """Recalculate balance for a credit card based on PAID transactions only"""
        from models.credit_cards import CreditCard
        from sqlalchemy.orm import Session
        
        card = CreditCard.query.get(credit_card_id)
        if not card:
            return
        
        # Get all transactions ordered by date (then by ID for stability)
        transactions = CreditCardTransaction.query.filter_by(
            credit_card_id=credit_card_id
        ).order_by(CreditCardTransaction.date.asc(), CreditCardTransaction.id.asc()).all()
        
        running_balance = 0.0
        for txn in transactions:
            # CREDIT CARD CONVENTION:
            # Negative amounts (purchases, interest) INCREASE debt (make balance more negative)
            # Positive amounts (payments, rewards) DECREASE debt (make balance less negative)
            # 
            # Calculate projected balance (including all transactions)
            running_balance += float(txn.amount)
            new_balance = round(running_balance, 2)
            new_available = round(float(card.credit_limit) - abs(running_balance), 2)
            
            # Update and mark as modified
            if txn.balance != new_balance or txn.credit_available != new_available:
                txn.balance = new_balance
                txn.credit_available = new_available
                db.session.add(txn)  # Explicitly mark for update
        
        # Update card's current balance using ONLY PAID transactions
        paid_balance = 0.0
        paid_transactions = CreditCardTransaction.query.filter_by(
            credit_card_id=credit_card_id,
            is_paid=True
        ).order_by(CreditCardTransaction.date.asc(), CreditCardTransaction.id.asc()).all()
        
        for txn in paid_transactions:
            paid_balance += float(txn.amount)
        
        # Card's current balance should reflect only PAID transactions
        new_current_balance = round(paid_balance, 2)
        new_available_credit = round(float(card.credit_limit) - abs(paid_balance), 2)
        
        if card.current_balance != new_current_balance or card.available_credit != new_available_credit:
            card.current_balance = new_current_balance
            card.available_credit = new_available_credit
            db.session.add(card)  # Explicitly mark for update
        
        if commit:
            db.session.commit()
    
    def __repr__(self):
        return f'<CreditCardTransaction {self.date}: {self.item} - £{self.amount}>'
