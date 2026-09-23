"""add owner_id to income and recurring_income for per-user privacy

Revision ID: 9d0242ddc986
Revises: 82b97dbffd04
Create Date: 2026-09-23 22:02:11.876138

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9d0242ddc986'
down_revision = '82b97dbffd04'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('income', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_income_owner_id'), ['owner_id'], unique=False)
        batch_op.create_foreign_key('fk_income_owner', 'users', ['owner_id'], ['id'])

    with op.batch_alter_table('recurring_income', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_recurring_income_owner_id'), ['owner_id'], unique=False)
        batch_op.create_foreign_key('fk_recurring_income_owner', 'users', ['owner_id'], ['id'])


def downgrade():
    with op.batch_alter_table('recurring_income', schema=None) as batch_op:
        batch_op.drop_constraint('fk_recurring_income_owner', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_recurring_income_owner_id'))
        batch_op.drop_column('owner_id')

    with op.batch_alter_table('income', schema=None) as batch_op:
        batch_op.drop_constraint('fk_income_owner', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_income_owner_id'))
        batch_op.drop_column('owner_id')