# Quick Start Guide - JonesHQ Finance

## Setup Complete! ✅

Your Flask application is now set up with:
- ✅ Virtual environment created (`venv/`)
- ✅ All dependencies installed
- ✅ Database initialized with 21 tables
- ✅ Configuration files ready
- ✅ .gitignore configured

## Running the Application

### Option 1: Using the Quick Start Script
```powershell
# For Command Prompt
.\run.bat

# For PowerShell
.\run.ps1
```

### Option 2: Manual Start
```powershell
# Activate virtual environment (if not already activated)
.\venv\Scripts\Activate.ps1

# Run the application
python app.py
```

The application will start on **http://localhost:5000**

## Project Status

### ✅ Completed
- Database schema design (21 models)
- Flask application structure
- All blueprints created
- Service layer structure
- Base templates with Bootstrap 5
- Configuration system (dev/prod/test)
- Environment variable setup

### 📋 Next Steps

1. **Data Import**
   - Create scripts to import your Excel data
   - Map Excel columns to database fields
   - Validate imported data

2. **Implement CRUD Operations**
   - Complete route handlers in blueprints
   - Add forms for data entry
   - Implement validation

3. **Business Logic**
   - Implement service layer methods
   - Add calculations (MPG, interest, etc.)
   - Create aggregation queries

4. **UI Enhancements**
   - Add charts and visualizations
   - Improve dashboard
   - Add filtering and search

5. **Advanced Features**
   - User authentication
   - Reports and exports
   - Budget alerts
   - Data visualizations

## Available Routes

Currently registered blueprints:
- `/` or `/dashboard` - Main dashboard
- `/accounts` - Account management
- `/transactions` - Transaction tracking
- `/budgets` - Budget management
- `/loans` - Loan tracking
- `/vehicles` - Vehicle management
- `/childcare` - Childcare expenses
- `/pensions` - Pension tracking
- `/mortgage` - Mortgage management
- `/networth` - Net worth analysis

## Database Tables

All 21 tables created:
1. accounts
2. balances
3. budgets
4. categories
5. childcare_records
6. credit_cards
7. credit_card_transactions
8. expenses
9. fuel_records
10. income
11. loans
12. loan_payments
13. mortgages
14. mortgage_payments
15. net_worth
16. pensions
17. pension_snapshots
18. planned_transactions
19. transactions
20. trips
21. vehicles

## Troubleshooting

### PowerShell Execution Policy Error
If you get an error about scripts being disabled:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Port Already in Use
If port 5000 is in use, edit `app.py` and change the port:
```python
app.run(host='0.0.0.0', port=5001, debug=True)
```

### Database Issues
To reset the database:
```powershell
# Delete the database file
Remove-Item joneshq_finance.db

# Recreate tables
python init_db.py
```

## Environment Variables

Edit `.env` file to configure:
- `SECRET_KEY` - Change for production!
- `DATABASE_URL` - Database connection string
- `FLASK_ENV` - development/production

## Development Tips

1. **Database Queries**: Set `SQLALCHEMY_ECHO = True` in config to see SQL
2. **Auto-reload**: Flask debug mode auto-reloads on code changes
3. **Migrations**: Use Flask-Migrate for database changes
4. **Testing**: Create test database with in-memory SQLite

## Documentation

- Database schema: [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md)
- Full documentation: [README.md](README.md)

## Need Help?

Check the detailed documentation:
- Model definitions: `models/` directory
- Route handlers: `blueprints/` directory
- Business logic: `services/` directory

Happy coding! 🚀
