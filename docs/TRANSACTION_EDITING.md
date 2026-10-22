# Transaction Editing

## Overview

The bank transaction list, forms, and actions are implemented in
`blueprints/transactions/routes.py`. Request parsing and redirects stay in the
blueprint; reusable transaction operations live in
`services/finance/transaction_service.py`.

## Current Routes

| Route | Methods | Purpose |
| --- | --- | --- |
| `/transactions` | GET | List, filter, and review bank transactions |
| `/transactions/create` | GET, POST | Create one or recurring transaction records |
| `/transactions/<id>/edit` | GET, POST | Edit a transaction and synchronize linked records |
| `/transactions/<id>/delete` | POST | Delete a transaction and handle linked records |
| `/transactions/<id>/toggle_paid` | POST | Toggle paid status and synchronize applicable links |
| `/transactions/<id>/toggle_fixed` | POST | Lock or unlock a transaction |
| `/transactions/bulk-edit` | POST | Edit supported fields on selected records |
| `/transactions/bulk-delete` | POST | Delete selected records and handle linked records |
| `/transactions/transfer` | GET, POST | Create paired account-transfer transactions |
| `/transactions/save-filter-preference` | POST | Save the user's filter-panel preference |
| `/transactions/consolidated` | GET | Review bank, card, and loan activity together |

The subscription-management routes are also part of the transactions blueprint;
see [Subscriptions](SUBSCRIPTIONS.md).

## Balance and Linked Records

The account balance helper recalculates an account from its transaction
amounts. In this application, positive amounts increase the account balance
and negative amounts decrease it. Transaction services and routes call the
helper after changes, including when an edit moves a record between accounts.
This is explicit service/route behavior; it is not implemented by the
`after_insert` / `after_update` / `after_delete` listeners described in older
versions of this document.

An edit or delete can also affect linked records:

- A linked credit-card payment is synchronized through `CreditCardService`.
- A linked loan payment or expense may have status or link fields updated.
- A transfer has a paired transaction whose account balance must also be
  recalculated.
- Paid-status changes can update the linked card/loan payment, transfer, or
  expense state where that relationship applies.

These links are maintained by the domain services. Do not assume that setting a
foreign key alone performs the full synchronization or that database cascades
cover every workflow.

## Household Isolation

Routes and services resolve transaction IDs with household-scoped helpers and
validate submitted account/category/vendor IDs against the active family.
Service-created transactions set `family_id` explicitly. The tenancy guard
checks new or changed foreign keys as a backstop; it does not replace scoped
lookups.

## Editing Workflow

1. Use the transaction list filters to locate a record, or choose the create
   action.
2. Edit the transaction using the form; linked domain records are handled by
   the service workflow.
3. Use paid/fixed toggles to change reconciliation state or protect a forecast
   from regeneration.
4. For batches, use bulk edit/delete. Transfers should be created through the
   paired-transfer workflow rather than by independently editing one side.

Database amount, date, and relationship fields are defined by
`models/transactions.py`. See [Integrated Transactions](INTEGRATED_TRANSACTIONS.md)
for linked-domain behavior and [Database Schema](DATABASE_SCHEMA.md) for the
current model inventory.
