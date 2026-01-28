# Scripts Directory

Scripts for managing and maintaining the JonesHQ Finance database.

## 📁 Structure

```
scripts/
├── README.md                  # This file
├── imports/                   # Data import scripts
│   ├── import_accounts.py
│   ├── import_accounts_ACTUAL.py
│   ├── import_categories.py
│   ├── import_credit_cards.py
│   ├── import_credit_cards_ACTUAL.py
│   ├── import_credit_card_transactions.py
│   ├── import_loans.py
│   ├── import_loans_ACTUAL.py
│   ├── import_transactions_csv.py
│   ├── import_transactions_nationwide.py
│   └── import_vendors.py
├── checks/                    # Verification & validation scripts
│   ├── check_active_cards.py
│   ├── check_card_balances.py
│   ├── check_paid_status.py
│   └── check_vendors.py
├── maintenance/               # Data maintenance & recalculation scripts
│   ├── delete_future_txns.py
│   ├── mark_past_transactions_paid.py
│   ├── migrate_credit_cards.py
│   ├── recalculate_active_cards.py
│   ├── recalculate_balances.py
│   ├── recalculate_credit_available.py
│   ├── reset_credit_cards.py
│   ├── sync_transfer_transactions.py
│   ├── update_account_balance.py
│   └── update_savings_balances.py
├── database/                  # Database initialization scripts
│   ├── init_db.py
│   └── populate_sample_data.py
└── data/                      # Sample data files
```

## 🚀 Usage

### Database Initialization

**Initialize Database:**
```powershell
cd "c:\Users\keiro\OneDrive\Documents\Programming\JonesHQ Finance"
.\.venv\Scripts\Activate.ps1
python scripts\database\init_db.py
```

**Populate Sample Data:**
```powershell
python scripts\database\populate_sample_data.py
```

### Import Scripts

**Import Categories:** ✅ COMPLETED
```powershell
python scripts\imports\import_categories.py
```
- 42 categories across 10 head budgets imported

**Import Vendors:** ✅ COMPLETED
```powershell
python scripts\imports\import_vendors.py
```
- 177 vendors imported and categorized by type

**Import Accounts:** ✅ COMPLETED
```powershell
python scripts\imports\import_accounts_ACTUAL.py
```

**Import Credit Cards:** ✅ COMPLETED
```powershell
python scripts\imports\import_credit_cards_ACTUAL.py
```

**Import Loans:** ✅ COMPLETED
```powershell
python scripts\imports\import_loans_ACTUAL.py
```

**Import Transactions:**
```powershell
python scripts\imports\import_transactions_csv.py
# or
python scripts\imports\import_transactions_nationwide.py
```

### Verification Scripts

**Check Active Cards:**
```powershell
python scripts\checks\check_active_cards.py
```

**Check Card Balances:**
```powershell
python scripts\checks\check_card_balances.py
```

**Check Payment Status:**
```powershell
python scripts\checks\check_paid_status.py
```

**Check Vendors:**
```powershell
python scripts\checks\check_vendors.py
```

### Maintenance Scripts

**Recalculate Balances:**
```powershell
python scripts\maintenance\recalculate_balances.py
python scripts\maintenance\recalculate_credit_available.py
python scripts\maintenance\update_account_balance.py
```

**Clean Up Data:**
```powershell
python scripts\maintenance\delete_future_txns.py
python scripts\maintenance\reset_credit_cards.py
```

**Sync Transactions:**
```powershell
python scripts\maintenance\sync_transfer_transactions.py
python scripts\maintenance\mark_past_transactions_paid.py
```

## 📝 Notes

- All import scripts check for duplicates before inserting
- Maintenance scripts include safety confirmations where appropriate
- Check scripts provide verification without modifying data
- Database scripts should be run before imports
- Scripts are idempotent - safe to run multiple times
- Always backup database before running bulk operations

## ✅ Completed Imports

- **Categories:** 42 categories across 10 head budgets
- **Vendors:** 177 vendors with type classification
- **Accounts:** Bank accounts with balances
- **Credit Cards:** 11 cards (3 active, 8 inactive)
- **Loans:** Active loan accounts

## 🎯 Script Organization

- **imports/** - One-time data import from Excel/CSV
- **checks/** - Verification and validation (read-only)
- **maintenance/** - Data cleanup and recalculation
- **database/** - Database initialization and setup
