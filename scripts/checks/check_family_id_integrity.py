"""Fail when tenant-owned records are missing a family_id."""
import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app import create_app
from extensions import db


# Tables where a NULL family_id is valid: users and security events can exist
# outside a household, and NULL tax settings are the shared global defaults.
NULL_FAMILY_ALLOWED = frozenset({'users', 'security_events', 'tax_settings'})


def tenant_tables():
    import models  # noqa: F401 - register every model on db.metadata
    return sorted(
        table.name for table in db.metadata.sorted_tables
        if 'family_id' in table.c and table.name not in NULL_FAMILY_ALLOWED
    )


def find_missing_family_ids(connection):
    existing_tables = set(inspect(connection).get_table_names())
    missing = {}
    for table in tenant_tables():
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