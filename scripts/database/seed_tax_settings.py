"""
Seed Tax Settings with UK Tax Rates
Creates default tax settings for different tax years
"""
import sys
import os
from datetime import date
from decimal import Decimal

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from models.tax_settings import TaxSettings
from extensions import db

app = create_app()

with app.app_context():
    print("Seeding UK Tax Settings...")
    
    # Tax year 2024-2025 (current rates frozen until April 2028)
    tax_2024_25 = TaxSettings.query.filter_by(tax_year='2024-2025').first()
    if not tax_2024_25:
        tax_2024_25 = TaxSettings(
            tax_year='2024-2025',
            effective_from=date(2024, 4, 6),
            effective_to=date(2025, 4, 5),
            # Income Tax
            personal_allowance=Decimal('12570'),
            basic_rate_limit=Decimal('50270'),
            higher_rate_limit=Decimal('125140'),
            basic_rate=Decimal('0.20'),  # 20%
            higher_rate=Decimal('0.40'),  # 40%
            additional_rate=Decimal('0.45'),  # 45%
            # National Insurance (Employee Class 1)
            ni_threshold=Decimal('12570'),
            ni_upper_earnings=Decimal('50270'),
            ni_basic_rate=Decimal('0.12'),  # 12%
            ni_additional_rate=Decimal('0.02'),  # 2%
            is_active=True,
            notes='Rates frozen until April 2028. Personal allowance tapers to zero for income above £100k.'
        )
        db.session.add(tax_2024_25)
        print("  ✓ Added 2024-2025 tax settings")
    else:
        print("  ℹ 2024-2025 tax settings already exist")
    
    # Tax year 2025-2026 (same rates as 2024-2025 due to freeze)
    tax_2025_26 = TaxSettings.query.filter_by(tax_year='2025-2026').first()
    if not tax_2025_26:
        tax_2025_26 = TaxSettings(
            tax_year='2025-2026',
            effective_from=date(2025, 4, 6),
            effective_to=date(2026, 4, 5),
            # Income Tax
            personal_allowance=Decimal('12570'),
            basic_rate_limit=Decimal('50270'),
            higher_rate_limit=Decimal('125140'),
            basic_rate=Decimal('0.20'),
            higher_rate=Decimal('0.40'),
            additional_rate=Decimal('0.45'),
            # National Insurance
            ni_threshold=Decimal('12570'),
            ni_upper_earnings=Decimal('50270'),
            ni_basic_rate=Decimal('0.12'),
            ni_additional_rate=Decimal('0.02'),
            is_active=True,
            notes='Rates frozen (part of multi-year freeze until April 2028)'
        )
        db.session.add(tax_2025_26)
        print("  ✓ Added 2025-2026 tax settings")
    else:
        print("  ℹ 2025-2026 tax settings already exist")
    
    # Tax year 2026-2027 (same rates - still frozen)
    tax_2026_27 = TaxSettings.query.filter_by(tax_year='2026-2027').first()
    if not tax_2026_27:
        tax_2026_27 = TaxSettings(
            tax_year='2026-2027',
            effective_from=date(2026, 4, 6),
            effective_to=date(2027, 4, 5),
            personal_allowance=Decimal('12570'),
            basic_rate_limit=Decimal('50270'),
            higher_rate_limit=Decimal('125140'),
            basic_rate=Decimal('0.20'),
            higher_rate=Decimal('0.40'),
            additional_rate=Decimal('0.45'),
            ni_threshold=Decimal('12570'),
            ni_upper_earnings=Decimal('50270'),
            ni_basic_rate=Decimal('0.12'),
            ni_additional_rate=Decimal('0.02'),
            is_active=True,
            notes='Rates frozen (part of multi-year freeze until April 2028)'
        )
        db.session.add(tax_2026_27)
        print("  ✓ Added 2026-2027 tax settings")
    else:
        print("  ℹ 2026-2027 tax settings already exist")
    
    db.session.commit()
    
    print("\n✅ Tax settings seeded successfully!")
    print("\nNote: UK tax rates are frozen until April 2028.")
    print("You can update these in the Settings section when rates change.")
