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

### Central Hub and workspaces

Signed-in visits to `/` and sign-in without a valid local `next` destination open
the user's default workspace: Central Hub (`/hub`) unless Finance (`/dashboard`)
or Household Hub (`/household/`) is chosen under Personal preferences.
Password, two-factor and passkey sign-in
use the same landing rules. Explicit local destinations take precedence and still
enforce their normal permissions. Detached accounts default to Account security.
Household registration and invitation acceptance still lead to Central Hub.
Managed children with Household Hub access instead start at **My day**
(`/household/my-day`), regardless of saved workspace preferences; `/hub` shows
the same child page. It uses London's date, all approved household activities,
visible calendar events, their own assigned/personal tasks and reward progress.
Earlier work stays separate, and completed jobs wait for adult approval.
Explicit safe links still take precedence. Revoked Hub access falls back to
Central; detached accounts still start at Account security.

The hub opens Finance at `/dashboard`; existing Finance URLs are unchanged.
Household Hub opens a manual calendar at `/household/`, with month and agenda
views, all-day/timed events in Europe/London and separate edit/delete permissions.
Shared events stay with the household when their creator leaves; private events
are removed. Adult-private events are creator-only; managed-child private events
also allow the designated guardian within the same household. Owners manage
shared events but never override private visibility. See
[access policy](docs/ACCESS_POLICY.md) for module grants and child restrictions.
The date-first meal planner has week/month views, per-day quick-add and multiple
meals per breakfast/lunch/dinner slot. Enter a title, description and recipe source
directly, or optionally copy them from the household meal library. Each date's
details are independent: library edits never change existing plans. Adults manage
meals and plans; managed children view only. Plans appear in month/agenda
calendars as source links, not duplicate events. Archiving a meal keeps its plans.
The activity planner also has week/month views and per-day quick-add, household
attendees, all-day or timed multi-day activities, and weekly repeats through a
chosen end date. Adults publish and manage activities; children suggest them for
adult approval. Pending/rejected suggestions are visible only to their creator
and household adults, and stay off the calendar. Recurring edits/deletions affect
the entire series, including past dates; single-occurrence exceptions are not yet
supported. Approved activities feed the calendar directly without duplicate events.
Tasks & lists provides personal/shared checklists, priorities, household
assignments, optional London due dates/times, completion attribution and
active/today/overdue/completed/assigned-to-me filters. Adults manage shared work;
children complete/reopen only shared tasks assigned to them, and manage their
own personal lists. A child's personal list is also viewable by their designated
guardian in the same household; adult personal lists remain creator-only.
Incomplete dated tasks feed each viewer's calendar according to list privacy.
List privacy is fixed at creation, and tasks cannot move between lists.
Rewards offers child-friendly My jobs / My rewards / My progress pages and a
separate adult setup/approval inbox. Adults can create a reward job directly or
attach points to an existing shared task assigned to a child. Personal lists
never earn points. Adult approval awards points once per job, even if reopened;
reward requests hold points until approved or returned on decline. Optional
reward goals show progress. Earlier jobs sit separately from current work;
finished/closed jobs stay in history. Adults can reschedule or close old work.
Behaviour ratings, streaks, achievements, recurring tasks and external sharing
remain future work; no old JonesHQ records or authentication are imported.
No billing or subscription entitlement enforcement is introduced.

The shared sidebar discovers available modules through the platform registry.
Each module owns its overview label, sidebar template and page labels; Finance
navigation lives in `templates/finance/_navigation.html`. Planned modules do not
appear as working sidebar destinations. Finance's dashboard Settings shortcut
opens Finance's grouped settings page for both owners and members.

Household-scoped reads and explicitly scoped service writes use the selected
household. The automatic `family_id` backstop also resolves the selected household,
including accounts whose legacy default household is unset. It does not replace
explicit IDs or stamp global records, and it does not run outside requests.
Services must still set `family_id` explicitly using `get_family_id()`.

Account security, household membership and personal preferences use the central
navigation shell. Finance retains its own section navigation and settings.
One sidebar Settings link always opens `/hub/settings`, grouped into **Your
account**, **Household & people** and **Module settings**. Finance settings
(`/hub/settings/finance`) and Household Hub settings (`/household/settings`)
remain linked from there. These landing pages are
available to members; their cards and shared sub-navigation respect existing
owner and section permissions. Central covers appearance, the starting workspace,
account security and household membership. Finance groups personal defaults,
financial access and shared financial rules. Breadcrumbs and scope labels make
the current workspace and personal-versus-household effects explicit. Settings
sub-pages are also discoverable in page search without cluttering the main sidebar.
Existing editor URLs and write permissions remain unchanged, including owner-only
`/settings`. Vendor types retain their existing vendor-section permissions.
Personal preferences at `/preferences` control account-wide appearance without
loading financial records. Finance preferences at `/preferences/finance` control
the user's dashboard, reminder window, list display and default bank account;
all household members can manage their own preferences. Owner-only `/settings`
contains shared financial rules, not platform configuration.
The starting-point form posts independently to `/preferences/workspace`; its
`default_workspace` choice is stored in the user's existing preferences without a
schema migration. It does not change module permissions, financial defaults or themes.
Existing POST requests to `/preferences` remain compatible with Finance preference
saving. The appearance and single-preference endpoints and stored values are unchanged.
Owners can open an optional **Household setup checklist** at `/hub/setup` from
home, Settings or Household & people. It reflects existing people, shared tasks
and rewards without writing records or marking optional features as required.
**Add child** opens one focused form at `/hub/settings/children/new`, linked from
Settings, Household & people, member access and guardian management. Failed
submissions retain only name/email, never passwords. Invitations, module access
and designated-guardian controls remain separate permissions but are connected
from the people pages.
Finance onboarding remains available from its dashboard and is not required to
enter Central Hub. Existing onboarding completion markers are unchanged.

Household membership and roles remain at `/family/`. Existing members' financial
section permissions, transaction display names and assignment labels are managed
at `/settings/access` (owner only, with recent authentication for permission writes).
Role changes preserve saved Finance permissions; Finance access changes cannot
change household roles. Owners retain full section access, subject to existing
private-record rules. Invitations retain their existing initial Finance permission
choices, now explicitly labelled separately from the household role.
Existing assignment-label POST URLs remain compatible and return to Finance access.

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
│   ├── core/             # Identity, households, Hub and shared preferences
│   └── finance/          # Finance module descriptor and feature blueprints
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
