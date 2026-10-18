"""Link income to household members: member_id on recurring_income and income.

`person` stays as the display name. Existing rows are linked when their person
matches exactly one current member's member name or account name (case- and
whitespace-insensitive) in the same household; anything else stays unlinked.

Revision ID: e6b1d4f8a2c3
Revises: d5a9c3e7f1b2
"""
from alembic import op
import sqlalchemy as sa


revision = 'e6b1d4f8a2c3'
down_revision = 'd5a9c3e7f1b2'
branch_labels = None
depends_on = None

TABLES = ('recurring_income', 'income')


def upgrade():
    for table in TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('member_id', sa.Integer(), nullable=True))
            batch_op.create_index(f'ix_{table}_member_id', ['member_id'])
            batch_op.create_foreign_key(
                f'fk_{table}_member_id', 'users', ['member_id'], ['id'], ondelete='SET NULL',
            )
    _backfill()


def _backfill():
    connection = op.get_bind()
    users = connection.execute(sa.text(
        'SELECT id, family_id, name, member_name FROM users WHERE family_id IS NOT NULL'
    )).fetchall()
    names = {}
    for user_id, family_id, name, member_name in users:
        for value in {(name or '').strip().lower(), (member_name or '').strip().lower()} - {''}:
            names.setdefault((family_id, value), set()).add(user_id)

    for table in TABLES:
        for (family_id, person), matches in names.items():
            if len(matches) == 1:
                connection.execute(
                    sa.text(
                        f'UPDATE {table} SET member_id = :member_id '
                        'WHERE family_id = :family_id AND lower(trim(person)) = :person'
                    ),
                    {'member_id': next(iter(matches)), 'family_id': family_id, 'person': person},
                )


def downgrade():
    for table in reversed(TABLES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(f'fk_{table}_member_id', type_='foreignkey')
            batch_op.drop_index(f'ix_{table}_member_id')
            batch_op.drop_column('member_id')
