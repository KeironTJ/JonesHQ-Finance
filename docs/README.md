# JonesHQ Finance Documentation

## Getting Started

- [Quick Start](QUICKSTART.md) - Local setup, migrations, and running the app
- [Authentication](AUTHENTICATION_SETUP.md) - Registration, sign-in, household invites, passkeys, and sessions

## Finance Workflows

- [Credit Cards](CREDIT_CARD_IMPLEMENTATION.md) - Statements, payments, promotions, and linked transactions
- [Expenses](EXPENSE_SYSTEM.md) - Expense tracking and reimbursements
- [Income and Pensions](INCOME_PENSION_SYSTEM.md) - Income records, forecasts, and retirement profiles
- [Integrated Transactions](INTEGRATED_TRANSACTIONS.md) - Links between bank transactions and domain records
- [Transaction Editing](TRANSACTION_EDITING.md) - Editing, synchronization, and deletion behavior
- [Vendors](VENDOR_SYSTEM.md) - Merchant records, types, autocomplete, and analytics
- [Payday Tracking](PAYDAY_TRACKING.md) - Period boundaries, filters, balances, and changing payday
- [Monthly Balance Cache](MONTHLY_BALANCE_CACHE.md) - Actual and projected account balances
- [Pension Projections](PENSION_PROJECTIONS.md) - Pension forecast workflows
- [Retirement Planning](RETIREMENT_PLANNING.md) - Retirement and net-worth planning
- [Subscriptions](SUBSCRIPTIONS.md) - Recurring bank and credit-card charges

## Implementation and Operations

- [Database Schema](DATABASE_SCHEMA.md) - Models, fields, and relationships
- [Directory Structure](DIRECTORY_STRUCTURE.md) - Repository layout
- [Service Map](../services/README.md) - Domain responsibilities and service entry points
- [Design System](DESIGN_SYSTEM.md) - Shared visual and interaction patterns
- [Security](SECURITY.md) - Controls and deployment expectations
- [Security Hardening](SECURITY_HARDENING.md) - Implementation and production requirements
- [Branching Strategy](BRANCHING_STRATEGY.md) - Repository workflow
- [Production Runbook](../deployment/README.md) - Authoritative updates, backups, recovery, and monitoring
- [Script Guide](../scripts/README.md) - Retained diagnostics and supported alternatives to removed scripts
- [Review Findings](REVIEW_FINDINGS.md) - Resolved concerns and outstanding follow-up work

## Keeping Documentation Current

Update the relevant guide alongside behavior changes and add new guides here.
Keep each topic in one place: this index links to the schema and directory
guides rather than duplicating their inventories.

Routes and services define current behavior; models and checked-in migrations
define database structure. Old import instructions and deployment procedures
are available in Git history, not maintained as runnable alternatives.
