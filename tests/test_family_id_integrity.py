from sqlalchemy import text

from extensions import db
from models.family import Family
from scripts.checks.check_family_id_integrity import find_missing_family_ids


def test_family_id_integrity_reports_only_tables_with_null_rows(app):
    connection = db_connection(app)
    db.session.add(Family(name='Integrity Test Family'))
    db.session.flush()
    connection.execute(text(
        "INSERT INTO accounts (family_id, name, account_type, balance) "
        "VALUES (NULL, 'Unassigned', 'Current', 0)"
    ))

    assert find_missing_family_ids(connection) == {'accounts': 1}


def test_family_id_integrity_passes_when_no_tenant_rows_are_unassigned(app):
    assert find_missing_family_ids(db_connection(app)) == {}


def db_connection(app):
    return db.session.connection()