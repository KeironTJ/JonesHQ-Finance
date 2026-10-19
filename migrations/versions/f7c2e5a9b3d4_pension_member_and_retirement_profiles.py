"""Link pensions and retirement profiles to household members.

Revision ID: f7c2e5a9b3d4
Revises: e6b1d4f8a2c3
"""
import logging
from datetime import date

from alembic import op
import sqlalchemy as sa


revision = 'f7c2e5a9b3d4'
down_revision = 'e6b1d4f8a2c3'
branch_labels = None
depends_on = None
logger = logging.getLogger('alembic.runtime.migration')


def _members(connection):
    members = connection.execute(sa.text(
        'SELECT id, family_id, name, member_name FROM users WHERE family_id IS NOT NULL'
    )).mappings().all()
    aliases = {}
    for member in members:
        for name in {(member['name'] or '').strip().lower(),
                     (member['member_name'] or '').strip().lower()} - {''}:
            aliases.setdefault((member['family_id'], name), set()).add(member['id'])
    return members, aliases


def _profiles(connection, members, aliases):
    settings = sa.table('settings',
                        sa.column('id', sa.Integer), sa.column('family_id', sa.Integer),
                        sa.column('key', sa.String), sa.column('value', sa.String),
                        sa.column('description', sa.String), sa.column('setting_type', sa.String))
    for member in members:
        family_id, member_id = member['family_id'], member['id']
        names = [name for (fid, name), ids in aliases.items()
                 if fid == family_id and ids == {member_id}]
        for suffix in ('date_of_birth', 'retirement_age'):
            key = f'retirement.member.{member_id}.{suffix}'
            if connection.execute(sa.select(settings.c.id).where(
                    settings.c.family_id == family_id, settings.c.key == key)).first():
                continue
            rows = connection.execute(sa.select(settings).where(
                settings.c.family_id == family_id,
                settings.c.key.in_([f'{name}_{suffix}' for name in names]),
            )).mappings().all()
            values = {row['value'] for row in rows}
            if len(values) == 1:
                original = rows[0]
                try:
                    if original['value']:
                        if suffix == 'date_of_birth':
                            date.fromisoformat(original['value'])
                        elif not 50 <= int(original['value']) <= 80:
                            raise ValueError('Retirement age out of range.')
                except (TypeError, ValueError):
                    logger.warning('Invalid retirement settings retained for member %s; review their profile.', member_id)
                    continue
                connection.execute(settings.insert().values(
                    family_id=family_id, key=key, value=original['value'],
                    description=original['description'],
                    setting_type='int' if suffix == 'retirement_age' and original['value'] else 'string',
                ))
            elif len(values) > 1:
                logger.warning('Conflicting retirement settings retained for member %s; review their profile.', member_id)
            elif suffix == 'retirement_age' and not rows:
                ages = connection.execute(sa.text(
                    'SELECT DISTINCT retirement_age FROM pensions '
                    'WHERE family_id = :family_id AND member_id = :member_id AND retirement_age IS NOT NULL'
                ), {'family_id': family_id, 'member_id': member_id}).scalars().all()
                if len(ages) == 1 and 50 <= ages[0] <= 80:
                    connection.execute(settings.insert().values(
                        family_id=family_id, key=key, value=str(ages[0]),
                        description='Target retirement age', setting_type='int',
                    ))
                elif ages:
                    logger.warning('Different or invalid pension retirement ages retained for member %s; choose a shared age.', member_id)


def upgrade():
    with op.batch_alter_table('pensions') as batch_op:
        batch_op.add_column(sa.Column('member_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_pensions_member_id', ['member_id'])
        batch_op.create_foreign_key(
            'fk_pensions_member_id', 'users', ['member_id'], ['id'], ondelete='SET NULL')
    connection = op.get_bind()
    members, aliases = _members(connection)
    rows = connection.execute(sa.text('SELECT id, family_id, person FROM pensions')).mappings().all()
    for row in rows:
        matches = aliases.get((row['family_id'], (row['person'] or '').strip().lower()), set())
        if len(matches) == 1:
            connection.execute(sa.text('UPDATE pensions SET member_id = :member_id WHERE id = :id'),
                               {'member_id': next(iter(matches)), 'id': row['id']})
    _profiles(connection, members, aliases)


def downgrade():
    # Preserve profile values in Settings, including legacy name-based keys.
    with op.batch_alter_table('pensions') as batch_op:
        batch_op.drop_constraint('fk_pensions_member_id', type_='foreignkey')
        batch_op.drop_index('ix_pensions_member_id')
        batch_op.drop_column('member_id')
