# JonesHQ Finance

A comprehensive personal finance management web application built with Flask, designed to track accounts, budgets, loans, vehicles, childcare, pensions, mortgages, and net worth.

## Documentation

📚 **[View Complete Documentation →](docs/)**

- [Quick Start Guide](docs/QUICKSTART.md) - Get up and running quickly
- [Database Schema](docs/DATABASE_SCHEMA.md) - Complete database structure
- [Category Mapping](docs/CATEGORY_MAPPING.md) - Excel to database category mapping
- [Vendor System](docs/VENDOR_SYSTEM.md) - Vendor tracking and management

## Features

- **Account Management**: Track multiple bank accounts (Joint, Personal, Savings)
- **Transaction Tracking**: Record and categorize all financial transactions
- **✅ Vendor Management**: Standardize merchant names for better analytics (177 vendors imported)
- **✅ Category Management**: Organize transactions with generic, reusable categories (42 categories imported)
- **Credit Card Management**: Monitor credit cards with interest tracking
- **Loan & Mortgage Tracking**: Track loan payments, interest, and amortization
- **Budget Planning**: Set and monitor budgets by category
- **Vehicle & Fuel Tracking**: Log fuel purchases, calculate MPG, track trips
- **Childcare Expenses**: Monitor childcare costs per child
- **Pension Tracking**: Track multiple pension accounts with growth
- **Net Worth Analysis**: Historical net worth snapshots with trend analysis
- **Work Expenses**: Track business expenses and mileage reimbursements
- **Income Tracking**: Detailed payslip tracking with pension contributions

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
JonesHQ Finance/
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
│   ├── income_service.py
│   ├── loan_service.py
│   ├── mortgage_service.py
│   └── ...
├── blueprints/            # Route blueprints
│   ├── dashboard/
│   ├── accounts/
│   ├── transactions/
│   └── ...
├── templates/             # HTML templates
│   ├── base.html
│   └── ...
├── static/                # Static assets
│   ├── css/
│   ├── js/
│   └── favicon.svg
└── migrations/            # Database migrations
```

## Database Schema

See [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) for detailed documentation of the database structure.

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

## Migration from Excel

To migrate data from your existing Excel spreadsheets:

1. Create import scripts in a `scripts/` directory
2. Read Excel data using `pandas` or `openpyxl`
3. Map Excel columns to database fields
4. Insert data using SQLAlchemy models
5. Validate imported data

Example:
```python
import pandas as pd
from app import create_app
from models import Transaction, Category

app = create_app()
with app.app_context():
    # Read Excel
    df = pd.read_excel('your_excel_file.xlsx', sheet_name='JOINTACCOUNT')
    
    # Process and insert
    for _, row in df.iterrows():
        transaction = Transaction(
            transaction_date=row['Date'],
            amount=row['Budget'],
            # ... map other fields
        )
        db.session.add(transaction)
    
    db.session.commit()
```

## Technologies Used

- **Flask**: Web framework
- **SQLAlchemy**: ORM for database operations
- **Flask-Migrate**: Database migrations
- **Bootstrap 5**: Frontend CSS framework
- **SQLite**: Development database (can use PostgreSQL/MySQL in production)

## Security Notes

- Never commit `.env` file to version control
- Change `SECRET_KEY` in production
- Use environment variables for sensitive data
- Enable HTTPS in production
- Use strong passwords for database access

## Future Enhancements

- [ ] Data visualization with charts (Chart.js/Plotly)
- [ ] Export to Excel/PDF reports
- [ ] Budget alerts and notifications
- [ ] Mobile responsive improvements
- [ ] REST API for mobile app integration
- [ ] Automated data import from bank feeds
- [ ] Multi-currency support
- [ ] Tax reporting features

Authentication, family membership, section permissions, CSRF protection,
rate limiting, and password policy are already implemented. See
[`docs/SECURITY.md`](docs/SECURITY.md) and
[`docs/AUTHENTICATION_SETUP.md`](docs/AUTHENTICATION_SETUP.md).

## License

Private - For Personal Use

## Author

Keiron Jones
