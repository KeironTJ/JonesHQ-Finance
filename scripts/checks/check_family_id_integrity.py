"""Fail when tenant-owned records are missing a family_id."""
import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app import create_app
from extensions import db


TENANT_TABLES = (
    'accounts', 'balances', 'budgets', 'categories', 'children',
    'child_activity_types', 'daily_childcare_activities',
    'monthly_childcare_summaries', 'childcare_records', 'credit_cards',
    'credit_card_promotions', 'credit_card_transactions', 'expenses',
    'expense_calendar', 'fuel_records', 'income', 'loans', 'loan_payments',
    'monthly_account_balances', 'mortgage_products', 'mortgages',
    'mortgage_snapshots', 'mortgage_payments', 'net_worth', 'pensions',
    'pension_snapshots', 'planned_transactions', 'properties',
    'recurring_income', 'settings', 'tax_settings', 'transactions', 'trips',
    'vehicles', 'vendor_types', 'vendors',
)


def find_missing_family_ids(connection):
    existing_tables = set(inspect(connection).get_table_names())
    missing = {}
    for table in TENANT_TABLES:
        if table not in existing_tables:
            continue
        count = connection.execute(text(
            f'SELECT COUNT(*) FROM "{table}" WHERE family_id IS NULL'
        )).scalar()
        if count:
            missing[table] = count
    return missing


def main():
    app = create_app()
    with app.app_context():
        missing = find_missing_family_ids(db.session.connection())

    if missing:
        print('Records missing family_id:')
        for table, count in sorted(missing.items()):
            print(f'  {table}: {count}')
        return 1

    print('All tenant-owned records have a family_id.')
    return 0


if __name__ == '__main__':
    sys.exit(main())