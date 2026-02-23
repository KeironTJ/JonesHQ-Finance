"""
Flask-Admin panel for JonesHQ Finance
Accessible at /admin - restricted to users with role='admin'
"""
from flask import redirect, url_for, flash
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.contrib.sqla import ModelView
from flask_admin.theme import Bootstrap4Theme
from flask_login import current_user


# ---------------------------------------------------------------------------
# Base secure views
# ---------------------------------------------------------------------------

class SecureAdminIndexView(AdminIndexView):
    """Admin home page - checks for admin role before rendering."""

    @expose('/')
    def index(self):
        if not current_user.is_authenticated or not current_user.is_site_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('auth.intro'))
        return super().index()

    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_site_admin

    def inaccessible_callback(self, name, **kwargs):
        flash('Admin access required.', 'danger')
        return redirect(url_for('auth.intro'))


class SecureModelView(ModelView):
    """Full CRUD model view - admin only."""

    can_export = True
    page_size = 50
    column_display_pk = True

    def __init__(self, model, session, **kwargs):
        # Auto-prefix all endpoints with 'admin_' to avoid conflicts with
        # existing app blueprints that share the same model names.
        if 'endpoint' not in kwargs:
            kwargs['endpoint'] = f'admin_{model.__name__.lower()}'

        # If the model has a family_id column, automatically inject it into
        # column_filters as an instance attribute before super().__init__()
        # so every table can be scoped by family without explicit per-view config.
        if hasattr(model, 'family_id'):
            # Gather any filters already declared on the subclass
            existing = list(getattr(self.__class__, 'column_filters', None) or [])
            if 'family_id' not in existing:
                existing.insert(0, 'family_id')
            # Set as instance attribute - Flask-Admin reads this in _refresh_cache()
            self.column_filters = existing

        super().__init__(model, session, **kwargs)

    def scaffold_list_columns(self):
        """Ensure family_id always appears in the column list for models that have it."""
        columns = super().scaffold_list_columns()
        if hasattr(self.model, 'family_id') and 'family_id' not in columns:
            columns.insert(1, 'family_id')  # after id
        return columns

    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_site_admin

    def inaccessible_callback(self, name, **kwargs):
        flash('Admin access required.', 'danger')
        return redirect(url_for('auth.intro'))


class ReadOnlyModelView(SecureModelView):
    """Read-only model view for sensitive or computed tables."""

    can_create = False
    can_edit = False
    can_delete = False


# ---------------------------------------------------------------------------
# Customised model views
# ---------------------------------------------------------------------------

class UserAdminView(SecureModelView):
    """Users - hide password hash, show useful columns."""
    column_exclude_list = ['password_hash']
    form_excluded_columns = ['password_hash']
    column_searchable_list = ['email', 'name', 'member_name']
    column_filters = ['role', 'is_active', 'is_site_admin', 'family_id']
    column_list = [
        'id', 'name', 'email', 'role', 'is_active', 'is_site_admin',
        'family_id', 'member_name', 'last_login', 'created_at',
        'failed_login_attempts', 'locked_until',
    ]


class TransactionAdminView(SecureModelView):
    column_searchable_list = ['description', 'item', 'assigned_to']
    column_filters = ['transaction_date', 'payment_type', 'account_id', 'family_id']
    column_default_sort = ('transaction_date', True)


class AccountAdminView(SecureModelView):
    column_searchable_list = ['name']
    column_filters = ['account_type', 'is_active', 'family_id']


class CategoryAdminView(SecureModelView):
    column_searchable_list = ['name']
    column_filters = ['category_type', 'family_id']


class VendorAdminView(SecureModelView):
    column_searchable_list = ['name']
    column_filters = ['is_active', 'family_id']


class ExpenseAdminView(SecureModelView):
    column_searchable_list = ['description']
    column_filters = ['date', 'expense_type', 'family_id']
    column_default_sort = ('date', True)


class IncomeAdminView(SecureModelView):
    column_searchable_list = ['person', 'tax_year']
    column_filters = ['pay_date', 'person', 'family_id']
    column_default_sort = ('pay_date', True)


class LoanAdminView(SecureModelView):
    column_searchable_list = ['name']
    column_filters = ['is_active', 'family_id']


class CreditCardAdminView(SecureModelView):
    column_searchable_list = ['card_name']
    column_filters = ['is_active', 'family_id']


class PensionAdminView(SecureModelView):
    column_searchable_list = ['provider', 'person']
    column_filters = ['person', 'is_active', 'family_id']


class VehicleAdminView(SecureModelView):
    column_searchable_list = ['make', 'model', 'registration']
    column_filters = ['fuel_type', 'is_active', 'family_id']


class FamilyAdminView(SecureModelView):
    column_searchable_list = ['name']


# ---------------------------------------------------------------------------
# Admin factory
# ---------------------------------------------------------------------------

def init_admin(app, db):
    """Create the Flask-Admin instance and register all model views."""

    admin = Admin(
        app,
        name='JonesHQ Admin',
        theme=Bootstrap4Theme(),
        index_view=SecureAdminIndexView(),
        url='/admin',
    )

    # ---- Import all models ------------------------------------------------
    from models.users import User
    from models.family import Family, FamilyInvite
    from models.accounts import Account
    from models.balances import Balance
    from models.budgets import Budget
    from models.transactions import Transaction
    from models.planned import PlannedTransaction
    from models.categories import Category
    from models.vendors import Vendor, VendorType
    from models.income import Income
    from models.recurring_income import RecurringIncome
    from models.expenses import Expense
    from models.expense_calendar import ExpenseCalendarEntry
    from models.loans import Loan
    from models.loan_payments import LoanPayment
    from models.credit_cards import CreditCard, CreditCardPromotion
    from models.credit_card_transactions import CreditCardTransaction
    from models.mortgage import Mortgage, MortgageProduct
    from models.mortgage_payments import MortgagePayment, MortgageSnapshot
    from models.pensions import Pension
    from models.pension_snapshots import PensionSnapshot
    from models.vehicles import Vehicle
    from models.fuel import FuelRecord
    from models.trips import Trip
    from models.childcare import ChildcareRecord, Child, ChildActivityType, DailyChildcareActivity, MonthlyChildcareSummary
    from models.networth import NetWorth
    from models.monthly_account_balance import MonthlyAccountBalance
    from models.settings import Settings
    from models.tax_settings import TaxSettings
    from models.property import Property

    # ---- Register views ---------------------------------------------------

    # Core / Auth
    admin.add_view(UserAdminView(User, db.session, name='Users', category='Core'))
    admin.add_view(FamilyAdminView(Family, db.session, name='Families', category='Core'))
    admin.add_view(SecureModelView(FamilyInvite, db.session, name='Invites', category='Core'))

    # Accounts & Transactions
    admin.add_view(AccountAdminView(Account, db.session, name='Accounts', category='Accounts'))
    admin.add_view(ReadOnlyModelView(Balance, db.session, name='Balances', category='Accounts'))
    admin.add_view(ReadOnlyModelView(MonthlyAccountBalance, db.session, name='Monthly Balances', category='Accounts'))
    admin.add_view(TransactionAdminView(Transaction, db.session, name='Transactions', category='Accounts'))
    admin.add_view(SecureModelView(PlannedTransaction, db.session, name='Planned', category='Accounts'))

    # Income
    admin.add_view(IncomeAdminView(Income, db.session, name='Income', category='Income'))
    admin.add_view(SecureModelView(RecurringIncome, db.session, name='Recurring Income', category='Income'))

    # Expenses
    admin.add_view(ExpenseAdminView(Expense, db.session, name='Expenses', category='Expenses'))
    admin.add_view(SecureModelView(ExpenseCalendarEntry, db.session, name='Calendar Entries', category='Expenses'))
    admin.add_view(SecureModelView(Budget, db.session, name='Budgets', category='Expenses'))

    # Credit Cards
    admin.add_view(CreditCardAdminView(CreditCard, db.session, name='Credit Cards', category='Credit Cards'))
    admin.add_view(SecureModelView(CreditCardPromotion, db.session, name='Promotions', category='Credit Cards'))
    admin.add_view(SecureModelView(CreditCardTransaction, db.session, name='CC Transactions', category='Credit Cards'))

    # Loans
    admin.add_view(LoanAdminView(Loan, db.session, name='Loans', category='Loans'))
    admin.add_view(SecureModelView(LoanPayment, db.session, name='Loan Payments', category='Loans'))

    # Mortgage
    admin.add_view(SecureModelView(Mortgage, db.session, name='Mortgage', category='Mortgage'))
    admin.add_view(SecureModelView(MortgageProduct, db.session, name='Products', category='Mortgage'))
    admin.add_view(SecureModelView(MortgagePayment, db.session, name='Payments', category='Mortgage'))
    admin.add_view(ReadOnlyModelView(MortgageSnapshot, db.session, name='Snapshots', category='Mortgage'))

    # Pensions
    admin.add_view(PensionAdminView(Pension, db.session, name='Pensions', category='Pensions'))
    admin.add_view(ReadOnlyModelView(PensionSnapshot, db.session, name='Snapshots', category='Pensions'))

    # Vehicles
    admin.add_view(VehicleAdminView(Vehicle, db.session, name='Vehicles', category='Vehicles'))
    admin.add_view(SecureModelView(FuelRecord, db.session, name='Fuel Records', category='Vehicles'))
    admin.add_view(SecureModelView(Trip, db.session, name='Trips', category='Vehicles'))

    # Childcare
    admin.add_view(SecureModelView(Child, db.session, name='Children', category='Childcare'))
    admin.add_view(SecureModelView(ChildActivityType, db.session, name='Activity Types', category='Childcare'))
    admin.add_view(SecureModelView(DailyChildcareActivity, db.session, name='Daily Activities', category='Childcare'))
    admin.add_view(ReadOnlyModelView(MonthlyChildcareSummary, db.session, name='Monthly Summary', category='Childcare'))
    admin.add_view(SecureModelView(ChildcareRecord, db.session, name='Records', category='Childcare'))

    # Reference Data
    admin.add_view(CategoryAdminView(Category, db.session, name='Categories', category='Reference'))
    admin.add_view(VendorAdminView(Vendor, db.session, name='Vendors', category='Reference'))
    admin.add_view(SecureModelView(VendorType, db.session, name='Vendor Types', category='Reference'))

    # Net Worth & Analytics
    admin.add_view(ReadOnlyModelView(NetWorth, db.session, name='Net Worth', category='Analytics'))
    admin.add_view(SecureModelView(Property, db.session, name='Properties', category='Analytics'))

    # Settings
    admin.add_view(SecureModelView(Settings, db.session, name='Settings', category='Settings'))
    admin.add_view(SecureModelView(TaxSettings, db.session, name='Tax Settings', category='Settings'))

    return admin
