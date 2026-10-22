from decimal import Decimal
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import psycopg
import pytest
from alembic.script import ScriptDirectory
from flask_migrate import downgrade, stamp, upgrade
from sqlalchemy import inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import NotFound

from extensions import db
from models.accounts import Account
from utils.db_helpers import family_get, family_get_or_404


def test_form_string_ids_work_in_scoped_lookups(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = Account(family_id=family.id, name='ID lookup', account_type='Joint', balance=0)
    db.session.add(account)
    db.session.commit()
    assert family_get(Account, str(account.id)) is account
    assert family_get_or_404(Account, str(account.id)) is account
    with pytest.raises(ValueError, match='Invalid record ID'):
        family_get(Account, 'invalid')
    with pytest.raises(NotFound):
        family_get_or_404(Account, 'invalid')


def test_postgres_enforces_foreign_keys_and_preserves_decimal_amounts(app, family):
    if db.engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL constraint regression.')
    account = Account(family_id=family.id, name='Precision', account_type='Joint',
                      balance=Decimal('1234.56'))
    db.session.add(account)
    db.session.commit()
    db.session.expire_all()
    assert db.session.get(Account, account.id).balance == Decimal('1234.56')
    with pytest.raises(IntegrityError):
        db.session.execute(Account.__table__.insert().values(
            family_id=family.id + 10000, name='Invalid FK', account_type='Joint'))
    db.session.rollback()


def test_postgres_current_release_migration_round_trip(app):
    if db.engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL migration regression.')
    directory = str(Path(__file__).resolve().parents[1] / 'migrations')
    # Legacy migrations start from the pre-Alembic schema, not an empty database.
    # Exercise the current release's upgrade/downgrade against its predecessor.
    scripts = ScriptDirectory(directory)
    head = scripts.get_current_head()
    previous = scripts.get_revision(head).down_revision
    stamp(directory=directory, revision=head)
    try:
        downgrade(directory=directory, revision=previous)
        assert 'subscription_price_changes' not in inspect(db.engine).get_table_names()
        upgrade(directory=directory)
        assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == head
        constraints = inspect(db.engine).get_check_constraints('subscription_price_changes')
        assert any(c['name'] == 'ck_subscription_price_changes_expense_amount' for c in constraints)
    finally:
        upgrade(directory=directory)
        db.session.execute(text('DROP TABLE alembic_version'))
        db.session.commit()


def test_actual_dump_restore_preserves_failed_database(app, tmp_path, monkeypatch):
    if db.engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL recovery regression.')
    from deployment import postgres_update_backup as backup
    from deployment import postgres_update_recovery as recovery

    url = db.engine.url
    schema = db.session.execute(text('SELECT current_schema()')).scalar_one()
    db.session.execute(text('CREATE TABLE recovery_probe (id serial PRIMARY KEY, note text)'))
    db.session.execute(text("INSERT INTO recovery_probe(note) VALUES ('before update')"))
    db.session.commit()
    archive = tmp_path / 'database.dump'
    backup.create_backup(url, archive)
    db.session.execute(text("INSERT INTO recovery_probe(note) VALUES ('failed update')"))
    db.session.commit()

    saved = tmp_path / 'saved.env'
    socket_url = URL.create(url.drivername, username=url.username, password=url.password,
                            port=url.port, database=url.database)
    saved.write_text('SECRET_KEY=test-secret\nDATABASE_URL='
                     + socket_url.render_as_string(hide_password=False) + '\n')
    active = tmp_path / 'active.env'
    active.write_text(saved.read_text())
    real_run = subprocess.run

    def run(command, **kwargs):
        # Exercise real PostgreSQL binaries; only replace local OS-user switching
        # and Unix sockets, unavailable on Windows and on CI's container boundary.
        command = command[3:] if command[:3] == ['sudo', '-u', 'postgres'] else command
        command = [part for part in command if not part.startswith('--preserve-env=')]
        command = ['--host=127.0.0.1' if part == '--host=/var/run/postgresql' else part
                   for part in command]
        kwargs['env'] = {**kwargs['env'], 'PGHOST': '127.0.0.1',
                         'PGUSER': url.username, 'PGPASSWORD': url.password or ''}
        return real_run(command, **kwargs)

    monkeypatch.setattr(recovery.subprocess, 'run', run)
    monkeypatch.setitem(sys.modules, 'pwd', SimpleNamespace(
        getpwnam=lambda name: SimpleNamespace(pw_uid=1, pw_gid=1)))
    monkeypatch.setattr(os, 'chown', lambda *args: None, raising=False)
    recovered_url = None
    try:
        recovery.restore_database(saved, archive, active, 'postgres')
        recovered_url = backup.production_url(active).set(host='127.0.0.1')
        with psycopg.connect(
            dbname=recovered_url.database, user=url.username, password=url.password,
            host=url.host, port=url.port,
        ) as connection:
            rows = connection.execute(
                psycopg.sql.SQL('SELECT note FROM {}.recovery_probe ORDER BY id').format(
                    psycopg.sql.Identifier(schema))).fetchall()
            assert rows == [('before update',)]
            next_id = connection.execute(
                psycopg.sql.SQL("INSERT INTO {}.recovery_probe(note) VALUES ('recovered') RETURNING id")
                .format(psycopg.sql.Identifier(schema))).fetchone()[0]
            assert next_id == 2
        assert db.session.execute(text('SELECT count(*) FROM recovery_probe')).scalar_one() == 2
        assert 'SECRET_KEY=test-secret' in active.read_text()
    finally:
        if recovered_url is not None:
            assert recovered_url.database.startswith('joneshq_recovery_')
            with psycopg.connect(
                dbname='postgres', user=url.username, password=url.password,
                host=url.host, port=url.port, autocommit=True,
            ) as connection:
                connection.execute(psycopg.sql.SQL('DROP DATABASE {}').format(
                    psycopg.sql.Identifier(recovered_url.database)))
        db.session.execute(text('DROP TABLE recovery_probe'))
        db.session.commit()
