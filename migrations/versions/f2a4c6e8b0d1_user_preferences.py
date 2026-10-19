"""Separate personal display preferences from household configuration.

Revision ID: f2a4c6e8b0d1
Revises: e6b1d4f8a2c3
"""
from alembic import op
import sqlalchemy as sa


revision = 'f2a4c6e8b0d1'
down_revision = 'e6b1d4f8a2c3'
branch_labels = None
depends_on = None

PREFERENCE_KEYS = (
    'dashboard.networth_expanded',
    'dashboard.account_selection_expanded',
    'dashboard.payday_expanded',
    'dashboard.summaries_expanded',
    'dashboard.quick_nav_expanded',
    'categories.collapse_all_default',
    'vendors.collapse_all_default',
)


def upgrade():
    op.add_column('users', sa.Column('preferences', sa.JSON(), nullable=True))
    connection = op.get_bind()
    settings = sa.table(
        'settings', sa.column('family_id', sa.Integer()),
        sa.column('key', sa.String()), sa.column('value', sa.String()),
    )
    users = sa.table(
        'users', sa.column('id', sa.Integer()), sa.column('family_id', sa.Integer()),
        sa.column('preferences', sa.JSON()),
    )
    by_family = {}
    for row in connection.execute(
        sa.select(settings.c.family_id, settings.c.key, settings.c.value)
        .where(settings.c.key.in_(PREFERENCE_KEYS))
    ):
        by_family.setdefault(row.family_id, {})[row.key] = (
            (row.value or '').lower() in ('true', '1', 'yes')
        )
    for row in connection.execute(sa.select(users.c.id, users.c.family_id)):
        # Unattached accounts must not inherit unscoped legacy settings.
        values = by_family.get(row.family_id, {}) if row.family_id is not None else {}
        connection.execute(
            users.update().where(users.c.id == row.id).values(preferences=values)
        )
    # Retain legacy rows so a downgrade can restore the household-level behaviour.


def downgrade():
    op.drop_column('users', 'preferences')
