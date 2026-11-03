import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_trip_limits_migration_preserves_settings_and_backfills_defaults():
    path = Path(__file__).resolve().parents[1] / 'migrations' / 'versions' / (
        'd7a2c5e8f103_add_trip_routine_limits.py'
    )
    spec = importlib.util.spec_from_file_location('trip_limits_migration', path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text(
            'CREATE TABLE site_settings (id INTEGER PRIMARY KEY, announcement VARCHAR(500))'
        ))
        connection.execute(sa.text(
            "INSERT INTO site_settings (id, announcement) VALUES (1, 'Existing announcement')"
        ))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            row = connection.execute(sa.text(
                'SELECT announcement, trip_planning_max_days, trip_active_routine_limit '
                'FROM site_settings WHERE id = 1'
            )).one()
            assert row == ('Existing announcement', 1800, 25)
            columns = {column['name']: column for column in sa.inspect(connection).get_columns(
                'site_settings'
            )}
            assert columns['trip_planning_max_days']['nullable'] is False
            assert columns['trip_active_routine_limit']['nullable'] is False
            connection.execute(sa.text('INSERT INTO site_settings (id) VALUES (2)'))
            assert connection.execute(sa.text(
                'SELECT trip_planning_max_days, trip_active_routine_limit '
                'FROM site_settings WHERE id = 2'
            )).one() == (1800, 25)
            migration.downgrade()
        assert [column['name'] for column in sa.inspect(connection).get_columns(
            'site_settings'
        )] == ['id', 'announcement']
        assert connection.execute(sa.text(
            'SELECT announcement FROM site_settings WHERE id = 1'
        )).scalar_one() == 'Existing announcement'
    engine.dispose()
