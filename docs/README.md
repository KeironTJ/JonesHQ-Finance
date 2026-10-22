# JonesHQ Finance Documentation

Complete documentation for the JonesHQ Finance personal finance management system.

## Documentation Index

### Getting Started
- **[Quick Start Guide](QUICKSTART.md)** - Installation and first steps

### Technical Documentation
- **[Design System](DESIGN_SYSTEM.md)** - Visual tokens, reusable templates, responsive shell and interaction patterns
- **[Database Schema](DATABASE_SCHEMA.md)** - Complete database structure and relationships
- **[Expense System](EXPENSE_SYSTEM.md)** - Expense and reimbursement workflows
- **[Income and Pension System](INCOME_PENSION_SYSTEM.md)** - Income records, forecasts and retirement profiles
- **[Integrated Transactions](INTEGRATED_TRANSACTIONS.md)** - Transaction and related-domain integration
- **[Category Mapping](CATEGORY_MAPPING.md)** - Excel to database category mapping reference
- **[Vendor System](VENDOR_SYSTEM.md)** - Vendor tracking and management implementation
- **[Authentication Setup](AUTHENTICATION_SETUP.md)** - Users, families, permissions, and login setup
- **[Security](SECURITY.md)** - Security controls and deployment expectations
- **[Security Hardening](SECURITY_HARDENING.md)** - Security implementation and deployment controls
- **[Transaction Editing](TRANSACTION_EDITING.md)** - Transaction editing behavior
- **[Monthly Balance Cache](MONTHLY_BALANCE_CACHE.md)** - Cached monthly account balances
- **[Payday Tracking](PAYDAY_TRACKING.md)** - Payday periods and balance calculations
- **[Payday Filtering Proposal](PAYDAY_FILTERING_PROPOSAL.md)** - Payday period filtering behavior
- **[Pension Projections](PENSION_PROJECTIONS.md)** - Pension projection workflows
- **[Retirement Planning](RETIREMENT_PLANNING.md)** - Retirement and net-worth planning
- **[Subscriptions](SUBSCRIPTIONS.md)** - Managed recurring bank and credit-card charges
- **[Branching Strategy](BRANCHING_STRATEGY.md)** - Repository branching guidance
- **[Production Runbook](../deployment/README.md)** - Current production setup, updates, backups, recovery and monitoring (authoritative)
- **[Deployment](DEPLOYMENT.md)** - Historical SQLite-era deployment guidance (do not follow for production)
- **[Directory Structure](DIRECTORY_STRUCTURE.md)** - Current repository layout

## 📂 Project Structure

```
JonesHQ Finance/
├── app.py                  # Flask application factory
├── config.py              # Configuration settings
├── extensions.py          # Flask extensions
├── requirements.txt       # Python dependencies
│
├── models/               # SQLAlchemy models
│   ├── accounts.py
│   ├── transactions.py
│   ├── categories.py
│   ├── vendors.py
│   ├── family.py
│   ├── users.py
│   └── ...
│
├── blueprints/          # Flask blueprints (routes)
│   ├── dashboard/
│   ├── accounts/
│   ├── transactions/
│   ├── categories/
│   ├── vendors/
│   ├── auth/
│   ├── family/
│   ├── plans/
│   ├── preferences/
│   ├── settings/
│   ├── site_admin/
│   ├── onboarding/
│   └── ... (21 registered blueprints)
│
├── templates/           # Jinja2 templates
│   ├── base.html
│   ├── shared/
│   ├── transactions/
│   ├── credit_cards/
│   └── ...
│
├── static/             # CSS, JS, and favicon
│   ├── css/
│   ├── js/
│   └── favicon.svg
│
├── services/           # Business logic grouped by domain
│   ├── analytics/
│   ├── finance/
│   ├── household/
│   ├── planning/
│   ├── platform/
│   └── vehicles/
│
├── migrations/         # Database migrations
│   └── versions/
├── scripts/            # Database, import, check, and maintenance tools
│
├── instance/          # Instance-specific files
│   └── joneshq_finance.db  # SQLite database
│
└── docs/              # Documentation (you are here)
    ├── README.md
    ├── QUICKSTART.md
    ├── DATABASE_SCHEMA.md
    ├── CATEGORY_MAPPING.md
    └── VENDOR_SYSTEM.md
```

## 🔑 Key Concepts

### Generic Category Structure
Instead of specific categories (e.g., "Barclaycard Payment"), the system uses generic categories (e.g., "Credit Card Payment") with foreign keys linking to specific entities (credit card IDs, loan IDs, etc.).

**Benefits:**
- Reusable categories
- Easier reporting and analytics
- Cleaner data structure
- Simplified maintenance

### Vendor Standardization
Vendors normalize merchant names across transactions to prevent duplicates like "Tesco", "TESCO", "tesco".

**Benefits:**
- Consistent data quality
- Accurate vendor spending analytics
- Autocomplete for transaction entry
- Default category suggestions

## 🗂️ Database Overview

The application uses SQLite by default in local development and tests.
Production runs on PostgreSQL 17, configured through `DATABASE_URL` or
`SQLALCHEMY_DATABASE_URI`; see the
[production runbook](../deployment/README.md). The schema is defined by the
SQLAlchemy models and managed through Flask-Migrate migrations.

**Core Financial:**
- `accounts` - Bank accounts
- `transactions` - All financial transactions
- `categories` - Transaction categories
- `vendors` - Merchant/vendor registry
- `budgets` - Budget planning

**Loans & Credit:**
- `loans` - Loan tracking
- `loan_payments` - Loan payment history
- `credit_cards` - Credit card accounts
- `credit_card_transactions` - Credit card purchases
- `mortgages` - Mortgage details
- `mortgage_payments` - Mortgage payment tracking

**Assets & Tracking:**
- `vehicles` - Vehicle registry
- `fuel_records` - Fuel purchases and MPG
- `trips` - Trip tracking
- `pensions` - Pension accounts
- `pension_snapshots` - Historical pension values
- `net_worth` - Net worth snapshots

**Expenses & Income:**
- `childcare_records` - Childcare expenses
- `expenses` - General expenses
- `income` - Income tracking
- `planned_transactions` - Future planned transactions
- `balances` - Account balance history

The schema also includes users and families, recurring income, family labels,
tax and application settings, monthly account balances, loan term changes,
properties and property valuation snapshots, mortgage products and snapshots,
credit-card promotions, vendor types, and other supporting records. See the
model modules in [`models/`](../models/) for the authoritative current list.

## 🚀 Quick Links

- [Back to Main README](../README.md)
- [View Database Schema](DATABASE_SCHEMA.md)
- [Category System Guide](CATEGORY_MAPPING.md)
- [Vendor Management](VENDOR_SYSTEM.md)

## 📝 Contributing

When adding new features, please update the relevant documentation:

1. Add model documentation to `DATABASE_SCHEMA.md`
2. Update category mappings in `CATEGORY_MAPPING.md`
3. Document new systems (like vendor management) in their own files
4. Update this index with new documentation files

## Maintenance

Update this index when adding a new subsystem or documentation guide. Keep
counts and directory listings qualitative unless they are generated or
verified against the source tree.
