from datetime import datetime, date, timedelta
from decimal import Decimal
from extensions import db
from models.expenses import Expense
from models.credit_card_transactions import CreditCardTransaction
from models.transactions import Transaction
from models.accounts import Account
from models.categories import Category
from models.credit_cards import CreditCard
from models.vendors import Vendor
from models.settings import Settings
from services.payday_service import PaydayService
from flask import current_app
from sqlalchemy import func


class ExpenseSyncService:
    """Service to sync Expense rows into linked transactions (credit card / bank) and keep them in sync.

    Workflow:
    1. When expense created → Create immediate transaction (credit card OR bank)
    2. Monthly reimbursement → Aggregate all expenses for calendar month → Single reimbursement on last working day
    3. Auto credit card payment → 1 working day after reimbursement, create payment transaction
    
    The service works for both current and future-dated expenses without distinction.
    """

    @staticmethod
    def reconcile(expense_id):
        """Reconcile a single expense - create/update its payment transaction"""
        exp = Expense.query.get(expense_id)
        if not exp:
            return

        # Check if service is enabled
        auto_sync = Settings.get_value('expenses.auto_sync', True)  # Default to True now
        if not auto_sync:
            current_app.logger.info(f"ExpenseSyncService.reconcile disabled by setting; skipping expense {expense_id}")
            return

        try:
            # Special handling for Fuel expenses - update trip entry instead of creating transaction
            if exp.expense_type == 'Fuel':
                ExpenseSyncService._link_fuel_expense_to_trip(exp)
                db.session.commit()
                return
            
            # Step 1: Create payment transaction (credit card OR bank account)
            if exp.credit_card_id:
                ExpenseSyncService._ensure_credit_card_payment(exp)
            else:
                ExpenseSyncService._ensure_bank_payment(exp)

            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    
    @staticmethod
    def reconcile_monthly_reimbursements(year_month=None):
        """
        Create monthly reimbursement transactions for all expenses.
        If year_month is provided (format: "2026-01"), only process that month.
        Otherwise, process all months with expenses.
        
        Returns dict with created reimbursement transaction IDs by month.
        """
        auto_sync = Settings.get_value('expenses.auto_sync', True)
        if not auto_sync:
            return {}
        
        try:
            # Get all months with expenses (regardless of submitted status)
            if year_month:
                months_to_process = [year_month]
            else:
                months_query = db.session.query(Expense.month).filter(
                    Expense.month != None
                ).distinct()
                months_to_process = [m[0] for m in months_query.all()]
            
            results = {}
            for month in months_to_process:
                txn_id = ExpenseSyncService._create_monthly_reimbursement(month)
                if txn_id:
                    results[month] = txn_id
            
            db.session.commit()
            return results
        except Exception:
            db.session.rollback()
            raise
    
    @staticmethod
    def reconcile_credit_card_payments(year_month=None):
        """
        Create automatic credit card payment transactions 1 working day after reimbursement.
        Returns dict with created payment transaction IDs by card.
        """
        auto_sync = Settings.get_value('expenses.auto_sync', True)
        if not auto_sync:
            return {}
        
        try:
            # Get reimbursement transactions
            if year_month:
                # Find reimbursement transaction for this month
                reimburse_txns = Transaction.query.filter(
                    Transaction.payment_type == 'Expense Reimbursement',
                    Transaction.year_month == year_month
                ).all()
            else:
                reimburse_txns = Transaction.query.filter(
                    Transaction.payment_type == 'Expense Reimbursement'
                ).all()
            
            results = {}
            for reimburse_txn in reimburse_txns:
                # Calculate payment date (1 working day after reimbursement)
                payment_date = ExpenseSyncService._next_working_day(reimburse_txn.transaction_date)
                
                # Get month from reimbursement
                month = reimburse_txn.year_month
                if not month:
                    continue
                
                # Find all credit card expenses for this month (regardless of submitted status)
                cc_expenses = Expense.query.filter(
                    Expense.month == month,
                    Expense.credit_card_id != None
                ).all()
                
                # Group by credit card
                card_totals = {}
                for exp in cc_expenses:
                    if exp.credit_card_id not in card_totals:
                        card_totals[exp.credit_card_id] = Decimal('0')
                    card_totals[exp.credit_card_id] += exp.total_cost
                
                # Create payment transaction for each card
                for card_id, total in card_totals.items():
                    if total > 0:
                        payment_txn_id = ExpenseSyncService._create_cc_payment_from_reimbursement(
                            card_id, total, payment_date, month
                        )
                        if payment_txn_id:
                            results[card_id] = payment_txn_id
            
            db.session.commit()
            return results
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def bulk_delete_linked_transactions(expense_ids=None):
        """Delete linked bank and credit-card transactions for the given expenses.

        If `expense_ids` is None, operate on all expenses that currently have links.
        Returns a summary dict with counts and lists of affected ids.
        """
        # Collect target expenses
        q = Expense.query
        if expense_ids:
            q = q.filter(Expense.id.in_(expense_ids))

        linked_expenses = q.filter(
            (Expense.bank_transaction_id != None) | (Expense.credit_card_transaction_id != None)
        ).all()

        bank_txn_ids = set()
        cc_txn_ids = set()
        accounts_to_recalc = set()
        cards_to_recalc = set()

        for exp in linked_expenses:
            if exp.bank_transaction_id:
                bank_txn_ids.add(exp.bank_transaction_id)
            if exp.credit_card_transaction_id:
                cc_txn_ids.add(exp.credit_card_transaction_id)

        # Inspect and collect affected accounts/cards
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

        summary = {
            'expenses_found': [e.id for e in linked_expenses],
            'bank_txn_ids': list(bank_txn_ids),
            'cc_txn_ids': list(cc_txn_ids),
            'deleted_bank_txns': 0,
            'deleted_cc_txns': 0,
            'accounts_recalced': list(accounts_to_recalc),
            'cards_recalced': list(cards_to_recalc)
        }

        # Delete credit card transactions
        if cc_txn_ids:
            CreditCardTransaction.query.filter(CreditCardTransaction.id.in_(list(cc_txn_ids))).delete(synchronize_session=False)
            db.session.commit()
            summary['deleted_cc_txns'] = len(cc_txn_ids)

        # Delete bank transactions
        if bank_txn_ids:
            Transaction.query.filter(Transaction.id.in_(list(bank_txn_ids))).delete(synchronize_session=False)
            db.session.commit()
            summary['deleted_bank_txns'] = len(bank_txn_ids)

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

        # Recalculate balances
        for account_id in accounts_to_recalc:
            if account_id:
                Transaction.recalculate_account_balance(account_id)

        for card_id in cards_to_recalc:
            if card_id:
                CreditCardTransaction.recalculate_card_balance(card_id)

        return summary

    @staticmethod
    def _ensure_credit_card_payment(exp: Expense):
        """Create or update credit card transaction for expense payment (outgoing)"""
        cc = CreditCard.query.get(exp.credit_card_id)
        if not cc:
            return

        # Credit card purchase = negative amount
        target_amount = -abs(float(exp.total_cost))

        # Look for existing transaction
        existing = CreditCardTransaction.query.filter_by(
            credit_card_id=cc.id,
            date=exp.date,
            item=exp.description
        ).first()

        if existing:
            # Update if amount or type changed
            updated = False
            if abs(existing.amount - Decimal(str(target_amount))) > Decimal('0.01'):
                existing.amount = Decimal(str(target_amount))
                updated = True
            if existing.transaction_type != 'Purchase':
                existing.transaction_type = 'Purchase'
                updated = True
            if updated:
                existing.updated_at = datetime.utcnow()
                db.session.add(existing)
            
            # Link expense to transaction
            if exp.credit_card_transaction_id != existing.id:
                exp.credit_card_transaction_id = existing.id
                db.session.add(exp)
        else:
            # Create new credit card purchase
            cc_txn = CreditCardTransaction(
                credit_card_id=cc.id,
                category_id=None,
                date=exp.date,
                day_name=exp.day_name,
                week=exp.week,
                month=exp.month,
                head_budget='Work Expenses',
                sub_budget=exp.expense_type,
                item=exp.description,
                transaction_type='Purchase',
                amount=Decimal(str(target_amount)),
                is_paid=False
            )
            db.session.add(cc_txn)
            db.session.flush()
            
            # Link expense to transaction
            exp.credit_card_transaction_id = cc_txn.id
            db.session.add(exp)
            
            # Recalculate card balance
            CreditCardTransaction.recalculate_card_balance(cc.id)
    
    @staticmethod
    def _ensure_bank_payment(exp: Expense):
        """Create or update bank transaction for direct expense payment (outgoing)"""
        # Get expense account - use expense's account_id if set, otherwise fall back to settings
        account = None
        if exp.account_id:
            account = Account.query.get(exp.account_id)
        else:
            # Fallback to settings or first account
            acct_id = Settings.get_value('expenses.payment_account_id')
            if acct_id:
                account = Account.query.get(int(acct_id))
            if not account:
                account = Account.query.order_by(Account.name).first()
        
        if not account:
            return

        # Find expense category (Income > Expense for both credits and debits)
        expense_cat = Category.query.filter_by(
            head_budget='Income',
            sub_budget='Expense'
        ).first()
        if not expense_cat:
            expense_cat = Category.query.filter_by(head_budget='Expenses').first()

        # Bank payment = negative amount (money out)
        target_amount = -abs(float(exp.total_cost))

        # Look for existing transaction
        existing = Transaction.query.filter_by(
            account_id=account.id,
            transaction_date=exp.date,
            description=exp.description,
            payment_type='Work Expense'
        ).first()

        if existing:
            # Update if amount changed
            if abs(existing.amount - Decimal(str(target_amount))) > Decimal('0.01'):
                existing.amount = Decimal(str(target_amount))
                existing.updated_at = datetime.utcnow()
                db.session.add(existing)
            
            # Link expense to transaction
            if exp.bank_transaction_id != existing.id:
                exp.bank_transaction_id = existing.id
                db.session.add(exp)
        else:
            # Create bank transaction for expense payment
            txn = Transaction(
                account_id=account.id,
                category_id=expense_cat.id if expense_cat else None,
                vendor_id=None,
                amount=Decimal(str(target_amount)),
                transaction_date=exp.date,
                description=exp.description,
                item=exp.description,
                assigned_to=None,
                payment_type='Work Expense',
                is_paid=True,
                year_month=exp.month,
                week_year=exp.week,
                day_name=exp.day_name,
                payday_period=exp.month
            )
            db.session.add(txn)
            db.session.flush()
            
            # Link expense to transaction
            exp.bank_transaction_id = txn.id
            db.session.add(exp)
            
            # Recalculate account balance
            Transaction.recalculate_account_balance(account.id)
    
    @staticmethod
    def _create_monthly_reimbursement(year_month):
        """
        Create a single reimbursement transaction for all expenses in a calendar month.
        Scheduled for last working day of the month.
        Returns transaction ID or None.
        """
        # Get all expenses for this month (regardless of submitted status)
        expenses = Expense.query.filter(
            Expense.month == year_month
        ).all()
        
        if not expenses:
            return None
        
        # Calculate total reimbursement
        total_reimbursement = sum(exp.total_cost for exp in expenses if exp.total_cost)
        if total_reimbursement <= 0:
            return None
        
        # Parse year_month to get last working day
        try:
            year, month = map(int, year_month.split('-'))
            reimbursement_date = ExpenseSyncService._last_working_day_of_month(year, month)
        except:
            return None
        
        # Get reimbursement account
        acct_id = Settings.get_value('expenses.reimburse_account_id')
        account = None
        if acct_id:
            account = Account.query.get(int(acct_id))
        if not account:
            account = Account.query.order_by(Account.name).first()
        if not account:
            return None
        
        # Find reimbursement category
        reimburse_cat = Category.query.filter_by(
            head_budget='Income',
            sub_budget='Expense Reimbursement'
        ).first()
        if not reimburse_cat:
            reimburse_cat = Category.query.filter_by(head_budget='Income').first()
        
        # Check if reimbursement already exists
        existing = Transaction.query.filter_by(
            account_id=account.id,
            transaction_date=reimbursement_date,
            payment_type='Expense Reimbursement',
            year_month=year_month
        ).first()
        
        if existing:
            # Update amount if changed
            if abs(existing.amount - total_reimbursement) > Decimal('0.01'):
                existing.amount = total_reimbursement
                existing.updated_at = datetime.utcnow()
                db.session.add(existing)
                Transaction.recalculate_account_balance(account.id)
            return existing.id
        else:
            # Create reimbursement transaction (positive = money in)
            # Only set is_paid=True if transaction date is today or in the past
            from datetime import date as date_class
            is_paid = reimbursement_date <= date_class.today()
            
            txn = Transaction(
                account_id=account.id,
                category_id=reimburse_cat.id if reimburse_cat else None,
                vendor_id=None,
                amount=total_reimbursement,
                transaction_date=reimbursement_date,
                description=f'Work Expense Reimbursement - {year_month}',
                item=f'Monthly reimbursement for {year_month}',
                assigned_to=None,
                payment_type='Expense Reimbursement',
                is_paid=is_paid,
                year_month=year_month,
                week_year=f"{reimbursement_date.isocalendar()[1]:02d}-{year}",
                day_name=reimbursement_date.strftime('%A'),
                payday_period=year_month
            )
            db.session.add(txn)
            db.session.flush()
            Transaction.recalculate_account_balance(account.id)
            return txn.id
    
    @staticmethod
    def _create_cc_payment_from_reimbursement(card_id, amount, payment_date, year_month):
        """
        Create credit card payment transaction from reimbursement.
        Also creates linked bank transaction from the card's default payment account.
        Returns transaction ID or None.
        """
        # Check if payment already exists
        existing = CreditCardTransaction.query.filter_by(
            credit_card_id=card_id,
            date=payment_date,
            transaction_type='Payment'
        ).filter(
            func.abs(CreditCardTransaction.amount - amount) < 0.01
        ).first()
        
        if existing:
            return existing.id
        
        # Get the credit card to find default payment account
        card = CreditCard.query.get(card_id)
        if not card:
            return None
        
        # Create payment transaction (positive = payment to card)
        # Only set is_paid=True if payment date is today or in the past
        from datetime import date as date_class
        is_paid = payment_date <= date_class.today()
        
        payment_txn = CreditCardTransaction(
            credit_card_id=card_id,
            category_id=None,
            date=payment_date,
            day_name=payment_date.strftime('%A'),
            week=f"{payment_date.isocalendar()[1]:02d}-{payment_date.year}",
            month=year_month,
            head_budget='Transfer',
            sub_budget='Credit Card Payment',
            item=f'Expense reimbursement payment - {year_month}',
            transaction_type='Payment',
            amount=amount,  # Positive amount
            is_paid=is_paid,
            is_fixed=True  # Lock to prevent regeneration
        )
        db.session.add(payment_txn)
        db.session.flush()
        
        # Create linked bank transaction if card has default payment account
        if card.default_payment_account_id:
            # Find Credit Cards category matching this specific card
            credit_card_category = Category.query.filter_by(
                head_budget='Credit Cards',
                sub_budget=card.card_name
            ).first()
            
            # If not found, try to find any Credit Cards category as fallback
            if not credit_card_category:
                credit_card_category = Category.query.filter_by(
                    head_budget='Credit Cards'
                ).first()
            
            # Find or create vendor matching card name
            vendor = Vendor.query.filter_by(name=card.card_name).first()
            if not vendor:
                vendor = Vendor(name=card.card_name)
                db.session.add(vendor)
                db.session.flush()
            
            # Create bank transaction (negative = money out)
            bank_txn = Transaction(
                account_id=card.default_payment_account_id,
                category_id=credit_card_category.id if credit_card_category else None,
                vendor_id=vendor.id,
                amount=Decimal(str(-abs(float(amount)))),  # Negative = expense from bank account
                transaction_date=payment_date,
                description=f'Payment to {card.card_name}',
                item='Credit Card Payment',
                payment_type='Card Payment',
                is_paid=is_paid,
                is_fixed=True,  # Lock to prevent deletion
                credit_card_id=card.id,
                year_month=year_month,
                week_year=f"{payment_date.isocalendar()[1]:02d}-{payment_date.year}",
                day_name=payment_date.strftime('%A'),
                payday_period=PaydayService.get_period_for_date(payment_date)
            )
            db.session.add(bank_txn)
            db.session.flush()
            
            # Link back to credit card transaction
            payment_txn.bank_transaction_id = bank_txn.id
            
            # Recalculate bank account balance
            Transaction.recalculate_account_balance(card.default_payment_account_id)
        
        # Recalculate card balance
        CreditCardTransaction.recalculate_card_balance(card_id)
        return payment_txn.id
    
    @staticmethod
    def _last_working_day_of_month(year, month):
        """Get the last working day of a given month (skip weekends)"""
        # Get last day of month
        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)
        last_day = next_month - timedelta(days=1)
        
        # Move back to Friday if weekend
        while last_day.weekday() >= 5:  # 5=Saturday, 6=Sunday
            last_day -= timedelta(days=1)
        
        return last_day
    
    @staticmethod
    def _next_working_day(from_date):
        """Get next working day after given date (skip weekends)"""
        next_day = from_date + timedelta(days=1)
        
        # Skip weekends
        while next_day.weekday() >= 5:
            next_day += timedelta(days=1)
        
        return next_day
    
    @staticmethod
    def _link_fuel_expense_to_trip(exp: Expense):
        """
        Link fuel expense to corresponding trip entry and update trip with expense details.
        Fuel expenses do NOT create transactions - they update the trip log.
        """
        from models.trips import Trip
        from models.vehicles import Vehicle
        
        # Find vehicle by registration
        if not exp.vehicle_registration:
            current_app.logger.warning(f"Fuel expense {exp.id} has no vehicle registration")
            return
        
        vehicle = Vehicle.query.filter_by(registration=exp.vehicle_registration).first()
        if not vehicle:
            current_app.logger.warning(f"Vehicle not found: {exp.vehicle_registration}")
            return
        
        # Find trip on same date for same vehicle
        trip = Trip.query.filter_by(
            vehicle_id=vehicle.id,
            date=exp.date
        ).first()
        
        if trip:
            # Update trip with expense details if provided
            if exp.covered_miles and not trip.business_miles:
                trip.business_miles = exp.covered_miles
                trip.total_miles = (trip.personal_miles or 0) + exp.covered_miles
            
            # Store link to expense (you may need to add this field to Trip model)
            # trip.expense_id = exp.id
            
            db.session.add(trip)
            current_app.logger.info(f"Linked fuel expense {exp.id} to trip {trip.id}")
        else:
            # Optionally create new trip entry
            current_app.logger.warning(f"No trip found for fuel expense {exp.id} on {exp.date}")


