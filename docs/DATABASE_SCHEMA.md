# Database Schema Design for JonesHQ Finance

## Overview
This document summarizes the implemented SQLAlchemy schema for the Flask
application. The model modules and Flask-Migrate revision history are
authoritative; this guide is a domain-oriented reference rather than a
complete generated table catalog.

The application uses SQLite by default for local development and tests.
Production runs on PostgreSQL 17 (configured via `DATABASE_URL` or
`SQLALCHEMY_DATABASE_URI`); migrations must work on both backends. Most household domain records carry `family_id` and are queried through the
family-scoped helpers. A separate, optional `owner_id` controls within-family
privacy on supported records; see the application instructions and model code
for the exact models and inherited visibility rules. Service-wide and
account-owned records are not household financial data.

## Configuration and Personal Preferences

- `Settings` stores family-scoped functional rules and defaults, including payday,
  credit-card generation, expense workflow and the shared net-worth timeline start.
  Household owners edit each area independently; saving one never resets another.
- `User.preferences` is a nullable JSON object containing allowlisted
  dashboard and category/vendor display preferences, plus personal appearance. Reads and writes use only the
  authenticated user; members do not need household-settings permission.
- `User.default_account_id` remains the personal dashboard account. Submitted IDs
  must identify an active account visible to the current user and family.
- `appearance.palette` accepts `blue` (default), `graphite`, `green`, `pink`, `sky`
  or `purple`; `appearance.mode` accepts `light` (default), `dark` or `auto`.
  Both are saved atomically to `User.preferences`, with no new columns or migration.
  Signed-in pages use account appearance before paint; `jhq-theme` browser storage
  applies only to signed-out display mode and never overrides an account.
- Migration `f2a4c6e8b0d1` copies existing household display defaults to each attached
  user's initial preferences without altering financial rules. Legacy rows remain
  for downgrade compatibility but are no longer read or written by preference
  screens. New users receive application display defaults. Downgrading removes
  personal display choices and restores the original household defaults.

## Passkey Authentication

- `user_passkeys`: account-owned WebAuthn credentials (unique credential ID,
  public key, signature counter, display name, created/last-used timestamps).
  Credentials follow the user across household changes; they are not family data.
- `passkey_challenges`: hashed browser flow token, challenge bytes, purpose,
  optional bound user, five-minute expiry and login/registration context.
  Consumed once in the database; expired rows are removed when starting flows.
- `user_sessions.authentication_method`: persisted sign-in/confirmation method,
  used to distinguish a verified passkey session from password-only fallback.
- Migration `b9e4a7c1d6f2` adds these tables and column without changing financial
  records. User-account deletion explicitly removes credentials and challenges.

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
- `family_id`: Household security boundary
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
- `is_fixed`, `is_forecasted`: Lock and forecast flags
- `credit_card_id`, `loan_id`: Optional related finance records
- `linked_transaction_id`: Paired account-to-account transfer
- `subscription_id`: Source recurring subscription, if generated
- `claim_group`, `reimbursement_group_id`: Expense reimbursement tracking
- `payday_period`: Assigned payday period
- `year_month`: For reporting (2026-01)
- `week_year`: For reporting (03-2026)
- `day_name`: Day of week
- `created_at`, `updated_at`: Audit timestamps

**Relationships:**
- Many-to-one with `Account`
- Many-to-one with `Category`
- Many-to-one with `Vendor` (optional)
- Many-to-one with `CreditCard` (optional)
- Many-to-one with `Loan` (optional)

## Credit Card Models

### 4. **CreditCard** (credit_cards.py)
From your CREDIT CARD HEADER sheet
- `family_id`, `owner_id`: Household boundary and optional within-family privacy
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

The same module defines `CreditCardPromotion` for dated promotional APR offers.

### 5. **CreditCardTransaction** (credit_card_transactions.py)
From your CREDIT CARD TRANSACTIONS sheet
- `family_id`: Household security boundary
- `credit_card_id`: Which card
- `category_id`, `vendor_id`: Optional classification and vendor links
- `date`: Transaction date
- `head_budget`, `sub_budget`: Category
- `item`: Merchant
- `assigned_to`: Optional family member or custom assignment label (same names as bank transactions)
  - Available when adding/editing a card transaction; recurring entries retain the assignment.
  - Shown in the card transaction list. Existing transactions remain unassigned.
- `vendor_id`: Optional vendor; the add/edit form supports quick-add without leaving the page.
- `transaction_type`: Purchase, Payment, Interest, Rewards
- `amount`: Amount (negative for purchases, positive for payments)
- `balance`: Card balance after transaction
- `credit_available`: Available credit after transaction
- `bank_transaction_id`: Linked bank-side payment, when applicable
- `statement_id`, `linked_cc_transaction_id`: Statement and paired balance-transfer links
- `subscription_id`: Source subscription for generated card charges
- `is_paid`, `is_fixed`: Reconciliation and regeneration controls
- `applied_apr`, `is_promotional_rate`: Interest audit fields

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
Legacy-compatible mortgage record; current property workflows use mortgage products.
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

`MortgageProduct` and `MortgageSnapshot` model product terms over time,
including current and future products, balances, and snapshots. Properties are
modeled separately in `property.py`.

## Vehicle & Fuel Models

### 10. **Vehicle** (vehicles.py)
From your FUEL LOG HEADER sheet
- `family_id`, `owner_id`: Household boundary and optional within-family privacy
- `name`: Vauxhall Zafira, Audi A6
- `make`, `model`, `year`: Vehicle identity
- `registration`: VRN (MV15LZJ, WF60RKA)
- `tank_size`: Fuel tank size in gallons
- `fuel_type`: Diesel, Petrol
- `refuel_threshold_pct`, `starting_mileage`, `fuel_account_id`: Forecasting and transaction settings
- `purchase_date`, `purchase_price`: Vehicle purchase information
- `is_active`: Active status

**Relationships:**
- One-to-many with `FuelRecord`
- One-to-many with `Trip`

### 11. **FuelRecord** (fuel.py)
From your FUEL LOG Table
- `family_id`: Household security boundary
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
- `is_partial_fill`: Whether this record represents a partial fill
- `linked_transaction_id`: Related bank transaction, when present

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
- `family_id`, `owner_id`: Household boundary and optional private visibility
- `date`: Expense date
- `description`: Tetrad, Garner Hotel, etc.
- `expense_type`: Fuel, Hotel, Food
- `credit_card_id`: Card used (optional)
- `account_id`: Direct-payment account, when applicable
- `credit_card_transaction_id`, `bank_transaction_id`: Linked payment records
- `covered_miles`: Business miles
- `rate_per_mile`: Mileage rate (£0.45)
- `total_cost`: Total expense
- `days`, `cumulative_miles_ytd`, `vehicle_registration`: Mileage claim data
- `claim_group`, `reimbursement_group_id`, `payday_period`: Claim grouping and period
- `income_id`: Payslip receiving a folded reimbursement
- `paid_for`, `submitted`, `reimbursed`: Status tracking

`ExpenseCalendarEntry` stores dated calendar items; `ExpenseReimbursementGroup`
selects whether a claim is paid as a separate transaction or folded into a
linked recurring-income payslip.

### 14. **Income** (income.py)
From your INCOME sheet - comprehensive payslip tracking
- `family_id`, `member_id`, `owner_id`: Household, linked member, and optional private visibility
- `pay_date`: Payment date
- `pay_frequency`, `bonus`, `student_loan`: Pay-period and pay inputs
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
- `deposit_account_id`, `transaction_id`, `recurring_income_id`: Linked records
- `expense_reimbursement_total`: Expenses folded into this payslip's deposit

`RecurringIncome` stores recurring pay-source schedules and calculation
settings. `IncomeChange` stores effective-dated salary, bonus, tax-code, and
pension changes for future forecasts.

## Childcare Models

### 15. **Childcare** (childcare.py)
The current workflow is based on children, activity types, dated activity
records, and monthly summaries:

- `Child`: Household child and default account/category/vendor settings
- `ChildActivityType`: Cost, provider, and weekly schedule for an activity
- `DailyChildcareActivity`: Whether an activity occurred, with optional cost override
- `MonthlyChildcareSummary`: Monthly total and linked account transaction

`ChildcareRecord` remains as a legacy-compatible record; it is not the primary
model used by the current childcare workflow.

### Legacy `ChildcareRecord`
- `date`: Date
- `child_name`: Michael, Emily, Ivy, Brian
- `service_type`: AM, PM1, PM2, Lunch, Breakfast Club, School Dinner
- `cost`: Cost for service
- `year_group`: Year 4, Nursery, etc.
- `provider`: Childcare provider

The same module also contains the current `Child`, `ChildActivityType`,
`DailyChildcareActivity`, and `MonthlyChildcareSummary` models used by the
childcare workflows.

## Pension & Net Worth Models

### 16. **Pension** (pensions.py)
Pension account header
- `family_id`, `member_id`, `owner_id`: Household, linked member, and optional private visibility
- `provider`: Peoples Pension, Aviva, Aegon, Scottish Widows
- `current_value`: Current value
- `contribution_rate`: Employee contribution %
- `employer_contribution`: Employer contribution %
- `retirement_age`, `monthly_contribution`, `projected_value_at_retirement`: Projection inputs/results
- `is_active`: Active status

**Relationships:**
- One-to-many with `PensionSnapshot`

### 17. **PensionSnapshot** (pension_snapshots.py)
From your PENSIONS sheet - monthly pension values
- `pension_id`: Which pension
- `review_date`: Snapshot date
- `value`: Value at date
- `growth_percent`: % growth since last snapshot
- `is_projection`, `scenario_name`, `growth_rate_used`: Distinguish scenario projections from actual values
- `notes`: Snapshot or projection notes

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

The current net-worth timeline is calculated by `NetWorthService`; it combines
account balances, pension values, credit-card and loan liabilities, and
property valuations/mortgage products for the selected date. `Property` and
`PropertyValuationSnapshot` hold property details and actual/projected values.

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

### 22. **Subscription** (subscriptions.py)
Managed recurring bank-account or credit-card charges
- `family_id`: Family boundary
- `account_id` or `credit_card_id`: Exactly one charge destination; visibility follows the selected account or card owner
- `amount`, `frequency`, `start_date`, optional `end_date`: Charge rule
- `horizon_years`: Per-subscription forecast limit (1–5 years)
- `category_id`, `vendor_id`: Optional classification (category required for bank entries)
- `is_active`: Whether pending entries continue to be maintained

Generated pending entries reference the subscription from
`transactions.subscription_id` or
`credit_card_transactions.subscription_id`. Paid entries are retained when a
subscription changes or is cancelled.

### 23. **SubscriptionPriceChange** (subscriptions.py)
Dated charge amounts for upgrades, downgrades, discounts and price increases
- `family_id`, `subscription_id`: Household scope and parent subscription
- `amount`: New charge amount, stored as a negative expense
- `effective_date`: Applies to subscription charges on or after this date
- `note`: Optional plan or price-change description

One price change is allowed per subscription per effective date. Forecast
charges are previewed before a change is confirmed; paid and manually fixed
entries remain unchanged.

## Current Model and Table Inventory

This inventory is derived from the current SQLAlchemy models. It includes the
primary and supporting tables; model files remain authoritative for exact
columns, indexes, and constraints.

| Model module | Models / tables |
| --- | --- |
| `accounts.py` | `Account` / `accounts` |
| `balances.py` | `Balance` / `balances` |
| `categories.py` | `Category` / `categories` |
| `vendors.py` | `VendorType` / `vendor_types`, `Vendor` / `vendors` |
| `transactions.py` | `Transaction` / `transactions` |
| `credit_cards.py` | `CreditCard` / `credit_cards`, `CreditCardPromotion` / `credit_card_promotions` |
| `credit_card_transactions.py` | `CreditCardTransaction` / `credit_card_transactions` |
| `loans.py`, `loan_payments.py`, `loan_term_changes.py` | `Loan` / `loans`, `LoanPayment` / `loan_payments`, `LoanTermChange` / `loan_term_changes` |
| `mortgage.py`, `mortgage_payments.py` | `MortgageProduct` / `mortgage_products`, `Mortgage` / `mortgages`, `MortgageSnapshot` / `mortgage_snapshots`, `MortgagePayment` / `mortgage_payments` |
| `vehicles.py`, `fuel.py`, `trips.py` | `Vehicle` / `vehicles`, `FuelRecord` / `fuel_records`, `Trip` / `trips` |
| `expenses.py`, `expense_calendar.py`, `expense_reimbursement_group.py` | `Expense` / `expenses`, `ExpenseCalendarEntry` / `expense_calendar_entries`, `ExpenseReimbursementGroup` / `expense_reimbursement_groups` |
| `income.py`, `recurring_income.py`, `income_change.py` | `Income` / `income`, `RecurringIncome` / `recurring_income`, `IncomeChange` / `income_changes` |
| `childcare.py` | `Child` / `children`, `ChildActivityType` / `child_activity_types`, `DailyChildcareActivity` / `daily_childcare_activities`, `MonthlyChildcareSummary` / `monthly_childcare_summaries`, legacy `ChildcareRecord` / `childcare_records` |
| `pensions.py`, `pension_snapshots.py` | `Pension` / `pensions`, `PensionSnapshot` / `pension_snapshots` |
| `networth.py` | `NetWorth` / `net_worth` |
| `budgets.py`, `planned.py` | `Budget` / `budgets`, `PlannedTransaction` / `planned_transactions` |
| `subscriptions.py` | `Subscription` / `subscriptions`, `SubscriptionPriceChange` / `subscription_price_changes` |
| `property.py`, `property_valuation_snapshot.py` | `Property` / `properties`, `PropertyValuationSnapshot` / `property_valuation_snapshots` |
| `monthly_account_balance.py` | `MonthlyAccountBalance` / `monthly_account_balances` |
| `family.py` | `Family` / `families`, `FamilyInvite` / `family_invites`, `HouseholdInvite` / `household_invites` |
| `users.py` | `User` / `users`, `UserSession` / `user_sessions`, `SecurityEvent` / `security_events`, `UserRecoveryCode` / `user_recovery_codes` |
| `passkeys.py` | `UserPasskey` / `user_passkeys`, `PasskeyChallenge` / `passkey_challenges` |
| `family_assignment_labels.py` | `FamilyAssignmentLabel` / `family_assignment_labels` |
| `plans.py` | `Plan` / `plans`, `PlanItem` / `plan_items` |
| `settings.py`, `tax_settings.py`, `site_settings.py` | `Settings` / `settings`, `TaxSettings` / `tax_settings`, `SiteSettings` / `site_settings` |

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

## Historical Import Strategy

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

## Maintenance Notes

1. Update the relevant model module when changing a domain entity.
2. Generate and review a Flask-Migrate revision for schema changes.
3. Keep import and maintenance scripts under `scripts/`.
4. Add or update service logic before duplicating domain rules in routes.
5. Update this guide when a new domain or relationship changes the conceptual model.
