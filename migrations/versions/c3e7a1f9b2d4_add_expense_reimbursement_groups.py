"""add expense reimbursement groups and link expenses/income/transactions

Revision ID: c3e7a1f9b2d4
Revises: a4c7e1f92b6d
Create Date: 2026-09-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone


# revision identifiers, used by Alembic.
revision = 'c3e7a1f9b2d4'
down_revision = 'a4c7e1f92b6d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'expense_reimbursement_groups',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('mode', sa.String(length=20), nullable=False, server_default='separate'),
        sa.Column('recurring_income_id', sa.Integer(), sa.ForeignKey('recurring_income.id'), nullable=True),
        sa.Column('is_default', sa.Boolean(), server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    with op.batch_alter_table('expense_reimbursement_groups', schema=None) as batch_op:
        batch_op.create_index('ix_expense_reimbursement_groups_family_id', ['family_id'], unique=False)

    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reimbursement_group_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('payday_period', sa.String(length=7), nullable=True))
        batch_op.add_column(sa.Column('income_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_expenses_reimbursement_group_id', ['reimbursement_group_id'], unique=False)
        batch_op.create_index('ix_expenses_payday_period', ['payday_period'], unique=False)
        batch_op.create_index('ix_expenses_income_id', ['income_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_expenses_reimbursement_group_id', 'expense_reimbursement_groups',
            ['reimbursement_group_id'], ['id']
        )
        batch_op.create_foreign_key('fk_expenses_income_id', 'income', ['income_id'], ['id'])

    with op.batch_alter_table('income', schema=None) as batch_op:
        batch_op.add_column(sa.Column('expense_reimbursement_total', sa.Numeric(10, 2), server_default='0'))

    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reimbursement_group_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_transactions_reimbursement_group_id', ['reimbursement_group_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_transactions_reimbursement_group_id', 'expense_reimbursement_groups',
            ['reimbursement_group_id'], ['id']
        )

    # Data backfill: give every family (and the NULL/legacy bucket) a default group,
    # then point all existing expenses/reimbursement-transactions at it. This keeps
    # "every expense has a reimbursement group" true from this point forward instead
    # of every call site having to special-case NULL.
    bind = op.get_bind()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    family_ids = [row[0] for row in bind.execute(sa.text('SELECT id FROM families'))]
    # Include the legacy NULL bucket if any expenses/transactions pre-date multi-tenancy.
    has_null_family_rows = bind.execute(sa.text(
        'SELECT 1 FROM expenses WHERE family_id IS NULL '
        'UNION SELECT 1 FROM transactions WHERE family_id IS NULL LIMIT 1'
    )).first()
    buckets = list(family_ids) + ([None] if has_null_family_rows else [])

    for family_id in buckets:
        bind.execute(
            sa.text(
                'INSERT INTO expense_reimbursement_groups '
                '(family_id, name, mode, is_default, created_at, updated_at) '
                'VALUES (:family_id, :name, :mode, :is_default, :created_at, :updated_at)'
            ),
            {
                'family_id': family_id, 'name': 'Default', 'mode': 'separate',
                'is_default': True, 'created_at': now, 'updated_at': now,
            },
        )
        select_sql = (
            'SELECT id FROM expense_reimbursement_groups WHERE family_id = :family_id AND is_default = 1'
            if family_id is not None else
            'SELECT id FROM expense_reimbursement_groups WHERE family_id IS NULL AND is_default = 1'
        )
        group_id = bind.execute(
            sa.text(select_sql), {'family_id': family_id} if family_id is not None else {}
        ).scalar()

        family_filter = 'family_id = :family_id' if family_id is not None else 'family_id IS NULL'
        params = {'family_id': family_id, 'group_id': group_id} if family_id is not None else {'group_id': group_id}

        bind.execute(sa.text(
            f'UPDATE expenses SET reimbursement_group_id = :group_id '
            f'WHERE {family_filter} AND reimbursement_group_id IS NULL'
        ), params)
        bind.execute(sa.text(
            f"UPDATE transactions SET reimbursement_group_id = :group_id "
            f"WHERE {family_filter} AND payment_type IN ('Expense Reimbursement', 'Expense Partial Reimbursement') "
            f"AND reimbursement_group_id IS NULL"
        ), params)


def downgrade():
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_transactions_reimbursement_group_id', type_='foreignkey')
        batch_op.drop_index('ix_transactions_reimbursement_group_id')
        batch_op.drop_column('reimbursement_group_id')

    with op.batch_alter_table('income', schema=None) as batch_op:
        batch_op.drop_column('expense_reimbursement_total')

    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.drop_constraint('fk_expenses_income_id', type_='foreignkey')
        batch_op.drop_constraint('fk_expenses_reimbursement_group_id', type_='foreignkey')
        batch_op.drop_index('ix_expenses_income_id')
        batch_op.drop_index('ix_expenses_payday_period')
        batch_op.drop_index('ix_expenses_reimbursement_group_id')
        batch_op.drop_column('income_id')
        batch_op.drop_column('payday_period')
        batch_op.drop_column('reimbursement_group_id')

    with op.batch_alter_table('expense_reimbursement_groups', schema=None) as batch_op:
        batch_op.drop_index('ix_expense_reimbursement_groups_family_id')
    op.drop_table('expense_reimbursement_groups')
