"""add household memberships

Revision ID: f42b7a91c6d3
Revises: d7a2c5e8f103
Create Date: 2026-11-10 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f42b7a91c6d3'
down_revision = 'd7a2c5e8f103'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'household_memberships',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('family_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('member_name', sa.String(length=100), nullable=True),
        sa.Column('allowed_sections', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'], name='fk_household_memberships_user_id_users',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['family_id'], ['families.id'], name='fk_household_memberships_family_id_families',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'family_id', name='uq_household_membership_user_family'),
    )
    op.create_index(
        'ix_household_memberships_user_id', 'household_memberships', ['user_id'],
    )
    op.create_index(
        'ix_household_memberships_family_id', 'household_memberships', ['family_id'],
    )
    op.execute(sa.text(
        """
        INSERT INTO household_memberships
            (user_id, family_id, role, member_name, allowed_sections, created_at)
        SELECT id, family_id, role, member_name, allowed_sections, CURRENT_TIMESTAMP
        FROM users
        WHERE family_id IS NOT NULL
        """
    ))


def downgrade():
    op.drop_index('ix_household_memberships_family_id', table_name='household_memberships')
    op.drop_index('ix_household_memberships_user_id', table_name='household_memberships')
    op.drop_table('household_memberships')
