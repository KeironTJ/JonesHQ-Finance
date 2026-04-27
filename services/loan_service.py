"""
Loan Service
============
Amortization schedule generation and bank-transaction linking for personal loans.

Amortization schedule
---------------------
Each Loan gets a series of LoanPayment records computed by the standard
amortization formula (fixed monthly payment = principal + interest).

  Period 0  — opening-balance record (payment_amount=0, is_paid=True); created once.
  Period 1+ — monthly payment records (is_paid=False by default).

If the loan has a ``default_payment_account_id``, a matching bank Transaction
(payment_type='Direct Debit') is created for every period >= 1 and linked via
loan_payment.bank_transaction_id.

Weekend adjustment
------------------
Each Loan has a ``weekend_adjustment`` field ('previous', 'next', or 'none').
When a computed payment date falls on a Saturday or Sunday:
  'previous' — roll back to the preceding Friday
  'next'     — roll forward to the following Monday
  'none'     — leave the date unchanged

Term changes
------------
When loan terms change mid-course (payment amount, APR, payment day, or term
extension), ``apply_term_change()`` records the change in ``LoanTermChange``,
updates the ``Loan`` fields, then deletes and regenerates all future unpaid
payments from the effective date onward.

Primary entry points
--------------------
  generate_amortization_schedule() — create LoanPayment records for a loan
  generate_payment_transaction()   — create a bank Transaction for one payment
  regenerate_schedule()            — delete future payments and regenerate
  apply_term_change()              — record a term change and re-generate schedule
  update_future_payment_dates()    — shift payment day-of-month for unpaid payments
  get_payment_statistics()         — summary counts and totals (paid/unpaid)
"""
from models.loans import Loan
from models.loan_payments import LoanPayment
from models.loan_term_changes import LoanTermChange
from models.transactions import Transaction
from models.vendors import Vendor
from services.payday_service import PaydayService
from extensions import db
from datetime import datetime
from dateutil.relativedelta import relativedelta
from decimal import Decimal
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


class LoanService:
    """
    Loan amortization schedule generation and payment-transaction management.

    Each Loan has a fixed monthly_payment and a monthly_apr (stored as a percentage).
    The service computes the interest and principal split for each month and creates
    LoanPayment records.  If the loan has a default_payment_account_id, a matching
    bank Transaction is created per payment period (>= 1).
    """

    # ------------------------------------------------------------------
    # Weekend adjustment
    # ------------------------------------------------------------------

    @staticmethod
    def _adjust_for_weekend(date_obj, adjustment):
        """
        Adjust a date if it falls on a weekend, according to the loan's rule.

        Args:
            date_obj:   datetime.date to check.
            adjustment: 'previous' — roll back to Friday
                        'next'     — roll forward to Monday
                        'none'     — leave unchanged

        Returns:
            datetime.date (possibly unchanged).
        """
        if adjustment == 'none' or not PaydayService.is_weekend(date_obj):
            return date_obj
        if adjustment == 'previous':
            return PaydayService.get_previous_working_day(date_obj)
        if adjustment == 'next':
            return PaydayService.get_next_working_day(date_obj)
        return date_obj
    
    @staticmethod
    def generate_amortization_schedule(loan_id, start_date=None, end_date=None, commit=True):
        """
        Generate LoanPayment records for a loan across its amortization term.

        Period 0 — opening-balance record (payment_amount=0, is_paid=True); created
                   only when no prior payments exist for the loan.
        Period 1+ — monthly payment records computed as:
                     interest_charge  = opening_balance × monthly_apr
                     amount_paid_off  = monthly_payment - interest_charge
                     closing_balance  = opening_balance - amount_paid_off
                   The final payment adjusts to clear the exact remaining balance.

        Skips months that already have a LoanPayment record.  Stops when
        closing_balance <= £0.01 or end_date is reached.

        After creating payments, generates a bank Transaction per period (>= 1) if
        loan.default_payment_account_id is set, then updates loan.current_balance.

        Args:
            loan_id:    ID of the Loan.
            start_date: First period date (defaults to loan.start_date).
            end_date:   Last period date (defaults to loan.end_date).
            commit:     Whether to commit and create bank transactions (default True).

        Returns:
            list[LoanPayment] — the payment records created.
        """
        loan = family_get(Loan, loan_id)
        if not loan:
            return None
        
        # Use loan's start_date if not provided
        if start_date is None:
            start_date = loan.start_date
        
        # Use loan's end_date if not provided
        if end_date is None:
            end_date = loan.end_date
        
        # Get opening balance (either from last payment or loan value)
        last_payment = family_query(LoanPayment).filter_by(loan_id=loan_id)\
            .filter(LoanPayment.date < start_date)\
            .order_by(LoanPayment.date.desc()).first()
        
        if last_payment:
            opening_balance = last_payment.closing_balance
            period = last_payment.period + 1
            create_opening_record = False  # Already have history
        else:
            opening_balance = loan.loan_value
            period = 0  # Start with opening balance
            create_opening_record = True
        
        current_date = start_date
        payments_created = []
        
        # Weekend adjustment rule for this loan
        weekend_adj = getattr(loan, 'weekend_adjustment', 'none') or 'none'

        # Create Period 0 - Opening Balance (if first time)
        if create_opening_record:
            existing = family_query(LoanPayment).filter_by(
                loan_id=loan_id,
                date=current_date,
                period=0
            ).first()
            
            if not existing:
                opening_payment = LoanPayment(
                    loan_id=loan_id,
                    date=current_date,
                    year_month=current_date.strftime('%Y-%m'),
                    period=0,
                    opening_balance=opening_balance,
                    payment_amount=Decimal('0.00'),
                    interest_charge=Decimal('0.00'),
                    amount_paid_off=Decimal('0.00'),
                    closing_balance=opening_balance,
                    is_paid=True  # Opening balance is always "paid" (it's just a record)
                )
                
                db.session.add(opening_payment)
                payments_created.append(opening_payment)
            
            # Move to next month for first actual payment
            current_date = current_date + relativedelta(months=1)
            period = 1
        
        # Create actual payment schedule
        while current_date <= end_date and opening_balance > Decimal('0.01'):  # Continue until balance is essentially zero
            # Apply weekend adjustment to the raw calendar date
            adjusted_date = LoanService._adjust_for_weekend(current_date, weekend_adj)

            # Check if payment already exists for this adjusted date or raw date
            existing = family_query(LoanPayment).filter_by(
                loan_id=loan_id,
                date=adjusted_date
            ).first()
            if not existing:
                existing = family_query(LoanPayment).filter_by(
                    loan_id=loan_id,
                    date=current_date
                ).first()
            
            if not existing:
                # Calculate interest charge for this period
                monthly_apr_decimal = Decimal(str(loan.monthly_apr)) / Decimal('100')
                interest_charge = opening_balance * monthly_apr_decimal
                interest_charge = interest_charge.quantize(Decimal('0.01'))
                
                # Calculate principal paid off
                payment_amount = Decimal(str(loan.monthly_payment))
                amount_paid_off = payment_amount - interest_charge
                
                # Calculate closing balance
                closing_balance = opening_balance - amount_paid_off
                
                # Handle final payment or overpayment
                if closing_balance < Decimal('0.00') or current_date == end_date:
                    # This is the final payment - pay off exact remaining balance
                    amount_paid_off = opening_balance
                    payment_amount = amount_paid_off + interest_charge
                    closing_balance = Decimal('0.00')
                
                # Round to avoid floating point issues
                closing_balance = closing_balance.quantize(Decimal('0.01'))
                
                # Create payment record
                payment = LoanPayment(
                    loan_id=loan_id,
                    date=adjusted_date,
                    year_month=adjusted_date.strftime('%Y-%m'),
                    period=period,
                    opening_balance=opening_balance,
                    payment_amount=payment_amount,
                    interest_charge=interest_charge,
                    amount_paid_off=amount_paid_off,
                    closing_balance=closing_balance,
                    is_paid=False
                )
                
                db.session.add(payment)
                payments_created.append(payment)
                
                # Update for next iteration
                opening_balance = closing_balance
                period += 1
            
            # Move to next month
            current_date = current_date + relativedelta(months=1)
        
        if commit:
            db.session.commit()
            
            # Auto-generate bank transactions if default payment account is set
            # Skip Period 0 (opening balance) - only create transactions for actual payments
            if loan.default_payment_account_id:
                for payment in payments_created:
                    if payment.period > 0:  # Skip Period 0 (opening balance)
                        LoanService.generate_payment_transaction(
                            loan_id=loan_id,
                            payment_id=payment.id,
                            commit=False
                        )
            
            # Update loan's current balance
            loan.current_balance = opening_balance
            db.session.commit()
        
        return payments_created
    
    @staticmethod
    def generate_payment_transaction(loan_id, payment_id, commit=True):
        """
        Create a bank Transaction for one LoanPayment and link the two records.

        Skips if loan has no default_payment_account_id, or if the payment already
        has a bank_transaction_id.  Gets/creates a "Loans > {loan.name}" category
        and a Vendor named after the loan.

        Args:
            loan_id:    ID of the Loan.
            payment_id: ID of the LoanPayment to generate a transaction for.
            commit:     Whether to commit and call recalculate_account_balance() (default True).

        Returns:
            Transaction — the bank transaction (new or existing), or None.
        """
        from models.categories import Category
        
        loan = family_get(Loan, loan_id)
        if not loan or not loan.default_payment_account_id:
            return None
        
        # Get the loan payment
        loan_payment = family_get(LoanPayment, payment_id)
        if not loan_payment:
            return None
        
        # Check if bank transaction already linked
        if loan_payment.bank_transaction_id:
            return family_get(Transaction, loan_payment.bank_transaction_id)
        
        # Get or create "Loans > {LoanName}" category
        loan_category = family_query(Category).filter_by(
            head_budget='Loans',
            sub_budget=loan.name
        ).first()
        
        if not loan_category:
            loan_category = Category(
                head_budget='Loans',
                sub_budget=loan.name,
                category_type='expense'
            )
            db.session.add(loan_category)
            db.session.flush()
        
        # Find or create vendor for this loan
        vendor = family_query(Vendor).filter_by(name=loan.name).first()
        if not vendor:
            vendor = Vendor(name=loan.name)
            db.session.add(vendor)
            db.session.flush()
        
        # Calculate computed fields
        payday_period = PaydayService.get_period_for_date(loan_payment.date)
        year_month = loan_payment.date.strftime('%Y-%m')
        week_year = f"{loan_payment.date.isocalendar()[1]:02d}-{loan_payment.date.year}"
        day_name = loan_payment.date.strftime('%a')
        
        # Create bank transaction
        bank_txn = Transaction(
            account_id=loan.default_payment_account_id,
            category_id=loan_category.id,
            loan_id=loan_id,
            vendor_id=vendor.id,
            transaction_date=loan_payment.date,
            amount=-float(loan_payment.payment_amount),  # Negative = expense (money out)
            description=f"Loan Payment - {loan.name}",
            item=f"Period {loan_payment.period}",
            payment_type='Direct Debit',
            is_paid=loan_payment.is_paid,
            year_month=year_month,
            week_year=week_year,
            day_name=day_name,
            payday_period=payday_period
        )
        
        db.session.add(bank_txn)
        db.session.flush()  # Get the transaction ID
        
        # Link the payment to the bank transaction
        loan_payment.bank_transaction_id = bank_txn.id
        
        if commit:
            db.session.commit()
            # Recalculate bank account balance
            Transaction.recalculate_account_balance(loan.default_payment_account_id)
        
        return bank_txn

    @staticmethod
    def delete_future_payments(loan_id, from_date, commit=True):
        """
        Delete all unpaid loan payments from from_date onward, including their
        linked bank transactions.  Account balances are recalculated after delete.
        """
        payments = family_query(LoanPayment).filter(
            LoanPayment.loan_id == loan_id,
            LoanPayment.date >= from_date
        ).all()

        account_ids = set()
        for payment in payments:
            if payment.bank_transaction_id:
                bank_txn = family_get(Transaction, payment.bank_transaction_id)
                if bank_txn:
                    if bank_txn.account_id:
                        account_ids.add(bank_txn.account_id)
                    db.session.delete(bank_txn)
            db.session.delete(payment)

        if commit:
            db.session.commit()
            for account_id in account_ids:
                Transaction.recalculate_account_balance(account_id)

        return len(payments)
    
    @staticmethod
    def regenerate_schedule(loan_id, from_date=None, end_date=None):
        """
        Regenerate amortization schedule from a specific date
        Deletes existing future payments and regenerates
        """
        loan = family_get(Loan, loan_id)
        if not loan:
            return None
        
        if from_date is None:
            from_date = datetime.now().date()
        
        if end_date is None:
            end_date = loan.end_date
        
        # Delete future payments
        deleted_count = LoanService.delete_future_payments(loan_id, from_date, commit=False)
        
        # Regenerate schedule
        payments = LoanService.generate_amortization_schedule(
            loan_id, 
            start_date=from_date,
            end_date=end_date,
            commit=True
        )
        
        return {
            'deleted': deleted_count,
            'created': len(payments)
        }
    
    @staticmethod
    def calculate_total_interest(loan_id):
        """Calculate total interest paid/to be paid over life of loan"""
        payments = family_query(LoanPayment).filter_by(loan_id=loan_id).all()
        total_interest = sum(float(p.interest_charge) for p in payments)
        return total_interest
    
    @staticmethod
    def calculate_remaining_balance(loan_id):
        """Get the most recent closing balance from paid payments only"""
        last_payment = family_query(LoanPayment).filter_by(loan_id=loan_id, is_paid=True)\
            .order_by(LoanPayment.date.desc(), LoanPayment.id.desc()).first()
        
        if last_payment:
            return float(last_payment.closing_balance)
        
        loan = family_get(Loan, loan_id)
        return float(loan.loan_value) if loan else 0.0
    
    @staticmethod
    def update_future_payment_dates(loan_id, new_day, from_date=None, commit=True):
        """
        Update the day-of-month for all future (unpaid) loan payment records.

        For each unpaid LoanPayment on or after ``from_date``, its date is moved to
        ``new_day`` of the same month (clamped to the last day of that month when the
        month is shorter, e.g. day 31 in February → 28/29).  The linked bank
        Transaction (if any) is updated in-step so both records stay in sync.

        Args:
            loan_id:   ID of the Loan.
            new_day:   Target day-of-month (1–31).
            from_date: Earliest payment date to update (defaults to today).
            commit:    Whether to commit the changes (default True).

        Returns:
            int — number of payment records updated.
        """
        import calendar as cal_mod
        from services.payday_service import PaydayService

        if from_date is None:
            from_date = datetime.now().date()

        new_day = max(1, min(31, int(new_day)))

        future_payments = (
            family_query(LoanPayment)
            .filter(
                LoanPayment.loan_id == loan_id,
                LoanPayment.is_paid == False,
                LoanPayment.period > 0,
                LoanPayment.date >= from_date,
            )
            .order_by(LoanPayment.date)
            .all()
        )

        updated = 0
        loan = family_get(Loan, loan_id)
        weekend_adj = getattr(loan, 'weekend_adjustment', 'none') or 'none'

        for payment in future_payments:
            # Clamp day to last day of month
            max_day = cal_mod.monthrange(payment.date.year, payment.date.month)[1]
            actual_day = min(new_day, max_day)
            new_date = payment.date.replace(day=actual_day)

            # Apply weekend adjustment
            new_date = LoanService._adjust_for_weekend(new_date, weekend_adj)

            payment.date = new_date
            payment.year_month = new_date.strftime('%Y-%m')

            # Sync linked bank transaction
            if payment.bank_transaction_id:
                bank_txn = family_get(Transaction, payment.bank_transaction_id)
                if bank_txn:
                    bank_txn.transaction_date = new_date
                    bank_txn.year_month = new_date.strftime('%Y-%m')
                    bank_txn.week_year = f"{new_date.isocalendar()[1]:02d}-{new_date.year}"
                    bank_txn.day_name = new_date.strftime('%a')
                    bank_txn.payday_period = PaydayService.get_period_for_date(new_date)

            updated += 1

        if commit and updated:
            db.session.commit()
            # Recalculate balances for any affected accounts
            account_ids = set()
            for payment in future_payments:
                if payment.bank_transaction_id:
                    bank_txn = family_get(Transaction, payment.bank_transaction_id)
                    if bank_txn and bank_txn.account_id:
                        account_ids.add(bank_txn.account_id)
            for account_id in account_ids:
                Transaction.recalculate_account_balance(account_id)

        return updated

    @staticmethod
    def get_payment_statistics(loan_id):
        """Get statistics about loan payments"""
        payments = family_query(LoanPayment).filter_by(loan_id=loan_id).all()
        
        if not payments:
            return {
                'total_payments': 0,
                'paid_count': 0,
                'unpaid_count': 0,
                'total_interest_scheduled': 0.0,
                'total_principal_scheduled': 0.0,
                'total_amount_scheduled': 0.0,
                'total_interest_paid': 0.0,
                'total_principal_paid': 0.0,
                'total_amount_paid': 0.0,
                'remaining_interest': 0.0,
                'remaining_principal': 0.0,
                'remaining_amount': 0.0
            }
        
        paid = [p for p in payments if p.is_paid]
        unpaid = [p for p in payments if not p.is_paid]
        
        # Scheduled totals (all payments)
        total_interest_scheduled = sum(float(p.interest_charge) for p in payments)
        total_principal_scheduled = sum(float(p.amount_paid_off) for p in payments)
        total_amount_scheduled = sum(float(p.payment_amount) for p in payments)
        
        # Paid totals (only paid payments)
        total_interest_paid = sum(float(p.interest_charge) for p in paid)
        total_principal_paid = sum(float(p.amount_paid_off) for p in paid)
        total_amount_paid = sum(float(p.payment_amount) for p in paid)
        
        # Remaining totals (only unpaid payments)
        remaining_interest = sum(float(p.interest_charge) for p in unpaid)
        remaining_principal = sum(float(p.amount_paid_off) for p in unpaid)
        remaining_amount = sum(float(p.payment_amount) for p in unpaid)
        
        return {
            'total_payments': len(payments),
            'paid_count': len(paid),
            'unpaid_count': len(unpaid),
            'total_interest_scheduled': total_interest_scheduled,
            'total_principal_scheduled': total_principal_scheduled,
            'total_amount_scheduled': total_amount_scheduled,
            'total_interest_paid': total_interest_paid,
            'total_principal_paid': total_principal_paid,
            'total_amount_paid': total_amount_paid,
            'remaining_interest': remaining_interest,
            'remaining_principal': remaining_principal,
            'remaining_amount': remaining_amount
        }

    @staticmethod
    def apply_term_change(
        loan_id,
        effective_date,
        new_monthly_payment=None,
        new_annual_apr=None,
        new_payment_day=None,
        new_term_months=None,
        notes=None,
    ):
        """
        Record a mid-loan term change and regenerate future payments.

        Captures the previous values from the Loan record, applies the requested
        changes to the Loan, writes a ``LoanTermChange`` history record, then deletes
        all unpaid payments on or after ``effective_date`` and regenerates the
        amortization schedule from that point using the updated terms.

        At least one of the ``new_*`` kwargs must differ from the current value.

        Args:
            loan_id:              ID of the Loan.
            effective_date:       datetime.date — first month the new terms apply.
            new_monthly_payment:  New fixed monthly payment amount (Decimal/float/str),
                                  or None to leave unchanged.
            new_annual_apr:       New annual APR percentage, or None to leave unchanged.
            new_payment_day:      New day-of-month (1–31) for payments, or None to
                                  leave unchanged.
            new_term_months:      New total term in months (extends the end_date),
                                  or None to leave unchanged.
            notes:                Optional free-text note about why the change occurred.

        Returns:
            dict with keys:
              'term_change'    — the LoanTermChange record created
              'deleted'        — number of future payments deleted
              'created'        — number of new payment records generated
              'loan'           — the updated Loan record

        Raises:
            ValueError: if loan not found, effective_date is in the past relative to
                        the earliest unpaid payment, or no fields were actually changed.
        """
        import calendar as cal_mod

        loan = family_get(Loan, loan_id)
        if not loan:
            raise ValueError(f"Loan {loan_id} not found.")

        # Snapshot previous values for history record
        prev_monthly_payment = Decimal(str(loan.monthly_payment))
        prev_annual_apr = Decimal(str(loan.annual_apr))
        prev_term_months = loan.term_months

        # Derive current payment day from the first unpaid future payment,
        # falling back to effective_date's day.
        first_future = (
            family_query(LoanPayment)
            .filter(
                LoanPayment.loan_id == loan_id,
                LoanPayment.is_paid == False,
                LoanPayment.period > 0,
                LoanPayment.date >= effective_date,
            )
            .order_by(LoanPayment.date)
            .first()
        )
        prev_payment_day = first_future.date.day if first_future else effective_date.day

        # Validate at least one thing is actually changing
        changes_requested = any([
            new_monthly_payment is not None and Decimal(str(new_monthly_payment)) != prev_monthly_payment,
            new_annual_apr is not None and Decimal(str(new_annual_apr)) != prev_annual_apr,
            new_payment_day is not None and int(new_payment_day) != prev_payment_day,
            new_term_months is not None and int(new_term_months) != prev_term_months,
        ])
        if not changes_requested:
            raise ValueError("No fields changed — at least one new value must differ from the current value.")

        # ------------------------------------------------------------------
        # Apply changes to the Loan record
        # ------------------------------------------------------------------
        if new_monthly_payment is not None:
            loan.monthly_payment = Decimal(str(new_monthly_payment))

        if new_annual_apr is not None:
            loan.annual_apr = Decimal(str(new_annual_apr))
            loan.monthly_apr = Decimal(str(new_annual_apr)) / Decimal('12')

        if new_term_months is not None:
            loan.term_months = int(new_term_months)
            # Recalculate end_date from start_date + new term
            loan.end_date = loan.start_date + relativedelta(months=int(new_term_months))

        # ------------------------------------------------------------------
        # Build LoanTermChange record
        # ------------------------------------------------------------------
        term_change = LoanTermChange(
            loan_id=loan_id,
            effective_date=effective_date,
            previous_monthly_payment=prev_monthly_payment
            if new_monthly_payment is not None else None,
            new_monthly_payment=Decimal(str(new_monthly_payment))
            if new_monthly_payment is not None else None,
            previous_annual_apr=prev_annual_apr
            if new_annual_apr is not None else None,
            new_annual_apr=Decimal(str(new_annual_apr))
            if new_annual_apr is not None else None,
            previous_payment_day=prev_payment_day
            if new_payment_day is not None else None,
            new_payment_day=int(new_payment_day)
            if new_payment_day is not None else None,
            previous_term_months=prev_term_months
            if new_term_months is not None else None,
            new_term_months=int(new_term_months)
            if new_term_months is not None else None,
            notes=notes,
        )
        db.session.add(term_change)

        # Propagate family_id from loan (mirrors other models)
        if hasattr(loan, 'family_id') and loan.family_id:
            term_change.family_id = loan.family_id

        # Commit loan + term_change before regenerating so the new rates are live
        db.session.commit()

        # ------------------------------------------------------------------
        # Delete future unpaid payments from effective_date onward and
        # regenerate the schedule using updated loan fields.
        # ------------------------------------------------------------------
        deleted_count = LoanService.delete_future_payments(loan_id, effective_date, commit=True)

        payments = LoanService.generate_amortization_schedule(
            loan_id=loan_id,
            start_date=effective_date,
            end_date=loan.end_date,
            commit=True,
        )

        # If payment day is changing, shift the newly created records to the new day
        if new_payment_day is not None:
            LoanService.update_future_payment_dates(
                loan_id=loan_id,
                new_day=int(new_payment_day),
                from_date=effective_date,
                commit=True,
            )

        return {
            'term_change': term_change,
            'deleted': deleted_count,
            'created': len(payments),
            'loan': loan,
        }
