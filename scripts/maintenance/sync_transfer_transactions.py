"""
Sync transfer transactions across accounts
This script finds transfer transactions and creates corresponding entries in target accounts
"""
import sys
import os
import re
from decimal import Decimal

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models.accounts import Account
from models.transactions import Transaction
from models.vendors import Vendor
from models.categories import Category

def parse_transfer_destination(transaction):
    """
    Parse the transfer transaction to determine the destination account
    Uses category (head_budget and sub_budget) which indicates the savings account
    """
    category = transaction.category
    if not category:
        return None
    
    head = category.head_budget.lower() if category.head_budget else ""
    sub = category.sub_budget.lower() if category.sub_budget else ""
    
    # Comprehensive mapping based on actual transfer patterns
    # Nationwide Savings Accounts
    nationwide_mappings = [
        (['clothing'], 'Nationwide - Clothing'),
        (['motor', 'car'], 'Nationwide - Motor'),
        (['home', 'household'], 'Nationwide - Home'),
        (['mr dales', 'dales'], 'Nationwide - Mr Dales'),
        (['christmas'], 'Nationwide - Christmas'),
        (['holiday'], 'Nationwide - Holiday'),
    ]
    
    # Halifax Savings Accounts (only if Savings or specific family member in head)
    halifax_mappings = [
        (['michael'], 'Halifax - Michael'),
        (['emily'], 'Halifax - Emily'),
        (['ivy'], 'Halifax - Ivy'),
        (['brian'], 'Halifax - Brian'),
        (['emma'], 'Halifax - Emma'),
    ]
    
    # Check Nationwide savings (most common)
    if 'savings' in head or any(kw in head or kw in sub for keywords, _ in nationwide_mappings for kw in keywords):
        for keywords, account_name in nationwide_mappings:
            if any(kw in head or kw in sub for kw in keywords):
                account = Account.query.filter_by(name=account_name).first()
                if account:
                    return account
    
    # Check Halifax savings
    if 'savings' in head or 'family' in head:
        # Special handling for "General" which could be Halifax General
        if 'general' in sub and 'savings' in head:
            account = Account.query.filter_by(name='Halifax - General').first()
            if account:
                return account
        
        for keywords, account_name in halifax_mappings:
            if any(kw in head or kw in sub for kw in keywords):
                account = Account.query.filter_by(name=account_name).first()
                if account:
                    return account
    
    # Special handling for transfers between personal accounts
    # "Other > Keiron Transfer" or "Other > Emma Transfer"
    if 'other' in head and 'transfer' in sub:
        if 'keiron' in sub:
            # This might be Halifax - Michael or other Keiron account
            return None  # Skip these for now
        if 'emma' in sub:
            account = Account.query.filter_by(name='Halifax - Emma').first()
            if account:
                return account
    
    return None

def sync_transfers():
    """Find and sync transfer transactions"""
    app = create_app()
    
    with app.app_context():
        # Get the Nationwide account
        nationwide = Account.query.filter_by(name='Nationwide Current Account').first()
        
        if not nationwide:
            print("ERROR: Nationwide Current Account not found")
            return
        
        # Get all transfer transactions
        transfers = Transaction.query.filter(
            Transaction.account_id == nationwide.id,
            Transaction.payment_type == 'Transfer'
        ).order_by(Transaction.transaction_date).all()
        
        print(f"\n{'='*80}")
        print(f"Transfer Transaction Sync")
        print(f"{'='*80}")
        print(f"Found {len(transfers)} transfer transactions in {nationwide.name}")
        
        # Analyze transfers
        created_count = 0
        skipped_count = 0
        no_match_count = 0
        
        # Get or create a Transfer category
        transfer_category = Category.query.filter_by(
            head_budget='Transfer',
            sub_budget='Account Transfer'
        ).first()
        
        if not transfer_category:
            transfer_category = Category(
                name='Account Transfer',
                head_budget='Transfer',
                sub_budget='Account Transfer',
                category_type='Transfer'
            )
            db.session.add(transfer_category)
            db.session.flush()
        
        # Sample some transfers first
        print("\nSample transfers:")
        for t in transfers[:10]:
            direction = "OUT" if t.amount > 0 else "IN"
            category_name = f"{t.category.head_budget} > {t.category.sub_budget}" if t.category else "No Category"
            print(f"  {t.transaction_date} | {direction:3} | GBP {abs(t.amount):>8.2f} | {t.item:30} | {category_name}")
        
        print(f"\nProcessing {len(transfers)} transfers...")
        
        for transfer in transfers:
            # Determine direction
            is_outgoing = transfer.amount > 0  # Positive = money leaving
            
            # Try to find the destination account from the category
            destination = parse_transfer_destination(transfer)
            
            if not destination:
                no_match_count += 1
                continue
            
            # Check if reverse transaction already exists
            reverse_amount = -transfer.amount  # Flip the sign
            
            existing = Transaction.query.filter_by(
                account_id=destination.id,
                transaction_date=transfer.transaction_date,
                amount=reverse_amount
            ).first()
            
            if existing:
                skipped_count += 1
                continue
            
            # Create the reverse transaction in the destination account
            reverse_transaction = Transaction(
                account_id=destination.id,
                category_id=transfer_category.id,
                vendor_id=transfer.vendor_id,
                amount=reverse_amount,
                transaction_date=transfer.transaction_date,
                description=f"Transfer from {nationwide.name}" if is_outgoing else f"Transfer to {nationwide.name}",
                item=transfer.item,
                assigned_to=transfer.assigned_to,
                payment_type='Transfer',
                year_month=transfer.year_month,
                week_year=transfer.week_year,
                day_name=transfer.day_name,
                is_paid=True
            )
            
            db.session.add(reverse_transaction)
            created_count += 1
            
            if created_count % 50 == 0:
                print(f"  Created {created_count} reverse transactions...")
                db.session.commit()
        
        # Final commit
        db.session.commit()
        
        print(f"\n{'='*80}")
        print(f"Transfer Sync Complete!")
        print(f"  Created: {created_count} new transactions")
        print(f"  Skipped: {skipped_count} (already exist)")
        print(f"  No match: {no_match_count} (couldn't identify destination)")
        print(f"{'='*80}\n")
        
        # Now update all account balances
        print("Updating account balances...")
        all_accounts = Account.query.all()
        
        for account in all_accounts:
            transactions = Transaction.query.filter_by(account_id=account.id).all()
            if transactions:
                balance = sum([-t.amount for t in transactions])
                old_balance = account.balance
                account.balance = balance
                print(f"  {account.name:30} | Old: GBP {old_balance or 0:>10.2f} | New: GBP {balance:>10.2f}")
        
        db.session.commit()
        print("\nAll account balances updated!")

if __name__ == '__main__':
    sync_transfers()
