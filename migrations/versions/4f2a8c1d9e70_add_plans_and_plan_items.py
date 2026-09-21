"""add plans and plan items

Revision ID: 4f2a8c1d9e70
Revises: c3e7a1f9b2d4
Create Date: 2026-09-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '4f2a8c1d9e70'
down_revision = 'c3e7a1f9b2d4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'plans',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('plan_type', sa.String(length=30), nullable=False, server_default='occasion'),
        sa.Column('person', sa.String(length=100), nullable=True),
        sa.Column('target_date', sa.Date(), nullable=True),
        sa.Column('target_amount', sa.Numeric(10, 2), nullable=True),
        sa.Column('saved_amount', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    with op.batch_alter_table('plans', schema=None) as batch_op:
        batch_op.create_index('ix_plans_family_id', ['family_id'], unique=False)

    op.create_table(
        'plan_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('plan_id', sa.Integer(), sa.ForeignKey('plans.id'), nullable=False),
        sa.Column('title', sa.String(length=160), nullable=False),
        sa.Column('estimated_cost', sa.Numeric(10, 2), nullable=True),
        sa.Column('actual_cost', sa.Numeric(10, 2), nullable=True),
        sa.Column('transaction_id', sa.Integer(), sa.ForeignKey('transactions.id'), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='idea'),
        sa.Column('priority', sa.String(length=20), nullable=False, server_default='normal'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    with op.batch_alter_table('plan_items', schema=None) as batch_op:
        batch_op.create_index('ix_plan_items_family_id', ['family_id'], unique=False)
        batch_op.create_index('ix_plan_items_plan_id', ['plan_id'], unique=False)
        batch_op.create_index('ix_plan_items_transaction_id', ['transaction_id'], unique=False)


def downgrade():
    with op.batch_alter_table('plan_items', schema=None) as batch_op:
        batch_op.drop_index('ix_plan_items_transaction_id')
        batch_op.drop_index('ix_plan_items_plan_id')
        batch_op.drop_index('ix_plan_items_family_id')
    op.drop_table('plan_items')

    with op.batch_alter_table('plans', schema=None) as batch_op:
        batch_op.drop_index('ix_plans_family_id')
    op.drop_table('plans')
