"""Household isolation tests.

Household B's rows all share one primary key (``FOREIGN_ID``) across every
household-scoped table, so any route parameter or submitted ``*_id`` field set to
that value points at one of B's records whatever model the route expects. Signed
in as household A, every route is exercised with that ID and B's data must be
neither revealed nor changed.
"""
import re
from datetime import date, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.family import Family
from models.monthly_account_balance import MonthlyAccountBalance
from models.transactions import Transaction
from models.users import User
from tests.auth_helpers import login_client
from utils.tenancy_guard import CrossFamilyReferenceError, find_cross_family_references

FOREIGN_ID = 900001
MARKER = 'ZZBSECRET'
NAME_COLUMNS = {
    'name', 'description', 'notes', 'title', 'card_name', 'registration', 'lender',
    'product_name', 'provider', 'item', 'make', 'model', 'label', 'reference',
}
ID_FIELDS = (
    'id', 'account_id', 'category_id', 'vendor_id', 'credit_card_id', 'card_id', 'loan_id',
    'vehicle_id', 'pension_id', 'plan_id', 'plan_item_id', 'item_id', 'child_id',
    'subscription_id', 'income_id', 'recurring_income_id', 'expense_id', 'transaction_id',
    'deposit_account_id', 'default_payment_account_id', 'fuel_account_id', 'property_id',
    'mortgage_id', 'mortgage_product_id', 'reimbursement_group_id', 'activity_type_id',
    'default_account_id', 'default_category_id', 'parent_id', 'group_id', 'member_id',
)
SKIP_ENDPOINT_PREFIXES = ('static', 'admin.', 'auth.', 'onboarding.')
# Satisfy table CHECK constraints the generic seeder cannot infer.
TABLE_OVERRIDES = {
    'subscriptions': {'amount': Decimal('-1'), 'account_id': FOREIGN_ID, 'credit_card_id': None},
}


def _value_for(column):
    column_type = column.type
    if isinstance(column_type, sa.Enum):
        return column_type.enums[0]
    if isinstance(column_type, sa.Boolean):
        return False
    if isinstance(column_type, sa.DateTime):
        return datetime(2026, 1, 15, 12, 0)
    if isinstance(column_type, sa.Date):
        return date(2026, 1, 15)
    if isinstance(column_type, sa.Numeric):
        return Decimal('1')
    if isinstance(column_type, (sa.Integer, sa.Float)):
        return 1
    if isinstance(column_type, (sa.String, sa.Text)):
        length = getattr(column_type, 'length', None)
        return MARKER[:length] if length else MARKER
    return None


def _seed_foreign_household():
    """Insert one row with id FOREIGN_ID into every household-scoped table for household B."""
    family_b = Family(name=f'{MARKER} Household')
    db.session.add(family_b)
    db.session.commit()
    inserted = set()
    for table in db.metadata.sorted_tables:
        if 'family_id' not in table.c or 'id' not in table.c:
            continue
        values = {'id': FOREIGN_ID, 'family_id': family_b.id}
        for column in table.c:
            if column.name in values:
                continue
            foreign_keys = list(column.foreign_keys)
            if foreign_keys:
                target = foreign_keys[0].column.table.name
                if column.name == 'owner_id' or column.nullable or target not in inserted:
                    values[column.name] = None if column.nullable else FOREIGN_ID
                else:
                    values[column.name] = FOREIGN_ID
                continue
            if column.name == 'email':
                values[column.name] = 'other-household@example.com'
            elif not column.nullable and column.default is None and column.server_default is None:
                values[column.name] = _value_for(column)
            elif column.name in NAME_COLUMNS and isinstance(column.type, (sa.String, sa.Text)):
                values[column.name] = _value_for(column)
        values.update(TABLE_OVERRIDES.get(table.name, {}))
        db.session.execute(table.insert().values(**values))
        inserted.add(table.name)
    db.session.commit()
    return family_b.id, inserted


def _snapshot(family_id, tables):
    snapshot = {}
    for table in db.metadata.sorted_tables:
        if table.name in tables:
            rows = db.session.execute(
                select(table).where(table.c.family_id == family_id).order_by(table.c.id)
            ).mappings().all()
            snapshot[table.name] = [dict(row) for row in rows]
    return snapshot


def _id_routes(app):
    for rule in app.url_map.iter_rules():
        if rule.endpoint.startswith(SKIP_ENDPOINT_PREFIXES):
            continue
        int_args = [arg for arg, conv in rule._converters.items() if conv.__class__.__name__ == 'IntegerConverter']
        if not int_args or any(arg not in int_args for arg in rule.arguments):
            continue
        path = rule.rule
        for arg in int_args:
            path = re.sub(rf'<int:{arg}>', str(FOREIGN_ID), path)
        yield rule, path


def _all_simple_routes(app):
    for rule in app.url_map.iter_rules():
        if rule.endpoint.startswith(SKIP_ENDPOINT_PREFIXES) or rule.arguments:
            continue
        yield rule, rule.rule


@pytest.fixture
def two_households(app, family, user):
    family_b_id, tables = _seed_foreign_household()
    return {'user_id': user.id, 'family_a_id': family.id, 'family_b_id': family_b_id, 'tables': tables}


def _request(client, method, path, user_id, query=None, form=None):
    login_client(client, user_id)
    try:
        if method == 'GET':
            return client.get(path, query_string=query)
        return client.post(path, data=form or {})
    except Exception:  # noqa: BLE001 - a crash is not a leak; data checks below still apply
        db.session.rollback()
        return None


def test_other_household_records_cannot_be_read_or_changed_through_any_route(app, two_households):
    user_id = two_households['user_id']
    family_b_id = two_households['family_b_id']
    tables = two_households['tables']
    before = _snapshot(family_b_id, tables)
    injected_ids = {field: str(FOREIGN_ID) for field in ID_FIELDS}
    client = app.test_client()

    leaks = []
    for rule, path in list(_id_routes(app)) + list(_all_simple_routes(app)):
        if 'GET' in rule.methods:
            response = _request(client, 'GET', path, user_id, query=injected_ids)
            if response is not None and response.status_code == 200 and MARKER.encode() in response.data:
                leaks.append(f'GET {path}')
    for rule, path in list(_id_routes(app)) + list(_all_simple_routes(app)):
        if 'POST' in rule.methods:
            response = _request(client, 'POST', path, user_id, form=injected_ids)
            if response is not None and MARKER.encode() in response.data:
                leaks.append(f'POST {path}')

    db.session.rollback()
    db.session.expire_all()
    assert not leaks, f'Other household data appeared in responses: {leaks}'
    assert _snapshot(family_b_id, tables) == before, 'Other household data was changed'
    assert find_cross_family_references(db) == {}


def _account(family_id, name):
    account = Account(family_id=family_id, name=name, account_type='Joint', balance=0, is_active=True)
    db.session.add(account)
    db.session.flush()
    return account


def _category(family_id, name):
    category = Category(
        family_id=family_id, name=name, head_budget=name, sub_budget=name, category_type='expense'
    )
    db.session.add(category)
    db.session.flush()
    return category


def test_guard_blocks_creating_record_that_points_at_other_household(app, family):
    family_b = Family(name='B')
    db.session.add(family_b)
    db.session.flush()
    foreign_account = _account(family_b.id, 'B account')
    db.session.commit()

    db.session.add(Transaction(
        family_id=family.id, account_id=foreign_account.id, amount=Decimal('-1'),
        category_id=_category(family.id, 'A cat').id, transaction_date=date(2026, 1, 1),
    ))
    with pytest.raises(CrossFamilyReferenceError):
        db.session.commit()
    db.session.rollback()


def test_guard_blocks_repointing_existing_record_at_other_household(app, family):
    family_b = Family(name='B')
    db.session.add(family_b)
    db.session.flush()
    own_account = _account(family.id, 'A account')
    foreign_category = _category(family_b.id, 'B cat')
    txn = Transaction(
        family_id=family.id, account_id=own_account.id, amount=Decimal('-1'),
        category_id=_category(family.id, 'A cat').id, transaction_date=date(2026, 1, 1),
    )
    db.session.add(txn)
    db.session.commit()

    txn.category_id = foreign_category.id
    with pytest.raises(CrossFamilyReferenceError):
        db.session.commit()
    db.session.rollback()


def test_guard_allows_same_household_references(app, family):
    account = _account(family.id, 'A account')
    txn = Transaction(
        family_id=family.id, account_id=account.id, amount=Decimal('-1'),
        category_id=_category(family.id, 'A cat').id, transaction_date=date(2026, 1, 1),
    )
    db.session.add(txn)
    db.session.commit()
    txn.amount = Decimal('-2')
    db.session.commit()
    assert db.session.get(Transaction, txn.id).amount == Decimal('-2')


def test_tenancy_scan_reports_existing_cross_household_rows(app, family):
    family_b = Family(name='B')
    db.session.add(family_b)
    db.session.flush()
    foreign_account = _account(family_b.id, 'B account')
    db.session.commit()
    db.session.execute(Transaction.__table__.insert().values(
        family_id=family.id, account_id=foreign_account.id, amount=Decimal('-1'),
        category_id=_category(family.id, 'A cat').id, transaction_date=date(2026, 1, 1), is_paid=False,
    ))
    db.session.commit()

    assert find_cross_family_references(db) == {'transactions.account_id': 1}


def test_check_tenancy_cli_reports_clean_database(app, family):
    result = app.test_cli_runner().invoke(args=['maintenance', 'check-tenancy'])
    assert result.exit_code == 0
    assert 'no cross-household references' in result.output


def test_dashboard_ignores_other_household_account_id(app, family, user, monkeypatch):
    from services.analytics.dashboard_service import DashboardService

    family_b = Family(name='B')
    db.session.add(family_b)
    db.session.flush()
    own_account = _account(family.id, 'A account')
    foreign_account = _account(family_b.id, 'B account')
    db.session.add(Transaction(
        family_id=family_b.id, account_id=foreign_account.id, amount=Decimal('12345'),
        category_id=_category(family_b.id, 'B cat').id,
        transaction_date=date(2026, 3, 1), is_paid=True,
    ))
    db.session.commit()
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)

    data = DashboardService.get_dashboard_data(foreign_account.id, 2026)

    assert data['selected_account'].id == own_account.id
    balances = [period['rolling_balance'] for period in data.get('payday_data', [])]
    assert Decimal('12345') not in balances


def test_payday_summary_excludes_other_household_transactions(app, family, monkeypatch):
    from services.finance.payday_service import PaydayService

    family_b = Family(name='B')
    db.session.add(family_b)
    db.session.flush()
    foreign_account = _account(family_b.id, 'B account')
    db.session.add(Transaction(
        family_id=family_b.id, account_id=foreign_account.id, amount=Decimal('12345'),
        category_id=_category(family_b.id, 'B cat').id,
        transaction_date=date(2026, 3, 1), is_paid=True,
    ))
    db.session.commit()
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)

    periods = PaydayService.get_payday_summary_for_year(foreign_account.id, 2026)

    assert all(period['rolling_balance'] == 0 for period in periods)


def test_cache_rebuild_keeps_other_household_cache(app, family, user, monkeypatch):
    from services.finance.monthly_balance_service import MonthlyBalanceService

    family_b = Family(name='B')
    db.session.add(family_b)
    db.session.flush()
    _account(family.id, 'A account')
    foreign_account = _account(family_b.id, 'B account')
    db.session.add(MonthlyAccountBalance(
        family_id=family_b.id, account_id=foreign_account.id, year_month='2026-01',
        actual_balance=5, projected_balance=5,
    ))
    db.session.commit()
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)

    MonthlyBalanceService.rebuild_all_cache(future_months=12)

    remaining = db.session.execute(
        select(MonthlyAccountBalance).where(MonthlyAccountBalance.family_id == family_b.id)
    ).scalars().all()
    assert len(remaining) == 1


def test_route_blocked_by_guard_rolls_back_and_redirects_with_message(app, family, user):
    from models.vendors import Vendor

    family_b = Family(name='B')
    db.session.add(family_b)
    db.session.flush()
    foreign_category = _category(family_b.id, 'B cat')
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)

    response = client.post('/vendors/add', data={
        'name': 'Corner shop', 'default_category_id': str(foreign_category.id),
    }, headers={'Referer': 'https://evil.example/phish'})

    assert response.status_code == 302
    assert 'evil' not in response.headers['Location']
    assert db.session.execute(select(Vendor).where(Vendor.name == 'Corner shop')).first() is None
    with client.session_transaction() as flask_session:
        messages = [message for _, message in flask_session.get('_flashes', [])]
    assert 'That selection is not available in your household.' in messages
