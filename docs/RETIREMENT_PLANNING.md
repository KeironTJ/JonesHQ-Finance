# Net Worth and Retirement Planning

## Current Capabilities

JonesHQ Finance combines monthly account-balance forecasts, pension snapshots
and projections, credit-card and loan liabilities, and property values in its
net-worth views. It is a planning aid based on recorded and configured data, not
personalized financial advice.

### Net-Worth Timeline

The `/networth` view defaults to 24 future months. Its `period` query parameter
selects the future window, bounded by the route to 12–180 months. Historical
coverage is a fixed 60-month window unless a household net-worth start date is
configured. The `year` parameter can select a year in the timeline.

The **Refresh Cache** action rebuilds monthly account balances. The cache
service defaults to 24 future months; the refresh route accepts 12–240 months.
The cache horizon and the visible net-worth timeline horizon are separate
settings.

### What the Timeline Uses

- **Accounts:** monthly cached balances. Future dates use projected balances;
  past dates use actual paid-transaction balances. A missing future cache entry
  falls back to the current account balance; a missing historical entry is
  reported as zero rather than reusing a current value.
- **Pensions:** actual snapshots for past and current dates; saved `default`
  scenario projections for future dates. If a future projection is missing, the
  service falls back to the pension's current value.
- **Credit cards and loans:** recorded balances/payments up to the target date;
  future dates include pending forecast activity.
- **Properties and mortgage products:** historical actual valuations and future
  valuation projections use property records and appreciation assumptions.
  Current and planned mortgage products supply mortgage liability data.

The date-specific calculation is implemented by
`NetWorthService.calculate_networth_at_date()` in
`services/analytics/networth_service.py`. It is household-scoped.

### Pension Projections

Pension projection snapshots are managed by
`PensionService` (`services/planning/pension_service.py`). The service supports
default, optimistic, and pessimistic growth scenarios and monthly contribution
inputs. A member's date of birth and retirement age are kept in a shared,
member-keyed retirement profile used by income planning and linked pensions.
See [Pension Projections](PENSION_PROJECTIONS.md) and
[Income and Pension System](INCOME_PENSION_SYSTEM.md).

## Known Limitations

- Net-worth forecasts use recorded transactions, saved pension projections,
  current/planned debt records, and configured property appreciation. They do
  not model arbitrary investment accounts or guarantee future balances.
- The application does not currently provide the proposed investment-account
  tracking, inflation-adjusted values, tax optimization, or retirement
  income-versus-expense scenario score described in older roadmap material.
- Future results depend on the accuracy and completeness of account forecasts,
  pension assumptions, loan/card schedules, property valuations, and settings.
- The timeline should not be treated as a substitute for financial advice.

## Useful References

- [Monthly Balance Cache](MONTHLY_BALANCE_CACHE.md) explains account cache
  behavior and maintenance.
- [Database Schema](DATABASE_SCHEMA.md) describes properties, valuations,
  mortgage products, pensions, and snapshot records.
- [Production Runbook](../deployment/README.md) documents the deployed service;
  it is not a guide to the forecast assumptions.
