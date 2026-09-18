# Service Organization

Services are grouped by domain. The top-level `*_service.py` modules are
compatibility shims that re-export the canonical implementations so existing
blueprint imports continue to work during the migration.

## Domains

- `finance/` - accounts, categories, transactions, payday periods, balances,
  income, vendors, credit cards, and expenses
- `household/` - family and childcare workflows
- `planning/` - loans, mortgages, and pensions
- `vehicles/` - vehicles, fuel forecasting, and mileage
- `platform/` - authentication and settings
- `analytics/` - dashboard and net-worth read models

New code should import from the domain package when practical, for example:

```python
from services.finance.transaction_service import TransactionService
```

Existing imports such as `from services.transaction_service import
TransactionService` remain supported through the compatibility shims.