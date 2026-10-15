import importlib.util
from io import StringIO
from pathlib import Path
import sqlite3

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine

from deployment import prepare_postgres_source as preparation
from deployment import rehearse_postgres as rehearsal


@pytest.fixture
def legacy_source(tmp_path):
    path = tmp_path / 'original.db'
    engine = create_engine('sqlite:///' + str(path))
    with engine.begin() as connection:
        rehearsal.db.metadata.create_all(connection)
        connection.exec_driver_sql('CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)')
        connection.exec_driver_sql('INSERT INTO alembic_version VALUES (?)', (rehearsal.migration_head(),))
        connection.execute(rehearsal.db.metadata.tables['families'].insert().values(id=1, name='Family'))
        connection.exec_driver_sql("""
            INSERT INTO credit_cards (id, family_id, card_name, annual_apr, monthly_apr, credit_limit)
            VALUES (1, 1, 'Card', 12, 1, 1000)
        """)
        connection.exec_driver_sql("""
            INSERT INTO credit_card_transactions
                (id, family_id, credit_card_id, category_id, date, week, transaction_type,
                 amount, head_budget, sub_budget, item)
            VALUES (1, 1, 1, 999, '2026-02-09', '2026-W07', 'Purchase',
                    -12.345, 'Legacy', 'Label', 'Retained detail')
        """)
        connection.execute(rehearsal.db.metadata.tables['vehicles'].insert().values(
            id=1, family_id=1, registration='TEST', make='Test', model='Test'))
        connection.exec_driver_sql("""
            INSERT INTO trips (id, family_id, vehicle_id, date, total_miles,
                               gallons_used, trip_cost)
            VALUES (1, 1, 1, '2026-02-09', 10, 0.123456789123, 1.235)
        """)
    engine.dispose()
    return path


def test_preparation_reports_without_writing(legacy_source, capsys):
    before = legacy_source.read_bytes()
    preparation.prepare(legacy_source)
    assert legacy_source.read_bytes() == before
    output = capsys.readouterr().out
    assert 'Report only' in output
    assert 'trips.gallons_used | 1' in output
    assert 'Retained detail' not in output


def test_preparation_preserves_source_and_only_applies_reviewed_changes(legacy_source, tmp_path):
    before = legacy_source.read_bytes()
    output = tmp_path / 'prepared.db'
    preparation.prepare(legacy_source, output)
    assert legacy_source.read_bytes() == before
    with sqlite3.connect(output) as connection:
        assert connection.execute("""
            SELECT category_id, week, amount, head_budget, sub_budget, item
            FROM credit_card_transactions
        """).fetchone() == (None, '07-2026', -12.34, 'Legacy', 'Label', 'Retained detail')
        assert connection.execute(
            'SELECT gallons_used, trip_cost FROM trips'
        ).fetchone() == (0.12345679, 1.24)
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    with pytest.raises(FileExistsError):
        preparation.prepare(legacy_source, output)
    with pytest.raises(ValueError, match='must not be the source'):
        preparation.prepare(legacy_source, legacy_source)
    assert legacy_source.read_bytes() == before


@pytest.mark.parametrize('sql', [
    'UPDATE credit_card_transactions SET credit_card_id = 999',
    "UPDATE credit_card_transactions SET week = '2026-W99'",
    "UPDATE credit_card_transactions SET week = 'invalid-week'",
    'UPDATE credit_card_transactions SET amount = 100000000',
    'UPDATE credit_card_transactions SET balance = 1.234',
    "INSERT INTO categories (id, family_id, name, category_type, head_budget, sub_budget) "
    "VALUES (2, 1, 'Match', 'Expense', 'Legacy', 'Label')",
])
def test_unreviewed_defects_refuse_preparation(legacy_source, tmp_path, sql):
    with sqlite3.connect(legacy_source) as connection:
        connection.execute(sql)
    before = legacy_source.read_bytes()
    output = tmp_path / 'prepared.db'
    with pytest.raises((ValueError, ArithmeticError)):
        preparation.prepare(legacy_source, output)
    assert not output.exists()
    assert legacy_source.read_bytes() == before


def test_final_validation_failure_removes_only_owned_output(legacy_source, tmp_path):
    with sqlite3.connect(legacy_source) as connection:
        connection.execute('UPDATE credit_card_transactions SET item = ?', ('x' * 256,))
    output = tmp_path / 'prepared.db'
    with pytest.raises(ValueError, match='declared length'):
        preparation.prepare(legacy_source, output)
    assert not output.exists()
    assert legacy_source.exists()


def test_copy_does_not_match_categories_from_another_family(legacy_source, tmp_path):
    with sqlite3.connect(legacy_source) as connection:
        connection.execute(
            "INSERT INTO families (id, name, created_at) VALUES (2, 'Other', '2026-01-01')")
        connection.execute("""
            INSERT INTO categories (family_id, name, category_type, head_budget, sub_budget)
            VALUES (2, 'Other family', 'Expense', 'Legacy', 'Label')
        """)
    output = tmp_path / 'prepared.db'
    preparation.prepare(legacy_source, output)
    with sqlite3.connect(output) as connection:
        assert connection.execute(
            'SELECT category_id FROM credit_card_transactions'
        ).fetchone() == (None,)


def precision_migration():
    path = Path(__file__).resolve().parents[1] / 'migrations' / 'versions' / (
        'a24c6e8f1032_widen_calculated_precision.py')
    spec = importlib.util.spec_from_file_location('precision_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_precision_migration_preserves_sqlite_raw_values_and_foreign_keys(legacy_source):
    before = legacy_source.read_bytes()
    migration = precision_migration()
    engine = create_engine('sqlite:///' + str(legacy_source))
    with engine.begin() as connection:
        connection.exec_driver_sql('PRAGMA foreign_keys=ON')
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.downgrade()
        assert connection.exec_driver_sql('SELECT gallons_used FROM trips').scalar_one() == 0.123456789123
    engine.dispose()
    assert legacy_source.read_bytes() == before


def test_precision_migration_emits_only_reviewed_postgres_changes():
    migration = precision_migration()
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name='postgresql', opts={'as_sql': True, 'output_buffer': output})
    with Operations.context(context):
        migration.upgrade()
    statements = output.getvalue()
    assert statements.count('ALTER TABLE') == 9
    assert 'ALTER COLUMN gallons_used TYPE NUMERIC(14, 8)' in statements
    assert 'ALTER COLUMN monthly_apr TYPE NUMERIC(11, 8)' in statements
    assert 'trip_cost' not in statements
    for table, column, precision, scale, _ in migration.CHANGES:
        model_type = rehearsal.db.metadata.tables[table].c[column].type
        assert (model_type.precision, model_type.scale) == (precision - scale + 8, 8)


def test_cli_requires_explicit_policy_to_write(legacy_source, tmp_path):
    with pytest.raises(SystemExit):
        preparation.main(['--source', str(legacy_source), '--output', str(tmp_path / 'copy.db')])
