# Payday Tracking

## Periods and Working Days

A payday period runs from one payday through the day before the next payday.
Its label is `YYYY-MM`, using the year and month of the nominal starting payday.
Payday moves to the previous working day when it falls on a weekend or an
England and Wales bank holiday. Consequently, actual boundaries can differ
from the configured calendar day and may start in the previous month.

The household setting `payday_day` defaults to 15 and accepts 1-31. Day 31
uses the final day in shorter months, before working-day adjustment. Legacy
stored values of 0 are interpreted as day 31; new settings must use 1-31.

`PaydayService.get_payment_date_for_month()` is a separate helper for scheduled
payments: it moves a non-working payment date forward, not backward.

## Filters and Analytics

- The transaction list accepts `payday_period` alongside the calendar
  `year_month` filter. A first visit without query parameters selects the
  current payday period and pending transactions.
- Bank transaction filters and payday category/vendor analytics use the stored
  `Transaction.payday_period`.
- The consolidated view uses stored labels for bank transactions and the
  selected period's date range for card transactions and loan payments.
- New and edited bank transactions normally derive their period from the
  transaction date. The transaction form also supports a period override.

## Dashboard Balances

`PaydayService.get_payday_summary_for_year(account_id, year)` calculates twelve
periods for the selected account using both paid and unpaid transactions.
Forecasting is intentional; this method has no paid-only option.

Each result contains the period label, start/end dates, opening balance, rolling
balance, minimum balance, net balance change, and income/expense category
breakdowns. Period balances carry forward into the next period.

- **Opening balance:** cumulative transaction balance before the period starts.
- **Rolling balance:** expected balance at the period's end.
- **Minimum balance:** lowest running balance, including the opening balance.
- **Max extra spend:** legacy field name for `rolling_balance - opening_balance`.
  It is a net change, not a safe-to-spend recommendation.

The summary derives balances from transaction amounts, not `Account.balance`.

## Changing Payday

Household owners can use **Settings → Household** to save a new payday. The
recurring-income page also offers an owner-only update action that can keep
the existing day and reassign periods.

Both flows use services to recalculate stored transaction labels. Changing the
setting therefore changes historical and future assignments; it is not merely
a display preference and replaces manual period overrides on affected rows.
Re-perioding covers every transaction in the household, including those on
members' private accounts, because payday is household-wide. It never touches
other households and does not report how many rows changed.

## Implementation and Validation

- [PaydayService](../services/finance/payday_service.py) owns date calculations,
  dashboard summaries, and re-perioding.
- [SettingsService](../services/platform/settings_service.py) validates household
  settings and refreshes transaction periods when payday changes.
- [Regression tests](../tests/test_payday_service.py) cover forecast balances,
  input validation, settings-driven and private-account re-perioding, household
  isolation, and legacy last-day values.
