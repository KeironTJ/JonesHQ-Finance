"""
Credit Card Service
===================
Business logic for credit card statement generation, interest calculation,
payment automation, and payment/bank-transaction synchronisation.

Balance sign convention
-----------------------
All credit card transaction amounts use the following convention:

  - Negative  → money owed to the card issuer (debt increases)
  - Positive  → payment or credit (debt decreases)

Interest transactions are stored as **negative** amounts (they add to what you owe).
Payment transactions are stored as **positive** amounts (they reduce what you owe).
The matching bank transaction is stored as **negative** (money leaving the bank account).

Statement chain
---------------
Each monthly statement creates up to three linked records:

  1. CreditCardTransaction (transaction_type='Interest')
       — the statement itself; amount is negative or zero.
  2. CreditCardTransaction (transaction_type='Payment', statement_id=<interest.id>)
       — the scheduled repayment; only created when statement balance < 0.
  3. Transaction (linked via cc_payment.bank_transaction_id)
       — the matching bank-account debit; only created when the card has a
         ``default_payment_account_id``.

Deleting a statement always walks the full chain (Interest → Payment → Bank txn).
Regeneration replaces unlocked chains (is_fixed=False) while leaving locked ones
(is_fixed=True) untouched.

``commit`` parameter
--------------------
Most write methods accept a ``commit`` flag (default True).  Pass ``commit=False``
when calling from within a loop to batch changes; the caller is then responsible
for calling ``db.session.commit()`` and any required balance recalculations.

Primary entry points (called from blueprints)
---------------------------------------------
  regenerate_future_transactions()       — delete + recreate future chains for one card
  regenerate_all_future_transactions()   — same for all active cards
  generate_all_monthly_statements()      — bulk-generate statements across a date range
  delete_non_fixed_future_transactions() — delete all unlocked future chains
  sync_bank_transaction_to_payment()     — called when a bank transaction is edited
  sync_payment_to_bank_transaction()     — called when a CC payment transaction is edited
  unlink_payment_and_transaction()       — called before either linked record is deleted
"""
import logging
from datetime import datetime, date, timedelta
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from models.credit_cards import CreditCard, CreditCardPromotion
from models.credit_card_transactions import CreditCardTransaction
from models.categories import Category
from models.transactions import Transaction
from models.vendors import Vendor
from services.payday_service import PaydayService
from extensions import db
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


class CreditCardService:
    
    @staticmethod
    def generate_monthly_statement(card_id, statement_date, payment_offset_days=14, commit=True):
        """
        Generate one month's statement for a card: interest charge + optional payment.

        Steps:
          1. Sum all CC transactions up to the day before ``statement_date`` to get the
             opening balance.
          2. If opening balance < 0 (debt exists), create an Interest transaction on
             ``statement_date``.  The transaction is always created — even when the APR
             is 0% (promotional) so the statement date is recorded.
          3. Re-sum all transactions up to ``statement_date`` (now including interest) to
             get the statement balance.
          4. If statement balance < 0, schedule a Payment transaction
             ``payment_offset_days`` later, linked to the Interest transaction.
          5. If statement balance >= 0, no payment is needed (card is paid off).

        Args:
            card_id:              ID of the CreditCard to process.
            statement_date:       Date the statement is issued (uses card.statement_date day).
            payment_offset_days:  Days after statement date to schedule the payment (default 14).
            commit:               Whether to commit all changes to the DB (default True).

        Returns:
            dict with keys:
              'interest_txn'     — CreditCardTransaction created, or None
              'payment_txn'      — CreditCardTransaction created, or None
              'statement_balance'— float; the balance after interest (negative = still in debt)

        Side effects:
            Creates CreditCardTransaction records (Interest and/or Payment).
            If the card has a default_payment_account_id, also creates a linked
            bank Transaction for the payment amount.
            Calls recalculate_card_balance() after each phase.
        """
        card = family_get(CreditCard, card_id)
        if not card or not card.is_active:
            return {'interest_txn': None, 'payment_txn': None, 'statement_balance': 0}
        
        result = {
            'interest_txn': None,
            'payment_txn': None,
            'statement_balance': 0
        }
        
        # Get balance BEFORE statement (including ALL transactions up to day before statement)
        # Interest should be charged on the projected balance, not just paid transactions
        day_before_statement = statement_date - timedelta(days=1)
        transactions_before_statement = family_query(CreditCardTransaction).filter(
            CreditCardTransaction.credit_card_id == card_id,
            CreditCardTransaction.date <= day_before_statement
        ).order_by(CreditCardTransaction.date).all()
        
        opening_balance = Decimal('0.0')
        for t in transactions_before_statement:
            opening_balance += Decimal(str(t.amount))
        opening_balance = float(opening_balance)
        
        # Step 1: Generate interest transaction only if you OWE money (negative balance)
        if opening_balance < 0:
            interest_txn = CreditCardService.generate_statement_interest(
                card_id, 
                statement_date, 
                balance_for_interest=opening_balance,
                commit=False
            )
            if interest_txn:
                result['interest_txn'] = interest_txn
                db.session.flush()  # Make sure it's in the database for recalculation
        
        # Step 2: Calculate statement balance (including the interest just generated)
        # We need to calculate the PROJECTED balance including all transactions up to statement date
        CreditCardTransaction.recalculate_card_balance(card_id)
        
        # Get projected balance by summing ALL transactions up to statement date
        transactions_up_to_statement = family_query(CreditCardTransaction).filter(
            CreditCardTransaction.credit_card_id == card_id,
            CreditCardTransaction.date <= statement_date
        ).order_by(CreditCardTransaction.date).all()
        
        statement_balance = Decimal('0.0')
        for t in transactions_up_to_statement:
            statement_balance += Decimal(str(t.amount))
        
        statement_balance = float(statement_balance)
        result['statement_balance'] = statement_balance
        
        # Step 3: Create payment only if you OWE money (negative balance)
        if statement_balance < 0:
            payment_date = statement_date + timedelta(days=payment_offset_days)
            # Pass the statement (interest) transaction id so the payment is linked back to it
            interest_id = result['interest_txn'].id if result['interest_txn'] else None
            payment_txn = CreditCardService.generate_payment_transaction(
                card_id, 
                payment_date,
                balance_override=statement_balance,  # Use the statement balance including interest
                statement_id=interest_id,
                commit=False
            )
            if payment_txn:
                result['payment_txn'] = payment_txn
                db.session.flush()
        
        # Step 4: Final recalculation to include payment
        if result['payment_txn']:
            CreditCardTransaction.recalculate_card_balance(card_id)
        
        # Commit all changes if requested
        if commit:
            db.session.commit()
        
        return result
    
    @staticmethod
    def calculate_interest(card_id, statement_date, balance_to_use=None):
        """
        Calculate the monthly interest charge for a card on a given statement date.

        Uses the card's APR for that date (respects 0% promotional periods).
        Interest is always returned as a positive number; the caller is responsible
        for negating it when storing as a transaction.

        Args:
            card_id:        ID of the CreditCard.
            statement_date: Date used to look up the applicable APR.
            balance_to_use: Balance to charge interest on.  If None, uses
                            card.current_balance.  Should be the absolute
                            balance (sign is ignored via abs()).

        Returns:
            float — interest amount, rounded to 2 decimal places.
            Returns 0.0 if the card is not found or the APR is 0%.
        """
        card = family_get(CreditCard, card_id)
        if not card:
            return 0.0
        
        # Get APR for this date (considers 0% offers)
        monthly_apr = card.get_current_purchase_apr(statement_date)
        
        # If 0%, return 0
        if monthly_apr == 0:
            return 0.0
        
        # Use provided balance or card's current balance
        if balance_to_use is not None:
            balance = balance_to_use
        else:
            balance = float(card.current_balance)
        
        # Calculate interest on balance (use absolute value since negative = owe)
        interest = abs(balance) * (monthly_apr / 100)
        return round(interest, 2)
    
    @staticmethod
    def generate_statement_interest(card_id, statement_date, balance_for_interest=None, commit=True):
        """
        Create an Interest CreditCardTransaction for a card on its statement date.

        Always creates a transaction, even when the calculated interest is £0 (e.g.
        during a 0% promotional period) so that the statement date is recorded in the
        chain.  Only call this method when the opening balance is negative (debt exists);
        the guard lives in generate_monthly_statement.

        The category "Credit Cards > {CardName}" is created automatically if it does
        not already exist.

        Args:
            card_id:              ID of the CreditCard.
            statement_date:       Date the interest is charged.
            balance_for_interest: Balance to calculate interest on (negative = debt).
                                  If None, uses card.current_balance.
            commit:               Whether to commit and recalculate balances (default True).

        Returns:
            CreditCardTransaction — the newly created Interest transaction.
            None if the card is not found or inactive.

        Side effects:
            Adds a CreditCardTransaction to the session.
            May add a Category if one does not exist for this card.
            If commit=True, commits and calls recalculate_card_balance().
        """
        card = family_get(CreditCard, card_id)
        if not card or not card.is_active:
            return None
        
        # Calculate interest (could be £0 if 0% promotional period)
        # Interest is negative (increases what you owe), calculated on abs(balance)
        interest_amount = CreditCardService.calculate_interest(
            card_id, 
            statement_date,
            balance_to_use=balance_for_interest
        )
        
        # Make interest negative (increases debt)
        interest_amount = -abs(interest_amount)

        # Get or create "Credit Cards > {CardName}" category
        credit_card_category = family_query(Category).filter_by(
            head_budget='Credit Cards',
            sub_budget=card.card_name
        ).first()
        
        if not credit_card_category:
            credit_card_category = Category(
                family_id=get_family_id(),
                name=card.card_name,
                head_budget='Credit Cards',
                sub_budget=card.card_name,
                category_type='expense'
            )
            db.session.add(credit_card_category)
            db.session.flush()
        
        # Get current APR and check if promotional
        monthly_apr = card.get_current_purchase_apr(statement_date)
        is_promo = (monthly_apr == 0 and (balance_for_interest is None or balance_for_interest < 0))  # negative = owe money
        
        # Create interest transaction
        transaction = CreditCardTransaction(
            credit_card_id=card.id,
            category_id=credit_card_category.id,
            date=statement_date,
            day_name=statement_date.strftime('%A'),
            week=f"{statement_date.isocalendar()[1]:02d}-{statement_date.year}",
            month=statement_date.strftime('%Y-%m'),
            head_budget='Credit Cards',
            sub_budget=card.card_name,
            item='Statement Interest',
            transaction_type='Interest',
            amount=interest_amount,  # Already negative (increases debt)
            applied_apr=monthly_apr,
            is_promotional_rate=is_promo,
            is_paid=False,
            is_fixed=False
        )
        
        db.session.add(transaction)
        
        # Recalculate balances
        if commit:
            db.session.commit()
            CreditCardTransaction.recalculate_card_balance(card.id)
        
        return transaction
    
    @staticmethod
    def generate_payment_transaction(card_id, payment_date, balance_override=None, statement_id=None, commit=True):
        """
        Create a Payment CreditCardTransaction (and a linked bank Transaction).

        Payment amount logic:
          - If ``balance_override`` is provided and >= 0, nothing is owed — returns None.
          - If ``card.set_payment`` is set: amount = MIN(set_payment, abs(balance)).
          - Otherwise: amount = abs(balance) * card.min_payment_percent / 100.

        If ``card.default_payment_account_id`` is set, a matching bank Transaction is
        also created (negative amount = debit from the bank account) and the two records
        are linked via cc_payment.bank_transaction_id.

        Args:
            card_id:          ID of the CreditCard.
            payment_date:     Date the payment is scheduled.
            balance_override: Balance to base the payment on.  If None, uses
                              card.calculate_actual_payment().
            statement_id:     ID of the Interest transaction that triggered this payment.
                              Stored on the Payment so the deletion/regen chain can find it.
            commit:           Whether to commit and recalculate balances (default True).

        Returns:
            CreditCardTransaction — the newly created Payment transaction.
            None if the card is inactive, not found, or payment amount is <= 0.

        Side effects:
            Adds a CreditCardTransaction (Payment) to the session.
            May add a Transaction (bank debit) and a Vendor if not already present.
            May add a Category if one does not exist for this card.
            If commit=True, commits and recalculates both CC and bank account balances.
        """
        card = family_get(CreditCard, card_id)
        if not card or not card.is_active:
            return None
        
        # If balance_override provided, use it; otherwise use card's actual balance
        if balance_override is not None:
            # Calculate payment based on override balance
            if balance_override >= 0:
                return None
            if card.set_payment:
                payment_amount = round(min(float(card.set_payment), abs(float(balance_override))), 2)
            else:
                # Use minimum payment percentage
                payment_amount = round(abs(float(balance_override)) * (float(card.min_payment_percent) / 100), 2)
        else:
            payment_amount = card.calculate_actual_payment()
        
        if payment_amount <= 0:
            return None
        
        # Get or create "Credit Cards > {CardName}" category
        credit_card_category = family_query(Category).filter_by(
            head_budget='Credit Cards',
            sub_budget=card.card_name
        ).first()
        
        if not credit_card_category:
            credit_card_category = Category(
                family_id=get_family_id(),
                name=card.card_name,
                head_budget='Credit Cards',
                sub_budget=card.card_name,
                category_type='expense'
            )
            db.session.add(credit_card_category)
            db.session.flush()
        
        # Create payment transaction
        transaction = CreditCardTransaction(
            credit_card_id=card.id,
            category_id=credit_card_category.id,
            date=payment_date,
            day_name=payment_date.strftime('%a'),
            week=f"{payment_date.isocalendar()[1]:02d}-{payment_date.year}",
            month=payment_date.strftime('%Y-%m'),
            head_budget='Credit Cards',
            sub_budget=card.card_name,
            item='Payment',
            transaction_type='Payment',
            amount=payment_amount,  # POSITIVE = reduces debt (pays off what you owe)
            is_paid=False,
            is_fixed=False,  # Generated payments can be regenerated
            statement_id=statement_id  # Link back to the statement that triggered this payment
        )
        
        db.session.add(transaction)
        db.session.flush()  # Get the transaction ID
        
        # Create linked bank transaction if default payment account is set
        if card.default_payment_account_id:
            # Find or create vendor for card provider
            vendor = family_query(Vendor).filter_by(name=card.card_name).first()
            if not vendor:
                vendor = Vendor(name=card.card_name)
                db.session.add(vendor)
                db.session.flush()
            
            # Calculate computed fields
            payday_period = PaydayService.get_period_for_date(payment_date)
            year_month = payment_date.strftime('%Y-%m')
            week_year = f"{payment_date.isocalendar()[1]:02d}-{payment_date.year}"
            day_name = payment_date.strftime('%a')
            
            bank_txn = Transaction(
                account_id=card.default_payment_account_id,
                category_id=credit_card_category.id,
                vendor_id=vendor.id,
                amount=-payment_amount,  # Negative = expense/debit (money leaving bank account)
                transaction_date=payment_date,
                description=f'Payment to {card.card_name}',
                item='Credit Card Payment',
                payment_type='Transfer',
                is_paid=False,
                is_fixed=False,
                credit_card_id=card.id,
                year_month=year_month,
                week_year=week_year,
                day_name=day_name,
                payday_period=payday_period
            )
            db.session.add(bank_txn)
            db.session.flush()  # Get the bank transaction ID
            
            # Link them together - bank txn is auto-generated, CC payment stays unlocked
            # so regeneration can still clean it up if needed.
            # It will be locked via sync_bank_transaction_to_payment when the user marks it paid/fixed.
            transaction.bank_transaction_id = bank_txn.id
        
        # Recalculate balances
        if commit:
            db.session.commit()
            CreditCardTransaction.recalculate_card_balance(card.id)
            if card.default_payment_account_id:
                Transaction.recalculate_account_balance(card.default_payment_account_id)
        
        return transaction
    
    @staticmethod
    def generate_future_statements(card_id, start_date, end_date):
        """
        Generate Interest transactions for a card across a date range.

        .. deprecated::
            Superseded by generate_future_monthly_statements(), which also handles
            linked payments and bank transactions.  Use that method instead.

        Walks month by month from start_date to end_date on the card's statement day,
        skipping months that already have an Interest transaction.

        Returns:
            list[CreditCardTransaction] — the Interest transactions created.
        """
        card = family_get(CreditCard, card_id)
        if not card or not card.statement_date:
            return []
        
        transactions = []
        current_date = start_date.replace(day=card.statement_date)
        
        # If we're past the statement date this month, start next month
        if current_date < start_date:
            current_date = current_date + relativedelta(months=1)
        
        while current_date <= end_date:
            # Check if transaction already exists
            existing = family_query(CreditCardTransaction).filter_by(
                credit_card_id=card.id,
                date=current_date,
                transaction_type='Interest'
            ).first()
            
            if not existing:
                txn = CreditCardService.generate_statement_interest(
                    card.id, 
                    current_date, 
                    commit=False
                )
                if txn:
                    transactions.append(txn)
            
            current_date = current_date + relativedelta(months=1)
        
        if transactions:
            db.session.commit()
            CreditCardTransaction.recalculate_card_balance(card.id)
        
        return transactions
    
    @staticmethod
    def generate_future_payments(card_id, start_date, end_date, payment_day_offset=5):
        """
        Generate Payment transactions for a card across a date range.

        .. deprecated::
            Superseded by generate_future_monthly_statements(), which handles
            interest, payments, and bank transactions together as a linked chain.
            Use that method instead.

        Payments are scheduled ``payment_day_offset`` days after the statement date.
        Skips months that already have a Payment transaction on the calculated date.

        Returns:
            list[CreditCardTransaction] — the Payment transactions created.
        """
        card = family_get(CreditCard, card_id)
        if not card or not card.statement_date:
            return []
        
        transactions = []
        statement_date = start_date.replace(day=card.statement_date)
        
        # If we're past the statement date this month, start next month
        if statement_date < start_date:
            statement_date = statement_date + relativedelta(months=1)
        
        while statement_date <= end_date:
            # Payment is X days after statement
            payment_date = statement_date + timedelta(days=payment_day_offset)
            
            # Check if transaction already exists
            existing = family_query(CreditCardTransaction).filter_by(
                credit_card_id=card.id,
                date=payment_date,
                transaction_type='Payment'
            ).first()
            
            if not existing:
                txn = CreditCardService.generate_payment_transaction(
                    card.id, 
                    payment_date, 
                    commit=False
                )
                if txn:
                    transactions.append(txn)
            
            statement_date = statement_date + relativedelta(months=1)
        
        if transactions:
            db.session.commit()
            CreditCardTransaction.recalculate_card_balance(card.id)
        
        return transactions
    
    @staticmethod
    def generate_all_monthly_statements(start_date=None, end_date=None, payment_offset_days=14):
        """
        Generate monthly statements for all active cards with intelligent payment triggering:
        - Creates interest transaction on statement date
        - Only creates payment if statement balance > 0
        - Payment scheduled payment_offset_days after statement (default 14 days)
        
        Returns: dict with counts and details
        """
        if not start_date:
            start_date = date.today()
        if not end_date:
            end_date = start_date + relativedelta(years=10)
        
        active_cards = family_query(CreditCard).filter_by(is_active=True).all()
        
        results = {
            'cards_processed': 0,
            'statements_created': 0,
            'payments_created': 0,
            'zero_balance_statements': 0,
            'details': []
        }
        
        for card in active_cards:
            card_results = CreditCardService.generate_future_monthly_statements(
                card.id, start_date, end_date, payment_offset_days
            )
            
            results['cards_processed'] += 1
            results['statements_created'] += card_results['statements_created']
            results['payments_created'] += card_results['payments_created']
            results['zero_balance_statements'] += card_results['zero_balance_statements']
            results['details'].append({
                'card_name': card.card_name,
                'statements': card_results['statements_created'],
                'payments': card_results['payments_created']
            })
        
        return results
    
    @staticmethod
    def generate_future_monthly_statements(card_id, start_date, end_date, payment_offset_days=14):
        """
        Generate full statement chains (Interest + Payment + bank txn) for a single card.

        Walks month by month from start_date to end_date on the card's statement day,
        calling generate_monthly_statement() for each month that does not already have
        an Interest transaction.

        Stops early once the projected statement balance reaches >= 0 (card paid off),
        so statements are not generated past the point the debt clears.

        Args:
            card_id:              ID of the CreditCard.
            start_date:           First date to consider.
            end_date:             Last date to consider.
            payment_offset_days:  Days after statement to schedule payment (default 14).

        Returns:
            dict with keys:
              'statements_created'        — number of Interest transactions created
              'payments_created'          — number of Payment transactions created
              'zero_balance_statements'   — months where interest was created but
                                           no payment was needed

        Side effects:
            Commits all changes and calls recalculate_card_balance() at the end.
        """
        card = family_get(CreditCard, card_id)
        if not card or not card.statement_date:
            return {'statements_created': 0, 'payments_created': 0, 'zero_balance_statements': 0}
        
        results = {
            'statements_created': 0,
            'payments_created': 0,
            'zero_balance_statements': 0
        }
        
        # Start from the next statement date
        current_date = start_date.replace(day=card.statement_date)
        if current_date < start_date:
            current_date = current_date + relativedelta(months=1)
        
        while current_date <= end_date:
            # Check if statement already exists
            existing_statement = family_query(CreditCardTransaction).filter_by(
                credit_card_id=card.id,
                date=current_date,
                transaction_type='Interest'
            ).first()
            
            if not existing_statement:
                # Generate statement (interest + payment if needed)
                statement_result = CreditCardService.generate_monthly_statement(
                    card_id, current_date, payment_offset_days, commit=False
                )
                
                if statement_result['interest_txn'] or statement_result['payment_txn']:
                    results['statements_created'] += 1
                    
                    if statement_result['payment_txn']:
                        results['payments_created'] += 1
                    else:
                        results['zero_balance_statements'] += 1
            
            # Move to next month
            current_date = current_date + relativedelta(months=1)
        
        # Commit all transactions
        db.session.commit()
        
        # Recalculate balances
        CreditCardTransaction.recalculate_card_balance(card.id)
        
        return results
    
    @staticmethod
    def _delete_statement_chain(stmt, card_id):
        """
        Delete a single statement (Interest CCT) and everything linked to it:
          statement → linked CC payment → linked bank transaction
        Returns the number of records deleted.
        """
        count = 0

        # Find the CC payment linked to this statement
        cc_payment = family_query(CreditCardTransaction).filter_by(
            credit_card_id=card_id,
            statement_id=stmt.id,
            transaction_type='Payment'
        ).first()

        if cc_payment:
            # Delete the bank transaction linked to the CC payment
            if cc_payment.bank_transaction_id:
                bank_txn = family_get(Transaction, cc_payment.bank_transaction_id)
                if bank_txn:
                    db.session.delete(bank_txn)
                    count += 1
            db.session.delete(cc_payment)
            count += 1

        db.session.delete(stmt)
        count += 1
        return count

    @staticmethod
    def delete_non_fixed_future_transactions(card_id=None, from_date=None):
        """
        Delete all future unlocked statement chains for a card (or all cards).
        Each chain: Interest (statement) → CC Payment → bank transaction.
        Skips statements marked is_fixed=True.
        """
        if not from_date:
            from_date = date.today()

        query = family_query(CreditCardTransaction).filter(
            CreditCardTransaction.date >= from_date,
            CreditCardTransaction.transaction_type == 'Interest',
            CreditCardTransaction.is_fixed == False
        )
        if card_id:
            query = query.filter(CreditCardTransaction.credit_card_id == card_id)

        statements = query.all()
        deleted = 0
        for stmt in statements:
            deleted += CreditCardService._delete_statement_chain(stmt, stmt.credit_card_id)

        db.session.commit()
        return deleted

    @staticmethod
    def regenerate_future_transactions(card_id, start_date=None, end_date=None, payment_offset_days=14):
        """
        Regenerate future statement chains for a card.

        DELETE PHASE:
          Find every future unlocked Interest (statement) CC transaction.
          For each: delete the linked CC Payment, then delete the linked bank transaction,
          then delete the statement itself.

        GENERATE PHASE:
          Walk month by month from start_date → end_date on the card's statement day.
          For each month: create Interest transaction → create linked CC Payment →
          create linked bank transaction (if card has a default payment account).
          Stop early once the projected balance reaches zero (card paid off).
        """
        logger = logging.getLogger(__name__)

        if not start_date:
            start_date = date.today()
        if not end_date:
            end_date = start_date + relativedelta(years=10)

        card = family_get(CreditCard, card_id)
        if not card or not card.statement_date:
            return {'deleted_count': 0, 'statements_created': 0, 'payments_created': 0}

        # ── DELETE PHASE ──────────────────────────────────────────────────────────
        statements_to_delete = family_query(CreditCardTransaction).filter(
            CreditCardTransaction.credit_card_id == card_id,
            CreditCardTransaction.transaction_type == 'Interest',
            CreditCardTransaction.is_fixed == False,
            CreditCardTransaction.date >= start_date,
            CreditCardTransaction.date <= end_date
        ).all()

        deleted_count = 0
        for stmt in statements_to_delete:
            deleted_count += CreditCardService._delete_statement_chain(stmt, card_id)

        db.session.flush()
        logger.info(f"card {card_id}: deleted {deleted_count} records (statements + payments + bank txns)")

        # ── GENERATE PHASE ────────────────────────────────────────────────────────
        statements_created = 0
        payments_created = 0

        current_date = start_date.replace(day=card.statement_date)
        if current_date < start_date:
            current_date += relativedelta(months=1)

        while current_date <= end_date:
            # Skip months that have a locked statement (is_fixed=True) — leave them alone
            existing_locked = family_query(CreditCardTransaction).filter_by(
                credit_card_id=card_id,
                date=current_date,
                transaction_type='Interest',
            ).filter(CreditCardTransaction.is_fixed == True).first()

            if existing_locked:
                current_date += relativedelta(months=1)
                continue

            result = CreditCardService.generate_monthly_statement(
                card_id, current_date, payment_offset_days, commit=False
            )

            if result['interest_txn']:
                statements_created += 1
            if result['payment_txn']:
                payments_created += 1

            db.session.flush()

            # Stop once the card is paid off (balance >= 0 means no more debt)
            if result['statement_balance'] >= 0:
                logger.info(f"card {card_id}: balance cleared at {current_date}, stopping")
                break

            current_date += relativedelta(months=1)

        db.session.commit()
        CreditCardTransaction.recalculate_card_balance(card_id)

        logger.info(f"card {card_id}: created {statements_created} statements, {payments_created} payments")
        return {
            'deleted_count': deleted_count,
            'statements_created': statements_created,
            'payments_created': payments_created,
        }
    
    @staticmethod
    def regenerate_all_future_transactions(start_date=None, end_date=None, payment_offset_days=14):
        """
        Regenerate future statement chains for all active cards.

        Iterates over every active CreditCard and calls regenerate_future_transactions()
        on each.  Transactions marked is_fixed=True are preserved on every card.

        Args:
            start_date:           Start of the regeneration window (default: today).
            end_date:             End of the regeneration window (default: 10 years out).
            payment_offset_days:  Days after statement to schedule payment (default 14).

        Returns:
            dict with keys:
              'cards_processed'  — number of active cards iterated
              'total_deleted'    — total records deleted across all cards
              'total_statements' — total Interest transactions created
              'total_payments'   — total Payment transactions created
        """
        if not start_date:
            start_date = date.today()
        if not end_date:
            end_date = start_date + relativedelta(years=10)
        
        active_cards = family_query(CreditCard).filter_by(is_active=True).all()
        
        overall_results = {
            'cards_processed': 0,
            'total_deleted': 0,
            'total_statements': 0,
            'total_payments': 0
        }
        
        for card in active_cards:
            card_results = CreditCardService.regenerate_future_transactions(
                card.id, start_date, end_date, payment_offset_days
            )
            
            overall_results['cards_processed'] += 1
            overall_results['total_deleted'] += card_results.get('deleted_count', 0)
            overall_results['total_statements'] += card_results.get('statements_created', 0)
            overall_results['total_payments'] += card_results.get('payments_created', 0)
        
        return overall_results
    
    @staticmethod
    def generate_all_future_transactions(start_date=None, end_date=None):
        """
        DEPRECATED: Use generate_all_monthly_statements instead
        Generate interest and payment transactions for all active cards
        """
        if not start_date:
            start_date = date.today()
        if not end_date:
            end_date = start_date + relativedelta(years=10)  # Default 10 years
        
        active_cards = family_query(CreditCard).filter_by(is_active=True).all()
        
        results = {
            'statements': 0,
            'payments': 0
        }
        
        for card in active_cards:
            statements = CreditCardService.generate_future_statements(card.id, start_date, end_date)
            payments = CreditCardService.generate_future_payments(card.id, start_date, end_date)
            
            results['statements'] += len(statements)
            results['payments'] += len(payments)
        
        return results

    @staticmethod
    def sync_bank_transaction_to_payment(bank_txn):
        """
        Sync edits from a bank Transaction to its linked CC Payment transaction.

        Called from the transaction-edit blueprint whenever a bank Transaction that
        has a credit_card_id is saved.  Keeps the two records in step for date, amount,
        and paid status.

        Locking behaviour: when synced, the CC payment is always marked is_fixed=True
        (regardless of the bank transaction's is_fixed value) because a real bank
        transaction is now linked — it should not be overwritten by regeneration.

        Does nothing (returns None) if:
          - bank_txn has no credit_card_id
          - no matching CC payment is found
          - the CC payment is already marked is_paid (historical record — do not touch)

        Args:
            bank_txn: Transaction instance whose credit_card_id links it to a CC payment.

        Returns:
            CreditCardTransaction — the updated payment, or None if no action taken.

        Side effects:
            Flushes the session.  Calls recalculate_card_balance() on the CC.
            Does NOT commit — the caller's transaction boundary handles that.
        """
        if not bank_txn.credit_card_id:
            return None
        
        # Find linked credit card payment
        cc_payment = family_query(CreditCardTransaction).filter_by(
            credit_card_id=bank_txn.credit_card_id,
            bank_transaction_id=bank_txn.id
        ).first()
        
        if not cc_payment:
            return None
        
        # Only sync if not paid (avoid changing historical data)
        if cc_payment.is_paid:
            return None
        
        # Sync date
        if bank_txn.transaction_date != cc_payment.date:
            cc_payment.date = bank_txn.transaction_date
            cc_payment.day_name = bank_txn.transaction_date.strftime('%A')
            cc_payment.week = f"{bank_txn.transaction_date.isocalendar()[1]:02d}-{bank_txn.transaction_date.year}"
            cc_payment.month = bank_txn.transaction_date.strftime('%Y-%m')
        
        # Sync amount (bank expense = credit card payment)
        if bank_txn.amount != cc_payment.amount:
            cc_payment.amount = abs(float(bank_txn.amount))
        
        # Sync paid status; always lock the CC payment since it has a real bank transaction
        cc_payment.is_paid = bank_txn.is_paid
        cc_payment.is_fixed = True  # Bank transaction is linked — protect from regen
        
        db.session.flush()
        
        # Recalculate credit card balance
        CreditCardTransaction.recalculate_card_balance(cc_payment.credit_card_id)
        
        return cc_payment

    @staticmethod
    def sync_payment_to_bank_transaction(cc_payment):
        """
        Sync edits from a CC Payment transaction to its linked bank Transaction.

        Called from the credit-card-transaction-edit blueprint whenever a CC Payment
        that has a bank_transaction_id is saved.  Mirrors date, amount, paid status,
        and is_fixed onto the bank record.

        Does nothing (returns None) if:
          - cc_payment has no bank_transaction_id
          - the linked bank transaction no longer exists
          - the bank transaction is already marked is_paid (historical — do not touch)

        Args:
            cc_payment: CreditCardTransaction instance whose bank_transaction_id links
                        it to a bank Transaction.

        Returns:
            Transaction — the updated bank record, or None if no action taken.

        Side effects:
            Flushes the session.  Calls recalculate_account_balance() on the bank account.
            Does NOT commit — the caller's transaction boundary handles that.
        """
        if not cc_payment.bank_transaction_id:
            return None
        
        # Find linked bank transaction
        bank_txn = family_get(Transaction, cc_payment.bank_transaction_id)
        
        if not bank_txn:
            return None
        
        # Only sync if not paid (avoid changing historical data)
        if bank_txn.is_paid:
            return None
        
        # Sync date
        if cc_payment.date != bank_txn.transaction_date:
            bank_txn.transaction_date = cc_payment.date
            bank_txn.year_month = cc_payment.date.strftime('%Y-%m')
            bank_txn.week_year = f"{cc_payment.date.isocalendar()[1]:02d}-{cc_payment.date.year}"
            bank_txn.day_name = cc_payment.date.strftime('%a')
        
        # Sync amount (credit card payment = bank expense)
        if abs(float(cc_payment.amount)) != bank_txn.amount:
            bank_txn.amount = abs(float(cc_payment.amount))
        
        # Sync paid status
        bank_txn.is_paid = cc_payment.is_paid
        bank_txn.is_fixed = cc_payment.is_fixed
        bank_txn.updated_at = datetime.now()
        
        db.session.flush()
        
        # Recalculate bank account balance
        if bank_txn.account_id:
            Transaction.recalculate_account_balance(bank_txn.account_id)
        
        return bank_txn

    @staticmethod
    def unlink_payment_and_transaction(cc_payment_id=None, bank_txn_id=None):
        """
        Remove the foreign-key links between a CC Payment and a bank Transaction.

        Called before either record is deleted so the remaining record is left in
        a clean, unlinked state rather than pointing at a deleted row.

        Both arguments are optional; pass whichever side is being unlinked.  If both
        are provided, each side is cleaned up independently.

        Args:
            cc_payment_id: ID of the CreditCardTransaction (Payment) to unlink.
            bank_txn_id:   ID of the bank Transaction to unlink.

        Side effects:
            Sets cc_payment.bank_transaction_id = None and/or bank_txn.credit_card_id = None.
            Does NOT commit — the caller's transaction boundary handles that.
        """
        if cc_payment_id:
            cc_payment = family_get(CreditCardTransaction, cc_payment_id)
            if cc_payment and cc_payment.bank_transaction_id:
                bank_txn = family_get(Transaction, cc_payment.bank_transaction_id)
                if bank_txn:
                    bank_txn.credit_card_id = None
                cc_payment.bank_transaction_id = None
        
        if bank_txn_id:
            bank_txn = family_get(Transaction, bank_txn_id)
            if bank_txn and bank_txn.credit_card_id:
                cc_payment = family_query(CreditCardTransaction).filter_by(
                    bank_transaction_id=bank_txn_id
                ).first()
                if cc_payment:
                    cc_payment.bank_transaction_id = None
                bank_txn.credit_card_id = None
