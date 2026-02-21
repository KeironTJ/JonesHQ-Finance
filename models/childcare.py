from extensions import db
from datetime import datetime


class Child(db.Model):
    """Represents a child with their default settings"""
    __tablename__ = 'children'
    
    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    year_group = db.Column(db.String(50))  # Year 4, Nursery, etc.
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    default_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)  # Default account for transactions
    transaction_day = db.Column(db.Integer, default=28)  # Day of month for transaction (1-28)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)  # Category for transactions
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=True)  # Vendor for transactions
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    activity_types = db.relationship('ChildActivityType', back_populates='child', cascade='all, delete-orphan')
    daily_activities = db.relationship('DailyChildcareActivity', back_populates='child', cascade='all, delete-orphan')
    default_account = db.relationship('Account', foreign_keys=[default_account_id])
    category = db.relationship('Category', foreign_keys=[category_id])
    vendor = db.relationship('Vendor', foreign_keys=[vendor_id])
    
    def __repr__(self):
        return f'<Child {self.name}>'


class ChildActivityType(db.Model):
    """Activity types available for each child (e.g., AM Session, Lunch, Breakfast Club)"""
    __tablename__ = 'child_activity_types'
    
    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey('children.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)  # "AM Session", "PM1", "Breakfast Club"
    cost = db.Column(db.Numeric(10, 2), nullable=False)
    provider = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    
    # Weekly pattern - which days this activity normally occurs
    occurs_monday = db.Column(db.Boolean, default=False)
    occurs_tuesday = db.Column(db.Boolean, default=False)
    occurs_wednesday = db.Column(db.Boolean, default=False)
    occurs_thursday = db.Column(db.Boolean, default=False)
    occurs_friday = db.Column(db.Boolean, default=False)
    occurs_saturday = db.Column(db.Boolean, default=False)
    occurs_sunday = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    child = db.relationship('Child', back_populates='activity_types')
    
    def occurs_on_weekday(self, weekday):
        """Check if activity occurs on a given weekday (0=Monday, 6=Sunday)"""
        weekday_map = {
            0: self.occurs_monday,
            1: self.occurs_tuesday,
            2: self.occurs_wednesday,
            3: self.occurs_thursday,
            4: self.occurs_friday,
            5: self.occurs_saturday,
            6: self.occurs_sunday
        }
        return weekday_map.get(weekday, False)
    
    def __repr__(self):
        return f'<ActivityType {self.child.name if self.child else "?"}: {self.name} - £{self.cost}>'


class DailyChildcareActivity(db.Model):
    """Tracks which activities occurred on which days"""
    __tablename__ = 'daily_childcare_activities'
    
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    child_id = db.Column(db.Integer, db.ForeignKey('children.id'), nullable=False)
    activity_type_id = db.Column(db.Integer, db.ForeignKey('child_activity_types.id'), nullable=False)
    occurred = db.Column(db.Boolean, default=False)  # Did this activity happen?
    cost_override = db.Column(db.Numeric(10, 2))  # Optional: override default cost
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    child = db.relationship('Child', back_populates='daily_activities')
    activity_type = db.relationship('ChildActivityType')
    
    # Composite unique constraint: one entry per child/activity/date
    __table_args__ = (
        db.UniqueConstraint('date', 'child_id', 'activity_type_id', name='unique_daily_activity'),
    )
    
    @property
    def actual_cost(self):
        """Returns the override cost if set, otherwise the activity type's default cost"""
        if self.cost_override is not None:
            return self.cost_override
        return self.activity_type.cost if self.activity_type else 0
    
    def __repr__(self):
        return f'<DailyActivity {self.date}: {self.child.name if self.child else "?"} - {self.activity_type.name if self.activity_type else "?"}>'


class MonthlyChildcareSummary(db.Model):
    """Monthly totals per child with linked transaction"""
    __tablename__ = 'monthly_childcare_summaries'
    
    id = db.Column(db.Integer, primary_key=True)
    year_month = db.Column(db.String(7), nullable=False, index=True)  # 2025-05
    child_id = db.Column(db.Integer, db.ForeignKey('children.id'), nullable=False)
    total_cost = db.Column(db.Numeric(10, 2), nullable=False)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'))  # Linked transaction
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))  # Which account to charge
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    child = db.relationship('Child')
    transaction = db.relationship('Transaction', foreign_keys=[transaction_id])
    account = db.relationship('Account')
    
    # Unique constraint: one summary per child per month
    __table_args__ = (
        db.UniqueConstraint('year_month', 'child_id', name='unique_monthly_summary'),
    )
    
    def __repr__(self):
        return f'<MonthlySummary {self.year_month}: {self.child.name if self.child else "?"} - £{self.total_cost}>'


# Keep old model for backwards compatibility (can be removed later)
class ChildcareRecord(db.Model):
    __tablename__ = 'childcare_records'
    
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    day_name = db.Column(db.String(10))
    year_month = db.Column(db.String(7))
    child_name = db.Column(db.String(100), nullable=False)
    service_type = db.Column(db.String(100))
    cost = db.Column(db.Numeric(10, 2), nullable=False)
    year_group = db.Column(db.String(50))
    provider = db.Column(db.String(100))
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<ChildcareRecord {self.date}: {self.child_name} - £{self.cost}>'
