"""
Credit Card Service
Handles interest calculations, statement generation, and payment automation
"""
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from models.credit_cards import CreditCard, CreditCardPromotion
from models.credit_card_transactions import CreditCardTransaction
from models.categories import Category
from extensions import db


class CreditCardService:
    
    @staticmethod
    def generate_monthly_statement(card_id, statement_date, payment_offset_days=14, commit=True):
        """
        Generate monthly statement with intelligent payment triggering:
        1. Check current balance BEFORE statement
        2. Create interest transaction if balance > 0
        3. Calculate statement balance (balance + interest)
        4. If statement balance > 0, create payment 14 days later
        5. If statement balance = 0, no payment needed
        
        Returns: dict with 'interest_txn', 'payment_txn', 'statement_balance'
        """
        card = CreditCard.query.get(card_id)
        if not card or not card.is_active:
            return {'interest_txn': None, 'payment_txn': None, 'statement_balance': 0}
        
        result = {
            'interest_txn': None,
            'payment_txn': None,
            'statement_balance': 0
        }
        
        # Get balance BEFORE statement
        opening_balance = float(card.current_balance) if card.current_balance else 0.0
        
        # Step 1: Generate interest transaction only if you OWE money (negative balance)
        if opening_balance < 0:
            interest_txn = CreditCardService.generate_statement_interest(card_id, statement_date, commit=False)
            if interest_txn:
                result['interest_txn'] = interest_txn
                db.session.flush()  # Make sure it's in the database for recalculation
        
        # Step 2: Recalculate balance to include interest
        CreditCardTransaction.recalculate_card_balance(card_id)
        card = CreditCard.query.get(card_id)  # Refresh to get updated balance
        statement_balance = float(card.current_balance) if card.current_balance else 0.0
        result['statement_balance'] = statement_balance
        
        # Step 3: Create payment only if you OWE money (negative balance)
        if statement_balance < 0:
            payment_date = statement_date + timedelta(days=payment_offset_days)
            payment_txn = CreditCardService.generate_payment_transaction(
                card_id, 
                payment_date, 
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
    def calculate_interest(card_id, statement_date):
        """
        Calculate interest for a credit card on a specific statement date
        Returns the interest amount (0 if in 0% period)
        """
        card = CreditCard.query.get(card_id)
        if not card:
            return 0.0
        
        # Get APR for this date (considers 0% offers)
        monthly_apr = card.get_current_purchase_apr(statement_date)
        
        # If 0%, return 0
        if monthly_apr == 0:
            return 0.0
        
        # Calculate interest on current balance (use absolute value since negative = owe)
        interest = abs(float(card.current_balance)) * (monthly_apr / 100)
        return round(interest, 2)
    
    @staticmethod
    def generate_statement_interest(card_id, statement_date, commit=True):
        """
        Generate an interest transaction for a credit card on statement date
        Returns the created transaction or None if no balance
        Note: This should only be called when opening balance > 0
        """
        card = CreditCard.query.get(card_id)
        if not card or not card.is_active:
            return None
        
        # Calculate interest (could be £0 if 0% promotional period)
        # Interest is positive (increases what you owe), calculated on abs(balance)
        interest_amount = abs(CreditCardService.calculate_interest(card_id, statement_date))
        
        # Get or create "Credit Cards > {CardName}" category
        credit_card_category = Category.query.filter_by(
            head_budget='Credit Cards',
            sub_budget=card.card_name
        ).first()
        
        if not credit_card_category:
            credit_card_category = Category(
                head_budget='Credit Cards',
                sub_budget=card.card_name,
                category_type='expense'
            )
            db.session.add(credit_card_category)
            db.session.flush()
        
        # Get current APR and check if promotional
        monthly_apr = card.get_current_purchase_apr(statement_date)
        is_promo = (monthly_apr == 0 and card.current_balance < 0)  # negative = owe money
        
        # Create interest transaction
        transaction = CreditCardTransaction(
            credit_card_id=card.id,
            category_id=credit_card_category.id,
            date=statement_date,
            day_name=statement_date.strftime('%A'),
            week=statement_date.strftime('%Y-W%U'),
            month=statement_date.strftime('%Y-%m'),
            head_budget='Credit Cards',
            sub_budget=card.card_name,
            item='Statement Interest',
            transaction_type='Interest',
            amount=-interest_amount,  # Negative = increases what you owe
            applied_apr=monthly_apr,
            is_promotional_rate=is_promo,
            is_paid=False
        )
        
        db.session.add(transaction)
        
        # Recalculate balances
        if commit:
            db.session.commit()
            CreditCardTransaction.recalculate_card_balance(card.id)
        
        return transaction
    
    @staticmethod
    def generate_payment_transaction(card_id, payment_date, commit=True):
        """
        Generate a payment transaction based on card's set_payment
        Uses logic: MIN(set_payment, current_balance)
        Returns the created transaction
        """
        card = CreditCard.query.get(card_id)
        if not card or not card.is_active:
            return None
        
        payment_amount = card.calculate_actual_payment()
        
        if payment_amount <= 0:
            return None
        
        # Get or create "Credit Cards > {CardName}" category
        credit_card_category = Category.query.filter_by(
            head_budget='Credit Cards',
            sub_budget=card.card_name
        ).first()
        
        if not credit_card_category:
            credit_card_category = Category(
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
            week=payment_date.strftime('%U-%Y'),
            month=payment_date.strftime('%Y-%m'),
            head_budget='Credit Cards',
            sub_budget=card.card_name,
            item='Payment',
            transaction_type='Payment',
            amount=payment_amount,  # POSITIVE = reduces debt (pays off what you owe)
            is_paid=False,
            is_fixed=False  # Generated payments can be regenerated
        )
        
        db.session.add(transaction)
        
        # Recalculate balances
        if commit:
            db.session.commit()
            CreditCardTransaction.recalculate_card_balance(card.id)
        
        return transaction
    
    @staticmethod
    def generate_future_statements(card_id, start_date, end_date):
        """
        Generate all future statement interest transactions for a card
        between start_date and end_date
        """
        card = CreditCard.query.get(card_id)
        if not card or not card.statement_date:
            return []
        
        transactions = []
        current_date = start_date.replace(day=card.statement_date)
        
        # If we're past the statement date this month, start next month
        if current_date < start_date:
            current_date = current_date + relativedelta(months=1)
        
        while current_date <= end_date:
            # Check if transaction already exists
            existing = CreditCardTransaction.query.filter_by(
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
        Generate all future payment transactions for a card
        Payments occur payment_day_offset days after statement date
        """
        card = CreditCard.query.get(card_id)
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
            existing = CreditCardTransaction.query.filter_by(
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
        
        active_cards = CreditCard.query.filter_by(is_active=True).all()
        
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
        Generate monthly statements for a single card with intelligent payment logic
        """
        card = CreditCard.query.get(card_id)
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
            existing_statement = CreditCardTransaction.query.filter_by(
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
    def delete_non_fixed_future_transactions(card_id=None, from_date=None):
        """
        Delete all non-fixed future transactions (Interest and Payment types)
        If card_id is specified, only delete for that card
        If from_date is specified, only delete transactions on or after that date
        This preserves any transactions marked as is_fixed=True
        """
        if not from_date:
            from_date = date.today()
        
        query = CreditCardTransaction.query.filter(
            CreditCardTransaction.date >= from_date,
            CreditCardTransaction.transaction_type.in_(['Interest', 'Payment']),
            CreditCardTransaction.is_fixed == False  # Only delete non-fixed
        )
        
        if card_id:
            query = query.filter(CreditCardTransaction.credit_card_id == card_id)
        
        deleted_count = query.delete(synchronize_session=False)
        db.session.commit()
        
        return deleted_count
    
    @staticmethod
    def regenerate_future_transactions(card_id, start_date=None, end_date=None, payment_offset_days=14):
        """
        Regenerate future transactions for a card:
        1. Delete all non-fixed Interest and Payment transactions from start_date
        2. Regenerate statements and payments
        3. Preserve any transactions marked as is_fixed=True
        
        This allows users to mark certain payments as "locked" and regenerate around them
        """
        if not start_date:
            start_date = date.today()
        if not end_date:
            end_date = start_date + relativedelta(years=10)
        
        # Step 1: Delete non-fixed future transactions
        deleted = CreditCardService.delete_non_fixed_future_transactions(card_id, start_date)
        
        # Step 2: Recalculate balance to current state (without future transactions)
        CreditCardTransaction.recalculate_card_balance(card_id)
        
        # Step 3: Generate new statements
        from datetime import date
        from dateutil.relativedelta import relativedelta
        
        results = {
            'statements_created': 0,
            'payments_created': 0,
            'zero_balance_statements': 0
        }
        
        card = CreditCard.query.get(card_id)
        if not card or not card.statement_date:
            return results
        
        current_date = start_date.replace(day=card.statement_date)
        if current_date < start_date:
            current_date = current_date + relativedelta(months=1)
        
        while current_date <= end_date:
            # Check if statement already exists (and not deleted)
            existing = CreditCardTransaction.query.filter_by(
                credit_card_id=card_id,
                date=current_date,
                transaction_type='Interest'
            ).first()
            
            if not existing:
                stmt_result = CreditCardService.generate_monthly_statement(
                    card_id, current_date, payment_offset_days, commit=False
                )
                
                if stmt_result['interest_txn'] or stmt_result['payment_txn']:
                    results['statements_created'] += 1
                    
                    if stmt_result['payment_txn']:
                        results['payments_created'] += 1
                    else:
                        results['zero_balance_statements'] += 1
            
            current_date = current_date + relativedelta(months=1)
        
        db.session.commit()
        
        results['deleted_count'] = deleted
        
        return results
    
    @staticmethod
    def regenerate_all_future_transactions(start_date=None, end_date=None, payment_offset_days=14):
        """
        Regenerate future transactions for ALL active cards
        Preserves any transactions marked as is_fixed=True
        """
        if not start_date:
            start_date = date.today()
        if not end_date:
            end_date = start_date + relativedelta(years=10)
        
        active_cards = CreditCard.query.filter_by(is_active=True).all()
        
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
        
        active_cards = CreditCard.query.filter_by(is_active=True).all()
        
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
