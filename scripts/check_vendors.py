"""Quick check to see vendors in database"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from models import Vendor

app = create_app()

with app.app_context():
    total = Vendor.query.count()
    print(f"Total vendors in database: {total}")
    print("\nFirst 10 vendors:")
    for vendor in Vendor.query.limit(10).all():
        print(f"  - {vendor.name} ({vendor.vendor_type})")
