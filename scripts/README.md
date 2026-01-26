# Import Scripts

Scripts for populating the JonesHQ Finance database with initial data.

## 📁 Structure

```
scripts/
├── README.md              # This file
├── import_categories.py   # Import 42 generic categories
├── import_vendors.py      # Import vendors from curated list
└── data/                  # Sample data files (future use)
```

## 🚀 Usage

### 1. Import Categories ✅ COMPLETED
```powershell
cd "c:\Users\keiro\OneDrive\Documents\Programming\JonesHQ Finance"
.\.venv\Scripts\Activate.ps1
python scripts\import_categories.py
```

**Status:** ✅ Complete - 42 categories across 10 head budgets imported

### 2. Import Vendors ✅ COMPLETED
```powershell
cd "c:\Users\keiro\OneDrive\Documents\Programming\JonesHQ Finance"
.\.venv\Scripts\Activate.ps1
python scripts\import_vendors.py
```

**Status:** ✅ Complete - 177 vendors imported and categorized

**What it does:**
- Imports 177 vendors from curated Excel list
- Auto-categorizes by type (Grocery, Fuel, Restaurant, etc.)
- Sets default categories where applicable
- Skips duplicates
- Shows progress for each vendor

**Vendor types included:**
- Grocery stores (Tesco, Asda, Aldi, etc.)
- Fuel stations (Esso, BP, etc.)
- Restaurants & takeaways (McDonald's, Greggs, etc.)
- Retail stores (Primark, B&M, Argos, etc.)
- Online retailers (Amazon, eBay, SHEIN, etc.)
- Utilities (EE, Sky, Octopus Energy, etc.)
- Insurance providers
- Schools & childcare
- Entertainment venues
- Health & fitness
- Services (barbers, car wash, etc.)

## 📝 Notes

### Excluded from Import
These items from your Excel were excluded as they're not vendors:
- **Year markers** (2024, 2025, 2026) - These are savings pots, handled elsewhere
- **Generic terms** (Payment, Transfer, IN, OUT, Credit)
- **Personal transfers** (Emma Transfer, Keiron Transfer, etc.)
- **Family names** (Paula & Chris, Michael and Emily, etc.)
- **Interest categories** (Holiday Interest, Christmas Interest, etc.)
- **Specific vehicle names** (Vauxhall Zafira, Fiat Punto, Audi A6) - These go in Vehicles table

### Cleaned Names
Some vendor names were standardized:
- "Coop" → "Co-op"
- Multiple barber entries consolidated where appropriate
- School names kept as distinct vendors

## 🎯 Next Steps

After importing vendors, you can:
1. **Review vendors** at http://127.0.0.1:5000/vendors
2. **Add missing vendors** manually through the web interface
3. **Set default categories** for vendors that don't have them
4. **Mark inactive vendors** for ones you no longer use

## 🔄 Future Import Scripts

Planned scripts:
- `import_accounts.py` - Bank accounts
- `import_loans.py` - Loan details
- `import_credit_cards.py` - Credit card accounts
- `import_vehicles.py` - Vehicle registry
- `import_transactions.py` - Bulk transaction import from Excel

## ⚠️ Important

- Scripts are idempotent - safe to run multiple times
- Existing data won't be duplicated
- Always backup your database before running bulk imports
- Review imported data in the web interface after running
