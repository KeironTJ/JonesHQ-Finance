# Service Organization

Services are grouped by domain. Import service implementations from their
domain package rather than maintaining top-level redirect modules.

## Domains

- `finance/` - accounts, categories, transactions, subscriptions, payday periods,
  balances, income, vendors, credit cards, and expenses
- `household/` - family and childcare workflows
- `planning/` - loans, mortgages, and pensions
- `vehicles/` - vehicles, fuel forecasting, and mileage
- `platform/` - authentication, household settings (`SettingsService`) and personal
  display preferences (`PreferenceService`)
- `analytics/` - dashboard and net-worth read models

`analytics/attention_service.py` builds the dashboard's **Needs attention** list.
It respects household scope, record visibility and section permissions. It shows
active credit-card offers ending within the user's reminder window, current active
mortgage products reaching their end date, active plan targets (including overdue
ones), and past pending bank entries on active accounts. Mortgage product end dates
are used because the model has no separate fixed-rate-end field. Pending entries
are reminders to check the ledger, not proof of a missed bill. The window is a
personal preference (`dashboard.attention_days`, default 60, range 1-365 days);
overdue plans, current products past their end date and pending bank entries are
not restricted by that upcoming window.

The attention hub is a ten-item work queue with category counts, Active/Snoozed
views, date filters and server-rendered pagination. Filters preserve the selected
dashboard account/year but never scope the reminders to those selections. An
initial dashboard visit starts collapsed, matching the other dashboard summary
cards with a coloured banner, active count and chevron. The banner is a
keyboard-accessible button that expands/collapses the queue. Queue navigation and snooze
redirects carrying attention filters keep it expanded.
Each reminder links to its source; bank entries also show the account and amount.
Queue rows use compact tiles with a title, date/status line and optional account
context. Explanations and snooze duration controls expand on demand. On mobile,
actions sit below the reminder and category chips scroll horizontally; snooze
controls have 44px touch targets. Tile surfaces use the shared light/dark tokens.
Personal snoozes last 1, 7 or 30 calendar days and can be restored early from
Snoozed. They are saved in `User.preferences['dashboard.attention_snoozes']`
without a schema change and never update financial records. Snooze keys include
the record, reminder type and due date, so a changed date is a fresh reminder.
Only currently accessible reminders can be snoozed/restored. Expired snoozes stop
hiding items on their return date and are pruned on the next snooze/restore write.

Plans support visible **Complete**, **Archive** and **Reopen** actions. Closing a
partially finished plan preserves item statuses, amounts and transaction links.
Open plans include active and draft plans only; completed and archived plans stay
available through their respective list filters and All, but do not generate
dashboard reminders.

Import from the domain package, for example:

```python
from services.finance.transaction_service import TransactionService
```

`finance/balance_service.py` owns account and credit-card balance
recalculation. Routes use it after transaction workflows; legacy model methods
delegate to the service to preserve existing callers.

`finance/income_forecast_service.py` owns saved recurring-income forecast
generation and maintenance. `IncomeService` continues to handle source and
actual payslip records.

`finance/credit_card_statement_service.py` owns card interest calculation,
statement/payment generation, and future-chain regeneration.
`CreditCardService` handles card records, transactions, and payment/bank sync.
The shared vendor lookup helpers live in `finance/credit_card_helpers.py`.

### Fuel forecasting

`vehicles/fuel_forecasting_service.py` assesses each positive-mile trip in date/ID
order. A trip that would leave the tank at or below the configured threshold
triggers a top-up **before that trip, dated on the trip's day**; there is no
earlier-trip look-ahead scheduling. The percentage still means fuel consumed:
95% means refill at 5% remaining. A full tank never produces a zero-gallon top-up.
Trips exceeding a tank's usable range receive additional same-day top-ups at the
threshold during the journey. Same-day refill costs are summed into one unpaid
forecast bank transaction.

Actual fills precede trips on the same day, ordered by record ID. Full fills
reset the tank to capacity; partial fills add purchased fuel, capped at capacity.
Only trips after the latest actual fill receive forecasts, including missed past
trips. Earlier history establishes the tank using **actual fills only**; omitted
hypothetical fills cannot inflate the level after a partial fill. The trip-log
tank column uses this same simulation. Current tank status uses actual fills and
trips through today only; its rolling-mileage "Fill In" estimate is separate from
the scheduled-trip forecast.

`VehicleService` derives MPG from completed full-to-full odometer intervals,
including intervening partial-fill gallons. Partial fills have no standalone MPG.
Forecasts use the latest ten positive intervals and the latest five positive
fuel prices (pence/litre, with a 150p fallback). Costs convert UK gallons using
4.54609 litres/gallon. Read calculations and fill-log MPG displays derive these
intervals rather than trusting legacy stored MPG; fuel creates, edits and deletes
also recalculate stored metrics in chronological order.

Trip add/edit/delete, bulk trip add/delete, fuel changes, vehicle-setting changes
and manual refresh rebuild saved forecasts. Registration changes also clear the
old registration's forecasts. Actual bank transactions are preserved, and monthly
balance caches refresh from the earliest removed or added forecast per affected
account. Existing saved forecasts are corrected on the next such action or with
**Refresh forecasts**; deploying this change does not rewrite household data.

`platform/passkey_service.py` owns WebAuthn enrollment, one-time challenges,
passwordless sign-in, recent identity confirmation, removal and server recovery.
It uses `UserSessionService` for revocation and passkey-authenticated sessions;
see [authentication setup](../docs/AUTHENTICATION_SETUP.md#passkeys-passwordless-sign-in)
for trusted-origin configuration and deployment.

## Settings ownership

`/settings` is an owner-only hub, not a combined save form. Household/payday,
credit cards, work expenses and net worth each save only their own allowlisted
fields through `SettingsService`; tax and vendor types keep their existing editors.
Modules link to the same editors rather than duplicating configuration forms.
`/settings/update` rejects stale combined submissions with an explanatory message.

`/preferences` is available to all signed-in users. `PreferenceService` stores
dashboard/list display defaults on the authenticated `User`, not the household.
The personal default-account selector uses the existing visibility-aware account
validation. `/preferences/save` supports lightweight boolean updates; the legacy
owner-only `/settings/save_preference` endpoint delegates to the same personal
write path. Signed-in appearance is saved on the user through
`/preferences/appearance`; form changes are previews until saved, while the
top-bar toggle saves immediately. Only signed-out appearance uses browser-local
storage. See the [design system](../docs/DESIGN_SYSTEM.md#personal-appearance).
