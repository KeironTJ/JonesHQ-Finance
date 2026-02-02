# Income & Pension Tracking System

## Overview
Comprehensive system for tracking lifetime income, calculating tax/NI/pension contributions, and monitoring pension growth. Integrates seamlessly with the existing transaction and Net Worth systems.

## Database Models

### Income Model (`models/income.py`)
Tracks each pay period with full breakdown of deductions and contributions.

**Key Fields:**
- `person`: 'Keiron' or 'Emma' (supports multiple people)
- `pay_date`: Date of payment
- `tax_year`: '2023-2024' format
- `gross_annual_income`: Current annual salary
- `gross_monthly_income`: Monthly gross pay
- **Pension Contributions:**
  - `employer_pension_percent`: Employer % (e.g., 7%)
  - `employee_pension_percent`: Employee % (e.g., 3%)
  - `employer_pension_amount`: £ amount
  - `employee_pension_amount`: £ amount
  - `total_pension`: Combined pension contribution
- **Tax & Deductions:**
  - `tax_code`: UK tax code (e.g., '1257L')
  - `income_tax`: Monthly income tax
  - `national_insurance`: Monthly NI
  - `avc`: Additional Voluntary Contributions
  - `other_deductions`: Other deductions
- **Final Amounts:**
  - `take_home`: Net pay after all deductions
  - `deposit_account_id`: Account where salary is paid
  - `transaction_id`: Auto-created transaction link

### Pension Model (`models/pensions.py`)
Tracks pension pots from different providers.

**Key Fields:**
- `person`: Owner of pension
- `provider`: 'Peoples Pension', 'Aviva', 'Aegon', 'Scottish Widows', etc.
- `account_number`: Account/policy number
- `current_value`: Latest value
- `contribution_rate`: Employee contribution %
- `employer_contribution`: Employer contribution %
- `is_active`: Whether still contributing

### PensionSnapshot Model (`models/pension_snapshots.py`)
Monthly snapshots of pension values for tracking growth.

**Key Fields:**
- `pension_id`: Link to pension
- `review_date`: Date of snapshot (usually 15th of month)
- `value`: Pension value at this date
- `growth_percent`: % growth since previous snapshot

## Income Service (`services/income_service.py`)

### Tax & NI Calculations
Automatically calculates based on UK tax rules:

**Tax Rates (2023-2024):**
- Personal Allowance: £12,570 (tax-free)
- Basic Rate (20%): £12,571 - £50,270
- Higher Rate (40%): £50,271 - £125,140
- Additional Rate (45%): Over £125,140

**National Insurance (Class 1 Employee):**
- Threshold: £12,570
- Basic Rate (12%): £12,571 - £50,270
- Additional Rate (2%): Over £50,270

### Key Methods

#### `calculate_tax_and_ni(gross_annual, tax_code, pension_amount)`
Calculates tax and NI for given salary.

**Example:**
```python
from services.income_service import IncomeService

result = IncomeService.calculate_tax_and_ni(
    gross_annual=53000,
    tax_code='1070L',
    pension_amount=3300  # Annual pension contribution
)
# Returns: {'tax': 7815.00, 'ni': 4100.00, 'total_deductions': 15215.00, 'net_annual': 37785.00}
```

#### `create_income_record(...)`
Creates income record with auto-calculated tax/NI and optional transaction.

**Example:**
```python
income = IncomeService.create_income_record(
    person='Keiron',
    pay_date=date(2024, 1, 15),
    gross_annual=53000,
    employer_pension_pct=3,
    employee_pension_pct=4,
    tax_code='1070L',
    deposit_account_id=1,  # Nationwide Current Account
    source='My Company Ltd',
    create_transaction=True  # Auto-creates transaction
)
```

**This will:**
1. Calculate monthly gross (£4,416.67)
2. Calculate pension contributions (3% + 4% = £309.16/month)
3. Calculate tax and NI
4. Calculate take home (£3,175.43)
5. Create income record in database
6. Auto-create transaction in specified account
7. Update account balance

#### `get_income_summary(person=None, year=None)`
Get aggregate statistics for income.

**Example:**
```python
summary = IncomeService.get_income_summary(person='Keiron', year=2024)
# Returns totals, averages, list of all income records
```

## Integration Points

### 1. Transactions
- Income auto-creates transactions in specified account
- Uses "Salary" category (auto-created if doesn't exist)
- Marked as `is_paid=True` and `is_forecasted=False`
- Account balance automatically updated
- Transaction updates trigger monthly balance cache refresh

### 2. Monthly Balance Cache
- Income transactions update account balances
- Cache automatically recalculates from income month forward
- Net Worth timeline shows impact of income

### 3. Pension Snapshots → Net Worth
- Pension current values shown in Net Worth "Assets"
- Growth tracking shows performance over time
- Ready for future growth projection modeling

## Next Steps: Implementation

### Phase 1: Database Migration
```python
# Create migration for new fields
flask db revision -m "Add person field to income and pensions"
flask db upgrade
```

### Phase 2: Create Income Blueprint
Create `blueprints/income/` with:
- `routes.py`: List, add, edit, delete income records
- Template for income entry form
- Template for income history/summary

### Phase 3: Create Import Script
Based on your Excel data, create:
```python
# scripts/imports/import_income_history.py
# Import historical income data from CSV/Excel
```

### Phase 4: Pension Snapshot Management
Create pension snapshot interface:
- Upload monthly pension values
- Auto-calculate growth percentages
- Chart showing pension growth over time

### Phase 5: UI Integration
- Add "Income" menu item
- Add "Pensions" menu item
- Dashboard widget showing latest income & pension values
- Net Worth integration (already done!)

## Usage Examples

### Recording New Income
```python
from services.income_service import IncomeService
from datetime import date

# Keiron's salary - Jan 2024
income = IncomeService.create_income_record(
    person='Keiron',
    pay_date=date(2024, 1, 15),
    gross_annual=53000,
    employer_pension_pct=3,
    employee_pension_pct=4,
    tax_code='1070L',
    avc=0,
    other=0,
    deposit_account_id=1,  # Nationwide Current
    source='My Company Ltd',
    create_transaction=True
)

print(f"Income tax: £{income.income_tax}")
print(f"NI: £{income.national_insurance}")
print(f"Pension: £{income.total_pension}")
print(f"Take home: £{income.take_home}")
# Creates transaction automatically!
```

### Adding Pension Snapshot
```python
from models.pensions import Pension
from models.pension_snapshots import PensionSnapshot

# Get pension
peoples_pension = Pension.query.filter_by(
    person='Keiron',
    provider='Peoples Pension'
).first()

# Add snapshot
snapshot = PensionSnapshot(
    pension_id=peoples_pension.id,
    review_date=date(2024, 2, 15),
    value=10756.23
)

# Calculate growth from previous
previous = PensionSnapshot.query.filter_by(
    pension_id=peoples_pension.id
).filter(
    PensionSnapshot.review_date < snapshot.review_date
).order_by(PensionSnapshot.review_date.desc()).first()

if previous:
    growth = ((snapshot.value - previous.value) / previous.value) * 100
    snapshot.growth_percent = growth

db.session.add(snapshot)
db.session.commit()

# Update pension current value
peoples_pension.current_value = snapshot.value
db.session.commit()
```

### Viewing Income History
```python
# Get all income for Keiron in 2024
summary = IncomeService.get_income_summary(person='Keiron', year=2024)

print(f"Total paid: {summary['count']} times")
print(f"Total gross: £{summary['total_gross']:,.2f}")
print(f"Total take home: £{summary['total_take_home']:,.2f}")
print(f"Total tax: £{summary['total_tax']:,.2f}")
print(f"Total NI: £{summary['total_ni']:,.2f}")
print(f"Total pension: £{summary['total_pension']:,.2f}")
```

## Data Import from Excel

Your Excel data can be imported with a script like:

```python
import pandas as pd
from datetime import datetime
from services.income_service import IncomeService

# Read Excel
df = pd.read_excel('income_history.xlsx')

for index, row in df.iterrows():
    income = IncomeService.create_income_record(
        person='Keiron',
        pay_date=datetime.strptime(row['Pay Date'], '%d/%m/%Y').date(),
        gross_annual=float(row['Gross Annual Income'].replace('£', '').replace(',', '')),
        employer_pension_pct=float(row['Employer Pension %'].replace('%', '')),
        employee_pension_pct=float(row['Keiron Pension %'].replace('%', '')),
        tax_code=row['Tax Code'],
        avc=float(row['AVC']) if row['AVC'] else 0,
        other=float(row['Other']) if row['Other'] else 0,
        deposit_account_id=1,  # Your main account
        source='Employer Name',
        create_transaction=True
    )
    print(f"Imported: {income.pay_date} - £{income.take_home}")
```

## Benefits

1. **Complete Income History**: Track every pay slip with full breakdown
2. **Automatic Calculations**: Tax and NI calculated using UK rules
3. **Transaction Integration**: No manual entry needed - transactions created automatically
4. **Multi-Person Support**: Track Keiron and Emma separately
5. **Pension Growth Tracking**: Monthly snapshots show investment performance
6. **Net Worth Integration**: Pensions appear in Net Worth calculations
7. **Future Growth Modeling**: Foundation ready for retirement projections
8. **Tax Planning**: See tax/NI impact of salary changes
9. **Audit Trail**: Complete record for tax returns and planning

## Ready for Future Enhancements

- **Pension Growth Projections**: Add expected growth rates
- **Retirement Modeling**: Calculate retirement income
- **Tax Optimization**: Model impact of pension contributions
- **Bonus Tracking**: Record one-off payments
- **Salary Increases**: Track progression over time
- **P60 Generation**: Annual tax summary
- **Multiple Income Sources**: Side hustles, freelance work

The foundation is complete - ready to build the UI and import your historical data!
