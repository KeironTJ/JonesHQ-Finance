from datetime import date
from decimal import Decimal

import pytest

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.settings import Settings
from models.transactions import Transaction
from services.finance.payday_service import PaydayService
from tests.auth_helpers import login_client


def test_year_summary_carries_balances_across_periods(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = Account(family_id=family.id, name='Joint', account_type='Joint', balance=0, is_active=True)
    bills = Category(family_id=family.id, name='Bills', head_budget='Bills', sub_budget='Energy',
                     category_type='expense')
    db.session.add_all([account, bills])
    db.session.flush()
    for when, amount, paid in (
        (date(2025, 12, 1), '1000', True),
        (date(2026, 1, 20), '-300', True),
        (date(2026, 1, 25), '100', False),
        (date(2026, 2, 20), '-50', False),
    ):
        db.session.add(Transaction(
            family_id=family.id, account_id=account.id, category_id=bills.id,
            amount=Decimal(amount), transaction_date=when, is_paid=paid,
        ))
    db.session.commit()

    periods = PaydayService.get_payday_summary_for_year(account.id, 2026)
    january, february = periods[0], periods[1]

    # Payday defaults to the 15th; 15 Feb 2026 is a Sunday so February starts on the 13th.
    assert (january['start_date'], january['end_date']) == (date(2026, 1, 15), date(2026, 2, 12))
    assert january['opening_balance'] == 1000
    assert january['min_balance'] == 700
    assert january['rolling_balance'] == 800
    assert january['max_extra_spend'] == -200
    assert january['category_breakdown']['expenses'][0]['total'] == 300
    assert january['category_breakdown']['income'][0]['total'] == 100

    assert february['opening_balance'] == 800
    assert february['rolling_balance'] == 750
    assert february['min_balance'] == 750


def test_change_payday_rejects_zero_and_out_of_range(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    for bad in ('0', 0, '32', 'abc'):
        with pytest.raises(ValueError, match='between 1 and 31'):
            PaydayService.change_payday_and_reperiod({'new_payday_day': bad})
        db.session.rollback()
    assert Settings.get_value('payday_day') is None


def test_change_payday_saves_day_and_reperiods(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = Account(family_id=family.id, name='Joint', account_type='Joint', balance=0, is_active=True)
    category = Category(family_id=family.id, name='Misc', head_budget='Misc', sub_budget='Misc',
                        category_type='expense')
    db.session.add_all([account, category])
    db.session.flush()
    txn = Transaction(family_id=family.id, account_id=account.id, category_id=category.id, amount=Decimal('-5'),
                      transaction_date=date(2026, 3, 10), payday_period='2026-02')
    db.session.add(txn)
    db.session.commit()

    commits = []
    commit = db.session.commit

    def record_commit():
        commits.append(True)
        commit()

    monkeypatch.setattr(db.session, 'commit', record_commit)
    updated, day = PaydayService.change_payday_and_reperiod({'new_payday_day': '1'})

    assert len(commits) == 1
    assert (updated, day) == (1, 1)
    assert Settings.get_value('payday_day') == 1
    assert db.session.get(Transaction, txn.id).payday_period == '2026-03'


def test_reperiod_covers_private_records_but_not_other_households(app, family, user, monkeypatch):
    from models.family import Family
    from models.users import User

    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)
    member = User(email='member@example.com', name='Member', family_id=family.id, role='member')
    member.set_password('TestPass1!')
    other_family = Family(name='Other household')
    db.session.add_all([member, other_family])
    db.session.flush()

    private_account = Account(family_id=family.id, owner_id=member.id, name='Private', account_type='Joint',
                              balance=0, is_active=True)
    other_account = Account(family_id=other_family.id, name='Other', account_type='Joint', balance=0,
                            is_active=True)
    db.session.add_all([private_account, other_account])
    db.session.flush()
    category = Category(family_id=family.id, name='Misc', head_budget='Misc', sub_budget='Misc',
                        category_type='expense')
    other_category = Category(family_id=other_family.id, name='Misc', head_budget='Misc', sub_budget='Misc',
                              category_type='expense')
    db.session.add_all([category, other_category])
    db.session.flush()
    private_txn = Transaction(family_id=family.id, account_id=private_account.id, category_id=category.id,
                              amount=Decimal('-5'), transaction_date=date(2026, 3, 10), payday_period='2026-02')
    other_txn = Transaction(family_id=other_family.id, account_id=other_account.id,
                            category_id=other_category.id, amount=Decimal('-5'),
                            transaction_date=date(2026, 3, 10), payday_period='2026-02')
    db.session.add_all([private_txn, other_txn])
    db.session.commit()

    updated, _ = PaydayService.change_payday_and_reperiod({'new_payday_day': '1'})

    assert updated == 1
    assert db.session.get(Transaction, private_txn.id).payday_period == '2026-03'
    assert db.session.get(Transaction, other_txn.id).payday_period == '2026-02'


def test_reperiod_requires_household(app, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: None)
    with pytest.raises(ValueError):
        PaydayService.reperiod_all_transactions()


def test_settings_payday_change_reperiods_transactions(app, family, monkeypatch):
    from services.platform.settings_service import SettingsService
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = Account(family_id=family.id, name='Joint', account_type='Joint', balance=0, is_active=True)
    category = Category(family_id=family.id, name='Misc', head_budget='Misc', sub_budget='Misc',
                        category_type='expense')
    db.session.add_all([account, category])
    db.session.flush()
    txn = Transaction(family_id=family.id, account_id=account.id, category_id=category.id,
                      amount=Decimal('-5'), transaction_date=date(2026, 3, 10), payday_period='2026-02')
    db.session.add(txn)
    db.session.commit()

    SettingsService.update_section('household', {'payday_day': '1'})

    assert db.session.get(Transaction, txn.id).payday_period == '2026-03'


def test_legacy_zero_payday_is_treated_as_last_day(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    Settings.set_value('payday_day', 0, setting_type='int')
    db.session.commit()

    # 30 April 2026 is a Thursday.
    assert PaydayService.get_payday_for_month(2026, 4) == date(2026, 4, 30)


@pytest.mark.parametrize('day', [-1, 32])
def test_invalid_stored_payday_is_reported(app, family, monkeypatch, day):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    Settings.set_value('payday_day', day, setting_type='int')
    db.session.commit()

    with pytest.raises(ValueError, match='between 1 and 31'):
        PaydayService.get_payday_setting()


@pytest.mark.parametrize('role,can_edit', [('admin', True), ('member', False)])
def test_recurring_income_payday_controls_match_owner_access(app, user, role, can_edit):
    user.role = role
    user.allowed_sections = '["income"]'
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)

    response = client.get('/income/recurring')

    assert response.status_code == 200
    assert ('/income/reperiod-transactions' in response.get_data(as_text=True)) is can_edit


def test_member_cannot_change_household_payday_through_income(app, user):
    user.role = 'member'
    user.allowed_sections = '["income"]'
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)

    response = client.post('/income/reperiod-transactions', data={'new_payday_day': '1'})

    assert response.status_code == 403
