# Subscriptions

Subscriptions manage recurring expenses as reusable rules rather than one-time
batches. A rule can create pending charges for either a bank account or a
credit card.

Subscriptions and dated price changes are household-scoped. Submitted account,
card, category, vendor, and subscription IDs must be resolved within the
current family. A rule targets either a bank account or a credit card, and its
generated records use separate synchronization paths for those destinations.

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

## Cost and renewal review

The subscriptions list annualizes the current charge using its schedule
(52 weekly, 13 every four weeks, 12 monthly, 4 quarterly, or 1 yearly). This
run-rate estimate does not include future dated price changes and is not a
statement of actual spending.

When a paid linked charge differs from the current rule amount, the list shows
the most recently paid amount for comparison. Paid history is retained when a
rule is edited, so this can help identify a changed price without changing
historical entries.

The dashboard **Needs attention** queue includes the next scheduled charge
within your personal reminder window. It links to the rule for review; it does
not send an external notification or change the scheduled transaction.

## Dated price changes

Use **Change price** on a subscription to record an upgrade, downgrade, annual
increase, or temporary discount. Enter the new amount, the date it takes effect,
and the reason for the change, such as the new plan or discount. The preview
lists the forecast charges that will use the new amount before it is saved.
The effective date must be today or later so overdue pending entries are not
silently repriced.
For a temporary discount, add another dated change for the normal price when
the discount ends. The subscription edit form keeps the starting price intact;
use the dated price workflow for amount changes so the change is recorded.

After confirmation, unpaid forecast charges dated on or after the effective
date are updated. For active subscriptions, missing forecast charges in the
planning horizon are included in the preview and generated using the dated
price. Paid charges and manually fixed charges are preserved. Paused
subscriptions update existing pending charges but do not generate new ones.
Price changes are retained as dated history on the subscription edit page, and
later changes supersede earlier ones from their own effective dates. Historical
changes without a recorded reason are labeled accordingly; new changes require
a reason.
The edit and change-price pages share the same price-history component and
stylesheet, with stacked history entries on phones and tables on larger screens.
The change-price page also uses before-and-after forecast cards on phones.

If no charges are currently forecast for the effective date, the price change
can still be saved for future forecast generation. A single subscription can
have only one price change per effective date.
