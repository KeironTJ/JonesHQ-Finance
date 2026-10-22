from datetime import date
from decimal import Decimal

import pytest

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.credit_card_transactions import CreditCardTransaction
from models.credit_cards import CreditCard
from models.family import Family
from models.transactions import Transaction


def _category(family_id):
    category = Category(family_id=family_id, name='Misc', head_budget='Misc', sub_budget='Misc',
                        category_type='expense')
    db.session.add(category)
    db.session.flush()
    return category


def _card(family_id):
    card = CreditCard(family_id=family_id, card_name='Card', annual_apr=Decimal('24'),
                      monthly_apr=Decimal('2'), credit_limit=Decimal('1000'), current_balance=Decimal('0'),
                      min_payment_percent=Decimal('2'), set_payment=Decimal('50'), statement_date=15,
                      is_active=True)
    db.session.add(card)
    db.session.flush()
    return card


@pytest.fixture
def households(app, family):
    other = Family(name='Other household')
    db.session.add(other)
    db.session.flush()
    account = Account(family_id=family.id, name='Main', account_type='Joint', balance=0, is_active=True)
    db.session.add(account)
    db.session.flush()
    own_category, other_category = _category(family.id), _category(other.id)
    card = _card(family.id)
    db.session.add_all([
        Transaction(family_id=family.id, account_id=account.id, category_id=own_category.id,
                    amount=Decimal('-10'), transaction_date=date(2026, 1, 1)),
        CreditCardTransaction(family_id=family.id, credit_card_id=card.id, date=date(2026, 1, 1),
                              transaction_type='Purchase', amount=Decimal('-20'), is_paid=True),
    ])
    db.session.commit()
    # Simulate legacy corrupt rows; the ORM write guard would reject these.
    db.session.execute(Transaction.__table__.insert().values(
        family_id=other.id, account_id=account.id, category_id=other_category.id,
        amount=Decimal('-500'), transaction_date=date(2026, 1, 2), is_paid=False))
    db.session.execute(CreditCardTransaction.__table__.insert().values(
        family_id=other.id, credit_card_id=card.id, date=date(2026, 1, 2),
        transaction_type='Purchase', amount=Decimal('-500'), is_paid=True))
    db.session.commit()
    return family, other, account, card


@pytest.mark.parametrize('in_request', [True, False])
def test_recalculation_ignores_rows_from_other_households(households, monkeypatch, in_request):
    family, _, account, card = households
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id if in_request else None)

    Transaction.recalculate_account_balance(account.id)
    CreditCardTransaction.recalculate_card_balance(card.id)
    db.session.commit()

    assert db.session.get(Account, account.id).balance == Decimal('-10')
    assert db.session.get(CreditCard, card.id).current_balance == Decimal('-20')


def test_recalculation_rejects_foreign_household_ids(households, monkeypatch):
    _, other, account, card = households
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: other.id)

    Transaction.recalculate_account_balance(account.id)
    CreditCardTransaction.recalculate_card_balance(card.id)
    db.session.commit()

    assert db.session.get(Account, account.id).balance == Decimal('0')
    assert db.session.get(CreditCard, card.id).current_balance == Decimal('0')
