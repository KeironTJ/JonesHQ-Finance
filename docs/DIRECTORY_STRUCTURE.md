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
- `budgets/` - Budget tracking
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
- `settings/` - User and application settings

### `/models/`
SQLAlchemy database models
- `accounts.py` - Account model
- `balances.py` - Balance history
- `budgets.py` - Budget model
- `categories.py` - Category model
- `childcare.py` - Childcare records and related entities
- `credit_cards.py` - Credit card model
- `credit_card_transactions.py` - Credit card transactions
- `expenses.py` - Expense tracking
- `fuel.py` - Fuel records
- `income.py` - Income tracking
- `loans.py` - Loan model
- `loan_payments.py` - Loan payment history
- `mortgage.py` - Mortgage model
- `mortgage_payments.py` - Mortgage payment history
- `networth.py` - Net worth snapshots
- `pensions.py` - Pension model
- `pension_snapshots.py` - Pension history
- `planned.py` - Planned transactions
- `transactions.py` - Bank transaction model
- `trips.py` - Trip tracking
- `vehicles.py` - Vehicle model
- `vendors.py` - Vendor model
- `family.py` / `users.py` - Family and user identity models
- `settings.py` / `tax_settings.py` - User configuration
- `property.py` / `property_valuation_snapshot.py` - Property assets and valuations
- `recurring_income.py` - Recurring income
- `monthly_account_balance.py` - Monthly account balances

### `/services/`
Business logic layer
- `childcare_service.py` - Childcare logic
- `credit_card_service.py` - Credit card automation
- `expense_sync_service.py` - Expense synchronization
- `fuel_forecasting_service.py` - Fuel forecasting
- `income_service.py` - Income workflows
- `loan_service.py` - Loan calculations
- `monthly_balance_service.py` - Monthly balance workflows
- `mortgage_service.py` - Mortgage operations
- `networth_service.py` - Net worth calculations
- `payday_service.py` - Payday calculations and filtering
- `pension_service.py` - Pension projections
- `vehicle_service.py` - Vehicle tracking
- `work_expense_mileage_service.py` - Work expense mileage

### `/templates/`
Jinja2 HTML templates
- `base.html` - Base template with navigation
- `categories/` - Category templates
- `components/` - Reusable components
- `credit_cards/` - Credit card templates
- `layout/` - Layout components
- `transactions/` - Transaction templates
- `vendors/` - Vendor templates

### `/static/`
Static assets
- `css/` - Stylesheets
- `js/` - JavaScript files
- `favicon.svg` - Application favicon

### `/scripts/`
Database management and import scripts
- `checks/` - Repository and data checks
- `database/` - Database setup and sample-data scripts
- `imports/` - Import and migration scripts
- `maintenance/` - Maintenance and recalculation scripts
- `README.md` - Script conventions and inventory

### `/docs/`
Documentation
- `README.md` - Main documentation
- `SECURITY.md` - Security guidelines
- `TRANSACTION_EDITING.md` - Transaction editing guide
- `BRANCHING_STRATEGY.md` - Git branching strategy
- `CATEGORY_MAPPING.md` - Category mapping documentation
- `CREDIT_CARD_IMPLEMENTATION.md` - Credit card system docs
- `DATABASE_SCHEMA.md` - Database schema documentation
- `VENDOR_SYSTEM.md` - Vendor system documentation
- `QUICKSTART.md` - Quick start guide
- `DIRECTORY_STRUCTURE.md` - This file

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
