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

### 2. **Retirement Summary Dashboard** (`/pensions/retirement_summary`)
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
1. **Update Personal Settings** (Settings page):
   - Set your and Emma's dates of birth
   - Confirm retirement ages (default: 65)
   - Adjust government pension amounts
   - Fine-tune growth rate assumptions

2. **Configure Each Pension**:
   - Add/edit pensions with retirement age and monthly contribution amounts
   - System uses this for accurate projections

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
   - Export to Excel if needed

3. **Check Retirement Readiness**:
   - Visit "Retirement Summary"
   - See total projected income
   - Review individual pension breakdowns

## Settings You Can Configure

### In Database (via Settings page or scripts):
- `pension_default_monthly_growth_rate`: Default 0.12% (0.0012)
- `pension_optimistic_monthly_growth_rate`: 0.5% (0.005)
- `pension_pessimistic_monthly_growth_rate`: 0.05% (0.0005)
- `keiron_retirement_age`: Default 65
- `emma_retirement_age`: Default 65
- `keiron_date_of_birth`: Format: YYYY-MM-DD
- `emma_date_of_birth`: Format: YYYY-MM-DD
- `government_pension_annual_keiron`: Annual amount
- `government_pension_annual_emma`: Annual amount
- `annuity_conversion_rate`: Default 5% (0.05)
- `auto_regenerate_projections`: true/false

### Update Dates of Birth:
```python
# Run this in Python console or create a script
from models.settings import Settings
from extensions import db

Settings.set_value('keiron_date_of_birth', '1985-06-15', setting_type='string')
Settings.set_value('emma_date_of_birth', '1987-03-20', setting_type='string')
db.session.commit()
```

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
from services.pension_service import PensionService

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
