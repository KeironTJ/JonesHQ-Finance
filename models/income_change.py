from datetime import datetime, timezone

from extensions import db


class IncomeChange(db.Model):
    """
    One dated event on an income source's timeline. Forecasts are worked out by
    applying every change dated on or before a pay date to the source's starting
    terms, so editing the timeline re-prices all unsettled future forecasts.

    change_type:
      salary        amount  = new annual gross from effective_date
      percent_rise  percent = rise applied to the annual gross from effective_date
      bonus         amount  = one-off, paid on the first pay date on/after effective_date
                    (bonus_pensionable controls whether pension is taken from it)
      tax_code      tax_code from effective_date
      pension       employee_pension_percent / employer_pension_percent from effective_date
    """
    __tablename__ = 'income_changes'

    CHANGE_TYPES = ('salary', 'percent_rise', 'bonus', 'tax_code', 'pension')
    CHANGE_TYPE_LABELS = {
        'salary': 'New salary',
        'percent_rise': 'Pay rise (%)',
        'bonus': 'Bonus / one-off',
        'tax_code': 'Tax code change',
        'pension': 'Pension % change',
    }

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    recurring_income_id = db.Column(
        db.Integer, db.ForeignKey('recurring_income.id', ondelete='CASCADE'), nullable=False, index=True,
    )
    effective_date = db.Column(db.Date, nullable=False)
    change_type = db.Column(db.String(20), nullable=False)

    amount = db.Column(db.Numeric(12, 2), nullable=True)
    percent = db.Column(db.Numeric(6, 3), nullable=True)
    tax_code = db.Column(db.String(10), nullable=True)
    employee_pension_percent = db.Column(db.Numeric(5, 2), nullable=True)
    employer_pension_percent = db.Column(db.Numeric(5, 2), nullable=True)
    bonus_pensionable = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    description = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    recurring_income = db.relationship(
        'RecurringIncome',
        backref=db.backref('changes', cascade='all, delete-orphan', passive_deletes=True,
                           order_by='IncomeChange.effective_date'),
    )

    @property
    def label(self):
        return self.CHANGE_TYPE_LABELS.get(self.change_type, self.change_type)

    @property
    def summary(self):
        if self.change_type == 'salary':
            return f"£{self.amount:,.2f} a year"
        if self.change_type == 'percent_rise':
            return f"+{self.percent.normalize():f}%"
        if self.change_type == 'bonus':
            return f"£{self.amount:,.2f}" + (' (pensionable)' if self.bonus_pensionable else '')
        if self.change_type == 'tax_code':
            return self.tax_code
        if self.change_type == 'pension':
            return f"You {self.employee_pension_percent or 0}% / employer {self.employer_pension_percent or 0}%"
        return ''

    def __repr__(self):
        return f'<IncomeChange {self.change_type} {self.effective_date}>'
