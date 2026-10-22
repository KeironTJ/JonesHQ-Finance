# Vendor Management System

## Overview
Vendor management standardizes merchant names across household transactions
and supports autocomplete, default categories, vendor types, and usage
statistics.

## Current Implementation

## Implementation

### 1. Database Layer ✅
- **Vendor Model** (`models/vendors.py`)
  - `family_id`: Household boundary
  - `name`: Vendor name (indexed; the database does not enforce global uniqueness)
  - `vendor_type_id`: Link to the household's `VendorType` record
  - `vendor_type`: Deprecated legacy text field retained for compatibility
  - `default_category_id`: Default category for transactions with this vendor
  - `website`: Vendor's website URL
  - `notes`: Additional information
  - `is_active`: Flag to disable vendors without deleting
  - `created_at`, `updated_at`: Timestamps
  - Relationships: `default_category`, `transactions`

- **Transaction Model Updates** (`models/transactions.py`)
  - Added `vendor_id` foreign key column
  - Added `vendor` relationship (back_populates with Vendor)
  - Updated `item` field comment to clarify usage (item = specific details, vendor = merchant)

- **Database Migration**
  - Adds the `vendors` and `vendor_types` tables and `transactions.vendor_id`

### 2. Application Layer
- **Vendors Blueprint** (`blueprints/vendors/`)
  - Registered in `app.py` with URL prefix `/vendors`
  - Routes (`routes.py`):
    - `GET /vendors/` - List all vendors with search and filter
    - `GET /vendors/add` - Add new vendor form
    - `POST /vendors/add` - Create new vendor
    - `GET /vendors/edit/<id>` - Edit vendor form
    - `POST /vendors/edit/<id>` - Update vendor
    - `POST /vendors/delete/<id>` - Delete vendor (protected when transactions exist)
    - `GET /vendors/types` - Manage vendor types
    - `GET /vendors/analytics` - Vendor analytics
    - `GET /vendors/api/search` - Autocomplete API endpoint
    - `GET /vendors/api/stats` - Vendor statistics API
    - `POST /vendors/quick-add` - Quick-add a vendor from a form

### 3. User Interface
- **Vendor List** (`templates/vendors/vendors.html`) ✅
  - Card-based layout showing all vendors
  - Search by name functionality
  - Filter by vendor type
  - Displays: name, type, default category, website, notes
  - Inactive vendors marked with badge
  - Edit/Delete buttons
  - **Note:** Transaction count temporarily removed to prevent query overhead

- **Add Vendor** (`templates/vendors/add.html`)
  - Form with fields: name (required), type, default category, website, notes
  - Grouped category dropdown by head budget
  - Predefined vendor types dropdown
  - Tips sidebar with usage guidance

- **Edit Vendor** (`templates/vendors/edit.html`)
  - All add fields plus active/inactive toggle
  - Info sidebar showing creation/update dates and transaction count
  - Warning when editing vendor with existing transactions
  - Protection against deletion when transactions exist

- **Navigation**
  - Added "Vendors" link to main navigation in `base.html`

### 4. Features

#### Core Functionality
- ✅ Create vendors with standardized names
- ✅ Assign default categories to vendors
- ✅ Categorize vendors by type (Grocery, Fuel, etc.)
- ✅ Search vendors by name
- ✅ Filter vendors by type
- ✅ Edit vendor details
- ✅ Deactivate vendors instead of deleting
- ✅ Track transaction count per vendor
- ✅ Prevent deletion of vendors with transactions
- ✅ Family-scoped vendor type names; vendor names are indexed
- ✅ Quick-add reuses an existing vendor with an exact matching name
- ✅ Website and notes tracking
- ✅ **Auto-create vendors** - Credit card payment transactions automatically create vendor matching card name

#### API Endpoints
- ✅ `/vendors/api/search` - Autocomplete for transaction forms
- ✅ `/vendors/api/stats` - Vendor analytics (transaction count)

#### Data Quality
- ✅ Vendor name is indexed; quick-add reuses an exact existing name within the family
- ✅ Standardized naming (e.g., "Tesco" not "TESCO EXTRA 123")
- ✅ Vendor type classification for reporting
- ✅ Default category suggestion for faster transaction entry
- ✅ Inactive flag preserves historical data

## Credit Card Integration

### Automatic Vendor Creation for Credit Card Payments
When a credit card payment transaction is generated:

1. **Vendor Lookup**: System searches for vendor with name matching card name
   ```python
   vendor = family_query(Vendor).filter_by(name=card.card_name).first()
   ```

2. **Auto-Create if Missing**: If vendor doesn't exist, creates new vendor:
   ```python
   if not vendor:
       vendor = Vendor(family_id=get_family_id(), name=card.card_name)
       db.session.add(vendor)
       db.session.flush()
   ```

3. **Link to Transaction**: Sets vendor_id on the bank transaction:
   ```python
   bank_txn.vendor_id = vendor.id
   ```

**Result**: When a linked bank transaction is created, it can have:
- Vendor tracking associated with the credit-card name
- Consistent vendor naming across all payments
- Ability to track spending per card via vendor analytics

## Benefits

### For Data Quality
1. **Standardization**: Consistent vendor names across all transactions
2. **Quick-add reuse**: An exact existing name is reused; case variants can still be separate vendors
3. **Completeness**: Website and notes provide additional context
4. **Validation**: Quick-add checks for exact-name matches; the database does not enforce vendor-name uniqueness

### For User Experience
1. **Autocomplete**: Quickly select vendors in transaction forms (API ready)
2. **Default Categories**: Faster transaction entry with pre-filled categories
3. **Search/Filter**: Easy to find and manage vendors
4. **Protection**: Cannot accidentally delete vendors with transactions

### For Analytics
1. **Spending by Vendor**: See total spending per vendor
2. **Vendor Types**: Analyze spending by merchant type
3. **Transaction Count**: Identify most frequent vendors
4. **Historical Tracking**: Inactive vendors preserve past data

## Technical Implementation

### Patterns Used
- **Blueprint Architecture**: Modular vendors blueprint
- **Back-populates Relationships**: Bidirectional vendor-transaction links
- **Card-based UI**: Consistent with categories interface
- **Form Validation**: Server-side request validation; quick-add reuses exact-name matches
- **Soft Deletes**: is_active flag instead of hard deletes
- **Protected Deletes**: Cannot delete vendors with transactions
- **Autocomplete API**: Vendor search endpoint is available to transaction forms

### Database Design
```sql
vendors
├── id (PK)
├── family_id (FK → families.id)
├── name (INDEXED; not globally unique)
├── vendor_type_id (FK → vendor_types.id)
├── vendor_type (legacy compatibility field)
├── default_category_id (FK → categories.id)
├── website
├── notes
├── is_active
├── created_at
└── updated_at

vendor_types
├── id (PK)
├── family_id (FK → families.id)
└── name (unique within a family)

transactions.vendor_id (FK → vendors.id)
```

### Navigation Flow
```
Home → Vendors → List (search/filter)
              → Add Vendor
              → Edit Vendor
              → Delete Vendor (protected)
```

## Possible Future Enhancements
1. **Vendor Tags**: Additional classification beyond vendor type
2. **Vendor Logos**: Upload and display vendor logos
3. **Vendor Merge**: Combine duplicate vendors
4. **Vendor History**: Timeline of transactions with vendor

## Vendor Analytics

Open `/vendors/analytics` to review vendor analytics. The route scopes
transaction queries to the active household and supports payday and monthly
views.

---

Vendor and vendor-type queries are family-scoped. Resolve submitted vendor,
type, and category IDs through the family-scoped helpers; do not use raw model
queries with request-provided IDs.
