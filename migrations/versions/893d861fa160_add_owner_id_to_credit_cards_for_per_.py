"""add owner_id to credit_cards for per-user privacy

Revision ID: 893d861fa160
Revises: 16473e7cf056
Create Date: 2026-09-23 22:32:54.763877

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '893d861fa160'
down_revision = '16473e7cf056'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('credit_cards', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_credit_cards_owner_id'), ['owner_id'], unique=False)
        batch_op.create_foreign_key('fk_credit_cards_owner', 'users', ['owner_id'], ['id'])


def downgrade():
    with op.batch_alter_table('credit_cards', schema=None) as batch_op:
        batch_op.drop_constraint('fk_credit_cards_owner', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_credit_cards_owner_id'))
        batch_op.drop_column('owner_id')