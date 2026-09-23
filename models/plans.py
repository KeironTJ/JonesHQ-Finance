from datetime import datetime, timezone
from decimal import Decimal

from extensions import db


class Plan(db.Model):
    __tablename__ = 'plans'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    plan_type = db.Column(db.String(30), nullable=False, default='occasion')
    person = db.Column(db.String(100), nullable=True)
    target_date = db.Column(db.Date, nullable=True)
    target_amount = db.Column(db.Numeric(10, 2), nullable=True)
    saved_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default='active')
    notes = db.Column(db.Text, nullable=True)
    # NULL = shared/joint, visible to the whole family. Set = private, visible only to that user.
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    items = db.relationship(
        'PlanItem',
        back_populates='plan',
        cascade='all, delete-orphan',
        order_by='PlanItem.created_at',
    )
    owner = db.relationship('User', foreign_keys=[owner_id])

    @property
    def is_private(self):
        """True if this plan is restricted to a single family member."""
        return self.owner_id is not None

    @property
    def estimated_total(self):
        return sum((item.estimated_cost or Decimal('0') for item in self.items), Decimal('0'))

    @property
    def actual_total(self):
        return sum((item.resolved_actual_cost for item in self.items), Decimal('0'))

    @property
    def saved_total(self):
        return (self.saved_amount or Decimal('0')) + self.actual_total

    @property
    def funding_target(self):
        return self.target_amount if self.target_amount is not None else self.estimated_total

    @property
    def progress_percent(self):
        target = self.funding_target or Decimal('0')
        if target <= 0:
            return 0
        if self.plan_type == 'savings_goal':
            progress = self.saved_total
        else:
            progress = self.actual_total
        return min(100, int((progress / target) * 100))


class PlanItem(db.Model):
    __tablename__ = 'plan_items'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    assigned_to = db.Column(db.String(100), nullable=True, index=True)
    estimated_cost = db.Column(db.Numeric(10, 2), nullable=True)
    actual_cost = db.Column(db.Numeric(10, 2), nullable=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True, index=True)
    credit_card_transaction_id = db.Column(db.Integer, db.ForeignKey('credit_card_transactions.id'), nullable=True, index=True)
    status = db.Column(db.String(20), nullable=False, default='idea')
    priority = db.Column(db.String(20), nullable=False, default='normal')
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    plan = db.relationship('Plan', back_populates='items')
    transaction = db.relationship('Transaction', foreign_keys=[transaction_id])
    credit_card_transaction = db.relationship('CreditCardTransaction', foreign_keys=[credit_card_transaction_id])

    @property
    def resolved_actual_cost(self):
        if self.transaction is not None:
            return abs(Decimal(str(self.transaction.amount)))
        if self.credit_card_transaction is not None:
            return abs(Decimal(str(self.credit_card_transaction.amount)))
        return self.actual_cost or Decimal('0')
