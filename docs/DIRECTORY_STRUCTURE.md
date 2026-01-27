# JonesHQ Finance - Directory Structure

## Root Files
- `app.py` - Flask application factory
- `config.py` - Application configuration
- `extensions.py` - Flask extensions initialization
- `init_db.py` - Database initialization script
- `populate_sample_data.py` - Sample data generator
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

### `/models/`
SQLAlchemy database models
- `accounts.py` - Account model
- `balances.py` - Balance history
- `budgets.py` - Budget model
- `categories.py` - Category model
- `childcare.py` - Childcare records
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

### `/services/`
Business logic layer
- `account_service.py` - Account operations
- `budget_service.py` - Budget calculations
- `childcare_service.py` - Childcare logic
- `credit_card_service.py` - Credit card automation
- `forecasting_service.py` - Financial forecasting
- `loan_service.py` - Loan calculations
- `mortgage_service.py` - Mortgage operations
- `networth_service.py` - Net worth calculations
- `pension_service.py` - Pension projections
- `vehicle_service.py` - Vehicle tracking

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
- `images/` - Images and logos
- `js/` - JavaScript files

### `/scripts/`
Database management and import scripts
- `check_vendors.py` - Vendor validation
- `import_accounts_ACTUAL.py` - Import accounts
- `import_categories.py` - Import categories
- `import_credit_cards_ACTUAL.py` - Import credit cards
- `import_loans_ACTUAL.py` - Import loans
- `import_transactions_csv.py` - CSV transaction import
- `import_transactions_nationwide.py` - Nationwide bank import
- `import_vendors.py` - Vendor import
- `migrate_credit_cards.py` - Credit card migration
- `recalculate_balances.py` - Balance recalculation
- `sync_transfer_transactions.py` - Transfer sync
- `update_account_balance.py` - Account balance updates
- `update_savings_balances.py` - Savings updates
- `data/` - Import data files

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

### `/data/`
Data files and outputs
- `transfer_output.txt` - Transfer processing output

## Environment Files
- `.env` - Environment variables (gitignored)
- `.env.example` - Environment template
- `.venv/` - Python virtual environment (gitignored)

## Git Files
- `.git/` - Git repository
- `.gitignore` - Git ignore rules
- `.gitattributes` - Git attributes

## Clean Directory Principles
1. **Documentation** → `/docs/`
2. **Data files** → `/data/`
3. **Database** → `/instance/`
4. **Source code** → `/blueprints/`, `/models/`, `/services/`
5. **Frontend** → `/templates/`, `/static/`
6. **Utilities** → `/scripts/`
7. **No `__pycache__`** - Cleaned automatically
8. **Single venv** - `.venv` (not `venv`)
