"""
Remove all transactions that were linked to `Expense` rows (bank and credit card transactions),
clear the corresponding link columns on `Expense`, and recalculate affected balances.

Usage:
    python scripts/maintenance/clear_expense_linked_transactions.py --yes

Warning: This will permanently delete rows from `transactions` and `credit_card_transactions`.
Make a DB backup before running if you're unsure.
"""

import sys
from app import create_app
from extensions import db

app = create_app()

with app.app_context():
    from models.expenses import Expense
    from models.transactions import Transaction
    from models.credit_card_transactions import CreditCardTransaction

    args = sys.argv[1:]
    force = '--yes' in args or '-y' in args

    # Find all expenses that have links
    linked_expenses = Expense.query.filter(
        (Expense.bank_transaction_id != None) | (Expense.credit_card_transaction_id != None)
    ).all()

    if not linked_expenses:
        print('No linked expenses found. Nothing to do.')
        sys.exit(0)

    print(f'Found {len(linked_expenses)} expenses with linked transactions.')

    if not force:
        confirm = input('This will DELETE linked transactions and clear links on the Expense rows. Continue? (yes/no): ')
        if confirm.lower() not in ('y', 'yes'):
            print('Aborted.')
            sys.exit(1)

    bank_txn_ids = set()
    cc_txn_ids = set()
    accounts_to_recalc = set()
    cards_to_recalc = set()

    for exp in linked_expenses:
        if exp.bank_transaction_id:
            bank_txn_ids.add(exp.bank_transaction_id)
        if exp.credit_card_transaction_id:
            cc_txn_ids.add(exp.credit_card_transaction_id)

    # Inspect and collect affected accounts and cards
    if bank_txn_ids:
        txns = Transaction.query.filter(Transaction.id.in_(list(bank_txn_ids))).all()
        for t in txns:
            if t.account_id:
                accounts_to_recalc.add(t.account_id)

    if cc_txn_ids:
        ccs = CreditCardTransaction.query.filter(CreditCardTransaction.id.in_(list(cc_txn_ids))).all()
        for c in ccs:
            if c.credit_card_id:
                cards_to_recalc.add(c.credit_card_id)

    print(f'Will delete {len(bank_txn_ids)} bank transaction(s) and {len(cc_txn_ids)} credit-card transaction(s).')
    print(f'Affected accounts: {sorted(list(accounts_to_recalc))}')
    print(f'Affected cards: {sorted(list(cards_to_recalc))}')

    # Delete credit card transactions
    if cc_txn_ids:
        CreditCardTransaction.query.filter(CreditCardTransaction.id.in_(list(cc_txn_ids))).delete(synchronize_session=False)
        db.session.commit()
        print(f'Deleted {len(cc_txn_ids)} credit card transaction(s).')

    # Delete bank transactions
    if bank_txn_ids:
        Transaction.query.filter(Transaction.id.in_(list(bank_txn_ids))).delete(synchronize_session=False)
        db.session.commit()
        print(f'Deleted {len(bank_txn_ids)} bank transaction(s).')

    # Clear expense links
    for exp in linked_expenses:
        changed = False
        if exp.bank_transaction_id:
            exp.bank_transaction_id = None
            changed = True
        if exp.credit_card_transaction_id:
            exp.credit_card_transaction_id = None
            changed = True
        if changed:
            db.session.add(exp)
    db.session.commit()
    print('Cleared links on Expense rows.')

    # Recalculate balances
    from models.transactions import Transaction as TxnModel
    from models.credit_card_transactions import CreditCardTransaction as CCTModel

    for account_id in accounts_to_recalc:
        if account_id:
            TxnModel.recalculate_account_balance(account_id)
            print(f'Recalculated balance for account {account_id}')

    for card_id in cards_to_recalc:
        if card_id:
            CCTModel.recalculate_card_balance(card_id)
            print(f'Recalculated balance for credit card {card_id}')

    print('Done.')
