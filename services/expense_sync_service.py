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
from models.trips import Trip
from models.vehicles import Vehicle
from models.settings import Settings
from services.payday_service import PaydayService
from flask import current_app
from sqlalchemy import func
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


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
        exp = family_get(Expense, expense_id)
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
    def get_period_mode():
        """
        Return the current expense period grouping mode.
        'calendar_month'  – group by calendar month, reimburse end of that month  (default)
        'payday_period'   – group by payday period, reimburse at end of payday period
        """
        return Settings.get_value('expenses.period_mode', 'calendar_month')

    @staticmethod
    def get_period_key_for_expense(exp):
        """
        Return the period key (YYYY-MM) that this expense belongs to under the current mode.
        Always derived from exp.date so it is resilient to NULL Expense.month fields.
        """
        if not exp.date:
            return None
        mode = ExpenseSyncService.get_period_mode()
        if mode == 'payday_period':
            return PaydayService.get_period_for_date(exp.date)
        # Default: calendar month
        return exp.date.strftime('%Y-%m')

    @staticmethod
    def reconcile_monthly_reimbursements(year_month=None):
        """
        Create reimbursement transactions for all submitted expenses.
        Respects the 'expenses.period_mode' setting:
          - 'calendar_month': group by calendar YYYY-MM, reimburse last working day of that month
          - 'payday_period':  group by payday-period YYYY-MM, reimburse last day of the payday period

        If year_month is provided (format "2026-01") only that period is processed.
        Returns dict with created/updated reimbursement transaction IDs by period key.
        """
        auto_sync = Settings.get_value('expenses.auto_sync', True)
        if not auto_sync:
            return {}

        try:
            if year_month:
                periods_to_process = [year_month]
            else:
                # Build the set of period keys from all expenses (submitted or not).
                # Always derive from expense.date (Expense.month can be NULL on older records).
                periods_set = set()
                all_expenses = family_query(Expense).all()
                for exp in all_expenses:
                    key = ExpenseSyncService.get_period_key_for_expense(exp)
                    if key:
                        periods_set.add(key)
                periods_to_process = sorted(periods_set)

            results = {}
            for period_key in periods_to_process:
                txn_id = ExpenseSyncService._create_period_reimbursement(period_key)
                if txn_id:
                    results[period_key] = txn_id

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
            current_app.logger.info('reconcile_credit_card_payments: auto_sync disabled, skipping')
            return {}

        try:
            fid = get_family_id()
            current_app.logger.info(
                f'reconcile_credit_card_payments: start  year_month={year_month!r}  family_id={fid}'
            )

            # Get reimbursement transactions
            if year_month:
                reimburse_txns = family_query(Transaction).filter(
                    Transaction.payment_type == 'Expense Reimbursement',
                    Transaction.year_month == year_month
                ).all()
            else:
                reimburse_txns = family_query(Transaction).filter(
                    Transaction.payment_type == 'Expense Reimbursement'
                ).all()

            current_app.logger.info(
                f'reconcile_credit_card_payments: found {len(reimburse_txns)} reimbursement txn(s): '
                f'{[t.id for t in reimburse_txns]}'
            )

            results = {}
            for reimburse_txn in reimburse_txns:
                payment_date = ExpenseSyncService._next_working_day(reimburse_txn.transaction_date)
                period_key = reimburse_txn.year_month
                current_app.logger.info(
                    f'  reimburse_txn #{reimburse_txn.id}  period_key={period_key!r}'
                    f'  payment_date={payment_date}'
                )
                if not period_key:
                    current_app.logger.warning(f'  skipping: period_key is empty')
                    continue

                try:
                    p_start, p_end = ExpenseSyncService._get_period_date_range(period_key)
                except (ValueError, AttributeError) as exc:
                    current_app.logger.warning(f'  skipping: _get_period_date_range failed: {exc}')
                    continue

                current_app.logger.info(f'  period range: {p_start} … {p_end}')

                cc_expenses = family_query(Expense).filter(
                    Expense.date >= p_start,
                    Expense.date <= p_end,
                    Expense.credit_card_id != None,  # noqa: E711
                ).all()

                current_app.logger.info(
                    f'  cc_expenses found: {len(cc_expenses)}  '
                    f'ids={[e.id for e in cc_expenses]}'
                )

                card_totals = {}
                for exp in cc_expenses:
                    if exp.credit_card_id not in card_totals:
                        card_totals[exp.credit_card_id] = Decimal('0')
                    card_totals[exp.credit_card_id] += (exp.total_cost or Decimal('0'))

                current_app.logger.info(f'  card_totals: {dict(card_totals)}')

                for card_id, total in card_totals.items():
                    if total > 0:
                        current_app.logger.info(
                            f'  creating CC payment: card_id={card_id}  total={total}'
                        )
                        payment_txn_id = ExpenseSyncService._create_cc_payment_from_reimbursement(
                            card_id, total, payment_date, period_key
                        )
                        current_app.logger.info(f'  → payment_txn_id={payment_txn_id}')
                        if payment_txn_id:
                            results[card_id] = payment_txn_id

            db.session.commit()
            current_app.logger.info(f'reconcile_credit_card_payments: done  results={results}')
            return results
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def bulk_delete_linked_transactions(expense_ids=None):
        """Delete linked bank and credit-card transactions for the given expenses.
        Also deletes auto-created trip rows for Fuel expenses.

        If `expense_ids` is None, operate on all expenses that currently have links.
        Returns a summary dict with counts and lists of affected ids.
        """
        # Collect target expenses
        q = family_query(Expense)
        if expense_ids:
            q = q.filter(Expense.id.in_(expense_ids))

        all_expenses = q.all()

        linked_expenses = [
            e for e in all_expenses
            if e.bank_transaction_id or e.credit_card_transaction_id
        ]

        # Delete auto-created trip rows for fuel expenses
        fuel_trips_deleted = 0
        for exp in all_expenses:
            if exp.expense_type == 'Fuel':
                try:
                    ExpenseSyncService.delete_fuel_trip_for_expense(exp)
                    fuel_trips_deleted += 1
                except Exception:
                    current_app.logger.exception(f"Error deleting fuel trip for expense {exp.id}")

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
            txns = family_query(Transaction).filter(Transaction.id.in_(list(bank_txn_ids))).all()
            for t in txns:
                if t.account_id:
                    accounts_to_recalc.add(t.account_id)

        if cc_txn_ids:
            ccs = family_query(CreditCardTransaction).filter(CreditCardTransaction.id.in_(list(cc_txn_ids))).all()
            for c in ccs:
                if c.credit_card_id:
                    cards_to_recalc.add(c.credit_card_id)

        summary = {
            'expenses_found': [e.id for e in linked_expenses],
            'bank_txn_ids': list(bank_txn_ids),
            'cc_txn_ids': list(cc_txn_ids),
            'deleted_bank_txns': 0,
            'deleted_cc_txns': 0,
            'deleted_fuel_trips': fuel_trips_deleted,
            'accounts_recalced': list(accounts_to_recalc),
            'cards_recalced': list(cards_to_recalc)
        }

        # Delete credit card transactions
        if cc_txn_ids:
            family_query(CreditCardTransaction).filter(CreditCardTransaction.id.in_(list(cc_txn_ids))).delete(synchronize_session=False)
            db.session.commit()
            summary['deleted_cc_txns'] = len(cc_txn_ids)

        # Delete bank transactions
        if bank_txn_ids:
            family_query(Transaction).filter(Transaction.id.in_(list(bank_txn_ids))).delete(synchronize_session=False)
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
        if not exp.total_cost:
            return
        cc = family_get(CreditCard, exp.credit_card_id)
        if not cc:
            return

        # Credit card purchase = negative amount
        target_amount = -abs(float(exp.total_cost))

        # Look for existing transaction
        existing = family_query(CreditCardTransaction).filter_by(
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
                family_id=get_family_id(),
                credit_card_id=cc.id,
                category_id=None,
                date=exp.date,
                day_name=exp.date.strftime('%A'),
                week=f"{exp.date.isocalendar()[1]:02d}-{exp.date.year}",
                month=exp.date.strftime('%Y-%m'),
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
        if not exp.total_cost:
            return
        # Get expense account - use expense's account_id if set, otherwise fall back to settings
        account = None
        if exp.account_id:
            account = family_get(Account, exp.account_id)
        else:
            # Fallback to settings or first account
            acct_id = Settings.get_value('expenses.payment_account_id')
            if acct_id:
                account = family_get(Account, int(acct_id))
            if not account:
                account = family_query(Account).order_by(Account.name).first()
        
        if not account:
            return

        # Category: prefer the configured reimburse category, then name-based fallback
        cat_id = Settings.get_value('expenses.reimburse_category_id')
        expense_cat = family_get(Category, int(cat_id)) if cat_id else None
        if not expense_cat:
            expense_cat = family_query(Category).filter_by(
                head_budget='Income', sub_budget='Expense').first()
        if not expense_cat:
            expense_cat = family_query(Category).filter_by(head_budget='Expenses').first()

        # Vendor: prefer the configured reimburse vendor
        vendor_id_setting = Settings.get_value('expenses.reimburse_vendor_id')
        expense_vendor_id = int(vendor_id_setting) if vendor_id_setting else None

        # Bank payment = negative amount (money out)
        target_amount = -abs(float(exp.total_cost))

        # Look for existing transaction
        existing = family_query(Transaction).filter_by(
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
            # Always derive date-related fields from exp.date directly — Expense.month/week/day_name
            # can be NULL on older or freshly-created records before the route populates them.
            txn = Transaction(
                family_id=get_family_id(),
                account_id=account.id,
                category_id=expense_cat.id if expense_cat else None,
                vendor_id=expense_vendor_id,
                amount=Decimal(str(target_amount)),
                transaction_date=exp.date,
                description=exp.description,
                item=exp.description,
                assigned_to=None,
                payment_type='Work Expense',
                is_paid=bool(exp.paid_for),
                year_month=exp.date.strftime('%Y-%m'),
                week_year=f"{exp.date.isocalendar()[1]:02d}-{exp.date.year}",
                day_name=exp.date.strftime('%A'),
                payday_period=PaydayService.get_period_for_date(exp.date)
            )
            db.session.add(txn)
            db.session.flush()
            
            # Link expense to transaction
            exp.bank_transaction_id = txn.id
            db.session.add(exp)
            
            # Recalculate account balance
            Transaction.recalculate_account_balance(account.id)
    
    @staticmethod
    def _get_period_date_range(period_key):
        """
        Return (start_date, end_date) for the given period key, respecting the current mode:
          'calendar_month' → first day … last day of that calendar month
          'payday_period'  → PaydayService start/end for that payday period
        Raises ValueError if period_key is malformed.
        """
        import calendar as _cal
        year, month = map(int, period_key.split('-'))
        mode = ExpenseSyncService.get_period_mode()
        if mode == 'payday_period':
            start_date, end_date, _ = PaydayService.get_payday_period(year, month)
            return start_date, end_date
        # Default: calendar month
        return date(year, month, 1), date(year, month, _cal.monthrange(year, month)[1])

    @staticmethod
    def _get_reimbursement_date(period_key):
        """
        Return the date on which the reimbursement transaction should be placed:
          'calendar_month' → last working day of that calendar month
          'payday_period'  → last working day on or before the payday period's end date
        """
        year, month = map(int, period_key.split('-'))
        mode = ExpenseSyncService.get_period_mode()
        if mode == 'payday_period':
            _, end_date, _ = PaydayService.get_payday_period(year, month)
            return PaydayService.get_previous_working_day(end_date)
        return ExpenseSyncService._last_working_day_of_month(year, month)

    @staticmethod
    def _create_period_reimbursement(period_key):
        """
        Create (or update) a single reimbursement transaction for all expenses
        in the given period (calendar month or payday period, depending on setting).
        Transaction is created as is_paid=False regardless of expense submission status.
        Returns transaction ID or None.
        """
        try:
            period_start, period_end = ExpenseSyncService._get_period_date_range(period_key)
            reimbursement_date       = ExpenseSyncService._get_reimbursement_date(period_key)
        except (ValueError, AttributeError):
            return None

        # Include all expenses in the period (submitted or not); created as is_paid=False.
        expenses = family_query(Expense).filter(
            Expense.date >= period_start,
            Expense.date <= period_end
        ).all()

        if not expenses:
            return None

        total_reimbursement = sum(exp.total_cost for exp in expenses if exp.total_cost)
        if total_reimbursement <= 0:
            return None
        # Look for existing reimbursement transaction for this period
        existing = family_query(Transaction).filter(
            Transaction.payment_type == 'Expense Reimbursement',
            Transaction.year_month == period_key
        ).first()

        if existing:
            if abs(existing.amount - total_reimbursement) > Decimal('0.01'):
                existing.amount = total_reimbursement
                existing.transaction_date = reimbursement_date
                existing.updated_at = datetime.utcnow()
                db.session.add(existing)
            return existing.id

        # Find reimbursement account
        acct_id = Settings.get_value('expenses.payment_account_id')
        account = family_get(Account, int(acct_id)) if acct_id else None
        if not account:
            account = family_query(Account).order_by(Account.name).first()
        if not account:
            return None

        # Category: prefer configured, then name-based fallback
        cat_id = Settings.get_value('expenses.reimburse_category_id')
        reimburse_cat = family_get(Category, int(cat_id)) if cat_id else None
        if not reimburse_cat:
            reimburse_cat = family_query(Category).filter_by(
                head_budget='Income', sub_budget='Expense').first()
        if not reimburse_cat:
            reimburse_cat = family_query(Category).filter_by(head_budget='Expenses').first()
        if not reimburse_cat:
            reimburse_cat = family_query(Category).first()
        if not reimburse_cat:
            raise ValueError('No category found — please create at least one category before generating reimbursements.')

        # Vendor: prefer configured
        vendor_id_setting = Settings.get_value('expenses.reimburse_vendor_id')
        reimburse_vendor_id = int(vendor_id_setting) if vendor_id_setting else None

        reimburse_txn = Transaction(
            family_id=get_family_id(),
            account_id=account.id,
            category_id=reimburse_cat.id,
            vendor_id=reimburse_vendor_id,
            amount=total_reimbursement,
            transaction_date=reimbursement_date,
            description=f'Expense Reimbursement {period_key}',
            item=f'Expense Reimbursement {period_key}',
            payment_type='Expense Reimbursement',
            is_paid=False,
            year_month=period_key,
            week_year=f"{reimbursement_date.isocalendar()[1]:02d}-{reimbursement_date.year}",
            day_name=reimbursement_date.strftime('%A'),
            payday_period=PaydayService.get_period_for_date(reimbursement_date)
        )
        db.session.add(reimburse_txn)
        db.session.flush()
        Transaction.recalculate_account_balance(account.id)
        return reimburse_txn.id

    @staticmethod
    def _create_monthly_reimbursement(period_key):
        """Backward-compatible alias for _create_period_reimbursement."""
        return ExpenseSyncService._create_period_reimbursement(period_key)

    @staticmethod
    def _last_working_day_of_month(year, month):
        """Return the last Monday-Friday of the given month."""
        import calendar as _cal
        last_day = date(year, month, _cal.monthrange(year, month)[1])
        # Walk backwards until we hit a weekday (Mon=0 … Fri=4)
        while last_day.weekday() > 4:
            last_day -= timedelta(days=1)
        return last_day

    @staticmethod
    def _next_working_day(d):
        """Return the next Monday-Friday on or after the day after d."""
        next_day = d + timedelta(days=1)
        while next_day.weekday() > 4:
            next_day += timedelta(days=1)
        return next_day

    @staticmethod
    def _create_cc_payment_from_reimbursement(card_id, total, payment_date, period_key):
        """Create or update a credit card Payment transaction from expense reimbursement funds."""
        cc = family_get(CreditCard, card_id)
        if not cc:
            return None

        description = f'Expense reimbursement payment {period_key}'
        existing = family_query(CreditCardTransaction).filter(
            CreditCardTransaction.credit_card_id == card_id,
            CreditCardTransaction.transaction_type == 'Payment',
            CreditCardTransaction.item.like(f'%{period_key}%')
        ).first()

        if existing:
            if abs(existing.amount - total) > Decimal('0.01'):
                existing.amount = total
                existing.date = payment_date
                existing.updated_at = datetime.utcnow()
                db.session.add(existing)
            return existing.id

        payment_txn = CreditCardTransaction(
            family_id=get_family_id(),
            credit_card_id=card_id,
            date=payment_date,
            day_name=payment_date.strftime('%A'),
            week=f"{payment_date.isocalendar()[1]:02d}-{payment_date.year}",
            month=payment_date.strftime('%Y-%m'),
            transaction_type='Payment',
            item=description,
            amount=total,
            is_paid=False
        )
        db.session.add(payment_txn)
        db.session.flush()
        CreditCardTransaction.recalculate_card_balance(card_id)
        return payment_txn.id

    @staticmethod
    def _link_fuel_expense_to_trip(exp):
        """
        Create or update a Trip row for a Fuel expense.
        Trips created here are identified by a sentinel prefix in journey_description:
          "Expense #<id>: <description>"
        """
        if not exp.vehicle_registration:
            return

        vehicle = family_query(Vehicle).filter_by(registration=exp.vehicle_registration).first()
        if not vehicle:
            return

        sentinel = f"Expense #{exp.id}: "
        journey_desc = f"{sentinel}{exp.description or 'Fuel'}"

        existing = family_query(Trip).filter(
            Trip.vehicle_id == vehicle.id,
            Trip.journey_description.like(sentinel + '%')
        ).first()

        miles = int(exp.covered_miles) if exp.covered_miles else 0

        if existing:
            existing.date = exp.date
            existing.month = exp.date.strftime('%Y-%m')
            existing.week = f"{exp.date.isocalendar()[1]:02d}-{exp.date.year}"
            existing.day_name = exp.date.strftime('%A')
            existing.total_miles = miles
            existing.business_miles = miles
            existing.journey_description = journey_desc
            existing.fuel_cost = exp.total_cost
            existing.trip_cost = exp.total_cost
            db.session.add(existing)
        else:
            trip = Trip(
                vehicle_id=vehicle.id,
                family_id=exp.family_id if hasattr(exp, 'family_id') else None,
                date=exp.date,
                month=exp.date.strftime('%Y-%m'),
                week=f"{exp.date.isocalendar()[1]:02d}-{exp.date.year}",
                day_name=exp.date.strftime('%A'),
                total_miles=miles,
                business_miles=miles,
                personal_miles=0,
                journey_description=journey_desc,
                fuel_cost=exp.total_cost,
                trip_cost=exp.total_cost
            )
            db.session.add(trip)

    @staticmethod
    def delete_fuel_trip_for_expense(exp):
        """
        Delete the auto-created Trip row for a Fuel expense (identified by sentinel prefix).
        """
        if not exp.vehicle_registration:
            return

        vehicle = family_query(Vehicle).filter_by(registration=exp.vehicle_registration).first()
        if not vehicle:
            return

        sentinel = f"Expense #{exp.id}: "
        trip = family_query(Trip).filter(
            Trip.vehicle_id == vehicle.id,
            Trip.journey_description.like(sentinel + '%')
        ).first()

        if trip:
            db.session.delete(trip)