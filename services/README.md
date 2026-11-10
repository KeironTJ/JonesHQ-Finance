# Service Organization

Services are grouped by domain. Import service implementations from their
domain package rather than maintaining top-level redirect modules.

## Domains

- `finance/` - accounts, categories, transactions, subscriptions, payday periods,
  balances, income, vendors, credit cards, expenses, Finance settings
  (`SettingsService`) and Finance defaults (`FinancePreferenceService`)
- `household/` - household memberships, family and childcare workflows
- `planning/` - loans, mortgages, and pensions
- `vehicles/` - vehicles, fuel forecasting, and mileage
- `platform/` - authentication, account appearance/starting point
  (`PreferenceService`), plus the module catalog and shared settings navigation
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

`household/membership_service.py` validates household membership, resolves the
active household context and changes the selected household. Membership roles
and Finance section access are household-specific; services must scope user
lookups to the active household rather than assuming `User.family_id` is the
only membership.

`platform/module_registry.py` orchestrates module discovery and registration.
Each available module supplies its descriptor, blueprint registrar and settings
navigation contributor; Finance owns these in `blueprints/finance/__init__.py`.
Core blueprints register separately in `blueprints/core/__init__.py`. The shared
shell determines module identity from registered blueprint ownership, not a
hard-coded list of core/Finance pages.

`platform/module_access_service.py` composes per-household module grants with
account-level managed-child restrictions. Its request guard covers registered
module blueprints and legacy Core financial entry points, including exports.
Finance section permissions apply only after the module gate.
`household/household_access_service.py` manages household-local grants and
designated-guardian child creation, transfer and release, with atomic audit
events. See [access policy](../docs/ACCESS_POLICY.md) for implemented boundaries
and the calendar/sharing design.

`household/setup_service.py` reads selected-household people, active invitations,
shared-task and reward availability for the optional owner setup checklist.
`household/my_day_service.py` composes the managed-child landing page from scoped
calendar events, all approved activity occurrences, their own actionable tasks,
reward jobs and point progress. Both are read-only and use existing module and
record-privacy checks; neither introduces onboarding state or billing grants.

`household/calendar_service.py` owns manual event validation, London/UTC
conversion, month/agenda data and independent edit/delete policies. Private
visibility is enforced by the scoped query helpers, including child/guardian
visibility without an owner bypass. Creator links and selected grants use
household membership IDs. Departing members' private events are deleted and
shared events retained for owners; account and household deletion use reviewed
lifecycle rules. It also reads meal-plan, approved activity and visible incomplete
dated-task source rows for month/agenda views;
no duplicate events are written.

`household/meal_service.py` manages the household-shared meal library, archive/
restore lifecycle and date-first week/month planner with per-day quick-add.
Adults with Household Hub access write; managed children read only. Multiple
meals per breakfast/lunch/dinner slot are supported. A library selection is optional
and copies editable title/description/source once; subsequent library edits do
not change plans. Archive preserves plans and blocks new selections. Added-by
attribution uses the active membership and is cleared on departure. Household
deletion removes plans before meals; individual account deletion preserves both.
External sharing is not implemented.

`household/activity_service.py` owns date-first week/month activity planning,
attendees, weekly recurrence and child suggestion reviews. Adults publish/manage;
children can create, revise/resubmit or withdraw their own unapproved suggestions.
Scoped helpers hide unapproved suggestions (and their attendee rows) from other
children. Only explicit adult approval publishes a suggestion. Weekly occurrences
are expanded on read without storing calendar-event copies; every London wall
time is validated on save, rejecting ambiguous/nonexistent DST times. Changes
apply to the whole series, including past dates. Member/account departure removes
attendance and clears creator/reviewer attribution but preserves activities.
`household/planner_helpers.py` supplies shared week/month periods and navigation
for both activity and meal planners.

`household/task_service.py` manages personal/shared lists, member assignments,
priorities, due dates/times and explicit complete/reopen actions. Scoped helpers
apply personal-list visibility to task rows and calendar feeds. A child's
designated guardian can view their personal lists but only the creator manages
personal work. Adults manage shared lists/tasks; children can complete/reopen
only shared tasks assigned to them. Creator/assignee/completer links use selected
household memberships. Completion stamps UTC time and actor on transitions;
repeating the same action retains attribution, reopening clears it. Privacy is
immutable and tasks cannot move lists, preventing accidental publication of
private content. Date-based stats/filters use London today; optional due times
must have dates and pass the calendar's DST validation. Personal lists/tasks
are removed on member/account departure, shared work survives with membership
links detached. Reward-bearing shared tasks call `RewardService` before commit
for configuration and completion transitions; ordinary task behaviour is unchanged.
Recurring tasks are not implemented.

`household/reward_service.py` supplies child jobs/rewards/progress and separate
adult setup/approvals. Jobs reuse shared tasks; personal lists never participate.
Household row locking covers task writes and reward transitions so concurrent
reviews, reopen actions and balance checks serialize. Unique ledger constraints
enforce once-only earnings, request reservation and refund. Reward requests
snapshot title/cost and reserve spendable points until approved or declined.
No Finance records, behaviour ratings, streaks or achievements are involved.
Earlier unfinished jobs are grouped separately; explicit close completes the
task without points, retaining history. Membership/task lifecycle helpers close
outstanding work and detach attribution; account deletion performs the same
reviewed transitions across all the account's memberships before detaching links.

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
Transaction mutations call `CreditCardStatementService.refresh_after_changes`
once per affected card/batch, using the household's `default_generation_years`
(default 10) and a 14-day payment offset. Card edits, linked bank payments,
expense sync and card subscriptions use the same path. It flushes without
committing; the enclosing write owns the commit/rollback. Only future unpaid,
unlocked statement chains are replaced: a paid/locked statement, card payment or
bank debit protects the whole chain. Account and card balances are refreshed,
later spending is still forecast after an earlier payoff, and manual generation
remains available.

### Fuel forecasting

`vehicles/fuel_forecasting_service.py` assesses each positive-mile actual trip and
upcoming planned trip in date/ID order. Skipped trips and overdue unconfirmed
plans do not affect mileage or fuel forecasts. A trip that would leave the tank at or below the configured threshold
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

`vehicles/trip_schedule_service.py` expands active weekly/fortnightly routines into
planned trips through the chosen end date (inclusive), or a rolling 90-day window
when no end date is set. Refreshing existing routines fills any missing upcoming
occurrences through that end date without duplicating trips.
Site Admin **Service settings → Trip routine limits** caps planning days ahead
(default 1,800) and active routines per household (default 25). Creation, edits,
resuming and automatic generation enforce these limits before generating trips;
the open-ended window also respects the horizon. Household quota checks include
private vehicles, exclude paused/expired routines, and serialize against a
household write lock. Lowering limits does not delete trips: refresh reports an
actionable warning and waits for routines to be adjusted or paused.
Apply migration `d7a2c5e8f103` with `flask db upgrade` before deploying this code.
Confirming an occurrence makes it
actual; skipping it excludes that date without ending the routine. Logging or
editing a fuel fill confirms that vehicle's planned trips dated on or before the
fill (`VehicleService._confirm_planned_trips`), and **Confirm due** confirms every
planned trip up to today. Until confirmed, past planned trips still count towards
tank status and forecasts. Editing one occurrence keeps its status and sets
`Trip.is_modified`, so later routine edits leave it alone until it is reset. The
Routines page (`/vehicles/routines`) manages routines and their occurrences, and
the Saved Journeys page (`/vehicles/journeys`) manages `TripTemplate`s; both sit
under the Trip Log sub-navigation (`templates/vehicles/_trip_nav.html`).
`VehicleService.get_trip_log_periods` limits the Trip Log pay-period filter to
periods containing trips or fuel fills; an empty selected period falls back to
the nearest earlier period with entries.
`TripScheduleService.clear_future_trips` backs the Trip Log's **Clear Future**
action. It deletes manually added trips from a chosen date, optionally for one
vehicle, and either keeps routine trips, marks them skipped, or ends their routines
the day before.

Trip add/edit/delete, routine changes, occurrence confirmation/skips, bulk trip
add/delete, fuel changes, vehicle-setting changes and manual refresh rebuild saved
forecasts. Registration changes also clear the old registration's forecasts. Actual bank transactions are preserved, and monthly
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

`/preferences` is available to all signed-in users. Core `PreferenceService`
owns appearance and starting point. `FinancePreferenceService` stores
dashboard/list display defaults on the authenticated `User`, not the household,
and owns `/preferences/finance`. The legacy `POST /preferences` is registered by
Finance; the core preferences page is GET-only.
The personal default-account selector uses the existing visibility-aware account
validation. `/preferences/save` supports lightweight boolean updates; the legacy
owner-only `/settings/save_preference` endpoint delegates to the same personal
write path. Signed-in appearance is saved on the user through
`/preferences/appearance`; form changes are previews until saved, while the
top-bar toggle saves immediately. Only signed-out appearance uses browser-local
storage. See the [design system](../docs/DESIGN_SYSTEM.md#personal-appearance).
