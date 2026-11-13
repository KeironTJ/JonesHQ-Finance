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
Flask blueprints are grouped by their owning application layer, not by URL.

- `core/` - Registers shared platform routes: `auth/`, `central/`, `family/`,
  `preferences/` (appearance and starting point), and `site_admin/`.
- `finance/` - Owns the Finance module descriptor and blueprint registration:
  `accounts/`, `categories/`, `childcare/`, `credit_cards/`, `dashboard/`,
  `expenses/`, `income/`, `loans/`, `mortgage/`, `networth/`, `onboarding/`,
  `pensions/`, `plans/`, `preferences/` (Finance defaults), `settings/`,
  `transactions/`, `vehicles/`, and `vendors/`.
- `household/` - Household Hub module descriptor, calendar, event and meal routes,
  separate from Core membership administration and Finance childcare.

The application factory registers core once, then the platform registry registers
available modules. Each available module contributes its overview label, sidebar
template, page labels and settings navigation, and identifies its blueprints to
the shared shell. Finance owns `templates/finance/_navigation.html`; shared
navigation renders the registry's available destinations and the active module's
template. Existing URLs are unchanged; Python imports
use the owning package directly, with no forwarding packages at the old paths.
Templates retain their existing feature folders and shared base/design system.
Household Hub owns `templates/household/` and uses the same shell and themes.
Generate internal URLs with `url_for`, including JavaScript form actions and
requests, so module and deployment prefixes are respected.

### `/models/`
SQLAlchemy database models
- `accounts.py` - Account model
- `subscriptions.py` - Managed recurring bank and credit-card charges
- `balances.py` - Balance history
- `budgets.py` - Budget model
- `categories.py` - Category model
- `calendar_event.py` - Household calendar dates, UTC times, visibility and action permissions
- `meals.py` - Shared household meal library and multiple planned meals per date/slot
- `activities.py` - Household activities, child suggestions/reviews and member attendance
- `household_tasks.py` - Personal/shared task lists, member assignments and completion attribution
- `rewards.py` - Shared-task reward jobs, reward catalogue/requests, point ledger and child goals
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
- `trip_schedule.py` - Recurring trip routines
- `trip_template.py` - Saved reusable trip details
- `vehicles.py` - Vehicle model
- `vendors.py` - Vendor model
- `family.py` / `users.py` - Family and user identity models
- `family.py` also defines `HouseholdMembership`: per-household roles, display
  names and Finance section permissions. `User.family_id` is the legacy default,
  not the selected household used by `get_family_id()`.
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
- `household/` - Family, managed-child access, calendar, meal/activity planning, tasks and childcare workflows
- `household/planner_helpers.py` - Shared week/month date periods and navigation
- `planning/` - Loans, mortgages, and pensions
- `vehicles/` - Vehicles, fuel forecasting, and mileage
- `platform/` - Authentication, shared appearance and module orchestration
- `platform/module_registry.py` - Module registration, discovery and shared-shell integration
- `analytics/` - Dashboard and net-worth read models

### `/templates/`
Jinja2 HTML templates
- `base.html` - Shared workspace shell and public header. Grouped sidebar navigation
  becomes a focus-trapped drawer below 992px. One Settings entry opens the shared
  account/people/module landing page; contextual sub-settings retain personal
  and owner-only controls. Children have a shorter My day/calendar/tasks/rewards menu.
- `shared/` - Permission-aware navigation, page search, UI macros and shared analytics chart setup
- `central/` - Registry-driven module launcher
- `finance/` - Finance-owned sidebar navigation
- `household/` - Child My day, month/agenda calendar, event forms, meal library, week/month meal/activity planners, personal/shared tasks and privacy settings
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
Services set `family_id` explicitly with `get_family_id()`. The request-only
auto-stamp backstop uses the same selected-household resolution, leaves explicit
IDs and global records unchanged, and does not infer a household outside requests.
