"""Copy a read-only SQLite snapshot into an EMPTY, disposable PostgreSQL database.

This is rehearsal tooling, not a production cutover command. Never prints data or URLs.
"""
import argparse
from decimal import Decimal, InvalidOperation
from itertools import zip_longest
import os
from pathlib import Path
import sqlite3
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Boolean, Column, MetaData, Numeric, String, Table, create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extensions import db
import models  # noqa: F401 - registers every application table
from models.expense_calendar import ExpenseCalendarEntry  # noqa: F401


BATCH_SIZE = 500


def migration_head():
    config = Config()
    config.set_main_option('script_location', str(ROOT / 'migrations'))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise ValueError('Expected one migration head. Resolve migration branches before rehearsing.')
    return heads[0]


def sqlite_source(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Source must be an existing SQLite snapshot file.')
    uri = path.as_uri() + '?mode=ro'
    return create_engine(
        'sqlite://', creator=lambda: sqlite3.connect(uri, uri=True), poolclass=NullPool)


def ordered_tables(metadata):
    remaining = {table: {
        fk.column.table for fk in table.foreign_keys
        if fk.column.table != table and not fk.use_alter
    } for table in metadata.tables.values()}
    result = []
    while remaining:
        ready = sorted(
            (table for table, dependencies in remaining.items()
             if not dependencies.intersection(remaining)), key=lambda table: table.name)
        if not ready:
            raise ValueError('New foreign-key cycles require a reviewed transfer rule.')
        result.extend(ready)
        for table in ready:
            del remaining[table]
    return result


def source_checks(connection, metadata, head):
    if connection.exec_driver_sql('PRAGMA integrity_check').scalars().all() != ['ok']:
        raise ValueError('SQLite integrity check failed. Do not migrate this snapshot.')
    if connection.exec_driver_sql('PRAGMA foreign_key_check').first() is not None:
        raise ValueError('SQLite contains broken foreign keys. Repair and take a new snapshot.')
    inspector = inspect(connection)
    expected = set(metadata.tables) | {'alembic_version'}
    if set(inspector.get_table_names()) != expected or inspector.get_view_names():
        raise ValueError('Source tables do not match the current application schema.')
    versions = connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalars().all()
    if versions != [head]:
        raise ValueError('Source is not at the current migration head. Upgrade SQLite before taking a snapshot.')
    for table in metadata.tables.values():
        if {column['name'] for column in inspector.get_columns(table.name)} != set(table.c.keys()):
            raise ValueError(f'Source columns do not match the model: {table.name}.')
        for column in table.columns:
            if isinstance(column.type, String) and column.type.length:
                oversized = connection.exec_driver_sql(
                    f'SELECT 1 FROM "{table.name}" WHERE LENGTH("{column.name}") > ? LIMIT 1',
                    (column.type.length,),
                ).first()
                if oversized:
                    raise ValueError(
                        f'Source text exceeds the declared length in {table.name}.{column.name}; '
                        'automatic truncation is refused.')
            if isinstance(column.type, Boolean):
                invalid = connection.exec_driver_sql(
                    f'SELECT 1 FROM "{table.name}" WHERE "{column.name}" NOT IN (0, 1) LIMIT 1'
                ).first()
                if invalid:
                    raise ValueError(f'Invalid SQLite boolean in {table.name}.{column.name}.')
            if isinstance(column.type, Numeric):
                raw = connection.exec_driver_sql(
                    f'SELECT "{column.name}" FROM "{table.name}" WHERE "{column.name}" IS NOT NULL')
                for (value,) in raw:
                    try:
                        number = Decimal(str(value))
                        unit = Decimal(1).scaleb(-column.type.scale)
                        valid = number.is_finite() and number == number.quantize(unit)
                    except (InvalidOperation, TypeError, ValueError):
                        valid = False
                    if not valid:
                        raise ValueError(
                            f'Source precision requires review in {table.name}.{column.name}; '
                            'automatic financial rounding is refused.')
    return {table.name: connection.execute(
        select(db.func.count()).select_from(table)).scalar_one()
        for table in metadata.tables.values()}


def deferred_columns(table):
    columns = [
        column for column in table.columns
        if any(fk.use_alter or fk.column.table == table for fk in column.foreign_keys)
    ]
    if any(not column.nullable for column in columns):
        raise ValueError(f'Required cyclic references need a transfer rule: {table.name}.')
    return columns


def copy_and_verify(source, target, metadata, head):
    """Caller owns both transactions; all target DDL/data must roll back on failure."""
    if inspect(target).get_table_names() or inspect(target).get_view_names():
        raise ValueError('Target is not empty. Use a new disposable rehearsal database.')
    tables = ordered_tables(metadata)
    metadata.create_all(target)
    deferred = []
    for table in tables:
        columns = deferred_columns(table)
        rows = source.execute(select(table).order_by(table.c.id)).mappings()
        while batch := rows.fetchmany(BATCH_SIZE):
            values = []
            for row in batch:
                value = dict(row)
                links = {column.name: value[column.name] for column in columns
                         if value[column.name] is not None}
                if links:
                    # Restoring cyclic links must not rewrite historical updated_at values.
                    links.update({column.name: value[column.name] for column in table.columns
                                  if column.onupdate is not None})
                    deferred.append((table, value['id'], links))
                for column in columns:
                    value[column.name] = None
                values.append(value)
            target.execute(table.insert(), values)
    for table, row_id, links in deferred:
        target.execute(table.update().where(table.c.id == row_id).values(**links))
    # Typed values, not just counts: money, dates, credentials and links must all agree.
    for table in tables:
        original = source.execute(select(table).order_by(table.c.id))
        copied = target.execute(select(table).order_by(table.c.id))
        for left, right in zip_longest(original, copied):
            if left != right:
                raise ValueError(f'Typed row verification failed for {table.name}; target will roll back.')
    if target.dialect.name == 'postgresql':
        for table in tables:
            target.execute(text(
                'SELECT setval(pg_get_serial_sequence(:table_name, :column_name), '
                f'GREATEST(COALESCE(MAX(id), 1), 1), COALESCE(MAX(id), 0) >= 1) FROM "{table.name}"'
            ), {'table_name': table.name, 'column_name': 'id'})
    version = Table('alembic_version', MetaData(),
                    Column('version_num', String(32), primary_key=True))
    version.create(target)
    target.execute(version.insert().values(version_num=head))


def rehearsal_target(url):
    parsed = make_url(url)
    if parsed.drivername != 'postgresql+psycopg':
        raise ValueError('Target must use postgresql+psycopg:// with the installed rehearsal driver.')
    if not parsed.database or not parsed.database.endswith('_rehearsal'):
        raise ValueError('Target database name must end in _rehearsal; production targets are refused.')
    if parsed.query:
        raise ValueError('Rehearsal URLs must not contain query parameters that override connection settings.')
    return parsed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, help='Path to a consistent SQLite backup/snapshot')
    parser.add_argument('--import-to-rehearsal', action='store_true',
                        help='Create schema and copy into PG_REHEARSAL_DATABASE_URL (empty database only)')
    args = parser.parse_args(argv)
    source_engine = target_engine = None
    try:
        source_engine = sqlite_source(args.source)
        head = migration_head()
        with source_engine.connect() as source:
            # sqlite3 otherwise starts no read transaction for SELECT: pin one snapshot.
            source.exec_driver_sql('BEGIN')
            counts = source_checks(source, db.metadata, head)
            print(f'Source checks passed: {len(counts)} application tables; {sum(counts.values())} rows.')
            if not args.import_to_rehearsal:
                print('Validation only. Source unchanged; no target connection opened.')
                return 0
            url = os.environ.get('PG_REHEARSAL_DATABASE_URL')
            if not url:
                raise ValueError('Set PG_REHEARSAL_DATABASE_URL privately before importing.')
            target_engine = create_engine(rehearsal_target(url), hide_parameters=True)
            with target_engine.begin() as target:
                copy_and_verify(source, target, db.metadata, head)
        print('Rehearsal committed: all typed rows verified, sequences reset, migration head recorded.')
        print('Production configuration was NOT changed. Do not switch production yet.')
        return 0
    except (ValueError, OSError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    except (SQLAlchemyError, sqlite3.Error, ImportError) as error:
        # Database exception strings can include financial rows, credentials and URLs.
        print(f'ERROR: Database rehearsal failed ({type(error).__name__}). '
              'No success was recorded; the target transaction was rolled back if opened. '
              'Inspect privately with an operator; no row values are printed.', file=sys.stderr)
        return 1
    finally:
        if target_engine is not None:
            target_engine.dispose()
        if source_engine is not None:
            source_engine.dispose()


if __name__ == '__main__':
    sys.exit(main())
