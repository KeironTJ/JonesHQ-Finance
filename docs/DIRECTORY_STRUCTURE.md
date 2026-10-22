# JonesHQ Finance - Directory Structure

## Root Files
- `app.py` - Flask application factory
- `config.py` - Application configuration
- `extensions.py` - Flask extensions initialization
- `requirements.txt` - Python dependencies
- `run.bat` / `run.ps1` - Launch scripts
- `README.md` - Project documentation

## Core Directories

### `/blueprints/`
Flask blueprints for modular route organization
- `accounts/` - Bank account management
- `categories/` - Transaction categories
- `childcare/` - Childcare expense tracking
- `credit_cards/` - Credit card management
- `dashboard/` - Main dashboard
- `loans/` - Loan tracking
- `mortgage/` - Mortgage management
- `networth/` - Net worth calculations
- `pensions/` - Pension tracking
- `transactions/` - Transaction management
- `vehicles/` - Vehicle expense tracking
- `vendors/` - Vendor management
- `auth/` - Authentication and login
- `expenses/` - General and work expense management
- `family/` - Family membership and assignments
- `income/` - Income and payslip tracking
- `settings/` - Owner-only household settings hub, independent configuration pages,
  and tax-year editing
- `preferences/` - Personal display and default-account preferences for all signed-in users
- `onboarding/` - Household onboarding
- `plans/` - Financial plans and plan items
- `site_admin/` - Service-operator administration

### `/models/`
SQLAlchemy database models
- `accounts.py` - Account model
- `subscriptions.py` - Managed recurring bank and credit-card charges
- `balances.py` - Balance history
- `budgets.py` - Budget model
- `categories.py` - Category model
- `childcare.py` - Childcare records and related entities
- `credit_cards.py` - Credit card model
- `credit_card_transactions.py` - Credit card transactions
- `expenses.py` - Expense tracking
- `expense_calendar.py` - Expense calendar entries
- `expense_reimbursement_group.py` - Reimbursement groups
- `fuel.py` - Fuel records
- `income.py` - Income tracking
- `income_change.py` - Income change history
- `loans.py` - Loan model
- `loan_payments.py` - Loan payment history
- `loan_term_changes.py` - Loan term changes
- `mortgage.py` - Mortgage model
- `mortgage_payments.py` - Mortgage payment history
- `networth.py` - Net worth snapshots
- `pensions.py` - Pension model
- `pension_snapshots.py` - Pension history
- `passkeys.py` - Passkey credentials
- `plans.py` - Plans and plan items
- `planned.py` - Planned transactions
- `transactions.py` - Bank transaction model
- `trips.py` - Trip tracking
- `vehicles.py` - Vehicle model
- `vendors.py` - Vendor model
- `family.py` / `users.py` - Family and user identity models
- `settings.py` / `tax_settings.py` - Household configuration; personal display
  preferences are stored in `User.preferences`
- `site_settings.py` - Service-wide site settings
- `property.py` / `property_valuation_snapshot.py` - Property assets and valuations
- `recurring_income.py` - Recurring income
- `monthly_account_balance.py` - Monthly account balances

### `/services/`
Domain-oriented business logic layer. See [`services/README.md`](../services/README.md)
for the package map and compatibility-import policy.
- `finance/` - Accounts, categories, transactions, subscriptions, payday, balances, income, vendors, credit cards, and expenses
- `household/` - Family and childcare workflows
- `planning/` - Loans, mortgages, and pensions
- `vehicles/` - Vehicles, fuel forecasting, and mileage
- `platform/` - Authentication and settings
- `analytics/` - Dashboard and net-worth read models

### `/templates/`
Jinja2 HTML templates
- `base.html` - Shared workspace shell and public header. Grouped sidebar navigation
  becomes a focus-trapped drawer below 992px. Owner-only Settings and Family links
  live under "Your workspace"; personal preferences is available to every member.
- `shared/` - Permission-aware navigation, page search, UI macros and shared analytics chart setup
- `email/` - Email templates
- `errors/` - Error pages
- `settings/` - Settings hub and independently saved household, credit-card,
  work-expense, net-worth and tax configuration
- `preferences/` - Personal dashboard/list defaults and account-persisted appearance
- `auth/` - Authentication pages
- `childcare/` - Childcare pages
- `categories/` - Category templates
- `credit_cards/` - Credit card templates
- `dashboard/` - Dashboard pages
- `expenses/` - Expense pages
- `family/` - Household pages
- `income/` - Income pages
- `loans/` - Loan pages
- `mortgage/` - Mortgage pages
- `networth/` - Net-worth pages
- `onboarding/` - Onboarding pages
- `pensions/` - Pension pages
- `plans/` - Planning pages
- `public/` - Public pages
- `site_admin/` - Site-administration pages
- `vehicles/` - Vehicle pages
- `transactions/` - Transaction templates
- `vendors/` - Vendor templates

### `/static/`
Static assets
- `css/theme.css` - Shared typography, base styles, layout utilities and accessibility
- `css/system/` - Theme tokens, reusable Bootstrap components, workspace shell,
  domain patterns and public/authentication styling (see [Design System](DESIGN_SYSTEM.md))
- `css/` - Additional domain styles for transactions, credit cards, plans and vehicles
- `js/` - Shared theme management, workspace interactions, analytics charts and feature scripts
- `favicon.svg` - Application favicon

### `/scripts/`
Retained diagnostics
- `checks/check_family_id_integrity.py` - Detect missing household IDs
- `README.md` - Usage and supported operational alternatives

### `/docs/`
Documentation
- `README.md` - Main documentation
- `AUTHENTICATION_SETUP.md` - Authentication setup and behavior
- `BRANCHING_STRATEGY.md` - Branching strategy
- `CREDIT_CARD_IMPLEMENTATION.md` - Credit card system documentation
- `DATABASE_SCHEMA.md` - Database schema documentation
- `DESIGN_SYSTEM.md` - Design tokens and UI patterns
- `EXPENSE_SYSTEM.md` - Expense workflows
- `INCOME_PENSION_SYSTEM.md` - Income and pension workflows
- `INTEGRATED_TRANSACTIONS.md` - Transaction and domain integrations
- `MONTHLY_BALANCE_CACHE.md` - Monthly balance cache
- `PAYDAY_TRACKING.md` - Payday tracking
- `PENSION_PROJECTIONS.md` - Pension projections
- `QUICKSTART.md` - Quick start guide
- `RETIREMENT_PLANNING.md` - Retirement planning
- `SECURITY.md` - Security guidelines
- `SECURITY_HARDENING.md` - Security controls and hardening
- `SUBSCRIPTIONS.md` - Subscription workflows
- `TRANSACTION_EDITING.md` - Transaction editing guide
- `VENDOR_SYSTEM.md` - Vendor system documentation
- `DIRECTORY_STRUCTURE.md` - This file
- `REVIEW_FINDINGS.md` - Resolved findings and detailed follow-up work

### `/instance/`
Instance-specific files (gitignored)
- Database file
- Instance configuration

### `/migrations/`
Flask-Migrate database migrations
- `alembic.ini` - Alembic configuration
- `env.py` - Migration environment
- `versions/` - Migration versions

## Environment Files
- `.env` - Environment variables (gitignored)
- `.env.example` - Environment template
- `venv/` - Python virtual environment (gitignored; local development)

## Git Files
- `.git/` - Git repository
- `.gitignore` - Git ignore rules
- `.gitattributes` - Git attributes

## Application Boundaries
1. **Documentation** → `/docs/`
2. **Database and instance state** → `/instance/`
3. **Source code** → `/blueprints/`, `/models/`, `/services/`, `/utils/`
4. **Frontend** → `/templates/`, `/static/`
5. **Utilities and operational scripts** → `/scripts/`
6. **Schema history** → `/migrations/`

The application uses the Flask application-factory pattern in `app.py`.
Blueprints own HTTP routes and templates, models define persistence, services
hold reusable domain workflows, and utilities hold cross-cutting helpers.
Authentication and family permissions are enforced centrally while feature
routes remain organized by blueprint.
