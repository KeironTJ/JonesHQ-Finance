"""
Expense Sync Service
====================
Keeps Expense records in sync with their corresponding bank/credit-card transactions
and handles end-of-period reimbursement and CC-payment generation.

Expense lifecycle
-----------------
1. Expense created → ``reconcile()`` creates an immediate Purchase transaction
   (CreditCardTransaction if the expense was paid by card, otherwise a bank Transaction).
2. End of period → ``reconcile_monthly_reimbursements()`` creates a single Expense
   Reimbursement bank Transaction aggregating all expenses in that period.
3. CC payoff → ``reconcile_credit_card_payments()`` creates a CC Payment transaction
   (and matching bank debit) 1 working day after the reimbursement date, covering the
   total card-expense spend for that period.

Period modes
------------
The service respects the ``expenses.period_mode`` setting:
  'calendar_month'  — periods run from the 1st to the last day of each month.
  'payday_period'   — periods follow the configured payday cycle.

Both modes use YYYY-MM as the period key (same format as the payday period label).

Cutoff day (``expenses.cutoff_day``, calendar_month mode only)
--------------------------------------------------------------
When set to a value between 1 and 28, periods are shifted so that expenses on or
after day N belong to the *following* month's period.  The reimbursement date
becomes the cutoff day itself (adjusted forward to a working day if needed).

  cutoff_day=0  (default) — identical to existing calendar_month behaviour.
  cutoff_day=15 — Jan 1–14 → period "2026-01" (reimburse 15 Jan);
                  Jan 15–31 → period "2026-02" (reimburse 15 Feb).

Partial / mid-period claims
---------------------------
``create_partial_reimbursement(from_date, to_date)`` creates a standalone
'Expense Partial Reimbursement' transaction covering any custom date range.
These are not touched by the automatic ``reconcile_monthly_reimbursements`` cycle
and appear alongside normal reimbursements in the expense list.

``auto_sync`` guard
-------------------
Every public write method checks the ``expenses.auto_sync`` setting and returns early
if sync is disabled, so callers don't need to check this themselves.

Primary entry points (called from blueprints)
---------------------------------------------
  reconcile()                       — sync a single expense after create/edit/delete
  reconcile_monthly_reimbursements()— rebuild end-of-period reimbursement transactions
  reconcile_credit_card_payments()  — rebuild per-card payment transactions
  bulk_delete_linked_transactions() — remove all linked bank/CC txns for given expenses
"""
from datetime import datetime, date, timedelta, timezone
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
    """
    Syncs Expense records into linked bank/CC transactions.

    One expense can be linked to at most one immediate transaction
    (expense.bank_transaction_id  OR  expense.credit_card_transaction_id).
    Fuel expenses are a special case: instead of a transaction, a Trip row is created
    and linked via the journey_description sentinel "Expense #<id>: <description>".

    Locking: expense-linked transactions are always created with is_fixed=True so
    regeneration (e.g. credit card regen) cannot delete them.
    """

    @staticmethod
    def reconcile(expense_id):
        """
        Create or update the immediate payment transaction for a single expense.

        Dispatches based on expense type:
          - 'Fuel' → creates/updates a Trip row (no bank/CC transaction).
          - Expense with credit_card_id → creates/updates a CreditCardTransaction
            (type='Purchase', is_fixed=True).
          - All others → creates/updates a bank Transaction (payment_type='Work Expense').

        Does nothing if ``expenses.auto_sync`` is disabled in settings.

        Args:
            expense_id: ID of the Expense to reconcile.

        Side effects:
            Commits the session.  Rolls back on exception and re-raises.
        """
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
    def get_cutoff_day():
        """
        Return the monthly cutoff day (1-28) used in 'calendar_month' mode.
        0 (default) means the last day of the month.
        """
        return Settings.get_value('expenses.cutoff_day', 0)

    @staticmethod
    def get_period_key_for_expense(exp):
        """
        Return the period key (YYYY-MM) that this expense belongs to under the current mode.
        Always derived from exp.date so it is resilient to NULL Expense.month fields.

        With cutoff_day=D (calendar_month mode):
          - expense date.day < D  → belongs to THIS month's period (YYYY-MM)
          - expense date.day >= D → belongs to NEXT month's period
        """
        if not exp.date:
            return None
        mode = ExpenseSyncService.get_period_mode()
        if mode == 'payday_period':
            return PaydayService.get_period_for_date(exp.date)
        # calendar_month: respect cutoff_day setting
        cutoff = ExpenseSyncService.get_cutoff_day()
        if cutoff > 0:
            if exp.date.day >= cutoff:
                # Expense falls on/after the cutoff → belongs to next month's period
                if exp.date.month == 12:
                    return f"{exp.date.year + 1}-01"
                return f"{exp.date.year}-{exp.date.month + 1:02d}"
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
                result = ExpenseSyncService._create_period_reimbursement(period_key)
                if result:
                    txn_id, changed = result
                    if changed:
                        results[period_key] = txn_id

            db.session.commit()
            return results
        except Exception:
            db.session.rollback()
            raise
    
    @staticmethod
    def reconcile_credit_card_payments(year_month=None):
        """
        Create or update CC Payment transactions funded by expense reimbursements.

        For each reimbursement transaction, groups CC expenses for that period by card
        and creates one CC Payment + linked bank debit per card (1 working day after the
        reimbursement date).  Skips periods/cards where the payment is already is_paid.

        Args:
            year_month: YYYY-MM period key to restrict to one period.
                        If None, processes all reimbursement transactions.

        Returns:
            dict mapping card_id → CreditCardTransaction.id for each payment created
            or updated.  Only changed records are included.

        Side effects:
            Commits the session.  Rolls back on exception and re-raises.
            Calls recalculate_account_balance() and recalculate_card_balance().
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
                        result = ExpenseSyncService._create_cc_payment_from_reimbursement(
                            card_id, total, payment_date, period_key
                        )
                        if result:
                            payment_txn_id, changed = result
                            current_app.logger.info(f'  → payment_txn_id={payment_txn_id} changed={changed}')
                            if changed:
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
    def create_partial_reimbursement(from_date, to_date, reimbursement_date=None):
        """
        Create (or update) a partial reimbursement transaction covering a custom date range.

        This is used for mid-period claims — e.g., generating a reimbursement for the
        first two weeks of a month rather than waiting for the full period to close.

        The transaction uses payment_type='Expense Partial Reimbursement' so the standard
        ``reconcile_monthly_reimbursements`` cycle does not overwrite it.

        Args:
            from_date:          First day of expenses to include (inclusive).
            to_date:            Last day of expenses to include (inclusive).
            reimbursement_date: Date to stamp on the reimbursement transaction.
                                Defaults to ``to_date`` adjusted to the next working day.

        Returns:
            (transaction_id, total_amount, claim_group) tuple, or None if no unclaimed
            expenses found in the date range.

        Side effects:
            Stamps ``claim_group`` on every covered expense.
            Commits the session on success.  Rolls back on failure and re-raises.
        """
        try:
            # Include expenses that are either:
            #   (a) not yet assigned to any claim group (claim_group is NULL), or
            #   (b) assigned to a full-period group (YYYY-MM, no -P suffix) meaning a
            #       full sync has run but no partial has claimed them yet.
            # Expenses already in a partial group (YYYY-MM-P*) are excluded.
            all_in_range = family_query(Expense).filter(
                Expense.date >= from_date,
                Expense.date <= to_date
            ).all()

            unclaimed = [
                exp for exp in all_in_range
                if exp.claim_group is None or '-P' not in exp.claim_group
            ]

            # Sort unclaimed so the earliest date determines the base period.
            unclaimed.sort(key=lambda e: e.date or date.min)

            if not unclaimed:
                return None

            total = sum(exp.total_cost for exp in unclaimed if exp.total_cost)
            if not total or total <= 0:
                return None

            if reimbursement_date is None:
                reimbursement_date = ExpenseSyncService._on_or_next_working_day(to_date)

            # Base period from the earliest expense in the range.
            base_period = unclaimed[0].date.strftime('%Y-%m')

            # Auto-number the partial suffix by counting distinct claim_groups already
            # used for this base period on the expenses table.  This is reliable even
            # when the reimbursement date falls in a different calendar month.
            existing_partial_count = (
                family_query(Expense)
                .filter(Expense.claim_group.like(f'{base_period}-P%'))
                .with_entities(Expense.claim_group)
                .distinct()
                .count()
            )
            partial_number = existing_partial_count + 1
            claim_group = f'{base_period}-P{partial_number}'

            description = (
                f'Expense Reimbursement {from_date.strftime("%d %b %Y")}'
                f' to {to_date.strftime("%d %b %Y")} ({claim_group})'
            )
            # year_month on the partial transaction = base_period so that partial
            # number counting is always consistent, regardless of whether the
            # reimbursement date falls in a different calendar month.
            txn_year_month = base_period

            # Stamp claim_group on every expense being claimed
            for exp in unclaimed:
                exp.claim_group = claim_group
                db.session.add(exp)

            # Resolve account
            acct_id = Settings.get_value('expenses.payment_account_id')
            account = family_get(Account, int(acct_id)) if acct_id else None
            if not account:
                account = family_query(Account).order_by(Account.name).first()
            if not account:
                raise ValueError('No account configured — set expenses.payment_account_id in Settings.')

            # Resolve category
            cat_id = Settings.get_value('expenses.reimburse_category_id')
            reimburse_cat = family_get(Category, int(cat_id)) if cat_id else None
            if not reimburse_cat:
                reimburse_cat = (
                    family_query(Category).filter_by(head_budget='Income', sub_budget='Expense').first()
                    or family_query(Category).filter_by(head_budget='Expenses').first()
                    or family_query(Category).first()
                )

            vendor_id_setting = Settings.get_value('expenses.reimburse_vendor_id')
            reimburse_vendor_id = int(vendor_id_setting) if vendor_id_setting else None

            partial_txn = Transaction(
                family_id=get_family_id(),
                account_id=account.id,
                category_id=reimburse_cat.id if reimburse_cat else None,
                vendor_id=reimburse_vendor_id,
                amount=total,
                transaction_date=reimbursement_date,
                description=description,
                item=description,
                payment_type='Expense Partial Reimbursement',
                is_paid=False,
                year_month=txn_year_month,
                week_year=f"{reimbursement_date.isocalendar()[1]:02d}-{reimbursement_date.year}",
                day_name=reimbursement_date.strftime('%A'),
                payday_period=PaydayService.get_period_for_date(reimbursement_date)
            )
            db.session.add(partial_txn)
            db.session.flush()
            Transaction.recalculate_account_balance(account.id)
            db.session.commit()

            # After committing the partial, re-sync the base period reimbursement so it
            # is updated to exclude the expenses now assigned to the partial group.
            try:
                ExpenseSyncService._create_period_reimbursement(base_period)
                db.session.commit()
            except Exception:
                db.session.rollback()
                # Non-fatal — the partial was created successfully; the base period
                # reimbursement will be corrected on the next full sync.

            return partial_txn.id, total, claim_group

        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def _ensure_credit_card_payment(exp: Expense):
        """
        Create or update the immediate CC Purchase transaction for an expense.

        Searches for an existing transaction via expense.credit_card_transaction_id first,
        then falls back to matching on (card, date, item description).  Updates amount and
        type if changed; always locks the record (is_fixed=True).  Links the expense to the
        transaction via expense.credit_card_transaction_id.

        Does nothing if exp.total_cost is falsy or the CC cannot be found.
        """
        if not exp.total_cost:
            return
        cc = family_get(CreditCard, exp.credit_card_id)
        if not cc:
            return

        # Credit card purchase = negative amount
        target_amount = -abs(float(exp.total_cost))

        # Look for existing transaction — prefer the stored link, fall back to description match
        existing = None
        if exp.credit_card_transaction_id:
            existing = family_query(CreditCardTransaction).filter_by(
                id=exp.credit_card_transaction_id
            ).first()
        if not existing:
            existing = family_query(CreditCardTransaction).filter_by(
                credit_card_id=cc.id,
                date=exp.date,
                item=exp.description
            ).first()

        if existing:
            # Update if amount or type changed; always ensure is_fixed=True
            updated = False
            if abs(existing.amount - Decimal(str(target_amount))) > Decimal('0.01'):
                existing.amount = Decimal(str(target_amount))
                updated = True
            if existing.transaction_type != 'Purchase':
                existing.transaction_type = 'Purchase'
                updated = True
            if not existing.is_fixed:
                existing.is_fixed = True  # Lock existing records that weren't previously locked
                updated = True
            if updated:
                existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
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
                is_paid=False,
                is_fixed=True  # Expense-linked purchases must never be deleted by regeneration
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
        """
        Create or update a bank Transaction for a directly-paid expense.

        Account lookup order: exp.account_id → expenses.payment_account_id setting
        → first account alphabetically.  Category and vendor come from the
        expenses.reimburse_category_id / expenses.reimburse_vendor_id settings with
        name-based fallbacks.

        Searches for an existing transaction via expense.bank_transaction_id first,
        then by (account, date, description, payment_type='Work Expense').  Updates
        amount if changed.  Links the expense via expense.bank_transaction_id.

        Does nothing if exp.total_cost is falsy or no account can be resolved.
        """
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

        # Look for existing transaction — prefer the stored link, fall back to description match
        existing = None
        if exp.bank_transaction_id:
            existing = family_query(Transaction).filter_by(
                id=exp.bank_transaction_id
            ).first()
        if not existing:
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
                existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
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
            If cutoff_day=D: start = D of previous month, end = (D-1) of this month
          'payday_period'  → PaydayService start/end for that payday period
        Raises ValueError if period_key is malformed.
        """
        import calendar as _cal
        year, month = map(int, period_key.split('-'))
        mode = ExpenseSyncService.get_period_mode()
        if mode == 'payday_period':
            start_date, end_date, _ = PaydayService.get_payday_period(year, month)
            return start_date, end_date
        # calendar_month: respect cutoff_day setting
        cutoff = ExpenseSyncService.get_cutoff_day()
        if cutoff > 0:
            prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
            # Clamp cutoff to valid day in previous month
            prev_max = _cal.monthrange(prev_year, prev_month)[1]
            start_date = date(prev_year, prev_month, min(cutoff, prev_max))
            # End is the day before cutoff in the current month; if cutoff=1, end = last day of prev month
            end_date = (
                date(year, month, 1) - timedelta(days=1)
                if cutoff == 1
                else date(year, month, cutoff - 1)
            )
            return start_date, end_date
        # Default: full calendar month
        return date(year, month, 1), date(year, month, _cal.monthrange(year, month)[1])

    @staticmethod
    def _get_reimbursement_date(period_key):
        """
        Return the date on which the reimbursement transaction should be placed:
          'calendar_month' → last working day of that calendar month
            If cutoff_day=D: the cutoff day itself (adjusted to a working day)
          'payday_period'  → last working day on or before the payday period's end date
        """
        import calendar as _cal
        year, month = map(int, period_key.split('-'))
        mode = ExpenseSyncService.get_period_mode()
        if mode == 'payday_period':
            _, end_date, _ = PaydayService.get_payday_period(year, month)
            return PaydayService.get_previous_working_day(end_date)
        cutoff = ExpenseSyncService.get_cutoff_day()
        if cutoff > 0:
            max_day = _cal.monthrange(year, month)[1]
            raw = date(year, month, min(cutoff, max_day))
            return ExpenseSyncService._on_or_next_working_day(raw)
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

        # Only include expenses that have NOT been claimed in a partial group.
        # An expense belongs to this full-period claim if:
        #   claim_group is NULL (never assigned) OR claim_group == period_key exactly.
        all_period_expenses = family_query(Expense).filter(
            Expense.date >= period_start,
            Expense.date <= period_end
        ).all()

        expenses = [
            exp for exp in all_period_expenses
            if exp.claim_group is None or exp.claim_group == period_key
        ]

        if not expenses:
            # All expenses in this period have been claimed by partials.
            # Remove the stale full-period reimbursement txn if it exists and is not yet paid.
            stale = family_query(Transaction).filter(
                Transaction.payment_type == 'Expense Reimbursement',
                Transaction.year_month == period_key
            ).first()
            if stale and not stale.is_paid:
                acct_id_for_del = stale.account_id
                db.session.delete(stale)
                db.session.flush()
                if acct_id_for_del:
                    Transaction.recalculate_account_balance(acct_id_for_del)
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
            if existing.is_paid:
                # Locked — do not stamp claim_group or modify anything
                return existing.id, False
            # Also locked if every expense in the full-period group is already reimbursed
            if expenses and all(exp.reimbursed for exp in expenses):
                return existing.id, False

        # Stamp claim_group on any unclaimed expenses so they are locked from future partials.
        # Only done here, after confirming the period is not already settled.
        for exp in expenses:
            if exp.claim_group is None:
                exp.claim_group = period_key
                db.session.add(exp)

        if existing:
            if abs(existing.amount - total_reimbursement) > Decimal('0.01'):
                existing.amount = total_reimbursement
                existing.transaction_date = reimbursement_date
                existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.session.add(existing)
                db.session.flush()
                Transaction.recalculate_account_balance(existing.account_id)
                return existing.id, True
            return existing.id, False

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
        return reimburse_txn.id, True

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
    def _on_or_next_working_day(d):
        """Return d if it is Mon–Fri, otherwise the next working day after d."""
        while d.weekday() > 4:  # Sat=5, Sun=6
            d += timedelta(days=1)
        return d

    @staticmethod
    def _next_working_day(d):
        """Return the next Monday-Friday on or after the day after d."""
        next_day = d + timedelta(days=1)
        while next_day.weekday() > 4:
            next_day += timedelta(days=1)
        return next_day

    @staticmethod
    def _create_cc_payment_from_reimbursement(card_id, total, payment_date, period_key):
        """
        Create (or update) a CC Payment + linked bank debit for one card's expenses in a period.

        Looks for an existing Payment matching (card_id, type='Payment', item LIKE %period_key%).
        If found and is_paid, skips (returns id, False).  If found and changed, updates amount/date.
        Otherwise creates new CC Payment (is_fixed=True) and a matching bank debit, linking them.

        Account for bank debit: card.default_payment_account_id →
        expenses.payment_account_id setting.

        Returns:
            (CreditCardTransaction.id, changed: bool) or None if card not found.
        """
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
            if existing.is_paid:
                # Locked — do not modify a paid/reconciled CC payment
                return existing.id, False
            updated = False
            if abs(existing.amount - total) > Decimal('0.01'):
                existing.amount = total
                existing.date = payment_date
                existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                updated = True
                # Also update the linked bank transaction amount/date if present
                if existing.bank_transaction_id:
                    bank_txn = family_query(Transaction).filter_by(
                        id=existing.bank_transaction_id
                    ).first()
                    if bank_txn and not bank_txn.is_paid:
                        bank_txn.amount = -abs(total)
                        bank_txn.transaction_date = payment_date
                        bank_txn.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                        db.session.add(bank_txn)
            if not existing.is_fixed:
                existing.is_fixed = True  # Lock existing records that weren't previously locked
                updated = True
            if updated:
                db.session.add(existing)
                return existing.id, True
            return existing.id, False

        # --- Resolve category (used by both CC txn and bank txn) ---
        cat = family_query(Category).filter_by(
            head_budget='Credit Cards',
            sub_budget=cc.card_name
        ).first()
        if not cat:
            cat = Category(
                family_id=get_family_id(),
                head_budget='Credit Cards',
                sub_budget=cc.card_name,
                category_type='expense'
            )
            db.session.add(cat)
            db.session.flush()

        # --- Build the linked bank account transaction ---
        bank_txn = None
        payment_account_id = cc.default_payment_account_id if cc.default_payment_account_id else None
        if not payment_account_id:
            # Fall back to the configured expense payment account
            acct_id = Settings.get_value('expenses.payment_account_id')
            payment_account_id = int(acct_id) if acct_id else None

        if payment_account_id:
            # Vendor: use the card's own name (create if missing)
            vendor = family_query(Vendor).filter_by(name=cc.card_name).first()
            if not vendor:
                vendor = Vendor(name=cc.card_name, family_id=get_family_id())
                db.session.add(vendor)
                db.session.flush()

            year_month = payment_date.strftime('%Y-%m')
            week_year  = f"{payment_date.isocalendar()[1]:02d}-{payment_date.year}"
            day_name   = payment_date.strftime('%A')

            bank_txn = Transaction(
                family_id=get_family_id(),
                account_id=payment_account_id,
                category_id=cat.id,
                vendor_id=vendor.id,
                amount=-abs(total),  # Negative — money leaving the account
                transaction_date=payment_date,
                description=description,
                item='Credit Card Payment',
                payment_type='Transfer',
                is_paid=False,
                credit_card_id=card_id,
                year_month=year_month,
                week_year=week_year,
                day_name=day_name,
                payday_period=PaydayService.get_period_for_date(payment_date)
            )
            db.session.add(bank_txn)
            db.session.flush()
            Transaction.recalculate_account_balance(payment_account_id)

        payment_txn = CreditCardTransaction(
            family_id=get_family_id(),
            credit_card_id=card_id,
            category_id=cat.id,
            date=payment_date,
            day_name=payment_date.strftime('%A'),
            week=f"{payment_date.isocalendar()[1]:02d}-{payment_date.year}",
            month=payment_date.strftime('%Y-%m'),
            transaction_type='Payment',
            item=description,
            amount=total,
            is_paid=False,
            is_fixed=True,  # Expense-linked payments must never be deleted by regeneration
            bank_transaction_id=bank_txn.id if bank_txn else None
        )
        db.session.add(payment_txn)
        db.session.flush()
        CreditCardTransaction.recalculate_card_balance(card_id)
        return payment_txn.id, True

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

        from services.vehicle_service import VehicleService
        trip_cost, gallons_used, approx_mpg = VehicleService.calculate_trip_cost(vehicle.id, miles, exp.date)

        if existing:
            existing.date = exp.date
            existing.month = exp.date.strftime('%Y-%m')
            existing.week = f"{exp.date.isocalendar()[1]:02d}-{exp.date.year}"
            existing.day_name = exp.date.strftime('%A')
            existing.total_miles = miles
            existing.business_miles = miles
            existing.journey_description = journey_desc
            existing.fuel_cost = exp.total_cost
            existing.trip_cost = trip_cost
            existing.gallons_used = gallons_used
            existing.approx_mpg = approx_mpg
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
                trip_cost=trip_cost,
                gallons_used=gallons_used,
                approx_mpg=approx_mpg
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