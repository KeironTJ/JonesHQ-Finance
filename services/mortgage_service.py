"""
Mortgage Service
================
Monthly mortgage projection generation, scenario modelling, and snapshot confirmation
for properties with one or more MortgageProduct records.

Key concepts
------------
MortgageSnapshot — one row per month per product, storing balance, payment,
                   interest, principal, and projected property valuation.
  is_projection=False  → confirmed actual (imported or manually entered).
  is_projection=True   → computed projection for a named scenario.

Scenarios
---------
  'base'        — no overpayments.
  'aggressive'  — £500/month overpayment (default second scenario).
  Any custom scenario can be passed as a dict to generate_projections().

After the last defined MortgageProduct ends, the service continues projecting
using an assumed variable rate (last product's rate + 2%) until the balance
reaches zero or 30 years pass (hard limit).

Transaction link
----------------
For the 'base' scenario, a bank Transaction (is_forecasted=True, is_paid=False)
is created for each snapshot when the product has an account_id.  Confirming a
snapshot via confirm_snapshot() marks it is_projection=False and is_paid=True.

Primary entry points
--------------------
  generate_projections()       — regenerate all scenarios for a property
  confirm_snapshot()           — convert a projection to actual, optionally with
                                 revised balance/valuation
  create_transaction_for_snapshot() — add a bank transaction to an existing snapshot
  get_combined_timeline()      — actual + projected rows merged, sorted by date
  get_scenario_comparison()    — interest totals and mortgage-free dates per scenario
  calculate_ltv()              — current loan-to-value ratio
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from extensions import db
from models.property import Property
from models.mortgage import MortgageProduct
from models.mortgage_payments import MortgageSnapshot
from models.transactions import Transaction
from models.categories import Category
from models.settings import Settings
from services.payday_service import PaydayService
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


class MortgageService:
    """
    Mortgage projection generation and snapshot management for properties.

    Projections are generated per-scenario by walking month by month through each
    MortgageProduct.  When the last product ends and there is still a balance, an
    assumed variable rate continuation is appended (rate = last product rate + 2%,
    capped at 30 years).
    """
    
    @staticmethod
    def generate_projections(property_id, scenarios=None):
        """
        Regenerate MortgageSnapshot projections for all products on a property.

        Deletes all unpaid projection snapshots (and their bank transactions), then
        generates new snapshots for each scenario.  Only 'base' scenario snapshots get
        bank Transactions (is_forecasted=True).  Paid snapshots are never deleted.

        Args:
            property_id: ID of the Property to project.
            scenarios:   List of scenario dicts, each with 'name' and 'overpayment'
                         (Decimal monthly overpayment amount).  Defaults to:
                         [{'name': 'base', 'overpayment': 0},
                          {'name': 'aggressive', 'overpayment': 500}].

        Returns:
            True on success, False if property or products not found.

        Side effects:
            Commits the session.  May create/delete Transaction and MortgageSnapshot rows.
        """
        if scenarios is None:
            scenarios = [
                {'name': 'base', 'overpayment': Decimal('0')},
                {'name': 'aggressive', 'overpayment': Decimal('500')},
            ]
        
        property_obj = family_get(Property, property_id)
        if not property_obj:
            return False
        
        # Get all mortgage products for this property, ordered by start date
        products = family_query(MortgageProduct).filter_by(
            property_id=property_id
        ).order_by(MortgageProduct.start_date).all()
        
        if not products:
            return False
        
        # Delete existing projections for this property
        for product in products:
            # Get all unpaid projection snapshots with transactions
            unpaid_projections = family_query(MortgageSnapshot).filter_by(
                mortgage_product_id=product.id,
                is_projection=True
            ).join(
                Transaction, MortgageSnapshot.transaction_id == Transaction.id, isouter=True
            ).filter(
                db.or_(
                    MortgageSnapshot.transaction_id.is_(None),  # No transaction
                    Transaction.is_paid == False  # Or transaction is unpaid
                )
            ).all()
            
            # Delete unpaid transactions and their snapshots
            for snapshot in unpaid_projections:
                if snapshot.transaction_id:
                    transaction = family_get(Transaction, snapshot.transaction_id)
                    if transaction and not transaction.is_paid:
                        db.session.delete(transaction)
                db.session.delete(snapshot)
        
        db.session.flush()  # Ensure deletions are committed before generating new ones
        
        # Generate projections for each scenario
        for scenario in scenarios:
            MortgageService._generate_scenario_projections(
                property_obj, products, scenario
            )
        
        db.session.commit()
        return True
    
    @staticmethod
    def _generate_scenario_projections(property_obj, products, scenario):
        """Generate projections for a specific scenario"""
        scenario_name = scenario['name']
        monthly_overpayment = scenario['overpayment']
        
        current_date = date.today().replace(day=1)  # Start of current month
        
        # Get property appreciation rate (annual)
        annual_appreciation = property_obj.annual_appreciation_rate or Decimal('3.0')
        monthly_appreciation = annual_appreciation / Decimal('12') / Decimal('100')
        
        current_valuation = property_obj.current_valuation
        
        # Track the last product and balance for assumed variable calculation
        last_product = None
        final_balance = None
        final_month = None
        final_valuation = None
        
        for product in products:
            # Skip if product hasn't started yet
            if product.start_date > current_date:
                balance = product.initial_balance
                start_month = product.start_date.replace(day=1)
            else:
                # Product already active - get latest confirmed snapshot (non-projection) or latest projection with transaction
                latest_confirmed = family_query(MortgageSnapshot).filter_by(
                    mortgage_product_id=product.id,
                    is_projection=False
                ).order_by(MortgageSnapshot.date.desc()).first()
                
                # Also check for projections that have been paid (have transactions)
                latest_paid_projection = family_query(MortgageSnapshot).filter_by(
                    mortgage_product_id=product.id,
                    is_projection=True,
                    scenario_name=scenario_name
                ).filter(
                    MortgageSnapshot.transaction_id.isnot(None)
                ).order_by(MortgageSnapshot.date.desc()).first()
                
                # Use whichever is more recent
                latest_snapshot = None
                if latest_confirmed and latest_paid_projection:
                    latest_snapshot = latest_confirmed if latest_confirmed.date > latest_paid_projection.date else latest_paid_projection
                elif latest_confirmed:
                    latest_snapshot = latest_confirmed
                elif latest_paid_projection:
                    latest_snapshot = latest_paid_projection
                
                if latest_snapshot:
                    balance = latest_snapshot.balance
                    start_month = (latest_snapshot.date + relativedelta(months=1)).replace(day=1)
                else:
                    balance = product.current_balance
                    start_month = current_date
            
            # Generate monthly snapshots from start to end of product
            projection_month = start_month
            end_month = product.end_date.replace(day=1)
            
            # Get payment day for this product (default to 1st if not set)
            payment_day = product.payment_day or 1
            
            while projection_month <= end_month and balance > Decimal('0.01'):
                # Calculate actual payment date for this month (adjust for working days)
                payment_date = PaydayService.get_payment_date_for_month(
                    projection_month.year, 
                    projection_month.month, 
                    payment_day
                )
                
                # Skip if a snapshot already exists for this date and product
                existing_snapshot = family_query(MortgageSnapshot).filter_by(
                    mortgage_product_id=product.id,
                    date=payment_date
                ).first()
                
                if existing_snapshot:
                    # Use existing snapshot's balance and move to next month
                    balance = existing_snapshot.balance
                    current_valuation = existing_snapshot.property_valuation
                    projection_month = projection_month + relativedelta(months=1)
                    continue
                
                # Calculate interest for this month
                monthly_rate = product.annual_rate / Decimal('12') / Decimal('100')
                interest_charge = (balance * monthly_rate).quantize(Decimal('0.01'), ROUND_HALF_UP)
                
                # Calculate payment (regular + overpayment)
                total_payment = product.monthly_payment + monthly_overpayment
                
                # Principal reduction
                principal_paid = total_payment - interest_charge
                
                # Ensure we don't overpay
                if principal_paid > balance:
                    principal_paid = balance
                    total_payment = balance + interest_charge
                    monthly_overpayment_actual = principal_paid - (product.monthly_payment - interest_charge)
                else:
                    monthly_overpayment_actual = monthly_overpayment
                
                # New balance
                new_balance = balance - principal_paid
                if new_balance < Decimal('0.01'):
                    new_balance = Decimal('0')
                
                # Project property valuation
                projected_valuation = (current_valuation * (Decimal('1') + monthly_appreciation)).quantize(
                    Decimal('0.01'), ROUND_HALF_UP
                )
                
                # Calculate equity
                equity = projected_valuation - new_balance
                equity_pct = (equity / projected_valuation * Decimal('100')).quantize(
                    Decimal('0.01'), ROUND_HALF_UP
                ) if projected_valuation > 0 else Decimal('0')
                
                # Create snapshot
                snapshot = MortgageSnapshot(
                    mortgage_product_id=product.id,
                    date=payment_date,
                    year_month=payment_date.strftime('%Y-%m'),
                    balance=new_balance,
                    monthly_payment=product.monthly_payment,
                    overpayment=monthly_overpayment_actual,
                    interest_charge=interest_charge,
                    principal_paid=principal_paid,
                    interest_rate=monthly_rate,
                    property_valuation=projected_valuation,
                    equity_amount=equity,
                    equity_percent=equity_pct,
                    is_projection=True,
                    scenario_name=scenario_name
                )
                db.session.add(snapshot)
                db.session.flush()  # Get snapshot ID
                
                # Create transaction for this projection if product has an account
                if product.account_id and scenario_name == 'base':
                    MortgageService._create_transaction_for_snapshot(snapshot, product, property_obj)
                
                # Move to next month
                balance = new_balance
                current_valuation = projected_valuation
                projection_month = projection_month + relativedelta(months=1)
            
            # Track final state after this product
            last_product = product
            final_balance = balance
            final_month = end_month
            final_valuation = current_valuation
        
        # Check if we need to extend with assumed variable rate
        # Find the product with the latest end date (chronologically last)
        if products:
            chronologically_last_product = max(products, key=lambda p: p.end_date)
            
            # Get the final balance from the chronologically last product
            last_snapshots = family_query(MortgageSnapshot).filter_by(
                mortgage_product_id=chronologically_last_product.id,
                is_projection=True,
                scenario_name=scenario_name
            ).order_by(MortgageSnapshot.date.desc()).first()
            
            if last_snapshots:
                final_balance = last_snapshots.balance
                final_month = last_snapshots.date
                final_valuation = last_snapshots.property_valuation
                
                # Extend if there's still a balance
                if final_balance > Decimal('0.01'):
                    MortgageService._generate_assumed_variable_projections(
                        property_obj=property_obj,
                        last_product=chronologically_last_product,
                        starting_balance=final_balance,
                        starting_month=final_month,
                        starting_valuation=final_valuation,
                        monthly_appreciation=monthly_appreciation,
                        monthly_overpayment=monthly_overpayment,
                        scenario_name=scenario_name
                    )
    
    @staticmethod
    def _generate_assumed_variable_projections(property_obj, last_product, starting_balance, 
                                               starting_month, starting_valuation, 
                                               monthly_appreciation, monthly_overpayment, scenario_name):
        """Generate assumed variable rate projections until mortgage is paid off"""
        
        # Get assumed variable rate from settings or use last product rate + 2%
        assumed_annual_rate = last_product.annual_rate + Decimal('2.0')  # Conservative estimate
        
        # Calculate new monthly payment for the assumed variable rate
        # Use the remaining term to calculate proper payment using amortization formula
        # Standard approach: assume 25 years remaining from end of last product
        remaining_term_months = 300  # 25 years standard term
        
        # Calculate monthly payment using amortization formula: M = P * [r(1+r)^n] / [(1+r)^n - 1]
        monthly_rate = assumed_annual_rate / Decimal('12') / Decimal('100')
        balance_decimal = starting_balance
        n = Decimal(str(remaining_term_months))
        
        numerator = monthly_rate * ((Decimal('1') + monthly_rate) ** n)
        denominator = ((Decimal('1') + monthly_rate) ** n) - Decimal('1')
        
        if denominator > 0:
            assumed_monthly_payment = (balance_decimal * (numerator / denominator)).quantize(
                Decimal('0.01'), ROUND_HALF_UP
            )
        else:
            # Fallback to simple division if calculation fails
            assumed_monthly_payment = (balance_decimal / n).quantize(Decimal('0.01'), ROUND_HALF_UP)
        
        balance = starting_balance
        projection_month = (starting_month + relativedelta(months=1)).replace(day=1)
        current_valuation = starting_valuation
        
        # Get payment day from last product
        payment_day = last_product.payment_day or 1
        
        # Limit to 30 years to prevent infinite loops
        max_months = 360
        months_projected = 0
        
        while balance > Decimal('0.01') and months_projected < max_months:
            # Calculate actual payment date (adjust for working days)
            payment_date = PaydayService.get_payment_date_for_month(
                projection_month.year,
                projection_month.month,
                payment_day
            )
            
            # Skip if a snapshot already exists for this date and product
            existing_snapshot = family_query(MortgageSnapshot).filter_by(
                mortgage_product_id=last_product.id,
                date=payment_date
            ).first()
            
            if existing_snapshot:
                # Use existing snapshot's balance and move to next month
                balance = existing_snapshot.balance
                current_valuation = existing_snapshot.property_valuation
                projection_month = projection_month + relativedelta(months=1)
                months_projected += 1
                continue
            
            # Calculate interest for this month
            monthly_rate = assumed_annual_rate / Decimal('12') / Decimal('100')
            interest_charge = (balance * monthly_rate).quantize(Decimal('0.01'), ROUND_HALF_UP)
            
            # Calculate payment (regular + overpayment)
            total_payment = assumed_monthly_payment + monthly_overpayment
            
            # Principal reduction
            principal_paid = total_payment - interest_charge
            
            # Ensure we don't overpay
            if principal_paid > balance:
                principal_paid = balance
                total_payment = balance + interest_charge
                monthly_overpayment_actual = principal_paid - (assumed_monthly_payment - interest_charge)
            else:
                monthly_overpayment_actual = monthly_overpayment
            
            # New balance
            new_balance = balance - principal_paid
            if new_balance < Decimal('0.01'):
                new_balance = Decimal('0')
            
            # Project property valuation
            projected_valuation = (current_valuation * (Decimal('1') + monthly_appreciation)).quantize(
                Decimal('0.01'), ROUND_HALF_UP
            )
            
            # Calculate equity
            equity = projected_valuation - new_balance
            equity_pct = (equity / projected_valuation * Decimal('100')).quantize(
                Decimal('0.01'), ROUND_HALF_UP
            ) if projected_valuation > 0 else Decimal('0')
            
            # Create snapshot - note we use the last product ID but mark it differently
            snapshot = MortgageSnapshot(
                mortgage_product_id=last_product.id,
                date=payment_date,
                year_month=payment_date.strftime('%Y-%m'),
                balance=new_balance,
                monthly_payment=assumed_monthly_payment,
                overpayment=monthly_overpayment_actual,
                interest_charge=interest_charge,
                principal_paid=principal_paid,
                interest_rate=monthly_rate,
                property_valuation=projected_valuation,
                equity_amount=equity,
                equity_percent=equity_pct,
                is_projection=True,
                scenario_name=scenario_name,
                notes=f'Assumed variable rate ({assumed_annual_rate}% APR)'
            )
            db.session.add(snapshot)
            db.session.flush()  # Get snapshot ID
            
            # Create transaction for assumed variable projections if account exists
            if last_product.account_id and scenario_name == 'base':
                MortgageService._create_transaction_for_snapshot(snapshot, last_product, property_obj)
            
            # Move to next month
            balance = new_balance
            current_valuation = projected_valuation
            projection_month = projection_month + relativedelta(months=1)
            months_projected += 1
    
    @staticmethod
    def get_combined_timeline(property_id, scenario='base'):
        """
        Get combined actual + projected timeline for a property (all products).
        Property valuations are computed live from PropertyValuationSnapshot so they
        always reflect the most recent actual entries and appreciation projections.
        Returns list of dictionaries with monthly data.
        """
        from models.property_valuation_snapshot import PropertyValuationSnapshot

        property_obj = family_get(Property, property_id)
        if not property_obj:
            return []

        products = family_query(MortgageProduct).filter_by(
            property_id=property_id
        ).order_by(MortgageProduct.start_date).all()

        today = date.today()

        # Fetch all actual valuation snapshots once (ordered oldest → newest)
        actual_pvs = family_query(PropertyValuationSnapshot).filter_by(
            property_id=property_id,
            is_projection=False,
        ).order_by(PropertyValuationSnapshot.valuation_date).all()

        def _property_value_at(target_date):
            """Return the best property value estimate for target_date."""
            is_future = target_date > today

            if not is_future:
                # Latest actual on or before target_date
                for pvs in reversed(actual_pvs):
                    if pvs.valuation_date <= target_date:
                        return float(pvs.value)
                return float(property_obj.current_valuation or 0)

            # Future: check for an explicit projection snapshot first
            proj = family_query(PropertyValuationSnapshot).filter(
                PropertyValuationSnapshot.property_id == property_id,
                PropertyValuationSnapshot.valuation_date <= target_date,
                PropertyValuationSnapshot.is_projection == True,
            ).order_by(PropertyValuationSnapshot.valuation_date.desc()).first()
            if proj:
                return float(proj.value)

            # Compound forward from latest actual
            if actual_pvs:
                latest = actual_pvs[-1]
                base_value = float(latest.value)
                base_date = latest.valuation_date
            else:
                base_value = float(property_obj.current_valuation or 0)
                base_date = today

            if property_obj.annual_appreciation_rate and base_value:
                months_diff = (
                    (target_date.year - base_date.year) * 12
                    + (target_date.month - base_date.month)
                )
                monthly_rate = (
                    Decimal(str(property_obj.annual_appreciation_rate))
                    / Decimal('12') / Decimal('100')
                )
                projected = Decimal(str(base_value)) * (
                    (Decimal('1') + monthly_rate) ** months_diff
                )
                return float(projected)
            return base_value

        timeline = []

        for product in products:
            actuals = family_query(MortgageSnapshot).filter_by(
                mortgage_product_id=product.id,
                is_projection=False
            ).order_by(MortgageSnapshot.date).all()

            projections = family_query(MortgageSnapshot).filter_by(
                mortgage_product_id=product.id,
                is_projection=True,
                scenario_name=scenario
            ).order_by(MortgageSnapshot.date).all()

            for snapshot in actuals:
                valuation = _property_value_at(snapshot.date)
                balance = float(snapshot.balance)
                equity = valuation - balance
                equity_pct = (equity / valuation * 100) if valuation > 0 else 0
                timeline.append({
                    'snapshot_id': snapshot.id,
                    'date': snapshot.date,
                    'year_month': snapshot.year_month,
                    'product_name': f"{product.lender} - {product.product_name}",
                    'balance': snapshot.balance,
                    'payment': snapshot.monthly_payment,
                    'overpayment': snapshot.overpayment,
                    'interest': snapshot.interest_charge,
                    'principal': snapshot.principal_paid,
                    'rate': product.annual_rate,
                    'valuation': valuation,
                    'equity': equity,
                    'equity_pct': equity_pct,
                    'is_projection': False,
                    'is_paid': snapshot.is_paid,
                    'transaction_id': snapshot.transaction_id,
                    'notes': snapshot.notes
                })

            for snapshot in projections:
                valuation = _property_value_at(snapshot.date)
                balance = float(snapshot.balance)
                equity = valuation - balance
                equity_pct = (equity / valuation * 100) if valuation > 0 else 0
                timeline.append({
                    'snapshot_id': snapshot.id,
                    'date': snapshot.date,
                    'year_month': snapshot.year_month,
                    'product_name': f"{product.lender} - {product.product_name}",
                    'balance': snapshot.balance,
                    'payment': snapshot.monthly_payment,
                    'overpayment': snapshot.overpayment,
                    'interest': snapshot.interest_charge,
                    'principal': snapshot.principal_paid,
                    'rate': product.annual_rate,
                    'valuation': valuation,
                    'equity': equity,
                    'equity_pct': equity_pct,
                    'is_projection': True,
                    'is_paid': snapshot.is_paid,
                    'transaction_id': snapshot.transaction_id,
                    'notes': snapshot.notes
                })

        timeline.sort(key=lambda x: x['date'])
        return timeline
    
    @staticmethod
    def get_scenario_comparison(property_id):
        """Get comparison data for all scenarios"""
        property_obj = family_get(Property, property_id)
        if not property_obj:
            return {}
        
        scenarios = {}
        
        # Get unique scenario names
        scenario_names = family_query(MortgageSnapshot).with_entities(
            MortgageSnapshot.scenario_name
        ).join(
            MortgageProduct
        ).filter(
            MortgageProduct.property_id == property_id,
            MortgageSnapshot.is_projection == True
        ).distinct().all()
        
        for (scenario_name,) in scenario_names:
            # Get all products for this property
            products = family_query(MortgageProduct).filter_by(property_id=property_id).all()
            
            total_interest = Decimal('0')
            total_payments = Decimal('0')
            mortgage_free_date = None
            
            for product in products:
                snapshots = family_query(MortgageSnapshot).filter_by(
                    mortgage_product_id=product.id,
                    is_projection=True,
                    scenario_name=scenario_name
                ).order_by(MortgageSnapshot.date).all()
                
                for snapshot in snapshots:
                    total_interest += snapshot.interest_charge
                    total_payments += (snapshot.monthly_payment + snapshot.overpayment)
                    
                    # Find mortgage-free date (when balance hits 0)
                    if snapshot.balance == 0 and not mortgage_free_date:
                        mortgage_free_date = snapshot.date
            
            scenarios[scenario_name] = {
                'total_interest': total_interest,
                'total_payments': total_payments,
                'mortgage_free_date': mortgage_free_date,
                'months_saved': None  # Calculate after getting all scenarios
            }
        
        # Calculate months saved compared to base scenario
        if 'base' in scenarios and scenarios['base']['mortgage_free_date']:
            base_date = scenarios['base']['mortgage_free_date']
            for scenario_name, data in scenarios.items():
                if scenario_name != 'base' and data['mortgage_free_date']:
                    delta = (base_date.year - data['mortgage_free_date'].year) * 12 + \
                            (base_date.month - data['mortgage_free_date'].month)
                    data['months_saved'] = delta
        
        return scenarios
    
    @staticmethod
    def confirm_snapshot(snapshot_id, actual_balance=None, actual_valuation=None):
        """
        Promote a projected MortgageSnapshot to an actual confirmed record.

        Clears is_projection=True and scenario_name, optionally updates balance and
        valuation (and recalculates equity).  If the product has an account_id and
        no transaction exists yet, creates one (is_paid=True, is_forecasted=False).

        Args:
            snapshot_id:        ID of the MortgageSnapshot to confirm.
            actual_balance:     Actual closing balance (replaces projected if provided).
            actual_valuation:   Actual property valuation (replaces projected if provided).

        Returns:
            True on success, False if snapshot not found or already confirmed.
        """
        snapshot = family_get(MortgageSnapshot, snapshot_id)
        if not snapshot or not snapshot.is_projection:
            return False
        
        product = snapshot.mortgage_product
        property_obj = product.property
        
        # Update snapshot values
        snapshot.is_projection = False
        snapshot.scenario_name = None  # Clear scenario since it's now actual
        
        if actual_balance is not None:
            snapshot.balance = actual_balance
        
        if actual_valuation is not None:
            snapshot.property_valuation = actual_valuation
            # Recalculate equity
            snapshot.equity_amount = actual_valuation - snapshot.balance
            snapshot.equity_percent = (
                snapshot.equity_amount / actual_valuation * Decimal('100')
            ).quantize(Decimal('0.01'), ROUND_HALF_UP) if actual_valuation > 0 else Decimal('0')
        
        # Update product current balance
        product.current_balance = snapshot.balance
        
        # Update property current valuation
        if actual_valuation is not None:
            property_obj.current_valuation = actual_valuation
        
        # Create transaction if account is linked and no transaction exists yet
        if product.account_id and not snapshot.transaction_id:
            # Get or create mortgage category
            mortgage_category = family_query(Category).filter_by(
                name='Mortgage',
                category_type='expense'
            ).first()
            if not mortgage_category:
                mortgage_category = Category(
                    name='Mortgage',
                    category_type='expense',
                    head_budget='Home',
                    sub_budget='Mortgage'
                )
                db.session.add(mortgage_category)
                db.session.flush()
            
            # Create transaction
            transaction = Transaction(
                account_id=product.account_id,
                transaction_date=snapshot.date,
                amount=-(snapshot.monthly_payment + snapshot.overpayment),  # Negative for expense
                description=f"Mortgage Payment - {property_obj.address}",
                category_id=mortgage_category.id,
                payment_type='Direct Debit',
                is_paid=True,
                is_fixed=False,  # Allow regeneration to update if needed
                year_month=snapshot.date.strftime('%Y-%m'),
                payday_period=PaydayService.get_period_for_date(snapshot.date),
                day_name=snapshot.date.strftime('%a'),
                is_forecasted=False
            )
            db.session.add(transaction)
            db.session.flush()
            
            # Link transaction to snapshot
            snapshot.transaction_id = transaction.id
        
        db.session.commit()
        return True
    
    @staticmethod
    def create_transaction_for_snapshot(snapshot_id):
        """
        Create a transaction for an existing snapshot
        Used when linking transactions to already confirmed snapshots
        """
        snapshot = family_get(MortgageSnapshot, snapshot_id)
        if not snapshot or snapshot.transaction_id:
            return False  # Already has transaction
        
        product = snapshot.mortgage_product
        property_obj = product.property
        
        if not product.account_id:
            return False  # No account linked
        
        # Get or create mortgage category (use product category if set)
        if product.category_id:
            category = family_get(Category, product.category_id)
        else:
            category = family_query(Category).filter_by(
                name='Mortgage',
                category_type='expense'
            ).first()
            if not category:
                category = Category(
                    name='Mortgage',
                    category_type='expense',
                    head_budget='Home',
                    sub_budget='Mortgage'
                )
                db.session.add(category)
                db.session.flush()
        
        # Create transaction
        transaction = Transaction(
            account_id=product.account_id,
            transaction_date=snapshot.date,
            amount=-(snapshot.monthly_payment + snapshot.overpayment),  # Negative for expense
            description=f"Mortgage Payment - {property_obj.address}",
            category_id=category.id,
            vendor_id=product.vendor_id,  # Use product's vendor if set
            payment_type='Direct Debit',
            is_paid=True,
            is_fixed=False,  # Allow regeneration to update if needed
            year_month=snapshot.date.strftime('%Y-%m'),
            payday_period=PaydayService.get_period_for_date(snapshot.date),
            day_name=snapshot.date.strftime('%a'),
            is_forecasted=False
        )
        db.session.add(transaction)
        db.session.flush()
        
        # Link transaction to snapshot
        snapshot.transaction_id = transaction.id
        
        db.session.commit()
        return True
    
    @staticmethod
    def _create_transaction_for_snapshot(snapshot, product, property_obj):
        """
        Internal helper to create a transaction for a snapshot during projection generation
        Does not commit - assumes caller will commit
        """
        # Get or create mortgage category (use product category if set)
        if product.category_id:
            category = family_get(Category, product.category_id)
        else:
            category = family_query(Category).filter_by(
                name='Mortgage',
                category_type='expense'
            ).first()
            if not category:
                category = Category(
                    name='Mortgage',
                    category_type='expense',
                    head_budget='Home',
                    sub_budget='Mortgage'
                )
                db.session.add(category)
                db.session.flush()
        
        # Create transaction
        transaction = Transaction(
            account_id=product.account_id,
            transaction_date=snapshot.date,
            amount=-(snapshot.monthly_payment + snapshot.overpayment),  # Negative for expense
            description=f"Mortgage Payment - {property_obj.address}",
            category_id=category.id,
            vendor_id=product.vendor_id,  # Use product's vendor if set
            payment_type='Direct Debit',
            is_paid=False,  # Projections start as unpaid
            is_fixed=False,  # Allow regeneration to update if needed
            year_month=snapshot.date.strftime('%Y-%m'),
            payday_period=PaydayService.get_period_for_date(snapshot.date),
            day_name=snapshot.date.strftime('%a'),
            is_forecasted=True  # Mark as forecasted for projections
        )
        db.session.add(transaction)
        db.session.flush()
        
        # Link transaction to snapshot
        snapshot.transaction_id = transaction.id
    
    @staticmethod
    def sync_transaction_to_snapshot(transaction_id):
        """
        Sync transaction changes back to the mortgage snapshot
        Updates snapshot when transaction is modified
        """
        from models.transactions import Transaction
        
        transaction = family_get(Transaction, transaction_id)
        if not transaction or not hasattr(transaction, 'mortgage_snapshot'):
            return False
        
        snapshot = transaction.mortgage_snapshot
        if not snapshot:
            return False
        
        # Update snapshot based on transaction
        total_payment = abs(transaction.amount)
        snapshot.monthly_payment = total_payment - snapshot.overpayment
        
        # Recalculate balance
        # Note: This is complex and might require recalculating the entire projection chain
        # For now, just mark it for review
        if snapshot.notes:
            snapshot.notes += " | Transaction updated - verify balance"
        else:
            snapshot.notes = "Transaction updated - verify balance"
        
        db.session.commit()
        return True
    
    @staticmethod
    def get_mortgage_free_projection(property_id, scenario='base'):
        """Calculate when the property will be mortgage-free"""
        products = family_query(MortgageProduct).filter_by(property_id=property_id).all()
        
        latest_date = None
        
        for product in products:
            last_snapshot = family_query(MortgageSnapshot).filter_by(
                mortgage_product_id=product.id,
                is_projection=True,
                scenario_name=scenario
            ).filter(
                MortgageSnapshot.balance == 0
            ).order_by(MortgageSnapshot.date.desc()).first()
            
            if last_snapshot:
                if not latest_date or last_snapshot.date > latest_date:
                    latest_date = last_snapshot.date
        
        return latest_date
    
    @staticmethod
    def calculate_ltv(property_id):
        """Calculate current Loan-to-Value ratio"""
        property_obj = family_get(Property, property_id)
        if not property_obj or not property_obj.current_valuation:
            return None
        
        total_mortgage = sum([
            p.current_balance for p in property_obj.mortgage_products if p.is_active
        ])
        
        ltv = (total_mortgage / property_obj.current_valuation * Decimal('100')).quantize(
            Decimal('0.01'), ROUND_HALF_UP
        )
        
        return ltv
