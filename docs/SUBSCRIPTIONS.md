# Subscriptions

Subscriptions manage recurring expenses as reusable rules rather than one-time
batches. A rule can create pending charges for either a bank account or a
credit card.

## Scheduling

Choose a first charge date, a frequency (weekly, every four weeks, monthly,
quarterly, or yearly), and an individual planning horizon from one to five
years. An optional end date can shorten that horizon. The application
maintains pending transactions only through the earlier of the selected
horizon or end date; it does not generate an unlimited series.

## Updating and cancelling

Editing a rule refreshes its future pending entries to match the updated
schedule and amount. Entries already marked paid are never changed. Pausing a
rule stops it from creating new pending entries but leaves existing pending
entries in place; editing a paused rule can update matching pending charges but
does not add new ones. Cancelling removes the rule's remaining pending entries
and retains paid transaction history.

Open **Banking → Subscriptions** to create or manage rules. The transaction
list also links to subscription management.

Use **New** beside the vendor selector to quick-add and select a vendor without
leaving the subscription form or losing entered details.
