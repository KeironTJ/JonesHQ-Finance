"""
Consolidated Transaction View
Combines transactions from all sources: bank accounts, credit cards, loans, etc.
"""
from flask import render_template, request
from datetime import datetime
from blueprints.transactions import transactions_bp as bp
from models.transactions import Transaction
from models.credit_card_transactions import CreditCardTransaction
from models.loan_payments import LoanPayment
from models.accounts import Account
from models.credit_cards import CreditCard
from models.loans import Loan
from models.categories import Category


@bp.route('/transactions/consolidated')
def consolidated():
    """Consolidated view of all transactions across all sources"""
    
    # Get filter parameters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    category_id = request.args.get('category_id', type=int)
    source = request.args.get('source')  # 'bank', 'credit_card', 'loan', 'all'
    
    # Build unified transaction list
    consolidated_transactions = []
    
    # 1. Bank Account Transactions
    if not source or source == 'all' or source == 'bank':
        bank_txns = Transaction.query
        
        if start_date:
            bank_txns = bank_txns.filter(Transaction.transaction_date >= datetime.strptime(start_date, '%Y-%m-%d').date())
        if end_date:
            bank_txns = bank_txns.filter(Transaction.transaction_date <= datetime.strptime(end_date, '%Y-%m-%d').date())
        if category_id:
            bank_txns = bank_txns.filter(Transaction.category_id == category_id)
        
        for txn in bank_txns.all():
            consolidated_transactions.append({
                'id': f'bank_{txn.id}',
                'source': 'Bank Account',
                'source_type': 'bank',
                'source_name': txn.account.name if txn.account else 'Unknown',
                'date': txn.transaction_date,
                'description': txn.description,
                'category': f"{txn.category.head_budget} > {txn.category.sub_budget}" if txn.category else '',
                'amount': float(txn.amount),
                'balance': float(txn.balance) if txn.balance else None,
                'vendor': txn.vendor.name if txn.vendor else '',
                'type': 'Income' if txn.amount > 0 else 'Expense'
            })
    
    # 2. Credit Card Transactions
    if not source or source == 'all' or source == 'credit_card':
        cc_txns = CreditCardTransaction.query
        
        if start_date:
            cc_txns = cc_txns.filter(CreditCardTransaction.date >= datetime.strptime(start_date, '%Y-%m-%d').date())
        if end_date:
            cc_txns = cc_txns.filter(CreditCardTransaction.date <= datetime.strptime(end_date, '%Y-%m-%d').date())
        if category_id:
            cc_txns = cc_txns.filter(CreditCardTransaction.category_id == category_id)
        
        for txn in cc_txns.all():
            consolidated_transactions.append({
                'id': f'cc_{txn.id}',
                'source': 'Credit Card',
                'source_type': 'credit_card',
                'source_name': txn.credit_card.card_name if txn.credit_card else 'Unknown',
                'date': txn.date,
                'description': txn.item,
                'category': f"{txn.head_budget} > {txn.sub_budget}" if txn.head_budget else '',
                'amount': float(txn.amount),
                'balance': float(txn.balance) if txn.balance else None,
                'vendor': '',
                'type': txn.transaction_type
            })
    
    # 3. Loan Payments
    if not source or source == 'all' or source == 'loan':
        loan_txns = LoanPayment.query
        
        if start_date:
            loan_txns = loan_txns.filter(LoanPayment.payment_date >= datetime.strptime(start_date, '%Y-%m-%d').date())
        if end_date:
            loan_txns = loan_txns.filter(LoanPayment.payment_date <= datetime.strptime(end_date, '%Y-%m-%d').date())
        
        for txn in loan_txns.all():
            consolidated_transactions.append({
                'id': f'loan_{txn.id}',
                'source': 'Loan',
                'source_type': 'loan',
                'source_name': txn.loan.loan_name if txn.loan else 'Unknown',
                'date': txn.payment_date,
                'description': f"Payment (Principal: £{txn.principal_payment:.2f}, Interest: £{txn.interest_payment:.2f})",
                'category': 'Loans > Payment',
                'amount': float(txn.payment_amount),
                'balance': float(txn.remaining_balance) if txn.remaining_balance else None,
                'vendor': '',
                'type': 'Loan Payment'
            })
    
    # Sort by date descending
    consolidated_transactions.sort(key=lambda x: x['date'], reverse=True)
    
    # Calculate totals
    total_inflows = sum([t['amount'] for t in consolidated_transactions if t['amount'] > 0])
    total_outflows = sum([abs(t['amount']) for t in consolidated_transactions if t['amount'] < 0])
    net_position = total_inflows - total_outflows
    
    # Get filter options
    accounts = Account.query.order_by(Account.name).all()
    credit_cards = CreditCard.query.order_by(CreditCard.card_name).all()
    loans = Loan.query.order_by(Loan.loan_name).all()
    categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
    
    return render_template('transactions/consolidated.html',
                         transactions=consolidated_transactions,
                         total_inflows=total_inflows,
                         total_outflows=total_outflows,
                         net_position=net_position,
                         accounts=accounts,
                         credit_cards=credit_cards,
                         loans=loans,
                         categories=categories,
                         selected_source=source,
                         selected_category=category_id,
                         start_date=start_date,
                         end_date=end_date)
