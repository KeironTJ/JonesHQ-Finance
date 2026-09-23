from datetime import date
from decimal import Decimal

from extensions import db
from models.loan_payments import LoanPayment
from models.loans import Loan
from models.accounts import Account
from models.categories import Category
from models.transactions import Transaction
from services.planning.loan_service import LoanService


def test_create_loan_assigns_family_and_generates_schedule(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)

    loan, payments = LoanService.create_loan({
        'name': 'Test Loan',
        'loan_value': '1000.00',
        'current_balance': '1000.00',
        'annual_apr': '12.00',
        'monthly_payment': '100.00',
        'start_date': '2026-01-15',
        'term_months': '12',
        'default_payment_account_id': '',
        'weekend_adjustment': 'none',
        'is_active': 'on',
    })

    assert loan.family_id == family.id
    assert loan.end_date.isoformat() == '2027-01-15'
    assert loan.monthly_apr == Decimal('1.00')
    assert payments
    assert payments[0].period == 0
    assert LoanPayment.query.filter_by(loan_id=loan.id).count() == len(payments)
    assert db.session.get(Loan, loan.id).current_balance <= Decimal('1000.00')


def test_loan_payment_mutations_sync_and_delete_bank_transactions(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = Account(
        family_id=family.id, name='Loan Account', account_type='Joint',
        balance=0, is_active=True
    )
    category = Category(
        family_id=family.id, name='Loan Payment', head_budget='Loans',
        sub_budget='Payment', category_type='expense'
    )
    db.session.add_all([account, category])
    db.session.flush()
    loan = Loan(
        family_id=family.id, name='Test Loan', loan_value=1000,
        principal=1000, current_balance=1000, annual_apr=12,
        monthly_apr=1, monthly_payment=100, start_date=date(2026, 1, 1),
        end_date=date(2027, 1, 1), term_months=12
    )
    db.session.add(loan)
    db.session.flush()
    bank_transaction = Transaction(
        family_id=family.id, account_id=account.id, category_id=category.id,
        amount=Decimal('-100'), transaction_date=date(2026, 1, 15),
        is_paid=False
    )
    db.session.add(bank_transaction)
    db.session.flush()
    payment = LoanPayment(
        family_id=family.id, loan_id=loan.id, date=date(2026, 1, 15),
        year_month='2026-01', period=1, opening_balance=1000,
        payment_amount=100, interest_charge=10, amount_paid_off=90,
        closing_balance=910, is_paid=False,
        bank_transaction_id=bank_transaction.id,
    )
    db.session.add(payment)
    db.session.commit()

    updated, account_id = LoanService.toggle_payment_paid(payment.id)
    deleted_account_id = LoanService.delete_payment(payment.id)

    assert updated.is_paid is True
    assert account_id == account.id
    assert deleted_account_id == account.id
    assert db.session.get(LoanPayment, payment.id) is None
    assert db.session.get(Transaction, bank_transaction.id) is None


def test_update_loan_payment_syncs_bank_transaction(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = Account(
        family_id=family.id, name='Loan Account', account_type='Joint',
        balance=0, is_active=True
    )
    category = Category(
        family_id=family.id, name='Loan Payment', head_budget='Loans',
        sub_budget='Payment', category_type='expense'
    )
    db.session.add_all([account, category])
    db.session.flush()
    loan = Loan(
        family_id=family.id, name='Editable Loan', loan_value=1000,
        principal=1000, current_balance=1000, annual_apr=12,
        monthly_apr=1, monthly_payment=100, start_date=date(2026, 1, 1),
        end_date=date(2027, 1, 1), term_months=12
    )
    db.session.add(loan)
    db.session.flush()
    bank_transaction = Transaction(
        family_id=family.id, account_id=account.id, category_id=category.id,
        amount=Decimal('-100'), transaction_date=date(2026, 1, 15)
    )
    db.session.add(bank_transaction)
    db.session.flush()
    payment = LoanPayment(
        family_id=family.id, loan_id=loan.id, date=date(2026, 1, 15),
        year_month='2026-01', period=1, opening_balance=1000,
        payment_amount=100, interest_charge=10, amount_paid_off=90,
        closing_balance=910, bank_transaction_id=bank_transaction.id,
    )
    db.session.add(payment)
    db.session.commit()

    updated, account_id = LoanService.update_payment(payment.id, {
        'payment_date': '2026-02-15',
        'payment_amount': '120',
        'interest_charge': '10',
        'amount_paid_off': '110',
    })

    assert account_id == account.id
    assert updated.payment_amount == Decimal('120')
    assert updated.closing_balance == Decimal('890')
    assert bank_transaction.transaction_date == date(2026, 2, 15)
    assert bank_transaction.amount == Decimal('-120')
    assert bank_transaction.description == 'Loan Payment - Editable Loan'


def test_private_loan_and_payments_hidden_but_shared_transaction_stays_visible(
    app, family, monkeypatch, user
):
    """Private hides the Loan and its payment schedule, but a payment transaction
    posted to a shared account still appears there for the whole family."""
    from utils.db_helpers import family_query

    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)

    account = Account(
        family_id=family.id, name='Joint', account_type='Joint',
        balance=0, is_active=True,
    )
    category = Category(
        family_id=family.id, name='Loan Payment', head_budget='Loans',
        sub_budget='Payment', category_type='expense',
    )
    db.session.add_all([account, category])
    db.session.flush()

    loan, _ = LoanService.create_loan({
        'name': 'Private Loan',
        'loan_value': '1000.00',
        'current_balance': '1000.00',
        'annual_apr': '12.00',
        'monthly_payment': '100.00',
        'start_date': '2026-01-15',
        'term_months': '12',
        'default_payment_account_id': '',
        'weekend_adjustment': 'none',
        'is_active': 'on',
        'visibility': 'private',
    })

    assert loan.owner_id == user.id
    assert loan.is_private is True
    assert account.owner_id is None  # the account itself stays shared

    bank_transaction = Transaction(
        family_id=family.id, account_id=account.id, category_id=category.id,
        amount=Decimal('-100'), transaction_date=date(2026, 2, 15),
    )
    db.session.add(bank_transaction)
    db.session.flush()
    payment = LoanPayment(
        family_id=family.id, loan_id=loan.id, date=date(2026, 2, 15),
        year_month='2026-02', period=1, opening_balance=1000,
        payment_amount=100, interest_charge=10, amount_paid_off=90,
        closing_balance=910, bank_transaction_id=bank_transaction.id,
    )
    db.session.add(payment)
    db.session.commit()

    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id + 999)

    # Loan and its payment schedule are hidden from other family members...
    assert loan not in family_query(Loan).all()
    assert payment not in family_query(LoanPayment).all()
    # ...but the payment transaction remains visible in the shared account.
    assert bank_transaction in family_query(Transaction).all()


def test_create_loan_with_default_account_generates_transactions_and_category(
    app, family, monkeypatch
):
    """Regression test: creating a loan with a default_payment_account_id must
    auto-generate bank transactions and a properly-named, family-scoped
    'Loans' category, without relying on a logged-in request context."""
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = Account(
        family_id=family.id, name='Joint', account_type='Joint',
        balance=0, is_active=True,
    )
    db.session.add(account)
    db.session.flush()

    loan, payments = LoanService.create_loan({
        'name': 'New Car Loan',
        'loan_value': '1000.00',
        'current_balance': '1000.00',
        'annual_apr': '12.00',
        'monthly_payment': '100.00',
        'start_date': '2026-01-15',
        'term_months': '12',
        'default_payment_account_id': str(account.id),
        'weekend_adjustment': 'none',
        'is_active': 'on',
    })

    category = Category.query.filter_by(head_budget='Loans', sub_budget='New Car Loan').one()
    assert category.name == 'New Car Loan'
    assert category.family_id == family.id

    period_1_payments = [p for p in payments if p.period > 0]
    assert period_1_payments
    for payment in period_1_payments:
        assert payment.family_id == family.id
        assert payment.bank_transaction_id is not None
        txn = db.session.get(Transaction, payment.bank_transaction_id)
        assert txn.family_id == family.id
