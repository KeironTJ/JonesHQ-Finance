"""add_category_vendor_to_children

Revision ID: 3087325ab8da
Revises: 37b762477f3b
Create Date: 2026-01-29 22:22:43.590340

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3087325ab8da'
down_revision = '37b762477f3b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('children', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('vendor_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_children_category', 'categories', ['category_id'], ['id'])
        batch_op.create_foreign_key('fk_children_vendor', 'vendors', ['vendor_id'], ['id'])


def downgrade():
    with op.batch_alter_table('children', schema=None) as batch_op:
        batch_op.drop_constraint('fk_children_vendor', type_='foreignkey')
        batch_op.drop_constraint('fk_children_category', type_='foreignkey')
        batch_op.drop_column('vendor_id')
        batch_op.drop_column('category_id')
