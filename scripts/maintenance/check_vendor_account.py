"""Check for Fuel Station vendor and accounts"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from models.vendors import Vendor
from models.accounts import Account

app = create_app()

with app.app_context():
    # Check for Fuel Station vendor
    fuel_vendor = Vendor.query.filter_by(name='Fuel Station').first()
    print(f"Fuel Station vendor exists: {fuel_vendor is not None}")
    if fuel_vendor:
        print(f"  ID: {fuel_vendor.id}")
    
    # List some vendors
    vendors = Vendor.query.limit(20).all()
    print(f"\nSample vendors:")
    for v in vendors:
        print(f"  - {v.name}")
    
    # List accounts
    accounts = Account.query.all()
    print(f"\nAccounts:")
    for a in accounts:
        print(f"  - {a.id}: {a.name}")
