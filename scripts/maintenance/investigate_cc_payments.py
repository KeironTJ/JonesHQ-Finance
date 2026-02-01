"""
Investigate credit card payment transactions
Find all transactions that might be CC payments
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import create_app
from extensions import db
from models.transactions import Transaction
from models.credit_cards import CreditCard


def investigate_cc_payments():
    """Find all transactions that might be CC payments"""
    app = create_app()
    
    with app.app_context():
        print("\n" + "=" * 70)
        print("CREDIT CARD PAYMENT TRANSACTIONS INVESTIGATION")
        print("=" * 70)
        
        # 1. Transactions linked to credit cards
        print("\n1. Transactions with credit_card_id:")
        cc_linked = Transaction.query.filter(
            Transaction.credit_card_id.isnot(None)
        ).all()
        print(f"   Found: {len(cc_linked)}")
        for txn in cc_linked[:10]:  # Show first 10
            print(f"   - ID {txn.id}: £{txn.amount:>8.2f} | {txn.description} | Account: {txn.account_id}")
        if len(cc_linked) > 10:
            print(f"   ... and {len(cc_linked) - 10} more")
        
        # 2. Transactions with 'Card Payment' type
        print("\n2. Transactions with payment_type='Card Payment':")
        card_payment_type = Transaction.query.filter(
            Transaction.payment_type == 'Card Payment'
        ).all()
        print(f"   Found: {len(card_payment_type)}")
        for txn in card_payment_type[:10]:
            print(f"   - ID {txn.id}: £{txn.amount:>8.2f} | {txn.description} | Account: {txn.account_id}")
        if len(card_payment_type) > 10:
            print(f"   ... and {len(card_payment_type) - 10} more")
        
        # 3. Transactions containing "credit card" in description
        print("\n3. Transactions with 'credit card' in description:")
        cc_desc = Transaction.query.filter(
            Transaction.description.ilike('%credit card%')
        ).all()
        print(f"   Found: {len(cc_desc)}")
        positive_count = sum(1 for txn in cc_desc if txn.amount > 0)
        negative_count = sum(1 for txn in cc_desc if txn.amount < 0)
        print(f"   - Positive (credits): {positive_count}")
        print(f"   - Negative (debits): {negative_count}")
        for txn in cc_desc[:10]:
            sign = "+" if txn.amount > 0 else "-"
            print(f"   - ID {txn.id}: {sign}£{abs(txn.amount):>8.2f} | {txn.description}")
        if len(cc_desc) > 10:
            print(f"   ... and {len(cc_desc) - 10} more")
        
        # 4. Transactions containing "Payment to" in description
        print("\n4. Transactions with 'Payment to' in description:")
        payment_to = Transaction.query.filter(
            Transaction.description.ilike('%payment to%')
        ).all()
        print(f"   Found: {len(payment_to)}")
        positive_count = sum(1 for txn in payment_to if txn.amount > 0)
        negative_count = sum(1 for txn in payment_to if txn.amount < 0)
        print(f"   - Positive (credits): {positive_count}")
        print(f"   - Negative (debits): {negative_count}")
        for txn in payment_to[:10]:
            sign = "+" if txn.amount > 0 else "-"
            print(f"   - ID {txn.id}: {sign}£{abs(txn.amount):>8.2f} | {txn.description}")
        if len(payment_to) > 10:
            print(f"   ... and {len(payment_to) - 10} more")
        
        # 5. Get all credit card names to search for
        print("\n5. Searching for transactions matching credit card names:")
        cards = CreditCard.query.all()
        for card in cards:
            matching = Transaction.query.filter(
                Transaction.description.ilike(f'%{card.card_name}%')
            ).all()
            if matching:
                positive_count = sum(1 for txn in matching if txn.amount > 0)
                negative_count = sum(1 for txn in matching if txn.amount < 0)
                print(f"\n   {card.card_name}:")
                print(f"   - Total: {len(matching)} | Positive: {positive_count} | Negative: {negative_count}")
                for txn in matching[:5]:
                    sign = "+" if txn.amount > 0 else "-"
                    print(f"     * ID {txn.id}: {sign}£{abs(txn.amount):>8.2f} | {txn.description}")
        
        print("\n" + "=" * 70)


if __name__ == '__main__':
    investigate_cc_payments()
