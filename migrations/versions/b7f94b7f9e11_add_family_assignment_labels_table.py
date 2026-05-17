"""add_family_assignment_labels_table

Revision ID: b7f94b7f9e11
Revises: aba54c1e02c1
Create Date: 2026-05-17 19:05:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'b7f94b7f9e11'
down_revision = 'aba54c1e02c1'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if 'family_assignment_labels' not in inspector.get_table_names():
        op.create_table(
            'family_assignment_labels',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('family_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
            sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['family_id'], ['families.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('family_id', 'name', name='uq_family_assignment_label_name'),
        )

    indexes = {idx['name'] for idx in inspector.get_indexes('family_assignment_labels')}
    index_name = op.f('ix_family_assignment_labels_family_id')
    if index_name not in indexes:
        op.create_index(index_name, 'family_assignment_labels', ['family_id'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if 'family_assignment_labels' in inspector.get_table_names():
        indexes = {idx['name'] for idx in inspector.get_indexes('family_assignment_labels')}
        index_name = op.f('ix_family_assignment_labels_family_id')
        if index_name in indexes:
            op.drop_index(index_name, table_name='family_assignment_labels')
        op.drop_table('family_assignment_labels')
