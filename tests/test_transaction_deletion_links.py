from datetime import date

import pytest
from sqlalchemy import text

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.credit_card_transactions import CreditCardTransaction
from models.credit_cards import CreditCard
from models.expenses import Expense
from models.transactions import Transaction
from services.finance.transaction_service import TransactionService


@pytest.fixture
def scoped(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr(
        'services.finance.transaction_service.PaydayService.get_period_for_date',
        lambda value: value.strftime('%Y-%m'),
    )
    if db.engine.dialect.name == 'sqlite':
        db.session.execute(text('PRAGMA foreign_keys=ON'))
    return family


def _accounts(family):
    first = Account(family_id=family.id, name='Current', account_type='Joint', balance=0, is_active=True)
    second = Account(family_id=family.id, name='Savings', account_type='Savings', balance=0, is_active=True)
    db.session.add_all([first, second])
    db.session.commit()
    return first, second


def _transfer(first, second):
    transactions, _, _ = TransactionService.create_transfer({
        'from_account_id': str(first.id),
        'to_account_id': str(second.id),
        'amount': '75',
        'transaction_date': '2026-03-01',
    })
    return transactions


def test_delete_transaction_removes_both_legs_of_two_way_transfer(scoped):
    first, second = _accounts(scoped)
    outgoing, incoming = _transfer(first, second)

    account_id, _, _, linked_account_id = TransactionService.delete_transaction(incoming.id)

    assert {account_id, linked_account_id} == {first.id, second.id}
    assert db.session.get(Transaction, outgoing.id) is None
    assert db.session.get(Transaction, incoming.id) is None


def test_bulk_delete_removes_unselected_transfer_leg_and_reports_its_account(scoped):
    first, second = _accounts(scoped)
    outgoing, incoming = _transfer(first, second)

    deleted, accounts, cards = TransactionService.bulk_delete([outgoing.id])

    assert deleted == 1
    assert accounts == {first.id, second.id}
    assert cards == set()
    assert db.session.get(Transaction, outgoing.id) is None
    assert db.session.get(Transaction, incoming.id) is None


def test_bulk_delete_handles_both_selected_transfer_legs(scoped):
    first, second = _accounts(scoped)
    outgoing, incoming = _transfer(first, second)

    deleted, accounts, _ = TransactionService.bulk_delete([outgoing.id, incoming.id])

    assert deleted == 2
    assert accounts == {first.id, second.id}
    assert db.session.query(Transaction).count() == 0


@pytest.mark.parametrize('bulk', [False, True])
def test_bank_delete_unlinks_every_household_reference_including_private_rows(
    scoped, user, monkeypatch, bulk
):
    from models import (
        FuelRecord, Income, LoanPayment, MortgageProduct, MortgageSnapshot, PlanItem, User,
    )
    from models.childcare import Child, MonthlyChildcareSummary
    from models.property import Property
    from tests.test_account_deletion import make_domains

    member = User(
        family_id=scoped.id, email='member@example.com', name='Member',
        password_hash=user.password_hash, role='member',
    )
    db.session.add(member)
    db.session.flush()
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)
    shared = make_domains(None, scoped.id, 'Shared')
    private = make_domains(member, scoped.id, 'Private')
    bank_id = shared['transaction'].id
    loan_payment = LoanPayment.query.filter_by(loan_id=private['loan'].id).one()
    loan_payment.bank_transaction_id = bank_id
    private['income'].transaction_id = bank_id
    private['expense'].bank_transaction_id = bank_id
    PlanItem.query.filter_by(plan_id=private['plan'].id).one().transaction_id = bank_id
    FuelRecord.query.filter_by(vehicle_id=private['vehicle'].id).one().linked_transaction_id = bank_id
    payment = private['cc_transaction']
    payment.bank_transaction_id = bank_id
    payment_plan_item = PlanItem(
        family_id=scoped.id, plan_id=private['plan'].id, title='Card payment',
        credit_card_transaction_id=payment.id,
    )
    account = shared['account']
    prop = Property(family_id=scoped.id, address='Home')
    db.session.add(prop)
    db.session.flush()
    product = MortgageProduct(
        family_id=scoped.id, property_id=prop.id, account_id=account.id, lender='Bank',
        product_name='Fixed', start_date=date(2026, 1, 1), end_date=date(2027, 1, 1),
        term_months=12, initial_balance=100, current_balance=100, annual_rate=1,
        monthly_payment=10,
    )
    child = Child(family_id=scoped.id, name='Child', default_account_id=account.id)
    db.session.add_all([payment_plan_item, product, child])
    db.session.flush()
    snapshot = MortgageSnapshot(
        family_id=scoped.id, mortgage_product_id=product.id, transaction_id=bank_id,
        date=date(2026, 1, 1), balance=100, monthly_payment=10, interest_charge=1,
        principal_paid=9,
    )
    summary = MonthlyChildcareSummary(
        family_id=scoped.id, child_id=child.id, year_month='2026-01', total_cost=5,
        transaction_id=bank_id, account_id=account.id,
    )
    db.session.add_all([snapshot, summary])
    db.session.commit()

    if bulk:
        _, _, cards = TransactionService.bulk_delete([bank_id])
    else:
        _, _, card_id, _ = TransactionService.delete_transaction(bank_id)
        cards = {card_id}

    db.session.expire_all()
    assert cards == {private['card'].id}
    assert db.session.get(Transaction, bank_id) is None
    assert db.session.get(CreditCardTransaction, payment.id) is None
    assert db.session.get(PlanItem, payment_plan_item.id).credit_card_transaction_id is None
    assert db.session.get(LoanPayment, loan_payment.id).bank_transaction_id is None
    assert db.session.get(Income, private['income'].id).transaction_id is None
    assert db.session.get(Expense, private['expense'].id).bank_transaction_id is None
    assert PlanItem.query.filter_by(transaction_id=bank_id).count() == 0
    assert FuelRecord.query.filter_by(linked_transaction_id=bank_id).count() == 0
    assert db.session.get(MortgageSnapshot, snapshot.id).transaction_id is None
    assert db.session.get(MonthlyChildcareSummary, summary.id).transaction_id is None


@pytest.mark.parametrize('bulk', [False, True])
def test_bank_delete_keeps_card_expense_link_with_colliding_id(scoped, bulk):
    first, _ = _accounts(scoped)
    category = Category(
        family_id=scoped.id, name='Travel', head_budget='Work',
        sub_budget='Travel', category_type='expense',
    )
    card = CreditCard(
        family_id=scoped.id, card_name='Card', annual_apr=24, monthly_apr=2,
        credit_limit=1000, is_active=True,
    )
    db.session.add_all([category, card])
    db.session.flush()
    bank_txn = Transaction(
        family_id=scoped.id, account_id=first.id, category_id=category.id,
        amount=-20, transaction_date=date(2026, 3, 1),
    )
    db.session.add(bank_txn)
    db.session.flush()
    db.session.execute(CreditCardTransaction.__table__.insert().values(
        id=bank_txn.id, family_id=scoped.id, credit_card_id=card.id,
        date=date(2026, 3, 2), amount=-20, transaction_type='Purchase',
    ))
    expense = Expense(
        family_id=scoped.id, date=date(2026, 3, 2), description='Train',
        expense_type='Travel', cost=20, total_cost=20,
        credit_card_transaction_id=bank_txn.id,
    )
    db.session.add(expense)
    db.session.commit()

    if bulk:
        TransactionService.bulk_delete([bank_txn.id])
    else:
        TransactionService.delete_transaction(bank_txn.id)

    assert db.session.get(Transaction, bank_txn.id) is None
    assert db.session.get(Expense, expense.id).credit_card_transaction_id == bank_txn.id
