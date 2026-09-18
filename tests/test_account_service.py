from datetime import date
from decimal import Decimal

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.transactions import Transaction
from services.account_service import AccountService


def test_create_account_assigns_current_family(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('services.account_service.get_family_id', lambda: family.id)

    account = AccountService.create_account('Current', 'Joint', 100, True)

    assert account.family_id == family.id
    assert db.session.get(Account, account.id).family_id == family.id


def test_get_overview_calculates_paid_balances_and_groups_accounts(
    app, family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)

    active_account = Account(
        family_id=family.id,
        name='Current',
        account_type='Joint',
        balance=0,
        is_active=True,
    )
    inactive_account = Account(
        family_id=family.id,
        name='Old',
        account_type='Savings',
        balance=0,
        is_active=False,
    )
    category = Category(
        family_id=family.id,
        name='Salary',
        head_budget='Income',
        sub_budget='Salary',
        category_type='income',
    )
    db.session.add_all([active_account, inactive_account, category])
    db.session.flush()
    db.session.add(
        Transaction(
            family_id=family.id,
            account_id=active_account.id,
            category_id=category.id,
            amount=Decimal('125.50'),
            transaction_date=date(2026, 1, 15),
            is_paid=True,
        )
    )
    db.session.commit()

    overview = AccountService.get_overview()

    assert overview['active_accounts'] == [active_account]
    assert overview['inactive_accounts'] == [inactive_account]
    assert overview['accounts_by_type']['Joint'] == [active_account]
    assert overview['type_totals']['Joint'] == 125.5
    assert overview['total_balance'] == 125.5
    assert active_account.calculated_balance == 125.5


def test_update_and_delete_account(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = Account(
        family_id=family.id,
        name='Old name',
        account_type='Joint',
        balance=0,
        is_active=True,
    )
    db.session.add(account)
    db.session.commit()

    updated = AccountService.update_account(account.id, 'New name', 'Savings', 42, False)
    deleted_name = AccountService.delete_account(account.id)

    assert updated.name == 'New name'
    assert updated.account_type == 'Savings'
    assert float(updated.balance) == 42
    assert updated.is_active is False
    assert deleted_name == 'New name'
    assert db.session.get(Account, account.id) is None
