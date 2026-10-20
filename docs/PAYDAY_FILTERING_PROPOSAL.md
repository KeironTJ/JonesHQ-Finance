# Payday Periods: Current Behavior and Next Steps

This document records the payday-period behavior already implemented and identifies
reasonable areas to consider next. The original proposal is superseded: payday-period
filtering is already available in transaction views and analytics.

## Current Behavior

### Period calculation

`PaydayService` in [`services/finance/payday_service.py`](../services/finance/payday_service.py)
calculates payday dates and periods. A period runs from one payday through the day
before the next payday and is labelled `YYYY-MM`, using the year and month of its
starting payday. Payday dates move to the previous England and Wales working day
when the configured date falls on a weekend or bank holiday.

The `payday_day` setting defaults to the 15th. `get_period_for_date()` maps a date
to its period label, and `get_recent_periods()` supplies period labels and display
dates to filter controls.

### Transactions

- The transaction list accepts a `payday_period` filter alongside the calendar
  `year_month` filter. On a first visit with no query parameters, it selects the
  current payday period and pending transactions.
- The period selector is populated across the date range of the family's
  transactions. When a period is selected, the list filters on the stored
  `Transaction.payday_period` value.
- The consolidated transactions view also accepts a payday-period filter. It
  filters bank transactions by their stored period and filters credit-card
  transactions and loan payments by the selected period's date range.
- New and edited bank transactions are assigned a period from their transaction
  date by default; the transaction form also supports a period override.

Relevant implementation: [`blueprints/transactions/routes.py`](../blueprints/transactions/routes.py),
[`services/finance/transaction_service.py`](../services/finance/transaction_service.py),
[`models/transactions.py`](../models/transactions.py), and
[`templates/transactions/transactions.html`](../templates/transactions/transactions.html).

### Analytics

Category analytics and vendor analytics support payday-period ranges as well as
calendar-month views. The payday analytics use the stored
`Transaction.payday_period` values.

Relevant implementation: [`blueprints/categories/routes.py`](../blueprints/categories/routes.py)
and [`blueprints/vendors/routes.py`](../blueprints/vendors/routes.py).

### Changing the payday setting

The income settings flow provides an action to update the payday day and re-stamp
transactions using the new setting. `PaydayService.reperiod_all_transactions()`
recalculates stored period labels from transaction dates. This means changing the
payday setting can change historical period assignments; it is not merely a
display preference.

Relevant implementation: [`blueprints/income/routes.py`](../blueprints/income/routes.py)
and [`services/finance/payday_service.py`](../services/finance/payday_service.py).

## What Is Not Proposed Again

The following items in the earlier proposal are already implemented and should not
be treated as new work:

- Adding a payday-period filter to the transactions page.
- Storing a payday-period label on bank transactions.
- Adding payday-period filtering to category and vendor analytics.
- Recalculating stored period labels after changing the payday setting.

## Next Focus

The most useful next payday-related work is to protect the existing behavior with
focused regression coverage, especially:

1. Period boundaries, including dates immediately before, on, and after payday.
2. Weekend and England and Wales bank-holiday adjustments.
3. Re-perioding transactions after the payday setting changes.
4. Consistent results between the transaction list, consolidated view, and
   category/vendor analytics, including their different transaction sources.

After that, consider adding payday-period views to other areas only where there is
a clear user need. Budgeting, planning, or additional reports should be evaluated
as separate feature requests; this document does not assume they need payday
filtering or recommend adding a new database field for them.
