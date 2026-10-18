"""Clear the legacy "actual payslip" flag on future income forecasts.

Older generators flagged every forecast built from a manual-deductions
template as is_manual_override, so they showed as "Actual" and were protected
from regenerate/delete. Clear it on rows that are still linked to such a
template, unpaid, dated after today, have no paid transaction, and still carry
the template's figures (so a real payslip entered with different figures is
left alone). Data only; no schema change.

Revision ID: c4f8a2d6e0b1
Revises: b3e5d7f9a1c2
"""
from datetime import date

from alembic import op
import sqlalchemy as sa


revision = 'c4f8a2d6e0b1'
down_revision = 'b3e5d7f9a1c2'
branch_labels = None
depends_on = None


income = sa.table(
    'income',
    sa.column('id', sa.Integer),
    sa.column('recurring_income_id', sa.Integer),
    sa.column('transaction_id', sa.Integer),
    sa.column('pay_date', sa.Date),
    sa.column('is_paid', sa.Boolean),
    sa.column('is_manual_override', sa.Boolean),
    sa.column('take_home', sa.Numeric),
)
recurring = sa.table(
    'recurring_income',
    sa.column('id', sa.Integer),
    sa.column('use_manual_deductions', sa.Boolean),
    sa.column('manual_take_home', sa.Numeric),
)
transactions = sa.table(
    'transactions',
    sa.column('id', sa.Integer),
    sa.column('is_paid', sa.Boolean),
)


def clear_legacy_overrides(connection, today=None):
    """Return the number of rows updated. Idempotent."""
    today = today or date.today()
    matching_template = sa.exists().where(
        recurring.c.id == income.c.recurring_income_id,
        recurring.c.use_manual_deductions.is_(True),
        recurring.c.manual_take_home == income.c.take_home,
    )
    paid_transaction = sa.exists().where(
        transactions.c.id == income.c.transaction_id,
        transactions.c.is_paid.is_(True),
    )
    statement = (
        sa.update(income)
        .where(
            income.c.is_manual_override.is_(True),
            sa.or_(income.c.is_paid.is_(False), income.c.is_paid.is_(None)),
            income.c.pay_date > today,
            matching_template,
            ~paid_transaction,
        )
        .values(is_manual_override=False)
    )
    return connection.execute(statement).rowcount


def upgrade():
    clear_legacy_overrides(op.get_bind())


def downgrade():
    # The old flag was wrong; there is nothing meaningful to restore.
    pass
