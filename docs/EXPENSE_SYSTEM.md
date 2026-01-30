# Expense System Documentation

## Overview

The expense system manages work-related expenses from initial payment through to reimbursement and credit card settlement. It automatically creates and links transactions throughout the entire workflow.

## Workflow

### 1. **Initial Payment** (Automatic)
When you enter an expense, the system immediately creates a payment transaction:

**Credit Card Expense:**
- Creates **Credit Card Transaction** (negative amount = purchase)
- Links expense to transaction
- Updates card balance

**Bank Account Expense** (direct payment):
- Creates **Bank Transaction** (negative amount = money out)
- Category: Work > Expenses
- Payment Type: "Work Expense"
- Links expense to transaction
- Updates account balance

### 2. **Monthly Reimbursement** (Manual Trigger)
At the end of each month, generate reimbursements for submitted expenses:

1. Click **"Generate Reimbursements"** button
2. Optional: Specify month (YYYY-MM) or leave blank for all months
3. System will:
   - Group all submitted expenses by calendar month
   - Calculate total reimbursement amount
   - Create single **Bank Transaction** on last working day of month
   - Transaction type: "Expense Reimbursement" (Income)
   - Category: Income > Expense Reimbursement
   - Amount: Positive (money in)

**Example:**
```
January 2026 Expenses:
- 06/01: Tetrad £103.50
- 13/01: Hotel £101.85
- 13/01: Food £21.37
Total: £226.72

Reimbursement Created:
- Date: 31/01/2026 (last working day)
- Amount: £226.72
- Type: Expense Reimbursement
```

### 3. **Credit Card Payment** (Manual Trigger)
One working day after reimbursement, pay off credit cards used for expenses:

1. Click **"Generate CC Payments"** button
2. Optional: Specify month or leave blank for all
3. System will:
   - Find all credit card expenses for each month
   - Group by credit card
   - Calculate total per card
   - Create **Credit Card Payment** transaction 1 working day after reimbursement
   - Transaction type: "Payment"
   - Amount: Positive (payment to card)

**Example:**
```
Reimbursement: 31/01/2026
CC Expenses (Vanquis): £123.22

Payment Created:
- Date: 03/02/2026 (next working day, skips weekend)
- Amount: £123.22
- Type: Payment
- Card: Vanquis
```

## Features

### Automatic Transaction Creation
- ✅ Enter expense → Transaction created immediately
- ✅ Works for both current AND future expenses (3-4 months ahead)
- ✅ Links maintained for easy tracking
- ✅ Balance calculations automatic

### Manual Controls
- ✅ Generate monthly reimbursements on demand
- ✅ Generate credit card payments on demand
- ✅ Process specific month or all months
- ✅ Bulk delete with transaction cleanup

### Smart Date Handling
- ✅ Last working day of month (skips weekends)
- ✅ Next working day calculation (skips weekends)
- ✅ Calendar month aggregation

## Field Mappings

### Expense Fields
| Field | Description | Required |
|-------|-------------|----------|
| date | Expense date | Yes |
| description | What was purchased | Yes |
| expense_type | Fuel, Hotel, Food, VAT | Yes |
| total_cost | Amount paid | Yes |
| credit_card_id | Card used (if any) | No |
| vehicle_registration | Vehicle (for fuel) | No |
| covered_miles | Business miles claimed | No |
| rate_per_mile | Mileage rate (£0.45) | No |
| paid_for | Checkbox | No |
| submitted | Mark when claim submitted | No |
| reimbursed | Auto-set by system | No |

### Transaction Links
| Expense Field | Links To | Purpose |
|---------------|----------|---------|
| bank_transaction_id | Transaction.id | Direct bank payment or reimbursement |
| credit_card_transaction_id | CreditCardTransaction.id | Credit card purchase |

## Configuration

### Settings (Auto-configured)
| Setting | Default | Purpose |
|---------|---------|---------|
| expenses.auto_sync | True | Enable automatic syncing |
| expenses.payment_account_id | Halifax - Brian | Account for direct payments |
| expenses.reimburse_account_id | Halifax - Brian | Account for reimbursements |

### Categories (Auto-created)
| Category | Type | Usage |
|----------|------|-------|
| Income > Expense Reimbursement | income | Monthly reimbursements |
| Work > Expenses | expense | Direct expense payments |

## Transaction Types

### Payment Transactions
```
Description: [Expense Description]
Amount: -[Cost] (negative = money out)
Payment Type: "Work Expense"
Category: Work > Expenses
Account: Payment Account
```

### Reimbursement Transactions
```
Description: Work Expense Reimbursement - YYYY-MM
Amount: +[Total] (positive = money in)
Payment Type: "Expense Reimbursement"
Category: Income > Expense Reimbursement
Account: Reimbursement Account
Date: Last working day of month
```

### Credit Card Transactions
**Purchase:**
```
Item: [Expense Description]
Amount: -[Cost] (negative = purchase)
Type: "Purchase"
Date: Expense date
```

**Payment:**
```
Item: Expense reimbursement payment - YYYY-MM
Amount: +[Total] (positive = payment)
Type: "Payment"
Date: 1 working day after reimbursement
```

## Scripts

### Enable System
```bash
python scripts/maintenance/enable_expense_sync.py
```
Enables service and creates required settings/categories.

### Reconcile Existing Expenses
```bash
python scripts/maintenance/reconcile_all_expenses.py
```
Backfills payment transactions for existing expenses.

### Test Verification
```bash
python scripts/maintenance/test_expense_transactions.py
```
Verifies transaction links are working correctly.

## UI Operations

### Adding Expense
1. Click **"Add Expense"**
2. Fill in details (date, description, type, amount)
3. Choose credit card OR leave blank for bank
4. Save
5. ✅ Payment transaction created automatically

### Monthly Reimbursement
1. Mark expenses as **"Submitted"**
2. Click **"Generate Reimbursements"**
3. Optional: Enter month (2026-01) or leave blank
4. Click "Generate Reimbursements"
5. ✅ Reimbursement transaction created for each month

### Credit Card Payment
1. After reimbursements generated
2. Click **"Generate CC Payments"**
3. Optional: Enter month or leave blank
4. Click "Generate Payments"
5. ✅ Payment transactions created 1 day after reimbursement

### Bulk Delete
1. Select expenses with checkboxes
2. Choose bulk action:
   - **Delete Linked Transactions** (keep expenses)
   - **Delete Expenses** (removes expenses + transactions)
3. Confirm

## Examples

### Scenario 1: Direct Bank Expense
```
Expense Entry:
- Date: 06/01/2026
- Description: Tetrad
- Type: Fuel
- Amount: £103.50
- Credit Card: [None]
- Submitted: ✓

Result:
→ Bank Transaction created immediately:
  - Halifax - Brian: -£103.50
  - Description: Tetrad
  - Type: Work Expense
  - Date: 06/01/2026
```

### Scenario 2: Credit Card Expense
```
Expense Entry:
- Date: 13/01/2026
- Description: Holiday Inn
- Type: Hotel
- Amount: £101.85
- Credit Card: Vanquis
- Submitted: ✓

Result:
→ Credit Card Transaction created immediately:
  - Vanquis: -£101.85
  - Item: Holiday Inn
  - Type: Purchase
  - Date: 13/01/2026
```

### Scenario 3: Monthly Workflow
```
January 2026 Submitted Expenses:
1. 06/01: Tetrad £103.50 (Bank)
2. 13/01: Hotel £101.85 (Vanquis)
3. 13/01: Food £21.37 (Vanquis)
4. 14/01: Tetrad £51.75 (Bank)
Total: £278.47

Click "Generate Reimbursements":
→ Bank Transaction (31/01/2026):
  - Halifax - Brian: +£278.47
  - Type: Expense Reimbursement
  - Description: Work Expense Reimbursement - 2026-01

Click "Generate CC Payments":
→ Credit Card Transaction (03/02/2026):
  - Vanquis: +£123.22
  - Type: Payment
  - Description: Expense reimbursement payment - 2026-01
```

## Troubleshooting

### No Transactions Created
1. Check setting: `expenses.auto_sync` = True
2. Run: `python scripts/maintenance/reconcile_all_expenses.py`
3. Check account settings exist

### Reimbursement Not Created
1. Ensure expenses marked as "Submitted"
2. Check expenses have month field populated
3. Verify reimburse account set in settings

### Wrong Account Used
1. Update settings:
   - `expenses.payment_account_id`
   - `expenses.reimburse_account_id`
2. Delete and recreate transactions

### Duplicate Transactions
1. Use bulk delete to remove linked transactions
2. Run reconcile script again

## Future Enhancements

- [ ] Auto-submit expenses on certain date
- [ ] Email notifications for reimbursements
- [ ] Receipt upload integration
- [ ] Expense approval workflow
- [ ] Mileage route optimization
- [ ] Integration with vehicle trips
