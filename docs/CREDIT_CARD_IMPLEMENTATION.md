# Credit Card System

## Overview
Current notes on credit-card management, generated transactions, and linked bank transactions.

## Current Features

### Credit Card Management

**Features:**
- Card management interface at `/credit-cards`
- Add/edit cards with promotional period tracking
- View all cards with summary statistics
- Individual card detail views with transaction history
- Delete confirmation modals
- Auto-calculate monthly APR from annual APR

**Relevant files:**
- `blueprints/credit_cards/__init__.py` - Blueprint registration
- `blueprints/credit_cards/routes.py` - All CRUD routes
- `templates/credit_cards/index.html` - Cards list
- `templates/credit_cards/form.html` - Add/edit form
- `templates/credit_cards/detail.html` - Card details

**Routes:**
- `GET /credit-cards` - List all cards
- `GET /credit-cards/add` - Add new card form
- `POST /credit-cards/add` - Create card
- `GET /credit-cards/<id>/edit` - Edit card form
- `POST /credit-cards/<id>/edit` - Update card
- `POST /credit-cards/<id>/delete` - Delete card
- `GET /credit-cards/<id>` - View card details
- `POST /credit-cards/<id>/generate-future` - Regenerate future transactions for one card
- `POST /credit-cards/generate-all-future` - Regenerate future transactions for all active cards
- `GET /credit-cards/<id>/transaction/<txn_id>/edit` - Edit credit card transaction
- `POST /credit-cards/<id>/transaction/<txn_id>/delete` - Delete transaction and clean up its linked records through the service
- `POST /credit-cards/<id>/payment/<txn_id>/edit` - Edit a card payment
- `POST /credit-cards/transaction/<txn_id>/toggle-paid` - Toggle paid status
- `POST /credit-cards/transaction/<txn_id>/toggle-fixed` - Lock or unlock a transaction
- `GET/POST /credit-cards/transfer` - Create a balance transfer

---

### Statement Interest

**Features:**
- Interest calculation respects purchase and balance-transfer APRs and their promotional periods
- Automatic category creation
- Records APR used for each transaction
- Tracks promotional rate status
- Generates interest on each card's statement date

**Relevant files:**
- `services/finance/credit_card_service.py` - Business logic
- Enhanced `models/credit_cards.py` - Promotional date fields
- Enhanced `models/credit_card_transactions.py` - APR tracking fields

---

### Payments

The card balance convention is negative for debt. The model's payment calculation
returns zero when no debt is owed; otherwise it caps a configured payment at the
debt balance, or uses the minimum-payment percentage when no fixed amount is set.
The service stores the card-side payment as a positive amount.

**Simplified calculation:**
```python
def calculate_actual_payment(self):
    if not self.current_balance or self.current_balance >= 0:
        return 0.0
    if not self.set_payment:
        return self.calculate_minimum_payment()
    return round(min(float(self.set_payment), abs(float(self.current_balance))), 2)

def generate_payment_transaction(card_id, payment_date):
    # Service creates a positive card-side payment.
    # A configured bank account can receive a linked debit transaction.
```

**Features:**
- Payment calculation uses the card's configured amount or minimum-payment logic
- Configurable offset from statement date (the current route defaults to 14 days)
- Automatic payment generation
- Creates positive card-side payments, which reduce debt
- **Vendor auto-creation** - A vendor matching the card name is used for the linked bank transaction
- **Linked to bank account** - Creates a corresponding bank transaction when a payment account is configured

**Payment Logic:**
- If `set_payment` not configured → use minimum payment %
- If `set_payment` > balance → pay full balance
- If `set_payment` < balance → pay set amount

---

---

### Consolidated Transaction View

**Features:**
- Unified view combining all transaction sources:
  - Bank account transactions
  - Credit card transactions
  - Loan payments
- Summary cards: Total inflows, outflows, net position
- Filter by:
  - Source type (bank/credit card/loan/all)
  - Category
  - Date range
- Color-coded source badges
- Transaction type badges
- Export to CSV
- Print functionality

**Relevant files:**
- `blueprints/transactions/routes.py` - Consolidated route logic
- `blueprints/transactions/templates/consolidated.html` - UI template
- Updated `blueprints/transactions/routes.py` - Added imports and route
- Updated `templates/base.html` - Navigation link

**Route:**
- `GET /transactions/consolidated` - Consolidated view

---

## Key Features

### 0% Promotional Tracking
- Dual system:
  1. Active dates on card (`purchase_0_percent_until`, `balance_transfer_0_percent_until`)
  2. Historical records (`CreditCardPromotion` model)
- Interest automatically = £0 when 0% active
- Visual badges on cards list
- Alert on card detail page when promotional offers active

### Balance Calculation
```python
def recalculate_card_balance(credit_card_id):
    # Transaction running balances include paid and unpaid transactions.
    # Card current_balance and available_credit use paid transactions only.
```

### Future Transaction Generation
- Monthly loop using `relativedelta`
- Checks for existing transactions (prevents duplicates)
- Uses each card's statement date
- Uses the configured payment offset (the current route defaults to 14 days)
- Generates through the end date selected by the user

### Transaction Types
- **Purchase, Interest, Fee** - Negative amounts increase debt
- **Payment, Reward** - Positive amounts reduce debt
- **Balance Transfer** - Follow the direction and sign convention of the specific transfer flow

### Transaction Deletion
**Individual Delete:**
- Delete button on credit card detail page for unpaid transactions
- Automatically deletes linked bank transaction
- Recalculates both credit card and bank account balances
- Confirmation required before deletion

**Cascading Deletes (Bidirectional):**
- Deleting credit card payment → deletes linked bank transaction
- Deleting bank transaction → deletes linked credit card payment
- Ensures data integrity across linked transactions

### Locked Statement Payment Generation
When regenerating transactions:
1. **Non-fixed transactions** (is_fixed=False) are deleted and regenerated
2. **Fixed/locked transactions** (is_fixed=True) are preserved
3. **Locked statement check**: For each locked Interest transaction:
   - Calculates historical balance at statement date
   - If debt exists (balance < 0) and no payment exists for payment date
   - Generates missing payment transaction
   - Uses absolute value of balance for payment amount
4. **Credit card balance convention**: Negative balance = debt owed

**Example:** If a locked statement has an outstanding debt and its payment is missing, regeneration can create the payment for the configured payment date.

---

## Database Schema

### Credit Cards Table (Enhanced)
```sql
- id
- family_id
- owner_id (nullable; shared when NULL)
- card_name
- credit_limit
- current_balance
- available_credit
- annual_apr
- monthly_apr (calculated from annual)
- min_payment_percent
- set_payment (user's configured monthly payment)
- statement_date (day of month)
- start_date
- default_payment_account_id
- is_active
- purchase_0_percent_until (NEW)
- balance_transfer_0_percent_until (NEW)
```

### Credit Card Transactions Table (Enhanced)
```sql
- id
- family_id
- credit_card_id
- date
- item (description)
- head_budget
- sub_budget
- category_id
- amount
- balance (running balance)
- transaction_type
- is_paid
- is_fixed
- vendor_id
- applied_apr (NEW - APR used for this transaction)
- is_promotional_rate (NEW - was 0% active?)
- bank_transaction_id (NEW - links to bank payment)
- statement_id (links a generated payment to its statement-interest transaction)
- linked_cc_transaction_id (links the other side of a balance transfer)
- subscription_id (links a generated subscription transaction)
```

### Credit Card Promotions Table (NEW)
```sql
- id
- family_id
- credit_card_id
- promotion_type (purchase/balance_transfer)
- apr_rate (0.0 for 0% offers)
- start_date
- end_date
- notes
```

---

## Usage Guide

### 1. View Cards
Navigate to: `http://localhost:5000/credit-cards`

You'll see:
- Summary: Total limit, balance, available, payments, weighted APR
- Active cards with their current balances
- 0% promotional badges
- Statement dates
- Active status

### 2. Generate Future Transactions
Click "Generate Future Transactions" button

**Options:**
- Select an end date
- Generate for all active cards, or use an individual card's detail page

**Result:**
- Creates monthly Interest transactions on statement dates
- Creates monthly Payment transactions at the configured offset (14 days by default in the current route)
- Interest = £0 if 0% promotional period active
- Payment is capped at the debt owed; if no fixed amount is configured, the minimum-payment percentage is used

### 3. View Individual Card
Click on any card to see:
- Current balance, limit, payment, status
- Active promotional offers alert
- Transaction statistics (purchases, payments, interest totals)
- Full transaction history with running balances
- Generate future for single card

### 4. View Consolidated Transactions
Navigate to: `http://localhost:5000/transactions/consolidated`

**Features:**
- See all transactions from all sources
- Filter by source type (bank/credit card/loan)
- Filter by category
- Filter by date range
- Summary cards show totals
- Color-coded by source
- Export to CSV

---

## Next Steps

The current payment workflow already creates and links the bank-side
transaction when a payment account is configured. Loan, vehicle, pension, planned-transaction, and income workflows
are documented in their domain guides; they are not pending modules in this
credit-card guide.

---

## Technical Notes

### Service Layer Pattern
All business logic is isolated in `services/finance/credit_card_service.py`:
- `calculate_interest()` - Interest calculation with 0% override
- `generate_statement_interest()` - Create interest transaction
- `generate_payment_transaction()` - Create payment transaction
- `generate_future_statements()` - Batch generate interest
- `generate_future_payments()` - Batch generate payments
- `generate_all_future_transactions()` - Process all cards

**Benefits:**
- Easy to test
- Reusable across routes
- Centralized business rules
- Clean separation of concerns

### Promotional Period Logic
```python
def get_current_purchase_apr(self, date):
    if self.purchase_0_percent_until and date <= self.purchase_0_percent_until:
        return 0.0  # 0% promotional period active
    return self.monthly_apr
```

### Payment Calculation
```python
def calculate_actual_payment(self):
    if not self.current_balance or self.current_balance >= 0:
        return 0.0
    if not self.set_payment:
        return self.calculate_minimum_payment()
    return round(min(float(self.set_payment), abs(float(self.current_balance))), 2)
```

### Duplicate Prevention
```python
# Check if transaction already exists before creating
existing = family_query(CreditCardTransaction).filter_by(
    credit_card_id=card.id,
    date=current_date,
    transaction_type='Interest'
).first()

if not existing:
    generate_statement_interest(card.id, current_date, commit=False)
```

---

## Success Criteria ✅

The current implementation includes:

1. ✅ **Credit Card Management UI**
   - Add/edit cards
   - View all cards with statistics
   - Individual card details
   - Promotional period tracking

2. ✅ **Auto-Generate Statement Interest**
   - Calculates interest: `balance × (monthly_apr / 100)`
   - Respects 0% promotional periods (interest = £0)
   - Records APR used
   - Auto-creates categories

3. ✅ **Auto-Generate Payments**
   - Payment calculation: capped at the outstanding debt, or the minimum-payment percentage when no fixed amount is configured
   - Configurable offset from statement
   - Batch generation to any date

4. **Historical card-data import**
   - A one-off historical import script remains in `scripts/imports/`
   - It is not a routine setup step and should be reviewed before reuse

5. ✅ **Consolidated Transaction View**
   - Combines bank, credit card, loan transactions
   - Filters by source, category, date
   - Summary statistics
   - Export to CSV
   - Single comprehensive financial view

---

The consolidated transaction view brings supported transaction sources into
one view. Projection results depend on the data and selected forecast period;
they should not be treated as a guarantee of future balances.

---

## Files Modified/Created

### New Files (14)
1. `blueprints/credit_cards/__init__.py`
2. `blueprints/credit_cards/routes.py`
3. `templates/credit_cards/index.html`
4. `templates/credit_cards/form.html`
5. `templates/credit_cards/detail.html`
6. `services/finance/credit_card_service.py`
7. `blueprints/transactions/routes.py` (consolidated route)
8. `blueprints/transactions/templates/consolidated.html`

### Modified Files (5)
1. `models/credit_cards.py` - Added promotional fields and methods
2. `models/credit_card_transactions.py` - Added APR tracking fields
3. `models/__init__.py` - Added CreditCardPromotion
4. `app.py` - Registered credit_cards blueprint
5. `templates/base.html` - Added Credit Cards and Consolidated links
6. `blueprints/transactions/routes.py` - Added consolidated route
7. `blueprints/transactions/templates/transactions.html` - Added consolidated button

---

## Database Migration Required

After import, run migration to add new fields:

```bash
flask db migrate -m "Add credit card promotional tracking"
flask db upgrade
```

**New Fields:**
- `credit_cards.purchase_0_percent_until`
- `credit_cards.balance_transfer_0_percent_until`
- `credit_card_transactions.applied_apr`
- `credit_card_transactions.is_promotional_rate`
- `credit_card_transactions.bank_transaction_id`

**New Table:**
- `credit_card_promotions`

---

## Project Status

**Complete:** 5/5 Tasks
**Ready For:** Production testing and data import
**Next Phase:** Link to bank accounts, import historical transactions, build remaining modules

🎉 **Credit Card System COMPLETE!**
