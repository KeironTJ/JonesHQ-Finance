# Integrated Transaction System

## Overview
The JonesHQ Finance system uses a **bi-directional sync** between credit card transactions and bank account transactions to maintain a complete, accurate financial picture.

## Architecture

### Key Relationships

```
Bank Account Transaction (transactions table)
    ↕ (linked via bank_transaction_id / credit_card_id)
Credit Card Transaction (credit_card_transactions table)
```

### Database Fields

**credit_card_transactions:**
- `bank_transaction_id` - Foreign key to `transactions.id` (the corresponding bank withdrawal)
- `is_paid` - Transaction has been reconciled/completed
- `is_fixed` - Transaction is locked from regeneration

**transactions:**
- `credit_card_id` - Foreign key to `credit_cards.id` (identifies which card the payment is for)
- `is_paid` - Transaction has been reconciled/completed
- `is_fixed` - Transaction is locked from regeneration

## Workflow: Credit Card Payment

### Creating a Credit Card Payment

When a credit card payment transaction is created:

1. **User Input Required:**
   - Payment date
   - Payment amount
   - Source bank account (which account is the payment coming from)
   - Credit card (which card is being paid)

2. **System Actions:**
   - Create `CreditCardTransaction` with `transaction_type='Payment'` and positive amount
   - Create linked `Transaction` in bank account with:
     - `account_id` = source account
     - `credit_card_id` = target card
     - `amount` = payment amount (positive, as it's a debit/expense)
     - `description` = "Credit Card Payment - {CardName}"
   - Link them: `credit_card_transaction.bank_transaction_id` = `bank_transaction.id`
   - Recalculate credit card balance
   - Recalculate bank account balance

### Editing a Credit Card Payment

When either side is edited:

**IF credit card payment is edited:**
1. Update credit card transaction
2. Find linked bank transaction via `bank_transaction_id`
3. Update bank transaction with new amount/date
4. Recalculate both balances

**IF bank transaction is edited (and it's linked to a credit card):**
1. Update bank transaction
2. Find linked credit card transaction via `credit_card_id` and matching amount
3. Update credit card transaction with new amount/date
4. Recalculate both balances

### Deleting a Credit Card Payment

1. Delete credit card transaction
2. Delete linked bank transaction (cascade)
3. Recalculate both balances

## Implementation Plan

### Phase 1: Basic Linking ✅
- [x] Add `is_fixed` to transactions table
- [x] Update Transaction model

### Phase 2: Payment Creation with Linking
- [ ] Add account selector to credit card payment creation
- [ ] Create service method: `create_linked_payment(card_id, account_id, amount, date)`
- [ ] Automatically create both transactions
- [ ] Link them together

### Phase 3: Bi-directional Sync
- [ ] Create service method: `sync_credit_card_payment(transaction_id, updates)`
- [ ] When credit card payment edited → update bank transaction
- [ ] When bank transaction edited (if linked) → update credit card payment
- [ ] Handle deletion cascades

### Phase 4: UI Updates
- [ ] Add account dropdown to credit card payment forms
- [ ] Show linked transaction indicator
- [ ] Add "View in Bank Account" link from credit card transaction
- [ ] Add "View Credit Card Payment" link from bank transaction

### Phase 5: Bank Transaction Features
- [ ] Add edit/lock/paid controls to bank transaction list
- [ ] Similar modals as credit cards
- [ ] Toggle buttons for is_paid and is_fixed

## Data Integrity Rules

1. **Payment amounts must match** - Credit card payment (positive) = Bank withdrawal (positive)
2. **Dates must match** - Transaction date should be same on both sides
3. **One-to-one relationship** - Each credit card payment links to exactly one bank transaction
4. **Cascade rules** - Deleting one side should handle the other appropriately
5. **Status sync** - If credit card payment marked as paid, bank transaction should also be marked as paid

## Examples

### Example 1: Making a Payment

**User Action:**
- Date: 2026-01-28
- Amount: £200
- From Account: Nationwide Current Account
- To Card: Barclaycard

**System Creates:**

```python
# Credit Card Transaction
{
    'credit_card_id': 3,  # Barclaycard
    'transaction_type': 'Payment',
    'amount': 200.00,  # Positive reduces debt
    'date': '2026-01-28',
    'bank_transaction_id': 12345  # Link to bank
}

# Bank Transaction
{
    'id': 12345,
    'account_id': 1,  # Nationwide
    'credit_card_id': 3,  # Barclaycard
    'amount': 200.00,  # Positive is expense
    'transaction_date': '2026-01-28',
    'description': 'Credit Card Payment - Barclaycard'
}
```

### Example 2: Editing a Payment

**User edits credit card payment from £200 to £250:**

System automatically:
1. Updates credit card transaction amount to £250
2. Finds linked bank transaction (id=12345)
3. Updates bank transaction amount to £250
4. Recalculates both balances

## Technical Notes

### Balance Conventions

**Credit Cards:**
- Negative balance = debt owed
- Positive amount (payment) = reduces debt
- Formula: new_balance = old_balance + payment_amount

**Bank Accounts:**
- Positive balance = money in account
- Positive amount (expense) = reduces balance
- Formula: new_balance = old_balance - expense_amount

### Service Layer

All linking logic should be in a service layer (e.g., `CreditCardService`) to ensure:
- Transactions are atomic (both created or neither)
- Validation happens before creation
- Proper error handling
- Consistent business logic

## Future Enhancements

1. **Transfer Detection** - Auto-detect when a bank transaction is a credit card payment and suggest linking
2. **Reconciliation View** - Show unlinked payments and suggest matches
3. **Payment Scheduling** - Schedule future payments with reminders
4. **Multi-card Payments** - Split one bank payment across multiple cards
5. **Payment History** - Track payment patterns and suggest optimal payment strategies
