"""
Pension Service
===============
Pension projection generation and retirement income estimates.

Projection model
----------------
Starting from the most recent actual PensionSnapshot (or pension.current_value if none
exists), the service compounds forward month by month:

    projected_value = prev_value × (1 + monthly_growth_rate) + monthly_contribution

Three named scenarios are supported (growth rates read from Settings):
  'default'     — moderate growth (pension_default_monthly_growth_rate, default 0.12%/mo)
  'optimistic'  — higher growth  (pension_optimistic_monthly_growth_rate, default 0.5%/mo)
  'pessimistic' — lower growth   (pension_pessimistic_monthly_growth_rate, default 0.05%/mo)

Inactive pensions still receive growth; contributions are set to £0.

PensionSnapshot rows
--------------------
  is_projection=False  → confirmed actual values (entered via review).
  is_projection=True   → computed projection; deleted and recreated on each regen.

Past projection rows (review_date < today) are intentionally preserved so the
historic projection chart doesn't lose data when a regen runs.

Retirement income estimate
--------------------------
Projected pot at retirement × annuity_conversion_rate (default 5%) + government
pension (from Settings) = estimated annual retirement income.

Primary entry points
--------------------
  generate_projections()        — compute projection list (in-memory, not saved)
  save_projections()            — compute and persist projections to DB
  regenerate_all_projections()  — save_projections() for all active pensions
  get_retirement_summary()      — current/projected values + income estimate
  get_combined_snapshots()      — merged actual + projection history for charts
"""
from models.pensions import Pension
from models.pension_snapshots import PensionSnapshot
from models.settings import Settings
from extensions import db
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from decimal import Decimal
import calendar
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


class PensionService:
    """
    Pension projection generation and retirement income estimation.

    Growth rates and retirement ages are read from the Settings model, allowing
    them to be updated without code changes.  All monetary values use Decimal.
    """

    @staticmethod
    def get_person_age(person):
        """Get current age of person from their date of birth"""
        dob_str = Settings.get_value(f'{person.lower()}_date_of_birth')
        if not dob_str:
            return None
        
        dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
        today = date.today()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        return age
    
    @staticmethod
    def get_months_until_retirement(person, retirement_age=None):
        """Calculate months remaining until retirement"""
        current_age = PensionService.get_person_age(person)
        if current_age is None:
            return None
        
        if retirement_age is None:
            retirement_age = Settings.get_value(f'{person.lower()}_retirement_age', 65)
        
        years_remaining = retirement_age - current_age
        months_remaining = years_remaining * 12
        
        # Adjust for partial year
        dob_str = Settings.get_value(f'{person.lower()}_date_of_birth')
        dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
        today = date.today()
        
        # More precise month calculation
        months_remaining = (retirement_age - current_age) * 12
        months_remaining -= today.month - dob.month
        
        return max(0, months_remaining)
    
    @staticmethod
    def generate_projections(pension, scenario='default', months_to_project=None):
        """
        Compute a list of monthly projection dicts from the last actual snapshot
        (or pension.current_value) forward to retirement.

        This is a pure calculation — no DB writes.  Call save_projections() to persist.

        Growth is applied whether the pension is active or not; monthly contributions
        are included only when pension.is_active=True.

        Args:
            pension:           Pension instance to project.
            scenario:          'default', 'optimistic', or 'pessimistic'.
            months_to_project: Override the automatic retirement-distance calculation.
                               Pass a positive integer to force a specific horizon.

        Returns:
            list[dict] — one dict per month with keys: pension_id, review_date, value,
            growth_percent, is_projection, scenario_name, growth_rate_used.
            Empty list if months_to_project is 0 or cannot be calculated.
        """
        # Get growth rate for scenario
        if scenario == 'optimistic':
            monthly_growth_rate = Decimal(str(Settings.get_value('pension_optimistic_monthly_growth_rate', 0.005)))
        elif scenario == 'pessimistic':
            monthly_growth_rate = Decimal(str(Settings.get_value('pension_pessimistic_monthly_growth_rate', 0.0005)))
        else:
            monthly_growth_rate = Decimal(str(Settings.get_value('pension_default_monthly_growth_rate', 0.0012)))
        
        # Determine how many months to project
        if months_to_project is None:
            months_to_project = PensionService.get_months_until_retirement(
                pension.person, 
                pension.retirement_age
            )
        
        if months_to_project is None or months_to_project <= 0:
            return []
        
        # Get the most recent actual snapshot
        last_actual = family_query(PensionSnapshot).filter_by(
            pension_id=pension.id,
            is_projection=False
        ).order_by(PensionSnapshot.review_date.desc()).first()
        
        if not last_actual:
            # Use current value
            current_value = pension.current_value
            start_date = date.today()
        else:
            current_value = last_actual.value
            start_date = last_actual.review_date
        
        # Start from next month
        start_date = start_date + relativedelta(months=1)
        # Set to 15th of month for consistency
        start_date = start_date.replace(day=15)
        
        projections = []
        projected_value = current_value
        # Only add monthly contributions if pension is active
        monthly_contribution = pension.monthly_contribution or Decimal('0') if pension.is_active else Decimal('0')
        
        for month_offset in range(months_to_project):
            # Calculate projection date
            projection_date = start_date + relativedelta(months=month_offset)
            
            # Apply growth (happens whether active or not)
            growth_amount = projected_value * monthly_growth_rate
            # Add contribution only if pension is active
            projected_value = projected_value + growth_amount + monthly_contribution
            
            # Calculate growth percentage
            if month_offset == 0:
                growth_percent = (projected_value - current_value) / current_value * 100 if current_value > 0 else Decimal('0')
            else:
                prev_value = projections[-1]['value']
                growth_percent = (projected_value - prev_value) / prev_value * 100 if prev_value > 0 else Decimal('0')
            
            projections.append({
                'pension_id': pension.id,
                'review_date': projection_date,
                'value': projected_value,
                'growth_percent': growth_percent,
                'is_projection': True,
                'scenario_name': scenario,
                'growth_rate_used': monthly_growth_rate
            })
        
        return projections
    
    @staticmethod
    def save_projections(pension, scenario='default', replace_existing=True):
        """
        Compute projections and persist them as PensionSnapshot rows.

        If replace_existing=True (default), deletes future projection rows for this
        scenario (review_date >= today) before saving.  Past projection rows are
        intentionally preserved (see module docstring).

        Also updates pension.projected_value_at_retirement to the last projected value.

        Returns:
            int — total number of projections computed (saved count may be lower if
            some fall before today).
        """
        if replace_existing:
            # Only delete FUTURE projections for this scenario - preserve past projection
            # records for months where no actual snapshot was ever confirmed, so historic
            # rows don't disappear from the projections table.
            today = date.today()
            family_query(PensionSnapshot).filter(
                PensionSnapshot.pension_id == pension.id,
                PensionSnapshot.is_projection == True,
                PensionSnapshot.scenario_name == scenario,
                PensionSnapshot.review_date >= today
            ).delete()
        
        projections = PensionService.generate_projections(pension, scenario)
        
        # Only save projections for today onwards - past projections are preserved in DB
        today = date.today()
        future_projections = [p for p in projections if p['review_date'] >= today]
        
        for proj_data in future_projections:
            snapshot = PensionSnapshot(**proj_data)
            db.session.add(snapshot)
        
        # Update projected value at retirement (use full projection list for accuracy)
        if projections:
            pension.projected_value_at_retirement = projections[-1]['value']
        
        db.session.commit()
        return len(projections)
    
    @staticmethod
    def regenerate_all_projections(scenario='default'):
        """Regenerate projections for all active pensions"""
        pensions = family_query(Pension).filter_by(is_active=True).all()
        total_generated = 0
        
        for pension in pensions:
            count = PensionService.save_projections(pension, scenario)
            total_generated += count
        
        return total_generated
    
    @staticmethod
    def calculate_annuity(pension_value):
        """Calculate estimated annual annuity from pension pot"""
        conversion_rate = Decimal(str(Settings.get_value('annuity_conversion_rate', 0.05)))
        return pension_value * conversion_rate
    
    @staticmethod
    def get_retirement_summary(person=None):
        """
        Aggregate retirement income projection across all active pensions.

        Reads stored projected_value_at_retirement (not recomputed on the fly), so
        save_projections() must have been run recently for results to be accurate.

        Args:
            person: 'keiron', 'emma', or None (to sum both).

        Returns:
            dict with keys:
              total_current_value, total_projected_value,
              total_annuity          — projected_value × annuity_conversion_rate,
              government_pension     — annual state pension from Settings,
              total_annual_income    — annuity + government_pension,
              total_monthly_income   — total_annual_income / 12,
              pension_details        — list of per-pension dicts.
        """
        query = family_query(Pension).filter_by(is_active=True)
        if person:
            query = query.filter_by(person=person)
        
        pensions = query.all()
        
        total_current = Decimal('0')
        total_projected = Decimal('0')
        
        pension_details = []
        
        for pension in pensions:
            total_current += pension.current_value or Decimal('0')
            total_projected += pension.projected_value_at_retirement or Decimal('0')
            
            pension_details.append({
                'provider': pension.provider,
                'current_value': pension.current_value,
                'projected_value': pension.projected_value_at_retirement,
                'person': pension.person
            })
        
        # Calculate annuities
        total_annuity = PensionService.calculate_annuity(total_projected)
        
        # Add government pension
        gov_pension = Decimal('0')
        if person:
            gov_pension = Decimal(str(Settings.get_value(f'government_pension_annual_{person.lower()}', 0)))
        else:
            # Sum both
            keiron_gov = Decimal(str(Settings.get_value('government_pension_annual_keiron', 0)))
            emma_gov = Decimal(str(Settings.get_value('government_pension_annual_emma', 0)))
            gov_pension = keiron_gov + emma_gov
        
        total_annual_income = total_annuity + gov_pension
        total_monthly_income = total_annual_income / 12
        
        return {
            'total_current_value': total_current,
            'total_projected_value': total_projected,
            'total_annuity': total_annuity,
            'government_pension': gov_pension,
            'total_annual_income': total_annual_income,
            'total_monthly_income': total_monthly_income,
            'pension_details': pension_details
        }
    
    @staticmethod
    def get_combined_snapshots(person=None, scenario='default', include_projections=True):
        """
        Get combined historical and projected snapshots across all pensions
        Grouped by review date (month)
        """
        query = family_query(PensionSnapshot).join(Pension).with_entities(PensionSnapshot, Pension)
        
        if person:
            query = query.filter(Pension.person == person)
        
        query = query.filter(Pension.is_active == True)
        
        if not include_projections:
            query = query.filter(PensionSnapshot.is_projection == False)
        else:
            # Filter for actual data OR projections matching the scenario
            query = query.filter(
                db.or_(
                    PensionSnapshot.is_projection == False,
                    PensionSnapshot.scenario_name == scenario
                )
            )
        
        query = query.order_by(PensionSnapshot.review_date, Pension.provider)
        
        results = query.all()
        
        # Group by date
        grouped = {}
        for snapshot, pension in results:
            date_key = snapshot.review_date
            if date_key not in grouped:
                grouped[date_key] = {
                    'review_date': date_key,
                    'is_projection': snapshot.is_projection,
                    'pensions': {},
                    'total_value': Decimal('0'),
                    'total_growth_percent': None
                }
            
            grouped[date_key]['pensions'][pension.provider] = {
                'value': snapshot.value,
                'growth_percent': snapshot.growth_percent,
                'person': pension.person
            }
            grouped[date_key]['total_value'] += snapshot.value
        
        # Convert to sorted list
        combined_list = sorted(grouped.values(), key=lambda x: x['review_date'])
        
        # Calculate total growth percentages
        for i, row in enumerate(combined_list):
            if i > 0:
                prev_total = combined_list[i-1]['total_value']
                if prev_total > 0:
                    row['total_growth_percent'] = (row['total_value'] - prev_total) / prev_total * 100
        
        return combined_list
