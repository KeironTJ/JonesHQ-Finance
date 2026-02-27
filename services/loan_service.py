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

Primary entry points
--------------------
  generate_amortization_schedule() — create LoanPayment records for a loan
  generate_payment_transaction()   — create a bank Transaction for one payment
  regenerate_schedule()            — delete future payments and regenerate
  get_payment_statistics()         — summary counts and totals (paid/unpaid)
"""
from models.loans import Loan
from models.loan_payments import LoanPayment
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
            # Check if payment already exists for this date
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
                    date=current_date,
                    year_month=current_date.strftime('%Y-%m'),
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
            amount=float(loan_payment.payment_amount),  # Positive = expense
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
        return bank_txn
    
    @staticmethod
    def delete_future_payments(loan_id, from_date, commit=True):
        """Delete all loan payments from a specific date onwards"""
        payments = family_query(LoanPayment).filter(
            LoanPayment.loan_id == loan_id,
            LoanPayment.date >= from_date
        ).all()
        
        for payment in payments:
            db.session.delete(payment)
        
        if commit:
            db.session.commit()
        
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
