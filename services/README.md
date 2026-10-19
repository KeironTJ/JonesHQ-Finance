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

Import from the domain package, for example:

```python
from services.finance.transaction_service import TransactionService
```

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
write path. Theme choice remains browser-local and saves immediately.
