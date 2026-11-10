"""Add household meal library and planner.

Revision ID: e83f9b5d012c
Revises: d72e8a4c901b
"""
from alembic import op
import sqlalchemy as sa


revision = 'e83f9b5d012c'
down_revision = 'd72e8a4c901b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'meals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('ingredients', sa.Text(), nullable=False, server_default=''),
        sa.Column('instructions', sa.Text(), nullable=False, server_default=''),
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index('ix_meals_family_id', 'meals', ['family_id'])
    op.create_table(
        'planned_meals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('meal_id', sa.Integer(), sa.ForeignKey('meals.id'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('slot', sa.String(10), nullable=False, server_default='dinner'),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.CheckConstraint("slot IN ('breakfast', 'lunch', 'dinner')", name='ck_planned_meal_slot'),
    )
    for column in ('family_id', 'meal_id', 'date'):
        op.create_index(f'ix_planned_meals_{column}', 'planned_meals', [column])


def downgrade():
    op.drop_table('planned_meals')
    op.drop_table('meals')
