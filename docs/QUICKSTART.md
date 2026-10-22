# Quick Start Guide - JonesHQ Finance

## Prerequisites

Create and activate the local Python virtual environment, install the project
dependencies, configure the environment, then apply the checked-in migrations:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
flask db upgrade
```

Edit `.env` before production use. Do not reuse development credentials or
secrets in production.

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
flask run
```

The application will start on **http://localhost:5000**

### Important: Database Migrations

If you encounter database errors, ensure migrations are applied:
```powershell
# Apply pending migrations
flask db upgrade
```

## Application Status

This is an actively developed finance application with authentication,
households, transaction and account management, income and expenses, credit
cards, loans, mortgages, pensions, vehicles, childcare, subscriptions, planning,
and net-worth views. The exact routes and workflows are maintained in the
registered blueprints and their templates; this guide intentionally avoids a
stale route or database-table inventory.

## Available Routes

Route handlers are organized under `blueprints/`; consult those packages for
the current routes. See [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) for the model
and table reference. Flask-Migrate's checked-in revisions are authoritative for
schema changes.

## Troubleshooting

### PowerShell Execution Policy Error
If you get an error about scripts being disabled:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Port Already in Use
If port 5000 is in use, start Flask on a different local port:
```powershell
flask run --port 5001
```

### Database Issues
Apply pending migrations:
```powershell
flask db upgrade
```

The development SQLite database is stored under `instance/`. Do not delete or
recreate it as a troubleshooting shortcut; back it up before any intentional
reset. `scripts/database/init_db.py` is for creating tables in a fresh local
database, not for upgrading an existing database.

## Environment Variables

Edit `.env` file to configure:
- `SECRET_KEY` - Use a strong secret; production requires at least 32 characters
- `DATABASE_URL` - Database connection string
- `FLASK_DEBUG` - Set to `1` only for local development

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
