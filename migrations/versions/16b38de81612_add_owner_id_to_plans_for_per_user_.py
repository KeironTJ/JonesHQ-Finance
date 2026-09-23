"""add owner_id to plans for per-user privacy

Revision ID: 16b38de81612
Revises: 491359418c58
Create Date: 2026-09-23 22:57:53.035956

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '16b38de81612'
down_revision = '491359418c58'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('plans', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_plans_owner_id'), ['owner_id'], unique=False)
        batch_op.create_foreign_key('fk_plans_owner', 'users', ['owner_id'], ['id'])


def downgrade():
    with op.batch_alter_table('plans', schema=None) as batch_op:
        batch_op.drop_constraint('fk_plans_owner', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_plans_owner_id'))
        batch_op.drop_column('owner_id')