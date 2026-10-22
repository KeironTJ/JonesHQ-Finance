# JonesHQ Finance

A household finance management web application built with Flask, designed to
track accounts, transactions, income, expenses, loans, vehicles, childcare,
pensions, mortgages, subscriptions, and net worth.

## Documentation

📚 **[View Complete Documentation →](docs/)**

- [Quick Start Guide](docs/QUICKSTART.md) - Get up and running quickly
- [Database Schema](docs/DATABASE_SCHEMA.md) - Complete database structure
- [Vendor System](docs/VENDOR_SYSTEM.md) - Vendor tracking and management

## Features

- **Account Management**: Track multiple bank accounts (Joint, Personal, Savings)
- **Transaction Tracking**: Record and categorize all financial transactions
- **Vendor Management**: Associate transactions with merchant records for analytics
- **Category Management**: Organize transactions with reusable categories
- **Credit Card Management**: Monitor credit cards with interest tracking
- **Loan & Mortgage Tracking**: Track loan payments, interest, and amortization
- **Budget Planning**: Set and monitor budgets by category
- **Vehicle & Fuel Tracking**: Log fuel purchases, calculate MPG, track trips
- **Childcare Expenses**: Monitor childcare costs per child
- **Pension Tracking**: Track multiple pension accounts with growth
- **Net Worth Analysis**: Historical net worth snapshots with trend analysis
- **Work Expenses**: Track business expenses and mileage reimbursements
- **Income Tracking**: Detailed payslip tracking with pension contributions
- **Subscription Tracking**: Manage recurring bank and credit-card charges, review
  estimated annual costs, compare paid history, and preview dated price changes
- **Cash-Flow Reminders**: Review upcoming subscription charges and other attention
  items from the dashboard

## Setup Instructions

### 1. Create Virtual Environment

```powershell
# Create virtual environment
python -m venv venv

# Activate virtual environment
.\venv\Scripts\Activate.ps1

# If you get an execution policy error, run:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 2. Install Dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure Environment

```powershell
# Copy the example environment file
copy .env.example .env

# Edit .env and set your configuration
# You can use any text editor
notepad .env
```

### 4. Initialize Database

```powershell
# Apply the checked-in migrations
flask db upgrade

# For model changes, generate and review a migration before applying it:
# flask db migrate -m "Describe the schema change"
# flask db upgrade
```

The application currently also calls `db.create_all()` during application
startup. Flask-Migrate remains the source of truth for schema changes; review
the migration history before deploying to an existing database.

### 5. Run the Application

```powershell
# Run development server
python app.py

# Or use Flask CLI
flask run
```

The application will be available at `http://localhost:5000`

## Project Structure

```
Family HQ/
├── app.py                  # Application factory
├── config.py               # Configuration settings
├── extensions.py           # Flask extensions
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (not in git)
├── .gitignore             # Git ignore rules
├── models/                 # Database models
│   ├── __init__.py
│   ├── accounts.py
│   ├── categories.py
│   ├── transactions.py
│   ├── credit_cards.py
│   ├── loans.py
│   ├── vehicles.py
│   └── ...
├── services/              # Business logic and domain workflows
│   ├── analytics/
│   ├── finance/
│   ├── household/
│   ├── planning/
│   ├── platform/
│   └── vehicles/
├── blueprints/            # Route blueprints
│   ├── dashboard/
│   ├── accounts/
│   ├── transactions/
│   ├── credit_cards/
│   ├── expenses/
│   ├── income/
│   ├── plans/
│   └── ...
├── templates/             # HTML templates
│   ├── base.html
│   ├── shared/
│   └── ...
├── static/                # Static assets
│   ├── css/
│   ├── js/
│   └── favicon.svg
└── migrations/            # Database migrations
```

## Database Schema

See [docs/DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md) for detailed documentation of the database structure.

## Development Workflow

### Making Database Changes

```powershell
# 1. Modify models in models/ directory
# 2. Create migration
flask db migrate -m "Description of changes"

# 3. Review the migration file in migrations/versions/
# 4. Apply migration
flask db upgrade

# To rollback:
flask db downgrade
```

### Adding New Features

1. Create/update model in `models/`
2. Create/update service in `services/`
3. Create/update routes in `blueprints/`
4. Create/update templates in `templates/`
5. Test thoroughly

### Tests and CI

Install `requirements-dev.txt`, then run the full SQLite suite:

```powershell
venv\Scripts\python.exe -m pytest -q
```

[CI](.github/workflows/tests.yml) also runs an isolated PostgreSQL 17 job covering
household isolation, financial writes, constraints, current-release migrations,
and a real recovery dump/restore. PostgreSQL fixtures require `TEST_DATABASE_URL`
to name a local `joneshq_ci_*` database and create/remove only their own unique
schema. Never use a production database. PostgreSQL-only checks are skipped in
the SQLite run; restore checks require matching PostgreSQL client tools.

## Migration from Excel

Historical one-off import and repair scripts have been removed. Use the
application's current forms and services for financial records. Any new import
workflow must be reviewed and tested separately, preserve household scoping,
and set `family_id` explicitly. See the [script guide](scripts/README.md) for
retained diagnostics and supported operational commands.

## Technologies Used

- **Flask**: Web framework
- **SQLAlchemy**: ORM for database operations
- **Flask-Migrate**: Database migrations
- **Bootstrap 5**: Frontend CSS framework
- **SQLite**: Local development and test database
- **PostgreSQL 17**: Production database (see [deployment/README.md](deployment/README.md))

## Security Notes

- Never commit `.env` file to version control
- Change `SECRET_KEY` in production
- Use environment variables for sensitive data
- Enable HTTPS in production
- Use strong passwords for database access

## Future Enhancements

Potential areas to explore:

- Guided bank-statement import with duplicate detection and category suggestions
- What-if cash-flow scenarios for large purchases or changes in income and bills
- User-defined transaction rules for categorization and recurring-charge matching
- Deeper budget-versus-actual comparisons across monthly and payday periods
- Custom Excel/PDF financial reports
- Multi-currency support and tax-focused reporting

Authentication, family membership, section permissions, CSRF protection,
rate limiting, and password policy are already implemented. See
[`docs/SECURITY.md`](docs/SECURITY.md) and
[`docs/AUTHENTICATION_SETUP.md`](docs/AUTHENTICATION_SETUP.md).

## License

Private - For Personal Use

## Author

Keiron Jones
