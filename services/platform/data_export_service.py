from datetime import date, datetime, timezone
from decimal import Decimal

from models import (
    Account, Balance, Budget, Category, CreditCard, CreditCardPromotion,
    CreditCardTransaction, Expense, Income, Loan, LoanPayment, LoanTermChange,
    Mortgage, MortgagePayment, MortgageProduct, MortgageSnapshot, Pension,
    PensionSnapshot, Plan, PlanItem, PlannedTransaction, Property,
    PropertyValuationSnapshot, RecurringIncome, Subscription, Transaction,
    Trip, Vehicle, Vendor, VendorType, FuelRecord,
)
from models.childcare import Child, ChildActivityType, ChildcareRecord, DailyChildcareActivity
from utils.db_helpers import family_query, get_family_id, get_current_user_id


# Explicit fields prevent new model columns or relationships from entering exports automatically.
EXPORTS = {
    'accounts': (
        (Account, 'id name account_type balance is_active owner_id'),
        (Balance, 'id account_id balance balance_date'),
    ),
    'transactions': (
        (Transaction, 'id account_id category_id vendor_id amount transaction_date description item assigned_to payment_type running_balance is_paid is_fixed credit_card_id loan_id linked_transaction_id subscription_id year_month week_year day_name payday_period is_forecasted claim_group reimbursement_group_id'),
        (Subscription, 'id name amount frequency start_date end_date horizon_years account_id credit_card_id category_id vendor_id is_active'),
        (PlannedTransaction, 'id category_id amount planned_date description is_recurring frequency'),
    ),
    'categories': (
        (Category, 'id name parent_id category_type head_budget sub_budget'),
        (Budget, 'id category_id amount period_start period_end'),
    ),
    'vendors': (
        (Vendor, 'id name vendor_type_id vendor_type default_category_id website notes is_active'),
        (VendorType, 'id name is_active sort_order'),
    ),
    'credit_cards': (
        (CreditCard, 'id card_name annual_apr monthly_apr purchase_0_percent_until balance_transfer_0_percent_until min_payment_percent set_payment statement_date default_transfer_fee_percent credit_limit current_balance available_credit default_payment_account_id owner_id start_date is_active'),
        (CreditCardPromotion, 'id credit_card_id promotion_type apr_rate start_date end_date notes'),
        (CreditCardTransaction, 'id credit_card_id category_id vendor_id date day_name week month head_budget sub_budget item assigned_to transaction_type amount applied_apr is_promotional_rate is_paid is_fixed balance credit_available bank_transaction_id statement_id linked_cc_transaction_id subscription_id'),
    ),
    'loans': (
        (Loan, 'id name loan_value principal current_balance annual_apr monthly_apr monthly_payment calculated_payment start_date end_date term_months default_payment_account_id weekend_adjustment owner_id is_active'),
        (LoanPayment, 'id loan_id date year_month period opening_balance payment_amount interest_charge amount_paid_off closing_balance is_paid bank_transaction_id'),
        (LoanTermChange, 'id loan_id effective_date previous_monthly_payment new_monthly_payment previous_annual_apr new_annual_apr previous_payment_day new_payment_day previous_term_months new_term_months notes'),
    ),
    'income': (
        (Income, 'id person pay_date tax_year gross_annual_income gross_monthly_income employer_pension_percent employee_pension_percent employer_pension_amount employee_pension_amount total_pension adjusted_monthly_income adjusted_annual_income tax_code income_tax national_insurance avc other_deductions take_home estimated_annual_take_home deposit_account_id transaction_id recurring_income_id owner_id source description is_recurring is_paid is_manual_override expense_reimbursement_total'),
        (RecurringIncome, 'id person start_date end_date pay_day last_generated_date gross_annual_income employer_pension_percent employee_pension_percent tax_code avc other_deductions use_manual_deductions manual_tax_monthly manual_ni_monthly manual_employer_pension manual_employee_pension manual_take_home deposit_account_id category_id auto_create_transaction owner_id source description is_active'),
    ),
    'pensions': (
        (Pension, 'id person provider account_number current_value contribution_rate employer_contribution is_active retirement_age monthly_contribution projected_value_at_retirement owner_id'),
        (PensionSnapshot, 'id pension_id review_date value growth_percent is_projection scenario_name growth_rate_used notes'),
    ),
    'mortgage': (
        (Mortgage, 'id property_address principal current_balance interest_rate fixed_payment optional_payment start_date term_years property_valuation equity_amount equity_percent is_active'),
        (Property, 'id address purchase_date purchase_price current_valuation annual_appreciation_rate is_primary_residence is_active'),
        (PropertyValuationSnapshot, 'id property_id valuation_date value change_percent is_projection appreciation_rate_used source notes'),
        (MortgageProduct, 'id property_id account_id vendor_id category_id lender product_name start_date end_date term_months initial_balance current_balance annual_rate monthly_payment payment_day is_active is_current ltv_ratio'),
        (MortgagePayment, 'id mortgage_id date year_month mortgage_balance fixed_payment optional_payment interest_charge interest_rate_percent equity_paid property_valuation equity_amount equity_percent'),
        (MortgageSnapshot, 'id mortgage_product_id transaction_id date year_month balance monthly_payment overpayment interest_charge principal_paid interest_rate property_valuation equity_amount equity_percent is_projection scenario_name notes'),
    ),
    'vehicles': (
        (Vehicle, 'id name make model year registration tank_size fuel_type refuel_threshold_pct starting_mileage fuel_account_id purchase_date purchase_price owner_id is_active'),
        (FuelRecord, 'id vehicle_id date price_per_litre mileage cost gallons actual_miles actual_cumulative_miles mpg price_per_mile last_fill_date is_partial_fill linked_transaction_id'),
        (Trip, 'id vehicle_id date month week day_name personal_miles business_miles total_miles cumulative_total_miles journey_description school_holidays approx_mpg gallons_used cumulative_gallons trip_cost fuel_cost fuel_log_entry_id vehicle_last_fill'),
    ),
    'expenses': (
        (Expense, 'id date month week day_name finance_year description expense_type credit_card_id account_id credit_card_transaction_id bank_transaction_id covered_miles rate_per_mile days cumulative_miles_ytd vehicle_registration cost total_cost claim_group reimbursement_group_id payday_period income_id paid_for submitted reimbursed owner_id'),
    ),
    'childcare': (
        (Child, 'id name year_group is_active sort_order default_account_id transaction_day category_id vendor_id'),
        (ChildActivityType, 'id child_id name cost provider is_active sort_order occurs_monday occurs_tuesday occurs_wednesday occurs_thursday occurs_friday occurs_saturday occurs_sunday'),
        (DailyChildcareActivity, 'id date child_id activity_type_id occurred cost_override notes'),
        (ChildcareRecord, 'id date day_name year_month child_name service_type cost year_group provider description'),
    ),
    'plans': (
        (Plan, 'id title plan_type person target_date target_amount saved_amount status notes owner_id'),
        (PlanItem, 'id plan_id title assigned_to estimated_cost actual_cost transaction_id credit_card_transaction_id status priority notes'),
    ),
}

# Scope child rows explicitly as well as using the shared visibility helpers.
PARENTS = {
    Balance: (('account_id', Account),),
    Transaction: (('account_id', Account),),
    CreditCardPromotion: (('credit_card_id', CreditCard),),
    CreditCardTransaction: (('credit_card_id', CreditCard),),
    LoanPayment: (('loan_id', Loan),),
    LoanTermChange: (('loan_id', Loan),),
    PensionSnapshot: (('pension_id', Pension),),
    FuelRecord: (('vehicle_id', Vehicle),),
    Trip: (('vehicle_id', Vehicle),),
    PlanItem: (('plan_id', Plan),),
    ChildActivityType: (('child_id', Child),),
    DailyChildcareActivity: (('child_id', Child), ('activity_type_id', ChildActivityType)),
    PropertyValuationSnapshot: (('property_id', Property),),
    MortgagePayment: (('mortgage_id', Mortgage),),
    MortgageSnapshot: (('mortgage_product_id', MortgageProduct),),
}


def _value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


class DataExportService:
    @staticmethod
    def create(user):
        if not user.is_authenticated or not user.is_active:
            raise ValueError('Sign in to export your data.')
        if user.id != get_current_user_id() or not user.family_id or user.family_id != get_family_id():
            raise ValueError('An active household membership is required to export data.')

        tables = {}
        sections = []
        for section, models in EXPORTS.items():
            if not user.can_access_section(section):
                continue
            sections.append(section)
            for model, fields in models:
                query = family_query(model)
                for foreign_key, parent in PARENTS.get(model, ()):
                    query = query.filter(
                        getattr(model, foreign_key).in_(family_query(parent).with_entities(parent.id)))
                tables[model.__tablename__] = [
                    {field: _value(getattr(row, field)) for field in fields.split()}
                    for row in query.order_by(model.id).all()
                ]

        return {
            'format_version': 1,
            'exported_at': datetime.now(timezone.utc).isoformat(),
            'profile': {
                'id': user.id, 'name': user.name, 'email': user.email,
                'role': user.role, 'member_name': user.member_name,
            },
            'sections': sections,
            'excluded': [
                'Data outside your current household, section permissions or record visibility',
                'Other users profiles, credentials, two-factor secrets, recovery codes, sessions and invites',
                'Security events, server logs, configuration, settings and backups',
                'Cached totals, net-worth snapshots, monthly summaries and reimbursement/calendar metadata',
            ],
            'notes': [
                'This is a user-visible source-data export, not a restorable database backup.',
                'Decimal amounts are strings to preserve precision; dates use ISO 8601.',
                'IDs identify source records; linked records may be absent due to access restrictions.',
                'Tables are read sequentially; avoid concurrent edits for a consistent point-in-time export.',
                'Shared accounts include all their visible transactions, even if a linked source is private.',
            ],
            'data': tables,
        }
