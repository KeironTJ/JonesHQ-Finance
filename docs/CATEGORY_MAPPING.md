# Category Mapping Guide

This document maps your Excel categories to the new generic database structure.

## Mapping Rules for Transaction Import

### LOANS - Map to generic "Loan Payment" + use loan_id foreign key

| Excel Sub Budget | New Sub Budget | Action |
|-----------------|----------------|---------|
| JN Bank | Loan Payment | Find loan by name="JN Bank", set loan_id |
| Zopa | Loan Payment | Find loan by name="Zopa", set loan_id |
| Creation | Loan Payment | Find loan by name="Creation", set loan_id |
| EE | Loan Payment | Find loan by name="EE", set loan_id |
| Loft Loan | Loan Payment | Find loan by name="Loft Loan", set loan_id |
| Oakbrook | Loan Payment | Find loan by name="Oakbrook", set loan_id |

**Note**: For loan credits (like "Zopa Credit"), use "Loan Credit" sub-budget

### CREDIT CARDS - Map to generic "Payment" + use credit_card_id foreign key

| Excel Sub Budget | New Sub Budget | Action |
|-----------------|----------------|---------|
| Barclaycard | Payment | Find card by name="Barclaycard", set credit_card_id |
| M&S | Payment | Find card by name="M&S", set credit_card_id |
| Capital One2 | Payment | Find card by name="Capital One2", set credit_card_id |
| Lloyds | Payment | Find card by name="Lloyds", set credit_card_id |
| Natwest | Payment | Find card by name="Natwest", set credit_card_id |

### SAVINGS - Map to specific savings categories

| Excel Sub Budget | New Sub Budget | Notes |
|-----------------|----------------|-------|
| Mr Dales | Savings Account | Specific savings account name |
| Clothing | Clothing Fund | Savings for clothing purchases |
| Holiday | Holiday Fund | Savings for holidays |
| Christmas | Christmas Fund | Savings for Christmas |

### INCOME - Simple mapping

| Excel Sub Budget | New Sub Budget |
|-----------------|----------------|
| Salary | Salary |
| Expenses | Expense Reimbursement |
| Benefits / Tax Credits | Benefits / Tax Credits |

### TRANSPORTATION - Clarified names

| Excel Sub Budget | New Sub Budget |
|-----------------|----------------|
| Tax | Vehicle Tax |
| Sale / Purchase | Vehicle Sale / Purchase |
| Fuel | Fuel |
| Parking | Parking |
| Public Transport | Public Transport |
| Fines | Fines |

### OTHER - Use 'item' field for specifics

| Excel Sub Budget | New Sub Budget | Store Vendor In |
|-----------------|----------------|-----------------|
| Mama Doreen | Miscellaneous | item field |

### UNCHANGED CATEGORIES

The following categories remain the same:
- **Family**: All sub-categories unchanged
- **General**: All sub-categories unchanged
- **Household**: All sub-categories unchanged
- **Insurance**: All sub-categories unchanged

## Import Script Logic

When importing transactions:

```python
# Example for Loan Payment
if excel_head_budget == "Loans":
    if excel_sub_budget in ["JN Bank", "Zopa", "Creation", "EE", "Loft Loan", "Oakbrook"]:
        category = get_category("Loans", "Loan Payment")
        loan = Loan.query.filter_by(name=excel_sub_budget).first()
        transaction.loan_id = loan.id if loan else None
    elif "Credit" in excel_item:
        category = get_category("Loans", "Loan Credit")

# Example for Credit Card Payment
if excel_head_budget == "Credit Cards":
    category = get_category("Credit Cards", "Payment")
    card = CreditCard.query.filter_by(card_name=excel_sub_budget).first()
    transaction.credit_card_id = card.id if card else None

# Example for Savings
if excel_head_budget == "Savings":
    if excel_sub_budget == "Mr Dales":
        category = get_category("Savings", "Savings Account")
    elif excel_sub_budget == "Clothing":
        category = get_category("Savings", "Clothing Fund")
    elif excel_sub_budget == "Holiday":
        category = get_category("Savings", "Holiday Fund")
    elif excel_sub_budget == "Christmas":
        category = get_category("Savings", "Christmas Fund")
```

## Benefits of This Structure

1. **Budgeting**: Budget against "Loan Payment" category total, not individual loans
2. **Reporting**: See all loan payments together
3. **Flexibility**: Can add/remove loans without changing categories
4. **Detail**: Still track which specific loan via foreign key
5. **Item Field**: Vendor names (Asda, Tesco, etc.) go in `item` field, not categories
