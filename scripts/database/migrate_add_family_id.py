"""
Migration: Add family_id to all data tables and stamp existing data.

Run once after the multi-tenancy model changes:
    python scripts/database/migrate_add_family_id.py

What it does:
    1. Ensures family_id = 1 ('Jones HQ') exists in the families table.
    2. Adds the `family_id` column to every data table that doesn't already have it.
    3. Stamps every existing row where family_id IS NULL with family_id = 1.
    4. Prints a summary of how many rows were updated per table.
"""
import sys
import os

# Allow running from any directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app import create_app
from extensions import db
from sqlalchemy import text, inspect

app = create_app()

# ------------------------------------------------------------
# All data tables that should have family_id
# (excludes: users, families, family_invites)
# ------------------------------------------------------------
DATA_TABLES = [
    'accounts',
    'balances',
    'budgets',
    'categories',
    'children',
    'credit_cards',
    'credit_card_transactions',
    'expenses',
    'expense_calendar',
    'fuel_records',
    'income',
    'loans',
    'loan_payments',
    'monthly_account_balances',
    'mortgage_products',
    'mortgages',
    'mortgage_snapshots',
    'mortgage_payments',
    'net_worth',
    'pensions',
    'pension_snapshots',
    'planned_transactions',
    'properties',
    'recurring_income',
    'settings',
    'tax_settings',
    'transactions',
    'trips',
    'vehicles',
    'vendor_types',
    'vendors',
]


def get_existing_tables(conn):
    inspector = inspect(conn)
    return set(inspector.get_table_names())


def column_exists(conn, table, column):
    inspector = inspect(conn)
    cols = [c['name'] for c in inspector.get_columns(table)]
    return column in cols


def add_family_id_column(conn, table):
    """Add family_id column if it doesn't already exist."""
    if not column_exists(conn, table, 'family_id'):
        print(f'  Adding family_id to {table}...', end=' ')
        conn.execute(text(
            f'ALTER TABLE "{table}" ADD COLUMN family_id INTEGER REFERENCES families(id)'
        ))
        print('done')
        return True
    return False


def stamp_rows(conn, table):
    """Set family_id = 1 for all rows where it is NULL."""
    result = conn.execute(text(
        f'UPDATE "{table}" SET family_id = 1 WHERE family_id IS NULL'
    ))
    return result.rowcount


def verify_nulls(conn, table):
    """Return count of rows still missing family_id."""
    result = conn.execute(text(
        f'SELECT COUNT(*) FROM "{table}" WHERE family_id IS NULL'
    ))
    return result.scalar()


def main():
    with app.app_context():
        with db.engine.begin() as conn:
            existing_tables = get_existing_tables(conn)

            # ── 1. Ensure family_id=1 exists ──────────────────────────
            row = conn.execute(text('SELECT id, name FROM families WHERE id = 1')).fetchone()
            if row is None:
                print('ERROR: No family with id=1 found in the families table.')
                print('       Run create_initial_users.py first, or insert a family manually.')
                sys.exit(1)
            print(f'Found family: id={row[0]}, name="{row[1]}"')
            print()

            # ── 2. Add columns ─────────────────────────────────────────
            print('=== Adding family_id columns ===')
            added = 0
            for table in DATA_TABLES:
                if table not in existing_tables:
                    print(f'  SKIP (table not found): {table}')
                    continue
                if add_family_id_column(conn, table):
                    added += 1
            print(f'Added {added} new column(s).\n')

            # ── 3. Stamp existing rows ─────────────────────────────────
            print('=== Stamping existing rows with family_id = 1 ===')
            total_updated = 0
            for table in DATA_TABLES:
                if table not in existing_tables:
                    continue
                if not column_exists(conn, table, 'family_id'):
                    continue
                updated = stamp_rows(conn, table)
                if updated:
                    print(f'  {table}: {updated} row(s) updated')
                    total_updated += updated
            print(f'\nTotal rows stamped: {total_updated}')

            # ── 4. Verify no nulls remain ──────────────────────────────
            print('\n=== Verifying no NULL family_ids remain ===')
            issues = []
            for table in DATA_TABLES:
                if table not in existing_tables:
                    continue
                if not column_exists(conn, table, 'family_id'):
                    continue
                nulls = verify_nulls(conn, table)
                if nulls:
                    issues.append((table, nulls))
                    print(f'  WARNING: {table} still has {nulls} row(s) with NULL family_id')

            if not issues:
                print('  All clear — no NULL family_ids found.')

            print('\nMigration complete.')


if __name__ == '__main__':
    main()
