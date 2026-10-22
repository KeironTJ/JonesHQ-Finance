# Pension Projection System - Quick Start Guide

## Overview
Your pension management system now includes comprehensive projection capabilities that replicate and enhance your Excel workflow.

## Key Features

### 1. **Pension Projections View** (`/pensions/projections`)
- Combined historical + projected data in Excel-style table
- Monthly snapshots from now through retirement age
- Three scenarios: Default (0.12%), Optimistic (0.5%), Pessimistic (0.05%)
- Automatic growth calculations
- Total values across all pensions

### 2. **Retirement Summary Dashboard** (`/pensions/retirement-summary`)
- Current age and years to retirement
- Total current vs projected values
- Estimated annual annuity income
- Government pension integration
- Monthly retirement income projections

### 3. **Automatic Projection Generation**
- Projections auto-regenerate when you add new snapshots
- Uses configured growth rates from settings
- Accounts for monthly contributions
- Projects through to retirement age

## How to Use

### Initial Setup
1. **Set the shared retirement profile** (pension edit page or Income -> Plan):
   - Select the household member by ID when adding/editing their pension
   - Set their date of birth and retirement age (default: 67)
   - The same profile is used by income and all that member's pension pots,
     including after a member rename
   - Regenerate pension projections after changing the profile
   - In Settings, you can still:
     - Adjust government pension amounts
     - Fine-tune growth rate assumptions

2. **Configure Each Pension**:
   - Add/edit pensions with monthly contribution amounts
   - A target age entered on a pension updates the person's shared retirement age;
     leave it blank to retain that member's age
   - Unmatched legacy labels remain available and are not silently reassigned

### Monthly Workflow
1. **Add Monthly Snapshot**:
   - Go to specific pension → "Add Snapshot"
   - Enter the current value from your statement
   - System automatically calculates growth %
   - Projections regenerate automatically

2. **Review Projections**:
   - Click "View Projections" from pensions page
   - See complete timeline from now to retirement
   - Compare different scenarios

3. **Check Retirement Readiness**:
   - Visit "Retirement Summary"
   - See total projected income
   - Review individual pension breakdowns

## Settings You Can Configure

### Growth and Government Pension Settings
- `pension_default_monthly_growth_rate`: Default 0.12% (0.0012)
- `pension_optimistic_monthly_growth_rate`: 0.5% (0.005)
- `pension_pessimistic_monthly_growth_rate`: 0.05% (0.0005)
- `government_pension_annual_keiron`: Annual amount
- `government_pension_annual_emma`: Annual amount

Date of birth and target retirement age belong to each household member's shared
retirement profile. Set or update that profile through the pension edit workflow
or the Income planning flow; do not write fixed `keiron_*` or `emma_*` keys
directly. Legacy name-based profiles may still be read for members without a
linked profile.

## Technical Details

### Projection Algorithm
1. Starts from most recent actual snapshot (or current value)
2. Projects monthly from now until retirement age
3. Each month: `New Value = (Previous Value × (1 + growth_rate)) + monthly_contribution`
4. Calculates growth % between months
5. Stores with `is_projection=True` flag

### Scenario Comparison
- Default: Conservative 0.12%/month (1.45%/year)
- Optimistic: Strong 0.5%/month (6.2%/year)  
- Pessimistic: Very low 0.05%/month (0.6%/year)
- Each scenario stored separately

### Database Structure
- `pensions`: Main pension accounts
- `pension_snapshots`: Historical values AND projections
- Use `is_projection` flag to distinguish
- `scenario_name` field for different projections

## API/Service Methods

```python
from services.planning.pension_service import PensionService

# Generate projections for one pension
PensionService.save_projections(pension, scenario='default')

# Regenerate all
PensionService.regenerate_all_projections(scenario='optimistic')

# Get retirement summary
summary = PensionService.get_retirement_summary(person='Keiron')

# Get combined data for table view
data = PensionService.get_combined_snapshots(person=None, scenario='default')
```

## Tips
- Add snapshots on the 15th of each month for consistency
- Review projections monthly to track progress
- Use scenario comparison before major financial decisions
- Export table data to Excel for custom analysis
- Update monthly contribution amounts as salary changes

## Future Enhancements (Optional)
- CSV import from provider statements
- Email alerts for monthly updates
- Tax-free lump sum calculations
- Drawdown vs annuity comparisons
- Inflation adjustment options
- Charts and visualizations
