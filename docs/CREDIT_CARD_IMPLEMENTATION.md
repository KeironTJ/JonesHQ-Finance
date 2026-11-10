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
- `blueprints/finance/credit_cards/__init__.py` - Blueprint registration
- `blueprints/finance/credit_cards/routes.py` - All CRUD routes
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
- `blueprints/finance/transactions/routes.py` - Consolidated route logic
- `templates/transactions/consolidated.html` - UI template
- Updated `blueprints/finance/transactions/routes.py` - Added imports and route
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
Transaction running balances include paid and unpaid transactions. Card
`current_balance` and `available_credit` use paid transactions only. The
recalculation implementation is in
[`CreditCardTransaction`](../models/credit_card_transactions.py).

### Future Transaction Generation
- Future statements and payments refresh automatically after card transactions
  are added, edited, deleted, locked/unlocked or marked paid/unpaid. Recurring
  additions refresh once for the batch; balance transfers refresh both cards.
- Linked bank-payment edits, expense purchases/reimbursement payments and
  card-funded subscriptions also refresh the affected cards.
- Automatic refresh uses `default_generation_years` (10 years by default) and
  a 14-day payment offset, starting today. It requires an active card with a
  statement day. Cards without a statement day can still record transactions.
- Refresh runs within the caller's transaction, without intermediate commits.
  Generation failures propagate so callers can roll back and show an error.
- Manual **Generate Future** actions remain available, including custom end dates
  and payment-offset overrides submitted to the existing endpoints.
- Monthly loop using `relativedelta`
- Checks for existing transactions (prevents duplicates)
- Uses each card's statement date
- Uses the configured payment offset (the current route defaults to 14 days)
- Generates through the configured or manually selected end date, continuing
  past a payoff if later spending exists in that window
- Statement days 29-31 clamp to month-end and return to the chosen day next month

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
1. Only unpaid, unlocked future statement chains are replaced. Purchases, fees,
   rewards, transfers and standalone manual payments are not deleted.
2. A paid/locked statement, its payment, or its linked bank debit protects the
   entire chain, even if the statement itself is unlocked.
3. Protected statement months are left unchanged; later months are recalculated.
4. **Credit card balance convention**: Negative balance = debt owed

**Example:** Editing a generated bank payment locks its linked card payment.
Later refreshes retain that statement and payment and adjust subsequent payments.

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
Statements and payments now refresh automatically when card transactions change.
Use **Generate Future Transactions** for a manual refresh or a custom end date.

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

## Related Workflows

The current payment workflow already creates and links the bank-side
transaction when a payment account is configured. Loan, vehicle, pension, planned-transaction, and income workflows
are documented in their domain guides; they are not pending modules in this
credit-card guide.

---

## Technical Notes

### Service Layer Pattern
Card CRUD, manual transactions, and payment/bank synchronization live in
`services/finance/credit_card_service.py`. Statement lifecycle and interest
calculation live in `services/finance/credit_card_statement_service.py`:
- `calculate_interest()` - Interest calculation with 0% override
- `generate_statement_interest()` - Create interest transaction
- `generate_payment_transaction()` - Create payment transaction
- `regenerate_future_transactions()` / `regenerate_all_future_transactions()` - Replace
  unlocked future statement chains for one card or all active cards

Both services use the shared vendor lookup helpers in
`services/finance/credit_card_helpers.py`.

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

### Duplicate Prevention

Statement generation checks for an existing transaction for the card, date, and
transaction type within the active household before creating another entry.

---

The consolidated transaction view brings supported transaction sources into
one view. Projection results depend on the data and selected forecast period;
they should not be treated as a guarantee of future balances.
