from datetime import date, datetime
from decimal import Decimal
import os

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import OperationalError

from deployment import rehearse_postgres as rehearsal
from deployment import rehearse_update_guard as guard
from extensions import db
from models import Account, Category, Family, Transaction, User


@pytest.fixture
def source_file(tmp_path):
    path = tmp_path / 'snapshot.db'
    engine = create_engine('sqlite:///' + str(path))
    with engine.begin() as connection:
        db.metadata.create_all(connection)
        connection.execute(Family.__table__.insert().values(id=10, name='Household'))
        connection.execute(User.__table__.insert().values(
            id=20, family_id=10, email='person@example.com', name='Person', password_hash='hash-kept',
            totp_secret='secret-kept', created_at=datetime(2026, 10, 15, 12, 30)))
        connection.execute(Account.__table__.insert().values(
            id=30, family_id=10, owner_id=20, name='Private', account_type='Current',
            balance=Decimal('123.45')))
        connection.execute(User.__table__.update().where(User.id == 20).values(default_account_id=30))
        connection.execute(Category.__table__.insert().values(
            id=40, family_id=10, name='Category', category_type='expense'))
        connection.execute(Category.__table__.update().where(Category.id == 40).values(parent_id=40))
        connection.execute(Transaction.__table__.insert().values(
            id=50, family_id=10, account_id=30, category_id=40,
            amount=Decimal('-12.34'), transaction_date=date(2026, 10, 15),
            description='Unicode \u00a3 text'))
        connection.execute(Transaction.__table__.update().where(Transaction.id == 50).values(
            linked_transaction_id=50))
        connection.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)'))
        connection.execute(text('INSERT INTO alembic_version VALUES (:head)'), {'head': rehearsal.migration_head()})
    engine.dispose()
    return path


def test_source_validation_is_read_only_and_no_target_needed(source_file, monkeypatch, capsys):
    before = source_file.read_bytes()
    monkeypatch.delenv('PG_REHEARSAL_DATABASE_URL', raising=False)
    assert rehearsal.main(['--source', str(source_file)]) == 0
    assert source_file.read_bytes() == before
    output = capsys.readouterr().out
    assert 'Validation only' in output
    assert 'person@example.com' not in output
    assert 'secret-kept' not in output
    engine = rehearsal.sqlite_source(source_file)
    try:
        with engine.connect() as connection, pytest.raises(OperationalError, match='readonly'):
            connection.execute(text("DELETE FROM users"))
    finally:
        engine.dispose()


def test_copy_preserves_typed_values_links_and_migration_head(source_file):
    source_engine = rehearsal.sqlite_source(source_file)
    target_engine = create_engine('sqlite://')
    try:
        with source_engine.connect() as source, target_engine.begin() as target:
            target.exec_driver_sql('PRAGMA foreign_keys=ON')
            counts = rehearsal.source_checks(source, db.metadata, rehearsal.migration_head())
            assert counts['transactions'] == 1
            rehearsal.copy_and_verify(source, target, db.metadata, rehearsal.migration_head())
            assert target.execute(select(Account.balance)).scalar_one() == Decimal('123.45')
            assert target.execute(select(User.default_account_id)).scalar_one() == 30
            assert target.execute(select(Category.parent_id)).scalar_one() == 40
            assert target.execute(select(Transaction.linked_transaction_id)).scalar_one() == 50
            assert target.execute(text('PRAGMA foreign_key_check')).all() == []
            assert target.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == rehearsal.migration_head()
    finally:
        source_engine.dispose()
        target_engine.dispose()


@pytest.mark.parametrize('sql,message', [
    ('UPDATE users SET default_account_id=999', 'broken foreign keys'),
    ("UPDATE alembic_version SET version_num='old'", 'migration head'),
    ('CREATE TABLE unexpected (id INTEGER)', 'tables do not match'),
    ('ALTER TABLE accounts ADD COLUMN surprise TEXT', 'columns do not match'),
    ('UPDATE users SET is_active=2', 'Invalid SQLite boolean'),
    ('UPDATE transactions SET amount=12.345', 'automatic financial rounding is refused'),
    ("UPDATE users SET name='" + 'x' * 101 + "'", 'automatic truncation is refused'),
])
def test_invalid_source_fails_before_target_access(source_file, sql, message, capsys):
    engine = create_engine('sqlite:///' + str(source_file))
    with engine.begin() as connection:
        connection.execute(text(sql))
    engine.dispose()
    assert rehearsal.main(['--source', str(source_file), '--import-to-rehearsal']) == 1
    assert message in capsys.readouterr().err


@pytest.mark.parametrize('url', [
    'postgresql+psycopg://localhost/finance',
    'sqlite:///target_rehearsal',
    'postgresql://localhost/finance_rehearsal',
    'postgresql+psycopg://localhost/finance_rehearsal?dbname=production',
])
def test_production_or_overridable_target_refused(url):
    with pytest.raises(ValueError):
        rehearsal.rehearsal_target(url)


def test_existing_target_refused_without_changes(source_file):
    source_engine = rehearsal.sqlite_source(source_file)
    target_engine = create_engine('sqlite://')
    try:
        with source_engine.connect() as source, target_engine.begin() as target:
            target.execute(text('CREATE TABLE keep_me (id INTEGER)'))
            with pytest.raises(ValueError, match='not empty'):
                rehearsal.copy_and_verify(source, target, db.metadata, rehearsal.migration_head())
            assert inspect(target).get_table_names() == ['keep_me']
    finally:
        source_engine.dispose()
        target_engine.dispose()


def test_missing_source_is_not_created(tmp_path, capsys):
    missing = tmp_path / 'missing.db'
    assert rehearsal.main(['--source', str(missing)]) == 1
    assert not missing.exists()
    assert 'ERROR' in capsys.readouterr().err


@pytest.mark.parametrize('url,expected', [
    ('sqlite:////home/joneshq/snapshot.db', 0),
    ('postgresql+psycopg://user:private@localhost/finance', 1),
    ('not-a-url', 1),
])
def test_sqlite_update_guard_refuses_other_backends(monkeypatch, capsys, url, expected):
    monkeypatch.setattr(guard, 'load_env_file', lambda path: {'DATABASE_URL': url})
    assert guard.main() == expected
    captured = capsys.readouterr()
    assert 'private' not in captured.out + captured.err


@pytest.mark.skipif(not os.environ.get('PG_REHEARSAL_DATABASE_URL'),
                    reason='Requires an explicitly provided empty disposable PostgreSQL database')
def test_actual_postgres_round_trip_and_sequence_reset(source_file):
    target_engine = create_engine(rehearsal.rehearsal_target(os.environ['PG_REHEARSAL_DATABASE_URL']))
    source_engine = rehearsal.sqlite_source(source_file)
    try:
        # Intentionally roll back even on success: leave this disposable database empty.
        with source_engine.connect() as source, target_engine.connect() as target:
            transaction = target.begin()
            try:
                rehearsal.source_checks(source, db.metadata, rehearsal.migration_head())
                rehearsal.copy_and_verify(source, target, db.metadata, rehearsal.migration_head())
                new_id = target.execute(Family.__table__.insert().values(name='Sequence probe')).inserted_primary_key[0]
                assert new_id > 10
                assert target.execute(select(Transaction.amount)).scalar_one() == Decimal('-12.34')
                assert target.execute(select(User.password_hash)).scalar_one() == 'hash-kept'
            finally:
                transaction.rollback()
    finally:
        source_engine.dispose()
        target_engine.dispose()


@pytest.mark.skipif(not os.environ.get('PG_REHEARSAL_DATABASE_URL'),
                    reason='Requires an explicitly provided empty disposable PostgreSQL database')
def test_actual_postgres_failure_rolls_back_schema_and_rows(source_file):
    from sqlalchemy.exc import DataError

    writer = create_engine('sqlite:///' + str(source_file))
    with writer.begin() as connection:
        # SQLite accepts oversized strings; PostgreSQL must reject, not truncate.
        connection.execute(User.__table__.update().values(name='x' * 101))
    writer.dispose()
    target_engine = create_engine(rehearsal.rehearsal_target(os.environ['PG_REHEARSAL_DATABASE_URL']))
    source_engine = rehearsal.sqlite_source(source_file)
    try:
        with source_engine.connect() as source, pytest.raises(DataError):
            with target_engine.begin() as target:
                rehearsal.copy_and_verify(source, target, db.metadata, rehearsal.migration_head())
        with target_engine.connect() as target:
            assert inspect(target).get_table_names() == []
    finally:
        source_engine.dispose()
        target_engine.dispose()
