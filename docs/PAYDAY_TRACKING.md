# Payday Period Tracking

## Overview

The Payday Period Tracking feature allows you to monitor your finances from payday to payday, giving you better visibility into available funds and helping you avoid overspending between pay periods.

## Key Concepts

### Payday Periods
Unlike traditional monthly tracking (1st to 31st), payday periods run from your payday to the day before your next payday. For example:
- If your payday is the **15th**, January's period runs from **Jan 15th to Feb 14th**
- If your payday is the **1st**, January's period runs from **Jan 1st to Jan 31st**

### Weekend Adjustment
If your payday falls on a weekend, the system automatically adjusts to the **previous working day**:
- Saturday payday → Friday
- Sunday payday → Friday

### Metrics Tracked

1. **Rolling Balance**: The expected balance at the end of the period (includes all paid and unpaid transactions)

2. **MIN Balance**: The lowest balance point during the period - this is your "danger zone"

3. **Max Extra Spend**: The difference between Rolling Balance and MIN Balance - this is how much you can safely spend without going below your minimum

4. **Opening Balance**: The balance at the start of the period

## Setup

### 1. Configure Your Payday
1. Go to **Settings** (gear icon on dashboard)
2. Find the "Payday Tracking" section
3. Set your payday (1-31)
4. Click "Save Settings"

### 2. Select Account to Track
1. Go to **Dashboard**
2. Use the "Account Selection" dropdown
3. Choose your main bank account (typically "Joint" account)
4. Click "Update"

## Dashboard Display

The dashboard shows a comprehensive table with:
- **12 months** of payday periods
- Color-coded columns for easy reading:
  - Blue: Rolling Balance (ending balance)
  - Yellow: MIN Balance (lowest point)
  - Teal: Max Extra Spend (safe to spend)
- Date ranges for each period
- Opening balance for context

### Summary Cards

Three prominent cards show current period metrics:
1. **Current Period Ending Balance** (Blue) - Where you'll be at end of period
2. **Current Period Minimum** (Yellow) - Lowest point this period
3. **Safe Extra Spend** (Teal) - How much extra you can safely spend

## Example

Your payday is the 15th. Today is January 28th, 2026.

```
Period: 2026-01 (Jan 15 - Feb 14)
Opening Balance: £500.00
Rolling Balance: £739.69
MIN Balance: £561.14
Max Extra Spend: £178.54
```

**Interpretation:**
- You started this period with £500
- By Feb 14th, you'll have £739.69 (if all transactions clear)
- Your lowest point will be £561.14 (perhaps before your next income)
- You can safely spend an extra £178.54 without dipping below your minimum

## Technical Details

### Including Unpaid Transactions
The system includes **both paid and unpaid** transactions in calculations. This gives you a forward-looking view of your finances, showing where you'll be after all scheduled transactions clear.

### Calculation Logic
```python
# For each payday period:
1. Get opening balance (balance at period start - 1 day)
2. Process all transactions in chronological order
3. Track running balance and record minimum
4. Final balance = Rolling Balance
5. Max Extra Spend = Rolling Balance - MIN Balance
```

### Database
- Payday setting stored in `settings` table
- Key: `payday_day`
- Type: `int`
- Default: `15`

## Files Modified

### New Files
- `services/payday_service.py` - Core payday calculation logic
- `scripts/maintenance/init_payday_setting.py` - Initialization script

### Modified Files
- `blueprints/dashboard/routes.py` - Dashboard data loading
- `blueprints/settings/routes.py` - Settings management
- `templates/dashboard/index.html` - Dashboard UI
- `templates/settings/index.html` - Settings UI

## API Reference

### PaydayService Methods

```python
# Get payday setting
payday_day = PaydayService.get_payday_setting()

# Get payday for specific month (with weekend adjustment)
payday = PaydayService.get_payday_for_month(2026, 1)

# Get period dates
start, end, label = PaydayService.get_payday_period(2026, 1)

# Get multiple periods
periods = PaydayService.get_payday_periods(2026, 1, num_periods=12)

# Calculate period metrics
metrics = PaydayService.calculate_period_balances(
    account_id=1,
    start_date=date(2026, 1, 15),
    end_date=date(2026, 2, 14),
    include_unpaid=True
)

# Get full dashboard summary
summary = PaydayService.get_payday_summary(
    account_id=1,
    num_periods=12,
    include_unpaid=True
)
```

## Future Enhancements

Potential improvements:
- [ ] Export payday data to Excel/CSV
- [ ] Alert when approaching minimum balance
- [ ] Historical comparison (this year vs last year)
- [ ] Multiple account tracking
- [ ] Category-based breakdown per period
- [ ] Paid vs Unpaid toggle view
- [ ] Custom period length (weekly, bi-weekly)

## Troubleshooting

### No data showing
- Ensure you have an active account selected
- Verify payday is set in Settings
- Check that you have transactions in the selected account

### Incorrect balances
- Verify transaction dates are correct
- Check paid/unpaid status of transactions
- Ensure txn_type is set correctly (Income vs Expense)

### Weekend payday not adjusting
- Check system date calculation
- Verify payday_day setting is saved correctly
- Test with specific dates to confirm adjustment logic
