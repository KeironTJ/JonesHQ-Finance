from extensions import db
from datetime import datetime


class Category(db.Model):
    __tablename__ = 'categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    category_type = db.Column(db.String(50), nullable=False)  # Income, Expense, Transfer, etc.
    head_budget = db.Column(db.String(100))  # Main category (Family, General, Home, etc.)
    sub_budget = db.Column(db.String(100))   # Sub category
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Self-referential relationship for hierarchy
    children = db.relationship('Category', backref=db.backref('parent', remote_side=[id]))
    
    # Relationships
    transactions = db.relationship('Transaction', backref='category', lazy=True)
    budgets = db.relationship('Budget', backref='category', lazy=True)
    
    def __repr__(self):
        return f'<Category {self.head_budget} > {self.sub_budget}>'
