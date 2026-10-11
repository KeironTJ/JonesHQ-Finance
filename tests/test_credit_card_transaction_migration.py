import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_assignment_migration_preserves_existing_transactions():
    path = Path(__file__).resolve().parents[1] / 'migrations' / 'versions' / (
        'f8b4d0e63a95_add_assigned_to_to_credit_card_transactions.py'
    )
    spec = importlib.util.spec_from_file_location('assignment_migration', path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text(
            'CREATE TABLE credit_card_transactions (id INTEGER PRIMARY KEY, item VARCHAR(255))'
        ))
        connection.execute(sa.text(
            "INSERT INTO credit_card_transactions (id, item) VALUES (1, 'Existing purchase')"
        ))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            row = connection.execute(sa.text(
                'SELECT item, assigned_to FROM credit_card_transactions WHERE id = 1'
            )).one()
            assert row == ('Existing purchase', None)
            connection.execute(sa.text(
                "UPDATE credit_card_transactions SET assigned_to = 'Child' WHERE id = 1"
            ))
            migration.downgrade()

        assert [column['name'] for column in sa.inspect(connection).get_columns(
            'credit_card_transactions'
        )] == ['id', 'item']
        assert connection.execute(sa.text(
            'SELECT item FROM credit_card_transactions WHERE id = 1'
        )).scalar_one() == 'Existing purchase'
    engine.dispose()
