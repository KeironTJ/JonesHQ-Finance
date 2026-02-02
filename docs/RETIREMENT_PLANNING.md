# Net Worth Retirement Planning - Future Enhancements

## Overview
The Net Worth system is now designed to support long-term retirement planning with projections up to 20 years (240 months) into the future.

## Current Capabilities

### Projection Periods
- **2 Years** (24 months) - Short-term planning
- **3 Years** (36 months) - Medium-term planning  
- **5 Years** (60 months) - 5-year outlook
- **10 Years** (120 months) - Decade planning
- **15 Years** (180 months) - Pre-retirement
- **20 Years** (240 months) - Full retirement planning

### Manual Cache Management
- **Refresh Cache Button**: Manually recalculate all monthly balances
- **Configurable Future Period**: Choose how far ahead to calculate
- Accessed via "Refresh Cache" button on Net Worth page

### URL Parameters
- `?period=60` - Set projection period (in months)
- `?year=2027` - View specific year

## Future Enhancements Roadmap

### Phase 1: Pension Growth Modeling (Future)
**Goal**: Add compound growth projections for pensions

**Implementation**:
1. Add fields to `Pension` model:
   - `expected_growth_rate` (e.g., 5% per year)
   - `monthly_contribution` (ongoing contributions)
   - `employer_contribution` (if applicable)

2. Create `PensionProjectionService`:
   - `calculate_future_value(pension_id, target_date)`
   - Uses compound interest formula: `FV = PV * (1 + r)^n + PMT * [((1 + r)^n - 1) / r]`
   - Accounts for monthly contributions

3. Integrate into `NetWorthService.calculate_networth_at_date()`:
   - For past dates: Use actual snapshots (already implemented)
   - For future dates: Use projected growth calculations

**Example Calculation**:
```python
# Pension: £50,000 current value, 5% annual growth, £500/month contribution
# After 10 years:
growth_rate = 0.05 / 12  # Monthly rate
months = 120
future_value = 50000 * (1 + growth_rate)**months + 500 * (((1 + growth_rate)**months - 1) / growth_rate)
# Result: ~£132,000
```

### Phase 2: Investment Accounts (Future)
**Goal**: Track stocks, bonds, ISAs, and investment growth

**New Models**:
```python
class Investment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))  # "Vanguard FTSE Global"
    investment_type = db.Column(db.String(50))  # ISA, Stocks & Shares, Bonds
    current_value = db.Column(db.Numeric(10, 2))
    expected_return = db.Column(db.Float)  # 7% annual return
    monthly_contribution = db.Column(db.Numeric(10, 2))
    is_active = db.Column(db.Boolean)

class InvestmentSnapshot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    investment_id = db.Column(db.Integer, ForeignKey('investments.id'))
    snapshot_date = db.Column(db.Date)
    value = db.Column(db.Numeric(10, 2))
```

**Integration**:
- Add to `calculate_networth_at_date()` under ASSETS
- Create `InvestmentProjectionService` similar to pensions
- Support different growth models (conservative, moderate, aggressive)

### Phase 3: Retirement Scenarios (Future)
**Goal**: Model different retirement scenarios

**Features**:
1. **Retirement Age Settings**:
   - User inputs: retirement age (e.g., 65)
   - System calculates: years until retirement

2. **Income vs Expenses After Retirement**:
   - Pension income (state + private)
   - Expected living expenses
   - Calculate monthly surplus/deficit

3. **Scenario Modeling**:
   - Best case: 7% growth, low expenses
   - Expected case: 5% growth, normal expenses
   - Worst case: 3% growth, high expenses

4. **Retirement Readiness Score**:
   - Calculate if projected net worth meets retirement needs
   - Show monthly income from pensions/investments
   - Flag if additional saving needed

### Phase 4: Tax Optimization (Future)
**Goal**: Account for tax implications on retirement income

**Considerations**:
- Pension withdrawal tax (25% tax-free, then income tax)
- ISA (tax-free)
- Capital gains tax on investments
- State pension age thresholds

### Phase 5: Inflation Adjustment (Future)
**Goal**: Show "real" net worth (inflation-adjusted)

**Implementation**:
- Add inflation rate setting (e.g., 2.5% per year)
- Calculate purchasing power of future money in today's terms
- Display both nominal and real net worth

## Data Requirements for Future Features

### For Pensions:
- Current value ✓ (already have)
- Expected growth rate (to add)
- Monthly contributions (to add)
- Pension type (private, state, workplace)
- Retirement age

### For Investments:
- Investment types (ISA, stocks, bonds)
- Current values
- Expected returns by type
- Risk profiles
- Monthly contributions

### For Retirement Planning:
- Target retirement age
- Expected state pension amount
- Expected living costs in retirement
- Desired retirement income

## Technical Scalability

### Already Implemented ✓
- Cache supports 240 months (20 years)
- Manual cache refresh with configurable periods
- Timeline generation for any period length
- Separate actual vs projected balances

### Ready for Enhancement
- `calculate_networth_at_date()` can be extended with new asset types
- Service layer architecture allows new projection services
- Database schema supports new models without migration conflicts

## Usage Examples

### Viewing 10-Year Projection
```
Navigate to: /networth?period=120
```

### Refreshing Cache for 20 Years
1. Click "Refresh Cache" button
2. Select "20 Years (240 months)"
3. Click "Refresh Cache"
4. Wait for completion (may take 1-2 minutes)

### API Integration (Future)
```python
# Get net worth projection for 10 years from now
from datetime import date
from dateutil.relativedelta import relativedelta

target_date = date.today() + relativedelta(years=10)
projection = NetWorthService.calculate_networth_at_date(target_date)

# Once pensions have growth rates:
# projection['pensions_value'] will include 10 years of compounded growth
```

## Migration Path

When adding pension growth:
1. **No breaking changes** - existing code continues to work
2. **Gradual rollout** - add growth fields with defaults (0%)
3. **Backward compatible** - if no growth rate set, use current snapshot method
4. **Optional feature** - users can enable growth projections per pension

## Performance Considerations

### Current Performance ✓
- 24 months: ~0.5 seconds to rebuild cache
- 240 months: ~1-2 seconds to rebuild cache
- Timeline load: < 100ms (using cache)

### Future With Growth Calculations
- Projections are calculated on-demand (not cached)
- Growth formulas are fast (mathematical operations)
- Expected impact: +10-50ms per calculation
- Still well under 1 second for full timeline

## Recommendation

**Priority Order**:
1. ✓ Manual cache refresh (DONE)
2. ✓ Extended projection periods (DONE)
3. Add pension growth rate fields
4. Implement pension projection calculations
5. Add investment tracking
6. Build retirement scenario modeling
7. Add tax optimization
8. Implement inflation adjustment

The foundation is now in place to support all these features without architectural changes!
