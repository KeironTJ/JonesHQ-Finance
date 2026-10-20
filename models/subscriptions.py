from datetime import datetime, timezone

from extensions import db


class Subscription(db.Model):
    __tablename__ = 'subscriptions'
    __table_args__ = (
        db.CheckConstraint('amount < 0', name='ck_subscriptions_expense_amount'),
        db.CheckConstraint(
            'horizon_years >= 1 AND horizon_years <= 5',
            name='ck_subscriptions_horizon_years',
        ),
        db.CheckConstraint(
            '(account_id IS NOT NULL AND credit_card_id IS NULL) OR '
            '(account_id IS NULL AND credit_card_id IS NOT NULL)',
            name='ck_subscriptions_single_target',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(
        db.Integer, db.ForeignKey('families.id'), nullable=False, index=True
    )
    name = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    frequency = db.Column(db.String(20), nullable=False, default='monthly')
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    horizon_years = db.Column(db.Integer, nullable=False, default=1)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    credit_card_id = db.Column(db.Integer, db.ForeignKey('credit_cards.id'), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    account = db.relationship('Account', foreign_keys=[account_id])
    credit_card = db.relationship('CreditCard', foreign_keys=[credit_card_id])
    category = db.relationship('Category', foreign_keys=[category_id])
    vendor = db.relationship('Vendor', foreign_keys=[vendor_id])
    price_changes = db.relationship(
        'SubscriptionPriceChange',
        back_populates='subscription',
        cascade='all, delete-orphan',
        order_by='SubscriptionPriceChange.effective_date',
    )

    @property
    def target_name(self):
        if self.account:
            return self.account.name
        if self.credit_card:
            return self.credit_card.card_name
        return 'Unknown'

    def __repr__(self):
        return f'<Subscription {self.name}: {self.frequency}>'


class SubscriptionPriceChange(db.Model):
    __tablename__ = 'subscription_price_changes'
    __table_args__ = (
        db.CheckConstraint('amount < 0', name='ck_subscription_price_changes_expense_amount'),
        db.UniqueConstraint(
            'subscription_id',
            'effective_date',
            name='uq_subscription_price_changes_effective_date',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(
        db.Integer, db.ForeignKey('families.id'), nullable=False, index=True
    )
    subscription_id = db.Column(
        db.Integer, db.ForeignKey('subscriptions.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    effective_date = db.Column(db.Date, nullable=False)
    note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    subscription = db.relationship('Subscription', back_populates='price_changes')

    def __repr__(self):
        return f'<SubscriptionPriceChange {self.subscription_id}: {self.effective_date}>'
