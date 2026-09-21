# Service Organization

Services are grouped by domain. Import service implementations from their
domain package rather than maintaining top-level redirect modules.

## Domains

- `finance/` - accounts, categories, transactions, payday periods, balances,
  income, vendors, credit cards, and expenses
- `household/` - family and childcare workflows
- `planning/` - loans, mortgages, and pensions
- `vehicles/` - vehicles, fuel forecasting, and mileage
- `platform/` - authentication and settings
- `analytics/` - dashboard and net-worth read models

Import from the domain package, for example:

```python
from services.finance.transaction_service import TransactionService
```
