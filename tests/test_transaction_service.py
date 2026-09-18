from datetime import date
from decimal import Decimal

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.transactions import Transaction
from models.expenses import Expense
from services.finance.transaction_service import TransactionService


def test_create_recurring_transactions_assigns_family_and_derives_fields(
    app, family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr(
        'services.finance.transaction_service.PaydayService.get_period_for_date',
        lambda value: value.strftime('%Y-%m'),
    )
    account = Account(
        family_id=family.id,
        name='Current',
        account_type='Joint',
        balance=0,
        is_active=True,
    )
    category = Category(
        family_id=family.id,
        name='Bills',
        head_budget='Home',
        sub_budget='Bills',
        category_type='expense',
    )
    db.session.add_all([account, category])
    db.session.commit()

    transactions = TransactionService.create_transactions({
        'account_id': str(account.id),
        'category_id': str(category.id),
        'vendor_id': '',
        'amount': '-25.50',
        'transaction_date': '2026-01-31',
        'description': 'Subscription',
        'item': 'Monthly plan',
        'assigned_to': 'Household',
        'payment_type': 'Direct Debit',
        'is_paid': '1',
        'is_recurring': 'on',
        'frequency': 'monthly',
        'occurrences': '2',
        'adjust_working_days': 'on',
        'weekend_adjustment': 'previous',
        'year_month': '',
        'week_year': '',
        'day_name': '',
        'payday_period_override': '',
    })

    assert len(transactions) == 2
    assert [transaction.transaction_date for transaction in transactions] == [
        date(2026, 1, 30), date(2026, 2, 27)
    ]
    assert transactions[0].family_id == family.id
    assert transactions[0].year_month == '2026-01'
    assert transactions[0].day_name == 'Fri'
    assert transactions[0].payday_period == '2026-01'
    assert transactions[0].amount == Decimal('-25.50')
    assert Transaction.query.count() == 2


def test_update_transaction_syncs_linked_transfer(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr(
        'services.finance.transaction_service.PaydayService.get_period_for_date',
        lambda value: value.strftime('%Y-%m'),
    )
    from_account = Account(
        family_id=family.id, name='From', account_type='Joint', balance=0, is_active=True
    )
    to_account = Account(
        family_id=family.id, name='To', account_type='Savings', balance=0, is_active=True
    )
    category = Category(
        family_id=family.id,
        name='Transfer',
        head_budget='Transfer',
        sub_budget='Transfer',
        category_type='transfer',
    )
    db.session.add_all([from_account, to_account, category])
    db.session.flush()
    outgoing = Transaction(
        family_id=family.id,
        account_id=from_account.id,
        category_id=category.id,
        amount=-100,
        transaction_date=date(2026, 1, 1),
        description='Transfer to To',
    )
    incoming = Transaction(
        family_id=family.id,
        account_id=to_account.id,
        category_id=category.id,
        amount=100,
        transaction_date=date(2026, 1, 1),
        description='Transfer from From',
    )
    db.session.add_all([outgoing, incoming])
    db.session.flush()
    outgoing.linked_transaction_id = incoming.id
    db.session.commit()

    updated, old_account_id, linked_account_id = TransactionService.update_transaction(
        outgoing.id,
        {
            'account_id': str(from_account.id),
            'category_id': str(category.id),
            'vendor_id': '',
            'amount': '-125',
            'transaction_date': '2026-02-15',
            'description': 'Updated transfer',
            'item': 'Savings move',
            'assigned_to': '',
            'payment_type': 'Transfer',
            'is_paid': '1',
            'txn_fixed': '1',
            'year_month': '',
            'week_year': '',
            'day_name': '',
            'payday_period_override': '',
        },
    )

    assert old_account_id == from_account.id
    assert linked_account_id == to_account.id
    assert updated.amount == Decimal('-125')
    assert updated.is_fixed is True
    assert incoming.amount == Decimal('125')
    assert incoming.transaction_date == date(2026, 2, 15)
    assert incoming.is_paid is True
    assert incoming.description == 'Transfer from From'


def test_delete_transaction_removes_transfer_and_clears_expense_link(
    app, family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = Account(
        family_id=family.id, name='Current', account_type='Joint', balance=0, is_active=True
    )
    category = Category(
        family_id=family.id,
        name='Expense',
        head_budget='Work',
        sub_budget='Travel',
        category_type='expense',
    )
    db.session.add_all([account, category])
    db.session.flush()
    transaction = Transaction(
        family_id=family.id,
        account_id=account.id,
        category_id=category.id,
        amount=-50,
        transaction_date=date(2026, 1, 10),
    )
    linked = Transaction(
        family_id=family.id,
        account_id=account.id,
        category_id=category.id,
        amount=50,
        transaction_date=date(2026, 1, 10),
    )
    db.session.add_all([transaction, linked])
    db.session.flush()
    transaction.linked_transaction_id = linked.id
    expense = Expense(
        family_id=family.id,
        date=date(2026, 1, 10),
        description='Work travel',
        expense_type='Travel',
        cost=50,
        total_cost=50,
        bank_transaction_id=transaction.id,
    )
    db.session.add(expense)
    db.session.commit()

    account_id, account_name, linked_card_id, linked_transfer_account_id = (
        TransactionService.delete_transaction(transaction.id)
    )

    assert account_id == account.id
    assert account_name == 'Current'
    assert linked_card_id is None
    assert linked_transfer_account_id == account.id
    assert db.session.get(Transaction, transaction.id) is None
    assert db.session.get(Transaction, linked.id) is None
    assert db.session.get(Expense, expense.id).bank_transaction_id is None


def test_toggle_paid_syncs_linked_transfer_and_expense(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = Account(
        family_id=family.id, name='Current', account_type='Joint', balance=0, is_active=True
    )
    category = Category(
        family_id=family.id,
        name='Expense',
        head_budget='Work',
        sub_budget='Travel',
        category_type='expense',
    )
    db.session.add_all([account, category])
    db.session.flush()
    transaction = Transaction(
        family_id=family.id,
        account_id=account.id,
        category_id=category.id,
        amount=-50,
        transaction_date=date(2026, 1, 10),
        is_paid=False,
    )
    linked = Transaction(
        family_id=family.id,
        account_id=account.id,
        category_id=category.id,
        amount=50,
        transaction_date=date(2026, 1, 10),
        is_paid=False,
    )
    db.session.add_all([transaction, linked])
    db.session.flush()
    transaction.linked_transaction_id = linked.id
    expense = Expense(
        family_id=family.id,
        date=date(2026, 1, 10),
        description='Work travel',
        expense_type='Travel',
        cost=50,
        total_cost=50,
        bank_transaction_id=transaction.id,
        paid_for=False,
    )
    db.session.add(expense)
    db.session.commit()

    updated = TransactionService.toggle_paid(transaction.id)

    assert updated.is_paid is True
    assert linked.is_paid is True
    assert expense.paid_for is True


def test_create_transfer_creates_linked_family_scoped_transactions(
    app, family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr(
        'services.finance.transaction_service.PaydayService.get_period_for_date',
        lambda value: value.strftime('%Y-%m'),
    )
    from_account = Account(
        family_id=family.id, name='Current', account_type='Joint', balance=0, is_active=True
    )
    to_account = Account(
        family_id=family.id, name='Savings', account_type='Savings', balance=0, is_active=True
    )
    db.session.add_all([from_account, to_account])
    db.session.commit()

    transactions, created_from, created_to = TransactionService.create_transfer({
        'from_account_id': str(from_account.id),
        'to_account_id': str(to_account.id),
        'amount': '250',
        'transaction_date': '2026-01-15',
        'description': 'Monthly saving',
        'category_id': '',
        'is_paid': '1',
        'is_recurring': 'on',
        'frequency': 'monthly',
        'occurrences': '2',
    })

    assert created_from.id == from_account.id
    assert created_to.id == to_account.id
    assert len(transactions) == 4
    assert transactions[0].family_id == family.id
    assert transactions[0].amount == Decimal('-250')
    assert transactions[1].amount == Decimal('250')
    assert transactions[0].linked_transaction_id == transactions[1].id
    assert transactions[1].linked_transaction_id == transactions[0].id


def test_bulk_edit_updates_transactions_and_linked_amounts(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = Account(
        family_id=family.id, name='Current', account_type='Joint', balance=0, is_active=True
    )
    category = Category(
        family_id=family.id,
        name='Transfer',
        head_budget='Transfer',
        sub_budget='Transfer',
        category_type='transfer',
    )
    db.session.add_all([account, category])
    db.session.flush()
    first = Transaction(
        family_id=family.id, account_id=account.id, category_id=category.id,
        amount=-100, transaction_date=date(2026, 1, 1), is_paid=False,
    )
    second = Transaction(
        family_id=family.id, account_id=account.id, category_id=category.id,
        amount=100, transaction_date=date(2026, 1, 1), is_paid=False,
    )
    db.session.add_all([first, second])
    db.session.flush()
    first.linked_transaction_id = second.id
    db.session.commit()

    updated, affected_accounts = TransactionService.bulk_edit(
        [first.id],
        {
            'bulk_category_id': str(category.id),
            'bulk_vendor_id': '',
            'bulk_payment_type': 'Transfer',
            'bulk_assigned_to': '',
            'bulk_is_paid': '1',
            'bulk_amount_operation': 'set',
            'bulk_amount_value': '-125',
        },
    )

    assert updated == 1
    assert account.id in affected_accounts
    assert first.amount == Decimal('-125')
    assert second.amount == Decimal('125')
    assert first.is_paid is True
    assert second.is_paid is True


def test_bulk_delete_clears_expenses_and_reports_affected_accounts(
    app, family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = Account(
        family_id=family.id, name='Current', account_type='Joint', balance=0, is_active=True
    )
    category = Category(
        family_id=family.id, name='Expense', head_budget='Work',
        sub_budget='Travel', category_type='expense'
    )
    db.session.add_all([account, category])
    db.session.flush()
    transaction = Transaction(
        family_id=family.id, account_id=account.id, category_id=category.id,
        amount=-40, transaction_date=date(2026, 1, 1)
    )
    db.session.add(transaction)
    db.session.flush()
    expense = Expense(
        family_id=family.id, date=date(2026, 1, 1), description='Travel',
        expense_type='Travel', cost=40, total_cost=40,
        bank_transaction_id=transaction.id
    )
    db.session.add(expense)
    db.session.commit()

    deleted, accounts, cards = TransactionService.bulk_delete([transaction.id])

    assert deleted == 1
    assert account.id in accounts
    assert cards == set()
    assert db.session.get(Transaction, transaction.id) is None
    assert db.session.get(Expense, expense.id).bank_transaction_id is None
