"""Income sources: pay frequency, income type, pension scheme, student loan,
yearly rise, pension link, and an income_changes timeline.

Existing rows keep working unchanged: every new recurring_income column has a
server default or is nullable, and NULL pay_frequency on income means monthly.

Revision ID: d5a9c3e7f1b2
Revises: c4f8a2d6e0b1
"""
from alembic import op
import sqlalchemy as sa


revision = 'd5a9c3e7f1b2'
down_revision = 'c4f8a2d6e0b1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('recurring_income', schema=None) as batch_op:
        batch_op.add_column(sa.Column('income_type', sa.String(length=30), nullable=False, server_default='employment'))
        batch_op.add_column(sa.Column('pay_frequency', sa.String(length=20), nullable=False, server_default='monthly'))
        batch_op.add_column(sa.Column('first_pay_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('pension_scheme', sa.String(length=20), nullable=False, server_default='salary_sacrifice'))
        batch_op.add_column(sa.Column('student_loan_plans', sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column('set_aside_percent', sa.Numeric(precision=5, scale=2), nullable=True))
        batch_op.add_column(sa.Column('annual_increase_percent', sa.Numeric(precision=6, scale=3), nullable=True))
        batch_op.add_column(sa.Column('annual_increase_start', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('pension_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_recurring_income_pension_id', 'pensions', ['pension_id'], ['id'], ondelete='SET NULL',
        )

    with op.batch_alter_table('income', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pay_frequency', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('bonus', sa.Numeric(precision=10, scale=2), nullable=True))
        batch_op.add_column(sa.Column('student_loan', sa.Numeric(precision=10, scale=2), nullable=True))

    op.create_table(
        'income_changes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('family_id', sa.Integer(), nullable=True),
        sa.Column('recurring_income_id', sa.Integer(), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('change_type', sa.String(length=20), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('percent', sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column('tax_code', sa.String(length=10), nullable=True),
        sa.Column('employee_pension_percent', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('employer_pension_percent', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('bonus_pensionable', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.ForeignKeyConstraint(['recurring_income_id'], ['recurring_income.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_income_changes_family_id', 'income_changes', ['family_id'])
    op.create_index('ix_income_changes_recurring_income_id', 'income_changes', ['recurring_income_id'])


def downgrade():
    op.drop_index('ix_income_changes_recurring_income_id', table_name='income_changes')
    op.drop_index('ix_income_changes_family_id', table_name='income_changes')
    op.drop_table('income_changes')

    with op.batch_alter_table('income', schema=None) as batch_op:
        batch_op.drop_column('student_loan')
        batch_op.drop_column('bonus')
        batch_op.drop_column('pay_frequency')

    with op.batch_alter_table('recurring_income', schema=None) as batch_op:
        batch_op.drop_constraint('fk_recurring_income_pension_id', type_='foreignkey')
        batch_op.drop_column('pension_id')
        batch_op.drop_column('annual_increase_start')
        batch_op.drop_column('annual_increase_percent')
        batch_op.drop_column('set_aside_percent')
        batch_op.drop_column('student_loan_plans')
        batch_op.drop_column('pension_scheme')
        batch_op.drop_column('first_pay_date')
        batch_op.drop_column('pay_frequency')
        batch_op.drop_column('income_type')
