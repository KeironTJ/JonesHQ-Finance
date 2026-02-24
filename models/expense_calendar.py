from extensions import db
from datetime import datetime, timezone


class ExpenseCalendarEntry(db.Model):
    __tablename__ = 'expense_calendar_entries'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    date = db.Column(db.Date, nullable=False)
    assigned_to = db.Column(db.String(100), nullable=True)
    expense_id = db.Column(db.Integer, db.ForeignKey('expenses.id'), nullable=True)
    amount = db.Column(db.Numeric(10, 2), nullable=True)
    description = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    expense = db.relationship('Expense', backref='calendar_entries', lazy=True)

    def __repr__(self):
        return f'<ExpenseCalendarEntry {self.date}: {self.description} - £{self.amount}>'
