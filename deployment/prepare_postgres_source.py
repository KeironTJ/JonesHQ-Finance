"""Report reviewed legacy issues, optionally preparing a NEW SQLite migration copy."""
import argparse
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
import os
from pathlib import Path
import re
import sqlite3
import sys

from sqlalchemy import Numeric
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deployment import rehearse_postgres as rehearsal


REVIEWED_NUMERICS = frozenset((
    'credit_card_transactions.amount',
    'fuel_records.mpg', 'fuel_records.price_per_mile',
    'income.income_tax', 'income.national_insurance', 'income.take_home',
    'loans.monthly_apr', 'mortgage_snapshots.interest_rate',
    'pension_snapshots.value', 'pension_snapshots.growth_percent',
    'pensions.projected_value_at_retirement',
    'property_valuation_snapshots.change_percent',
    'trips.approx_mpg', 'trips.gallons_used', 'trips.cumulative_gallons', 'trips.trip_cost',
))


def plan_changes(connection):
    changes = []
    broken = connection.execute('PRAGMA foreign_key_check').fetchall()
    category_fk = next(
        row[0] for row in connection.execute('PRAGMA foreign_key_list(credit_card_transactions)')
        if row[2:5] == ('categories', 'category_id', 'id')
    )
    if any(table != 'credit_card_transactions' or parent != 'categories' or fk != category_fk
           for table, _, parent, fk in broken):
        raise ValueError('Unreviewed foreign-key violations; no copy can be prepared.')
    orphans = connection.execute("""
        SELECT t.id FROM credit_card_transactions t
        WHERE t.category_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM categories c WHERE c.id = t.category_id)
    """).fetchall()
    if len(orphans) != len(broken):
        raise ValueError('Unexpected category foreign-key coverage.')
    if orphans:
        # Do not silently discard a recoverable mapping or guess across households.
        matches = connection.execute("""
            SELECT 1 FROM credit_card_transactions t
            JOIN categories c ON c.family_id = t.family_id
              AND c.head_budget = t.head_budget
              AND COALESCE(c.sub_budget, '') = COALESCE(t.sub_budget, '')
            WHERE t.category_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM categories x WHERE x.id = t.category_id)
            LIMIT 1
        """).fetchone()
        if matches:
            raise ValueError('Orphan categories have possible label matches; review before clearing.')
        changes.append(('credit_card_transactions', 'category_id',
                        [(None, row_id) for (row_id,) in orphans], Decimal(0), Decimal(0)))

    weeks = []
    for row_id, week in connection.execute("""
        SELECT id, week FROM credit_card_transactions WHERE LENGTH(week) > 7
    """):
        if not re.fullmatch(r'\d{4}-W\d{2}', week):
            raise ValueError('Unreviewed oversized card week label.')
        year, number = int(week[:4]), int(week[-2:])
        date.fromisocalendar(year, number, 1)
        weeks.append((f'{number:02d}-{year:04d}', row_id))
    if weeks:
        changes.append(('credit_card_transactions', 'week', weeks, Decimal(0), Decimal(0)))

    for table in rehearsal.db.metadata.tables.values():
        for column in table.columns:
            if not isinstance(column.type, Numeric):
                continue
            unit = Decimal(1).scaleb(-column.type.scale)
            limit = Decimal(10) ** (column.type.precision - column.type.scale)
            updates, maximum, total_delta = [], Decimal(0), Decimal(0)
            for row_id, value in connection.execute(
                f'SELECT id, "{column.name}" FROM "{table.name}" '
                f'WHERE "{column.name}" IS NOT NULL'
            ):
                number = Decimal(str(value))
                if not number.is_finite():
                    raise ValueError(f'Invalid numeric value: {table.name}.{column.name}.')
                rounded = number.quantize(unit, rounding=ROUND_HALF_EVEN)
                if abs(rounded) >= limit:
                    raise ValueError(f'Numeric capacity exceeded: {table.name}.{column.name}.')
                if rounded != number:
                    key = f'{table.name}.{column.name}'
                    if key not in REVIEWED_NUMERICS:
                        raise ValueError(f'Unreviewed excess precision: {key}.')
                    updates.append((str(rounded), row_id))
                    delta = rounded - number
                    maximum = max(maximum, abs(delta))
                    total_delta += delta
            if updates:
                changes.append((table.name, column.name, updates, maximum, total_delta))
    return changes


def report(changes):
    print('column | changed cells | maximum absolute rounding | signed rounding total')
    for table, column, updates, maximum, total_delta in changes:
        print(f'{table}.{column} | {len(updates)} | {maximum} | {total_delta}')
    print('Category/week changes have zero rounding deltas. No individual records printed.')


def prepare(source, output=None):
    source = Path(source).resolve(strict=True)
    engine = rehearsal.sqlite_source(source)
    connection = None
    try:
        connection = engine.connect()
        connection.exec_driver_sql('BEGIN')
        rehearsal.source_schema_checks(connection, rehearsal.db.metadata, rehearsal.migration_head())
        original = connection.connection.driver_connection
        if original.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Source integrity check failed.')
        changes = plan_changes(original)
        report(changes)
        if output is None:
            print('Report only. Source unchanged; no output created.')
            return

        output = Path(output).absolute()
        if output.resolve() == source:
            raise ValueError('Output must not be the source.')
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        complete = False
        try:
            copy = sqlite3.connect(output)
            try:
                original.backup(copy)
                copy.execute('PRAGMA foreign_keys=ON')
                with copy:
                    for table, column, updates, _, _ in changes:
                        copy.executemany(
                            f'UPDATE "{table}" SET "{column}" = ? WHERE id = ?', updates)
            finally:
                copy.close()
            prepared = rehearsal.sqlite_source(output)
            try:
                with prepared.connect() as verified:
                    verified.exec_driver_sql('BEGIN')
                    counts = rehearsal.source_checks(
                        verified, rehearsal.db.metadata, rehearsal.migration_head())
            finally:
                prepared.dispose()
            complete = True
            print(f'Prepared and validated: {len(counts)} tables; {sum(counts.values())} rows.')
            print('Original source unchanged. No PostgreSQL connection or production switch made.')
        finally:
            if not complete:
                output.unlink()
    finally:
        if connection is not None:
            connection.close()
        engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--apply-reviewed-policy', action='store_true')
    args = parser.parse_args(argv)
    if bool(args.output) != args.apply_reviewed_policy:
        parser.error('--output and --apply-reviewed-policy must be supplied together.')
    try:
        prepare(args.source, args.output)
        return 0
    except ValueError as error:
        print(f'ERROR: {error} Source unchanged; preparation did not succeed.', file=sys.stderr)
        return 1
    except (OSError, ArithmeticError, StopIteration, sqlite3.Error, SQLAlchemyError):
        print('ERROR: Source preparation failed. No successful output was recorded. '
              'Check the current migration head, source schema, reviewed data policy and '
              'unused writable output path. Source values were not changed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
