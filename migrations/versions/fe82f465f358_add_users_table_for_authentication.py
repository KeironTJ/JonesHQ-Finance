"""Add users table for authentication

Revision ID: fe82f465f358
Revises: 953c136cfbc2
Create Date: 2026-02-04 15:09:35.728255

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fe82f465f358'
down_revision = '953c136cfbc2'
branch_labels = None
depends_on = None


def upgrade():
    # Users table was created by db.create_all() - this migration documents it
    # Check if table exists before creating
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'users' not in inspector.get_table_names():
        op.create_table('users',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('email', sa.String(length=120), nullable=False),
            sa.Column('password_hash', sa.String(length=255), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('last_login', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
