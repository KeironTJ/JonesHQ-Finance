# Monthly Account Balance Cache System

## Overview

The Monthly Account Balance Cache system optimizes Net Worth timeline calculations by pre-computing and storing monthly account balances. This eliminates the need to query thousands of transactions on every page load.

## Why This System?

### The Problem
- The Nationwide Current Account alone has 7,912 transactions
- Calculating historical balances required querying all transactions up to each month
- Timeline views (24 months) would require 14 accounts × 24 months = 336 separate calculations
- Each calculation would scan thousands of transaction records

### The Solution
- Pre-compute monthly balances for all accounts
- Store in a cache table: `monthly_account_balances`
- ~434 cache entries (14 accounts × 31 months) vs 8000+ transaction queries
- Timeline loads in milliseconds instead of seconds

## Database Schema

### Table: `monthly_account_balances`

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Primary key |
| `account_id` | Integer | Foreign key to accounts table |
| `year_month` | String(7) | Format: "YYYY-MM" (e.g., "2024-12") |
| `actual_balance` | Float | Balance from **paid** transactions only |
| `projected_balance` | Float | Balance including **paid + unpaid + forecasted** |
| `last_calculated` | DateTime | Timestamp of last calculation |

### Indexes
- **Primary Key**: `id`
- **Unique Constraint**: `(account_id, year_month)` - One entry per account per month
- **Index**: `idx_account_year_month` on `(account_id, year_month)` for fast lookups

## Balance Types

### Actual Balance (Past/Current)
- **What**: Sum of all PAID transactions up to month end
- **When**: Used for historical months (on or before today)
- **Purpose**: Shows real money that has moved

### Projected Balance (Future)
- **What**: Sum of all transactions (paid + unpaid + forecasted)
- **When**: Used for future months
- **Purpose**: Shows expected balance if all forecasted transactions occur

## Architecture

### Components

1. **Model**: `models/monthly_account_balance.py`
   - SQLAlchemy model definition
   - Relationships to Account model

2. **Service**: `services/monthly_balance_service.py`
   - `calculate_month_balance(account_id, year, month)` - Core calculation logic
   - `update_month_cache(account_id, year, month)` - Update single month
   - `update_account_from_month(account_id, start_year, start_month)` - Update from month forward
   - `get_balance_for_month(account_id, year, month, use_projected)` - Retrieve cached balance
   - `rebuild_all_cache()` - Full cache rebuild
   - `handle_transaction_change(account_id, transaction_date)` - Auto-update trigger

3. **Event Listeners**: `models/transactions.py`
   - Auto-update cache when transactions are added/edited/deleted
   - Uses SQLAlchemy `@event.listens_for` hooks

4. **Net Worth Integration**: `services/networth_service.py`
   - `calculate_networth_at_date()` updated to use cache via `MonthlyBalanceService.get_balance_for_month()`
   - Falls back to `Account.balance` if cache miss

## Cache Management

### Initial Population

```bash
python scripts/maintenance/populate_monthly_balances.py
```

This will:
- Clear existing cache
- Find earliest transaction across all accounts
- Calculate monthly balances from earliest month to 12 months in future
- Populate cache for all active accounts

### Automatic Updates

Cache automatically updates when:
- **Transaction Added**: Updates affected month + all future months
- **Transaction Edited**: Updates affected month + all future months
- **Transaction Deleted**: Updates affected month + all future months

Example:
```python
# User adds transaction on 2024-12-15
# Automatically triggers:
MonthlyBalanceService.handle_transaction_change(account_id, date(2024, 12, 15))
# Updates: 2024-12, 2025-01, 2025-02, ... up to 12 months from now
```

### Manual Updates

Force rebuild entire cache:
```python
from services.monthly_balance_service import MonthlyBalanceService
MonthlyBalanceService.rebuild_all_cache()
```

Update specific account from a month forward:
```python
MonthlyBalanceService.update_account_from_month(account_id, 2024, 12)
```

## Usage Examples

### Get Balance for Specific Month

```python
from services.monthly_balance_service import MonthlyBalanceService

# Get actual balance (paid transactions only)
actual = MonthlyBalanceService.get_balance_for_month(account_id, 2024, 12, use_projected=False)

# Get projected balance (includes forecasted)
projected = MonthlyBalanceService.get_balance_for_month(account_id, 2025, 6, use_projected=True)
```

### Calculate Net Worth Timeline

```python
from services.networth_service import NetWorthService

# Get 24-month timeline (uses cache automatically)
timeline = NetWorthService.get_monthly_timeline(start_year=2024, start_month=1, num_months=24)

for month in timeline:
    print(f"{month['month_label']}: £{month['net_worth']:.2f}")
```

## Performance Gains

### Before (Direct Transaction Queries)
- **Query**: 14 accounts × 24 months = 336 queries
- **Records Scanned**: Up to 7,912 transactions per query
- **Time**: 3-5 seconds for timeline load

### After (Monthly Balance Cache)
- **Query**: 14 accounts × 24 months = 336 cache lookups
- **Records Scanned**: 1 record per lookup
- **Time**: < 100ms for timeline load

**Result**: ~50x performance improvement

## Maintenance

### Check Cache Status

```bash
python scripts/checks/check_balance_cache.py
```

Shows:
- Total cache entries
- Active accounts
- Sample balances
- Month range covered

### Test Net Worth Calculations

```bash
python scripts/checks/test_networth_cache.py
```

Verifies:
- Current net worth calculation
- Historical point-in-time calculation
- Timeline generation
- Comparison data

### Common Issues

**Problem**: Timeline shows same values for all months
**Solution**: Run `populate_monthly_balances.py` to rebuild cache

**Problem**: New transactions not reflected in timeline
**Solution**: Check event listeners are working. Manually run:
```python
MonthlyBalanceService.handle_transaction_change(account_id, transaction_date)
```

**Problem**: Cache entries missing
**Solution**: Rebuild cache:
```python
MonthlyBalanceService.rebuild_all_cache()
```

## Migration History

**Migration**: `dc41d8efc05f_add_monthly_account_balances_cache_table.py`

Creates:
- `monthly_account_balances` table
- Unique constraint on `(account_id, year_month)`
- Index on `(account_id, year_month)` for performance

## Future Enhancements

1. **Scheduled Refresh**: Nightly cron job to ensure future months stay up to date
2. **Cache Warming**: Pre-calculate next 6 months on app startup
3. **Incremental Updates**: Only recalculate changed months (currently recalculates from month forward)
4. **Cache Invalidation**: Track when Account.balance is manually edited
5. **Historical Snapshots**: Preserve actual historical values even if transactions are edited later

## Related Documentation

- [Net Worth System](NETWORTH_SYSTEM.md) - Overview of Net Worth functionality
- [Database Schema](DATABASE_SCHEMA.md) - Full database structure
- [Transaction System](INTEGRATED_TRANSACTIONS.md) - Transaction management
