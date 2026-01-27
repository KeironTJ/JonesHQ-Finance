# Database Schema Design for JonesHQ Finance

## Overview
This document outlines the database schema designed to migrate your Excel-based personal finance tracking system to a Flask web application with SQLAlchemy ORM.

## Core Financial Models

### 1. **Account** (accounts.py)
Represents bank accounts (Joint Account, Second Bank Account, etc.)
- `name`: Account name
- `account_type`: Joint, Personal, Savings
- `balance`: Current balance
- `is_active`: Whether account is active

**Relationships:**
- One-to-many with `Transaction`
- One-to-many with `Balance` (historical balances)

### 2. **Category** (categories.py)
Hierarchical budget categories matching your Excel "Head Budget" and "Sub Budget" structure
- `head_budget`: Main category (Family, General, Home, Income, etc.)
- `sub_budget`: Sub category (Hobbies/Interests, General Spending, etc.)
- `parent_id`: For hierarchical categories
- `category_type`: Income, Expense, Transfer

**Relationships:**
- Self-referential (parent/children categories)
- One-to-many with `Transaction`
- One-to-many with `Budget`
- One-to-many with `Vendor` (as default_category)

### 2a. **Vendor** (vendors.py)
Standardized vendor/merchant tracking for consistent transaction categorization
- `name`: Unique vendor name (indexed, e.g., "Tesco", "Amazon")
- `vendor_type`: Category of vendor (Grocery, Fuel, Restaurant, Online, Utility, etc.)
- `default_category_id`: Default category for transactions with this vendor
- `website`: Vendor's website URL
- `notes`: Additional information
- `is_active`: Whether vendor is active (allows deactivation without deletion)
- `created_at`, `updated_at`: Timestamps

**Relationships:**
- Many-to-one with `Category` (default category)
- One-to-many with `Transaction`

### 3. **Transaction** (transactions.py)
Main transaction table combining data from JOINTACCOUNT and SECONDBANKACCOUNT sheets
- `account_id`: Link to account
- `category_id`: Link to category (Head Budget + Sub Budget)
- `vendor_id`: Link to vendor/merchant (standardized names)
- `amount`: Transaction amount
- `transaction_date`: Date of transaction
- `description`: Transaction description
- `item`: Specific item/details (e.g., "Weekly shop" when vendor=Tesco)
- `assigned_to`: Person (Keiron, Emma, Ivy, etc.)
- `payment_type`: BACS, Direct Debit, Card Payment, Transfer
- `running_balance`: Balance after transaction
- `is_paid`: Payment status
- `credit_card_id`: Optional link to credit card (if paid by card)
- `loan_id`: Optional link to loan (if loan payment)
- `year_month`: For reporting (2026-01)
- `week_year`: For reporting (03-2026)
- `day_name`: Day of week

**Relationships:**
- Many-to-one with `Account`
- Many-to-one with `Category`
- Many-to-one with `Vendor` (optional)
- Many-to-one with `CreditCard` (optional)
- Many-to-one with `Loan` (optional)

## Credit Card Models

### 4. **CreditCard** (credit_cards.py)
From your CREDIT CARD HEADER sheet
- `card_name`: Barclaycard, M&S, Natwest
- `annual_apr`: Annual interest rate %
- `monthly_apr`: Monthly interest rate %
- `min_payment_percent`: Minimum payment %
- `credit_limit`: Credit limit
- `set_payment`: Regular payment amount
- `statement_date`: Day of month for statement
- `current_balance`: Current balance (negative = owe money)
- `available_credit`: Available credit
- `is_active`: Active status

**Relationships:**
- One-to-many with `CreditCardTransaction`

### 5. **CreditCardTransaction** (credit_card_transactions.py)
From your CREDIT CARD TRANSACTIONS sheet
- `credit_card_id`: Which card
- `date`: Transaction date
- `head_budget`, `sub_budget`: Category
- `item`: Merchant
- `transaction_type`: Purchase, Payment, Interest, Rewards
- `amount`: Amount (negative for purchases, positive for payments)
- `balance`: Card balance after transaction
- `credit_available`: Available credit after transaction

## Loan & Mortgage Models

### 6. **Loan** (loans.py)
From your LOANS HEADER sheet
- `name`: EE, JN Bank, Loft Loan, Creation, Zopa
- `loan_value`: Original loan amount
- `current_balance`: Current outstanding balance
- `annual_apr`, `monthly_apr`: Interest rates
- `monthly_payment`: Regular payment amount
- `calculated_payment`: Calculated vs actual
- `start_date`, `end_date`: Loan term
- `term_months`: Loan term in months
- `is_active`: Active status

**Relationships:**
- One-to-many with `LoanPayment`
- One-to-many with `Transaction` (for actual payments)

### 7. **LoanPayment** (loan_payments.py)
From your LOAN TRANSACTIONS sheet
- `loan_id`: Which loan
- `date`: Payment date
- `period`: Payment number
- `opening_balance`: Balance at start
- `payment_amount`: Payment made
- `interest_charge`: Interest portion
- `amount_paid_off`: Principal reduction
- `closing_balance`: Balance after payment
- `is_paid`: Payment status

### 8. **Mortgage** (mortgage.py)
From your HOUSE sheet
- `property_address`: Property address
- `principal`: Original mortgage amount
- `current_balance`: Current balance
- `interest_rate`: Annual interest rate %
- `fixed_payment`: Regular payment
- `optional_payment`: Extra payments
- `property_valuation`: Current property value
- `equity_amount`, `equity_percent`: Equity calculations
- `term_years`: Mortgage term

**Relationships:**
- One-to-many with `MortgagePayment`

### 9. **MortgagePayment** (mortgage_payments.py)
Monthly mortgage payment history
- `mortgage_id`: Which mortgage
- `date`: Payment date
- `mortgage_balance`: Balance
- `fixed_payment`, `optional_payment`: Payments
- `interest_charge`: Interest paid
- `equity_paid`: Principal paid
- `property_valuation`: Property value at time
- `equity_amount`, `equity_percent`: Equity tracking

## Vehicle & Fuel Models

### 10. **Vehicle** (vehicles.py)
From your FUEL LOG HEADER sheet
- `name`: Vauxhall Zafira, Audi A6
- `registration`: VRN (MV15LZJ, WF60RKA)
- `tank_size`: Fuel tank size in gallons
- `fuel_type`: Diesel, Petrol
- `is_active`: Active status

**Relationships:**
- One-to-many with `FuelRecord`
- One-to-many with `Trip`

### 11. **FuelRecord** (fuel.py)
From your FUEL LOG Table
- `vehicle_id`: Which vehicle
- `date`: Fill-up date
- `price_per_litre`: Fuel price (pence)
- `mileage`: Odometer reading
- `cost`: Total cost
- `gallons`: Gallons purchased
- `actual_miles`: Miles since last fill
- `actual_cumulative_miles`: Total tracked miles
- `mpg`: Calculated MPG
- `price_per_mile`: Cost per mile
- `last_fill_date`: Previous fill date

**Relationships:**
- Many-to-one with `Vehicle`
- One-to-many with `Trip` (trips between fills)

### 12. **Trip** (trips.py)
From your CAR FUEL TRIPS sheet
- `vehicle_id`: Which vehicle
- `date`: Trip date
- `personal_miles`: Personal mileage
- `business_miles`: Business mileage
- `total_miles`: Total miles
- `cumulative_total_miles`: Running total
- `journey_description`: Daily Commute, GIRLS DANCING, etc.
- `approx_mpg`: Estimated MPG
- `trip_cost`: Estimated cost
- `fuel_log_entry_id`: Link to fuel fill

**Relationships:**
- Many-to-one with `Vehicle`
- Many-to-one with `FuelRecord` (optional)

## Expense & Income Models

### 13. **Expense** (expenses.py)
From your WORK EXPENSES sheet
- `date`: Expense date
- `description`: Tetrad, Garner Hotel, etc.
- `expense_type`: Fuel, Hotel, Food
- `credit_card_id`: Card used (optional)
- `covered_miles`: Business miles
- `rate_per_mile`: Mileage rate (£0.45)
- `total_cost`: Total expense
- `cumulative_miles_ytd`: Year-to-date miles
- `paid_for`, `submitted`, `reimbursed`: Status tracking

**Relationships:**
- Many-to-one with `CreditCard` (optional)

### 14. **Income** (income.py)
From your INCOME sheet - comprehensive payslip tracking
- `pay_date`: Payment date
- `tax_year`: Tax year (2022-2023)
- `gross_annual_income`, `gross_monthly_income`: Gross pay
- `employer_pension_percent`, `employee_pension_percent`: Pension rates
- `employer_pension_amount`, `employee_pension_amount`: Pension amounts
- `total_pension`: Total pension contribution
- `adjusted_monthly_income`, `adjusted_annual_income`: After pensions
- `tax_code`: Tax code
- `income_tax`, `national_insurance`: Deductions
- `avc`: Additional Voluntary Contributions
- `take_home`: Net pay
- `estimated_annual_take_home`: Estimated annual

## Childcare Model

### 15. **ChildcareRecord** (childcare.py)
From your CHILDCARE sheet
- `date`: Date
- `child_name`: Michael, Emily, Ivy, Brian
- `service_type`: AM, PM1, PM2, Lunch, Breakfast Club, School Dinner
- `cost`: Cost for service
- `year_group`: Year 4, Nursery, etc.
- `provider`: Childcare provider

## Pension & Net Worth Models

### 16. **Pension** (pensions.py)
Pension account header
- `provider`: Peoples Pension, Aviva, Aegon, Scottish Widows
- `current_value`: Current value
- `contribution_rate`: Employee contribution %
- `employer_contribution`: Employer contribution %
- `is_active`: Active status

**Relationships:**
- One-to-many with `PensionSnapshot`

### 17. **PensionSnapshot** (pension_snapshots.py)
From your PENSIONS sheet - monthly pension values
- `pension_id`: Which pension
- `review_date`: Snapshot date
- `value`: Value at date
- `growth_percent`: % growth since last snapshot

### 18. **NetWorth** (networth.py)
From your NETWORTH sheet
- `date`: Snapshot date
- `year_month`: Month identifier
- `is_active_month`: Active flag
- **Assets:**
  - `cash`, `savings`, `house_value`, `pensions_value`
  - `total_assets`
- **Liabilities:**
  - `credit_cards`, `loans`, `mortgage`
  - `total_liabilities`
- **Tracking:**
  - `net_worth`: Total net worth
  - `one_month_track`: % change from previous month
  - `three_month_track`: % change from 3 months ago

## Supporting Models

### 19. **Budget** (budgets.py)
Budget tracking per category
- `category_id`: Which category
- `amount`: Budget amount
- `period_start`, `period_end`: Budget period

**Relationships:**
- Many-to-one with `Category`

### 20. **PlannedTransaction** (planned.py)
Future planned transactions
- `category_id`: Category
- `amount`: Amount
- `planned_date`: When planned
- `is_recurring`: If recurring
- `frequency`: Frequency if recurring

### 21. **Balance** (balances.py)
Historical account balances
- `account_id`: Which account
- `balance`: Balance amount
- `balance_date`: Date of balance

## Key Design Decisions

### 1. **Normalized Structure**
- Separate tables for different entity types rather than one large transaction table
- Relationships use foreign keys for referential integrity
- Categories use hierarchical structure (parent/child)

### 2. **Calculated vs Stored Fields**
Some fields like `running_balance`, `mpg`, `equity_percent` are stored rather than calculated on-the-fly for:
- Historical accuracy
- Performance
- Matching your Excel formulas

### 3. **Temporal Fields**
Fields like `year_month`, `week_year`, `day_name` are stored for easy filtering and reporting, matching your Excel structure.

### 4. **Status Tracking**
Boolean fields for status (`is_paid`, `is_active`, `submitted`, `reimbursed`) to track workflow states.

### 5. **Flexibility**
- `assigned_to` field allows tracking per-person expenses
- `description` and `item` fields separate for better categorization
- Optional foreign keys (nullable) for flexibility

## Migration Strategy

### Phase 1: Core Data
1. Create accounts
2. Import categories (matching your hierarchy)
3. Import basic transactions

### Phase 2: Credit & Debt
1. Import credit cards
2. Import credit card transactions
3. Import loans and loan payments
4. Import mortgage and payments

### Phase 3: Assets & Tracking
1. Import vehicles and fuel records
2. Import trips
3. Import expenses
4. Import childcare records

### Phase 4: Long-term Tracking
1. Import income history
2. Import pensions and snapshots
3. Import net worth snapshots

## Benefits Over Excel

1. **Data Integrity**: Foreign key constraints prevent orphaned records
2. **Scalability**: Database can handle millions of records
3. **Concurrent Access**: Multiple users can access simultaneously
4. **Advanced Queries**: Complex reporting with SQL/SQLAlchemy
5. **APIs**: Easy to build APIs for mobile apps
6. **Backups**: Automated database backups
7. **Validation**: Model-level validation before saving
8. **Relationships**: Automatic handling of related data

## Next Steps

1. Review and approve the schema design
2. Create database migration files (using Flask-Migrate/Alembic)
3. Build data import scripts from Excel
4. Create service layer for business logic
5. Build REST API endpoints
6. Create UI for data entry and reporting
