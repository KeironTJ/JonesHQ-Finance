"""
Expense Reimbursement Group
============================
Groups expenses under a named reimbursement strategy, letting a family run
several claim streams side by side (e.g. one per job, or "manual" vs "payslip").

mode='separate' — behaves like the original system: a standalone
    'Expense Reimbursement' Transaction is created at period end.
mode='folded'   — the period's expense total is added on top of the linked
    RecurringIncome's take-home pay instead of creating a separate transaction.
    Requires recurring_income_id to be set (which job/payslip absorbs the claim).

Every family always has exactly one is_default=True group (created lazily by
ExpenseReimbursementGroupService.get_default_group()); new expenses fall back to
it when no group is explicitly chosen, so `Expense.reimbursement_group_id` should
never be relied on as NULL in application logic once that call has run.
"""
from extensions import db
from datetime import datetime, timezone


class ExpenseReimbursementGroup(db.Model):
    __tablename__ = 'expense_reimbursement_groups'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    name = db.Column(db.String(100), nullable=False)

    # 'separate' = own reimbursement transaction; 'folded' = added to a payslip
    mode = db.Column(db.String(20), nullable=False, default='separate')

    # Which job/payslip absorbs the claim when mode='folded'. Required in that case.
    recurring_income_id = db.Column(db.Integer, db.ForeignKey('recurring_income.id'), nullable=True)

    is_default = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    recurring_income = db.relationship('RecurringIncome', foreign_keys=[recurring_income_id])

    def __repr__(self):
        return f'<ExpenseReimbursementGroup {self.name} mode={self.mode}>'
