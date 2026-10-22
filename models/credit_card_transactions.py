from extensions import db
from datetime import datetime, timezone


class CreditCardTransaction(db.Model):
    __tablename__ = 'credit_card_transactions'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    credit_card_id= db.Column(db.Integer, db.ForeignKey('credit_cards.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=True)
    
    # Transaction Details
    date = db.Column(db.Date, nullable=False)
    day_name = db.Column(db.String(10))
    week = db.Column(db.String(7))  # 51-2025
    month = db.Column(db.String(7))  # 2025-12
    
    # Categories (denormalized for quick access)
    head_budget = db.Column(db.String(100))  # Main category
    sub_budget = db.Column(db.String(100))   # Sub category
    item = db.Column(db.String(255))  # Merchant/description
    assigned_to = db.Column(db.String(100))
    
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
    
    # Link to the Statement (Interest) transaction that generated this Payment.
    # SET NULL on delete so removing a statement NULLs the FK without cascading.
    statement_id = db.Column(db.Integer, db.ForeignKey('credit_card_transactions.id', ondelete='SET NULL'), nullable=True)

    # Link to the paired transaction on the other card in a Balance Transfer
    linked_cc_transaction_id = db.Column(db.Integer, db.ForeignKey('credit_card_transactions.id', ondelete='SET NULL'), nullable=True)
    subscription_id = db.Column(
        db.Integer,
        db.ForeignKey('subscriptions.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    
    # Audit Fields
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    # Relationships
    bank_transaction = db.relationship('Transaction', foreign_keys=[bank_transaction_id])
    vendor = db.relationship('Vendor')
    linked_cc_transaction = db.relationship('CreditCardTransaction', foreign_keys=[linked_cc_transaction_id], remote_side=[id])
    
    @staticmethod
    def recalculate_card_balance(credit_card_id, commit=True):
        """Compatibility wrapper for the finance balance service."""
        from services.finance.balance_service import BalanceService
        BalanceService.recalculate(
            credit_card_ids=[credit_card_id],
            commit=commit,
        )
    
    def __repr__(self):
        return f'<CreditCardTransaction {self.date}: {self.item} - £{self.amount}>'
