"""add owner_id to expenses for per-user privacy

Revision ID: 491359418c58
Revises: 15f1d6efdfad
Create Date: 2026-09-23 22:48:58.637962

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '491359418c58'
down_revision = '15f1d6efdfad'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_expenses_owner_id'), ['owner_id'], unique=False)
        batch_op.create_foreign_key('fk_expenses_owner', 'users', ['owner_id'], ['id'])


def downgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.drop_constraint('fk_expenses_owner', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_expenses_owner_id'))
        batch_op.drop_column('owner_id')