# Expense System

## Overview

Expenses are household-scoped records with linked bank or credit-card activity,
claim tracking, mileage reporting, calendar support, and configurable
reimbursement workflows. The routes are in `blueprints/expenses/routes.py`;
business logic lives in `services/finance/expense_service.py`,
`services/finance/expense_sync_service.py`, and the reimbursement-group
service.

## Expense Records and Privacy

`Expense` stores the date, description, type, cost, payment account/card,
linked transaction IDs, claim and payday-period keys, submission/reimbursement
state, and optional mileage details. `family_id` is the household boundary.
`owner_id` is optional: `NULL` means shared with the household, while a value
restricts the expense to that user.

Creating or updating an expense reconciles linked activity when
`expenses.auto_sync` is enabled:

- A fuel expense is linked to a vehicle trip.
- A credit-card expense creates or updates a fixed `Purchase` transaction.
- Other expenses create or update a bank transaction.

The sync service tracks linked IDs so it can update or remove related records.
It is not a database-level cascade; changes go through the service workflow.

`ExpenseCalendarEntry` stores dated calendar items and may link to an expense.
Mileage records use the expense's vehicle, covered miles, days, and rate data;
the mileage page supports monthly, yearly, and detail views and CSV export.

## Reimbursement Workflows

`ExpenseReimbursementGroup` lets a household maintain multiple claim streams:

- **Separate:** create a standalone reimbursement transaction.
- **Folded:** add the claim total to the selected recurring-income payslip.

Each household has a default group; new expenses use it unless another group is
selected. Periods can use calendar months or configured payday periods.
Calendar-month periods can use a cutoff day, and reimbursement dates can be
configured. Do not assume every claim is reimbursed on the last working day of
the calendar month.

The expense page supports:

- Reconcile reimbursements for a selected period or all periods.
- Create a partial reimbursement for a custom date range.
- Reconcile credit-card payments after reimbursement.
- Run the combined reconciliation workflow.
- Delete linked transactions separately or delete expenses and their links.

Partial reimbursements are tracked with claim-group keys so they are distinct
from full-period claims. A folded reimbursement is linked to the applicable
income record; a separate reimbursement is a bank transaction.

## Routes

The implemented routes include:

| Route | Purpose |
| --- | --- |
| `GET /expenses` | Expense list, reimbursement controls, and mileage summary |
| `GET /expenses/mileage` | Mileage review and CSV export |
| `POST /expenses/mileage/rate-update` | Apply an effective-dated mileage-rate update |
| `POST /expenses/add`, `/expenses/update/<id>` | Create or update an expense |
| `POST /expenses/<id>/set-period` | Set the expense period |
| `POST /expenses/generate-reimbursements` | Reconcile period reimbursements |
| `POST /expenses/generate-cc-payments` | Reconcile credit-card payments |
| `POST /expenses/generate-partial-reimbursement` | Create a custom-range claim |
| `POST /expenses/generate-all` | Run reimbursement then card-payment reconciliation |
| `GET /expenses/groups` | Manage reimbursement groups |

Expense routes and services use family-scoped queries and lookups. Submitted
IDs must be resolved within the current household; the write-time tenancy guard
is a backstop, not a replacement for those lookups.

## Relevant Models

- `Expense` — expense data, payment links, claim status, mileage, visibility.
- `ExpenseCalendarEntry` — dated calendar item, optionally linked to an expense.
- `ExpenseReimbursementGroup` — reimbursement mode and linked recurring income.
- `Income.expense_reimbursement_total` — amount folded into a payslip.
- `Transaction.claim_group` and `Transaction.reimbursement_group_id` — separate
  reimbursement transaction tracking.

See [Database Schema](DATABASE_SCHEMA.md) for the wider model map and source
model files for exact columns.
