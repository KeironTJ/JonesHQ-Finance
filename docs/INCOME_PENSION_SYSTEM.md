# Income & Pension Tracking System

## Overview
Comprehensive system for tracking lifetime income, calculating tax/NI/pension contributions, and monitoring pension growth. Integrates seamlessly with the existing transaction and Net Worth systems.

## How income works (sources → timeline → payslips → plan)

| Concept | Table | What it is |
|---|---|---|
| **Income source** | `recurring_income` | One job, pension, self-employment or rental income for one person: type, pay frequency, starting pay, tax code, pension, student loan, yearly rise, deposit account, category, visibility. |
| **Timeline change** | `income_changes` | A dated event on a source: new salary, % pay rise, bonus / one-off, tax-code change, pension % change. Deleted with its source. |
| **Payslip** | `income` | One pay date. Forecasts are saved up to **24 months** ahead (`FORECAST_HORIZON_MONTHS`); actuals are entered over them. |
| **Plan** | none (computed) | `/income/plan`: per-tax-year totals up to retirement, projected in memory from each source's timeline. Nothing is saved. |

**Terms on a date** (`income_schedule.terms_for`): start from the source's own
figures, apply the yearly rise (`annual_increase_percent` each year from
`annual_increase_start`), then apply every timeline change dated on or before the
pay date. A `salary` change resets the base that later yearly rises compound on.
A bonus is paid with the first payment on or after its date.

**Pay dates** (`income_schedule.pay_dates`): `weekly`, `fortnightly`, `four_weekly`
(anchored on `first_pay_date`, moved back to the previous working day), `monthly`
(`pay_day`, `0` = last day) and `annual`.

**Income types** decide the maths: `employment` (PAYE tax, Class 1 NI, workplace
pension, student loan); `private_pension` (PAYE tax only); `state_pension`,
`benefit`, `other_untaxed` (untaxed — state pension tax is collected via your
other tax codes); `self_employed` (tax + Class 4 NI + student loan on profit, or a
set-aside %); `rental` (set-aside %).

**Refresh** (`IncomeService.refresh_forecasts(source_id)`): re-prices every
*unsettled* forecast of the source from its terms, removes forecasts outside its
dates, and fills up to the horizon. Settled rows (paid, actual payslip entered, or
paid transaction) are never changed. It runs automatically after saving a source,
adding/removing a change, and when the Payslips page tops up the horizon.
**Tools → Refresh all forecasts** (`refresh_all_forecasts`) re-runs it for every
source you can see, e.g. after new tax rates are loaded.

**Manual overrides:** edit a payslip (choose manual figures) or **Enter actual**;
that row is then settled and kept. A source can also keep the legacy fixed
monthly figures (`use_manual_deductions`); those sources ignore yearly rises and
the timeline until switched to "calculated".

**Retirement:** set an end date on the job (**End income** on the source page)
and add a `pension` source starting the day after. The plan stops each source at
its end date. Inactive or ended sources only contribute payslips actually saved.

**Expense integration:** a source can fold reimbursable expenses into its payday
(`fold_expenses`), as before.

### Routes (`blueprints/income/routes.py`)

| Route | Purpose |
|---|---|
| `GET /income` | Payslips list (tops forecasts up to the horizon) |
| `GET /income/recurring` | Sources, grouped by person |
| `GET/POST /income/recurring/add`, `/income/recurring/<id>/edit` | Source form with live preview (`static/js/income-source-form.js`) |
| `GET /income/recurring/<id>` | Source page: current terms, timeline, upcoming/recent payslips, end income, rebuild range, delete |
| `POST /income/recurring/<id>/changes`, `/income/changes/<id>/delete` | Add / remove a timeline change |
| `POST /income/refresh-forecasts` | Refresh all forecasts |
| `GET /income/plan?until=&person=` | Plan to a tax year (max 50 years) |

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

## Income Service (`services/finance/income_service.py`)

### Tax & NI Calculations
All deduction maths lives in one pure module, `services/finance/payroll_calculator.py`
(`calculate_payslip`, any frequency). Forecasts, record edits, the source preview and
the plan all use it, so they can't disagree. Rates come from `TaxSettings` for the pay
date's tax year (fallback: 2025-26 rUK rates); Scottish bands and student-loan
thresholds come from `uk_tax_tables.py`. When a year is missing from those tables the
latest known year is used and a warning is shown (2026-27 Scottish and student-loan
figures still need adding). The plan assumes thresholds stay frozen.

- **Tax year** runs 6 April → 5 April (`tax_year_for()`).
- **Tax codes:** `1257L` (and M/N/T suffixes), `0T`, `K475`, `BR`, `D0`, `D1`, `NT`,
  `C` (Welsh) prefix, `S` (Scottish, taxed with Scottish bands) and `W1/M1/X`
  emergency suffixes. Anything else is rejected.
- **Student loan:** plans 1, 2, 4, 5 and postgraduate, per pay period.
- **Bonus:** taxed at the marginal rate; pension taken from it only if pensionable.
- **Bands** apply to taxable income after the allowance (basic band is a fixed
  £37,700 width; additional rate above £125,140). The personal allowance tapers by
  £1 per £2 over £100k, but only for codes carrying the full standard allowance.
  K-code tax is capped at 50% of pay.
- **Pension:** employee pension is deducted once. Default scheme is salary sacrifice
  (reduces taxable and NI-able pay); the calculator also supports `net_pay` and
  `relief_at_source`.
- **Simplifications:** tax is annualised (annual ÷ periods, no cumulative PAYE);
  NI and student loan use per-period thresholds; 53-week years are not modelled;
  AVCs and "other" are post-tax deductions.

### Key Methods

#### `estimate_payslip(gross_annual, tax_code, pay_date, ...)`
Returns a `PayslipEstimate` (monthly gross, pension, tax, NI, take home, warnings).

#### `calculate_tax_and_ni(gross_annual, tax_code, pension_amount)`
Back-compat annual helper; `pension_amount` is treated as salary-sacrifice.

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

## Generation & Deletion Rules

- Generated records are matched to their template by `recurring_income_id` + pay date,
  so two jobs paid on the same day don't collide. Pay dates before the template's
  start date or after its end date are skipped.
- Forecast rows are saved at most 24 months ahead (the plan projects further in
  memory); a source and its timeline may span at most 60 years; delete/regenerate
  ranges are capped at 50 years. Older data may still hold forecasts beyond 24
  months: they stay until trimmed (Payslips → Tools → Trim forecasts).
- A record is **settled** if it is paid, has an actual payslip entered, or its
  transaction is paid. Deleting or regenerating a range removes unsettled forecasts
  *and their forecast transactions*; settled records (including future months you
  have overridden) are kept.
- **Ending a job or deleting a template** is stricter: only money actually received
  is kept (paid, paid transaction, or an actual payslip dated today or earlier).
  Every future forecast goes. Kept history is detached from a deleted template, and
  folded expense groups revert to "separate".
- Older versions flagged template-generated forecasts as actuals and left a deleted
  template's forecasts behind. Migration `c4f8a2d6e0b1` clears the wrong flag on
  linked future forecasts. `flask maintenance purge-orphan-income-forecasts`
  previews leftover detached forecasts (flagged, or a run of 3+ for the same
  person/source); re-run with `--apply` to delete them. See `deployment/README.md`.
- Only the person an income belongs to can make it private (or the household owner,
  for income not tied to a member's name). Template visibility cascades to its
  generated records.

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
from services.finance.income_service import IncomeService
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
from services.finance.income_service import IncomeService

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
