# Integrated Transactions

## Overview

Bank transactions are the shared ledger for account activity. Related workflows
create and maintain linked rows for credit-card payments, loan payments,
account transfers, subscriptions, expenses, income, and childcare. Coordination
belongs in domain services, not in a database-wide cascade assumption.

## Credit-Card Payments

`CreditCardTransaction.bank_transaction_id` points to the bank-side
`Transaction` for a card payment. The linked bank row records its
`credit_card_id`; the card transaction is the durable link back to that row.
When a payment is edited or deleted, `CreditCardService` synchronizes or clears
the link and recalculates the affected card/account balances. Deletion behavior
is implemented in service logic; do not assume deleting either row always
triggers a database cascade.

Relevant service methods include:

- `CreditCardService.generate_payment_transaction()` to create a card payment
  and its bank-side transaction.
- `CreditCardService.sync_bank_transaction_to_payment()` to propagate bank-side
  edits to a linked card payment.
- `CreditCardService.update_payment_transaction()` to update a card payment
  and its linked bank-side transaction.

The routes also support payment editing, paid/fixed toggles, manual
transactions, balance transfers, and future statement/payment regeneration.
See `blueprints/credit_cards/routes.py` for the current route list.

## Other Linked Workflows

- **Account transfers:** `Transaction.linked_transaction_id` pairs the outgoing
  and incoming bank rows. `TransactionService.create_transfer()` validates both
  accounts within the household and creates the paired records.
- **Loans:** loan payment services maintain bank transactions and synchronize
  payment status where a linked payment exists.
- **Expenses:** `ExpenseSyncService` maintains an expense's bank or card
  transaction link. Fuel expenses instead link to a vehicle trip. Reimbursement
  rows use claim-group and reimbursement-group fields.
- **Income:** income services can maintain a deposit transaction. Folded expense
  reimbursement totals are incorporated into the income transaction.
- **Subscriptions:** generated pending transactions reference their source
  through `subscription_id`. Paid/fixed entries are treated differently from
  replaceable forecasts.
- **Childcare:** monthly childcare summaries can link to their account
  transaction.

These references are distinct domain relationships; they are not interchangeable
and should be updated through their owning service.

## Transaction Fields and Household Scope

`Transaction` contains the account, category, vendor, amount, date, paid/fixed
and forecast flags, optional card/loan/subscription references, optional
transfer counterpart, expense-claim metadata, and derived period fields such as
`year_month` and `payday_period`. `CreditCardTransaction` stores its card,
classification, amount/date, balance, paid/fixed state, bank-payment link,
statement/transfer links, and subscription reference.

Application queries and submitted foreign keys must be family-scoped using
`family_query()` / `family_get()` / `family_get_or_404()`. Keep
`family_id` explicit when creating records in service code. The tenancy guard
provides a final write-time check, but should not replace scoped lookups.

## Balance and Status Maintenance

Services explicitly recalculate account and card balances after the relevant
changes. Paid-status changes may be synchronized to linked loan, card-payment,
transfer, or expense records. Forecast regeneration preserves fixed records
according to the owning domain's rules.

The transaction list and consolidated view are implemented in
`blueprints/transactions/routes.py`; the consolidated view is at
`GET /transactions/consolidated`. This page brings together bank, credit-card,
and loan activity for review; it does not replace the underlying domain
records.

## Change Guidance

When adding a linked transaction workflow:

1. Identify the owning domain record and its explicit link fields.
2. Validate submitted IDs within the active family.
3. Create, update, delete, and clear links in the owning service with a
   transaction-safe commit/rollback boundary.
4. Recalculate every affected account/card balance and synchronize status where
   the existing domain requires it.
5. Test both sides of edits and deletions, duplicate/retry behavior, and
   household isolation.

See [Transaction Editing](TRANSACTION_EDITING.md),
[Credit Card Implementation](CREDIT_CARD_IMPLEMENTATION.md), and
[Database Schema](DATABASE_SCHEMA.md) for domain-specific details.
