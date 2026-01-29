# Payday Bucket Filtering - Implementation Proposal

## Current State

### What We Have
The **PaydayService** currently provides:
- **Payday period calculation** - Determines date ranges for each payday-to-payday period
- **Balance forecasting** - Calculates rolling balances, minimum balance, and max extra spend
- **Dashboard integration** - Shows 12 months of payday periods with metrics

### Payday Settings
- **payday_day**: Day of month when payday occurs (stored in Settings table, default: 15)
- **Weekend adjustment**: Automatically adjusts to previous working day if payday falls on weekend
- **Period label format**: `YYYY-MM` (e.g., "2026-01" for January payday period)

### Current PaydayService Features
1. `get_payday_for_month(year, month)` - Returns actual payday date for a month
2. `get_payday_period(year, month)` - Returns (start_date, end_date, label) for a period
3. `get_payday_periods(start_year, start_month, num_periods)` - Returns list of periods
4. `calculate_period_balances(account_id, start_date, end_date)` - Calculates metrics for a period
5. `get_payday_summary(account_id, num_periods)` - Dashboard summary data

### Where It's Used
- **Dashboard only** (`blueprints/dashboard/routes.py`)
- Shows 12 payday periods with balance forecasts
- Account-specific tracking

---

## Proposal: App-Wide Payday Filtering

### Concept
Add a payday bucket filter option to key areas of the app, allowing users to:
- View transactions within specific payday periods
- Filter reports by payday periods
- Analyze spending by payday period instead of calendar month

### Benefits
1. **Better cash flow visibility** - Aligns with when money actually arrives
2. **Real spending patterns** - Calendar months split paychecks; payday periods don't
3. **Consistent forecasting** - Same logic across dashboard and transactions
4. **Budgeting alignment** - Budget by payday period, not arbitrary month boundaries

---

## Implementation Options

### Option 1: Basic Payday Filter (Quick Win)
**Scope**: Add payday period filter to transactions page only

**Changes Required**:
1. Add `payday_period` dropdown to transaction filters (next to year_month)
2. Populate dropdown with last 12 payday periods
3. Convert period label to date range and filter transactions
4. Keep existing year_month filter as alternative

**Pros**:
- Simple to implement
- No database changes
- Users can toggle between calendar and payday views

**Cons**:
- Limited to transactions page
- Have to calculate periods on every page load

**Effort**: ~2 hours

---

### Option 2: Store Payday Period in Transactions (Medium)
**Scope**: Add payday_period field to transactions table

**Changes Required**:
1. **Migration**: Add `payday_period` column to transactions (nullable string)
2. **Script**: Backfill existing transactions with payday_period (e.g., "2026-01")
3. **Transaction creation**: Automatically set payday_period when creating/editing transactions
4. **Filters**: Add payday_period to filters across:
   - Transactions page
   - Category reports
   - Vendor reports
   - Budget tracking
5. **Bulk operations**: Allow changing payday_period (for adjustments)

**Pros**:
- Fast filtering (indexed field)
- Persistent - no recalculation needed
- Enables powerful payday-based reports
- Can track transactions across payday boundary changes

**Cons**:
- Database migration required
- Need to maintain payday_period on updates
- What if payday setting changes? (need migration tool)

**Effort**: ~6-8 hours

---

### Option 3: Dynamic Payday Filtering (Advanced)
**Scope**: Add payday period as a query-time calculation everywhere

**Changes Required**:
1. **Helper function**: `get_payday_period_for_date(transaction_date)` 
2. **Filter UI**: Add payday period selector to all list views
3. **Query modification**: Convert selected period to date range filter
4. **Caching**: Cache payday period calculations (since they change monthly)
5. **Apply to**:
   - Transactions
   - Budgets
   - Reports (category, vendor, spending trends)
   - Credit card transactions
   - Loan payments

**Pros**:
- No database changes
- Always accurate (recalculates based on current settings)
- If payday changes, historical data auto-adjusts
- Can coexist with calendar filters

**Cons**:
- Performance hit on large datasets
- More complex queries
- Period labels not stored (harder to export)

**Effort**: ~10-12 hours

---

## Recommended Approach

### **Hybrid: Option 1 + Enhanced (Best Balance)**

Start with **Option 1** (basic filter) but build it properly:

#### Phase 1: Transactions Page (Immediate)
1. Add payday period filter dropdown (populated by PaydayService)
2. When selected, converts to date range filter behind the scenes
3. Shows period label in filter summary
4. Works alongside existing filters

#### Phase 2: Reports & Analytics (Next)
1. Add same payday filter to:
   - Budget tracking page
   - Category summary page
   - Vendor reports
2. Reuse the same filtering logic

#### Phase 3: Future Enhancement (Optional)
- Add `payday_period` column if performance becomes an issue
- Add "View by Payday Period" toggle for budget pages

---

## Technical Design

### Payday Period Filter Component

```python
# In PaydayService, add:
@staticmethod
def get_period_for_date(target_date):
    """
    Get the payday period label for a given date.
    Returns: period_label (e.g., "2026-01")
    """
    # Find which period this date falls in
    # Work backwards from current date to find the right period

@staticmethod
def get_recent_periods(num_periods=24):
    """
    Get recent payday periods for filter dropdown.
    Returns: List of (period_label, start_date, end_date, display_name)
    """
    # Generate list like:
    # [("2026-01", date(2026,1,15), date(2026,2,14), "Jan 15 - Feb 14, 2026"), ...]
```

### Transaction Filter UI
Add to filter form:
```html
<div class="col-md-2">
    <label for="payday_period" class="form-label">Payday Period</label>
    <select name="payday_period" class="form-select" onchange="this.form.submit()">
        <option value="">All Periods</option>
        {% for period in payday_periods %}
        <option value="{{ period.label }}" 
                {% if selected_payday_period == period.label %}selected{% endif %}>
            {{ period.display_name }}
        </option>
        {% endfor %}
    </select>
</div>
```

### Route Logic
```python
# In transactions/routes.py
payday_period = request.args.get('payday_period')

if payday_period:
    # Convert period label to date range
    year, month = map(int, payday_period.split('-'))
    start_date, end_date, _ = PaydayService.get_payday_period(year, month)
    query = query.filter(
        Transaction.transaction_date >= start_date,
        Transaction.transaction_date <= end_date
    )
```

---

## Areas to Apply Payday Filtering

### High Priority
1. ✅ **Dashboard** (already has it)
2. **Transactions List** - Main transaction page with filters
3. **Budget Tracking** - Track budget by payday period
4. **Spending Reports** - Category/vendor analysis by payday

### Medium Priority
5. **Networth Snapshots** - Align with payday periods
6. **Income Tracking** - See income by payday period
7. **Childcare Payments** - Track by payday period

### Low Priority
8. **Credit Cards** - Payday-based payment planning
9. **Loans** - See loan payments by payday period
10. **Export/Reports** - CSV exports filtered by payday

---

## Migration Considerations

### If Payday Setting Changes
If user changes payday from 15th to 25th:

**Option 1 (Dynamic)**: Historical data auto-adjusts, periods recalculate
**Option 2 (Stored)**: Need migration script to recalculate all payday_period values
**Option 3 (Hybrid)**: Store original period, but allow recalculation on demand

**Recommendation**: Start with dynamic (no stored field), add storage only if needed for performance.

---

## Performance Impact

### Current State
- Transactions page: Loads all 10,000 transactions filtered by account/category/etc.
- Now has pagination (100 per page)

### With Payday Filter
- **Dynamic approach**: Add date range filter (start_date, end_date) - very fast with indexes
- **No performance concern**: Date range filters are efficient in SQL

### Optimization
- Add index on `transaction_date` if not already present
- Cache payday period calculations (they only change once per month)

---

## Next Steps

### Immediate (1-2 hours)
1. ✅ Review this proposal
2. Add `get_recent_periods()` method to PaydayService
3. Add payday period filter to transactions page
4. Test with existing data

### Short Term (1 week)
5. Add payday filter to budget tracking
6. Add payday filter to category/vendor reports
7. Create settings page to adjust payday_day

### Long Term (Future)
8. Consider storing payday_period if performance needed
9. Add payday period comparison reports
10. Payday-based forecasting tools

---

## Questions for User

1. **Priority**: Which pages need payday filtering first?
   - Transactions (most important?)
   - Budgets
   - Reports
   - Other?

2. **Calendar vs Payday**: Should we:
   - Replace year_month filter with payday_period?
   - Keep both options (toggle or separate dropdown)?
   - Default to payday or calendar?

3. **Period Display**: How should periods be labeled?
   - "2026-01" (concise)
   - "Jan 2026" (readable)
   - "15 Jan - 14 Feb 2026" (explicit)
   - "Jan 15, 2026 Payday" (clear)

4. **Historical Data**: For transactions before payday tracking:
   - Calculate retroactively based on current payday setting?
   - Mark as "Unknown Period"?
   - Ignore (only filter recent transactions)?

5. **Bulk Operations**: Should bulk edit include payday period?
   - Useful if we store the field
   - Not needed if dynamic

---

## Summary

**Recommendation**: Start with **Option 1 Enhanced** (dynamic filtering)

**Why**:
- No database changes
- Quick to implement
- Flexible (works anywhere)
- No migration headaches if payday changes
- Can always add storage later if needed

**Next Action**: 
- Extend PaydayService with `get_recent_periods()`
- Add payday filter to transactions page
- Test and iterate based on usage

This gives you full payday filtering without committing to a database schema change yet.
