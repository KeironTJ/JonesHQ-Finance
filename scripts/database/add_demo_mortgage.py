"""
Script to add demo mortgage data to test the system
"""
from app import create_app
from extensions import db
from models.property import Property
from models.mortgage import MortgageProduct
from services.mortgage_service import MortgageService
from datetime import date
from decimal import Decimal

app = create_app()

with app.app_context():
    print("Creating demo property and mortgage products...")
    
    # Create a property
    demo_property = Property(
        address="123 Demo Street, London, SW1A 1AA",
        purchase_date=date(2022, 1, 1),
        purchase_price=Decimal('350000.00'),
        current_valuation=Decimal('380000.00'),
        annual_appreciation_rate=Decimal('3.0'),
        is_primary_residence=True,
        is_active=True
    )
    
    db.session.add(demo_property)
    db.session.flush()  # Get ID without committing
    
    print(f"✓ Created property: {demo_property.address}")
    
    # Create mortgage products (simulating your Excel structure)
    
    # Product 1: The Mortgage Lender - 2YR FIXED 70%
    product1 = MortgageProduct(
        property_id=demo_property.id,
        lender="The Mortgage Lender",
        product_name="2YR FIXED 70%",
        start_date=date(2022, 1, 1),
        end_date=date(2024, 7, 31),
        term_months=31,
        initial_balance=Decimal('245000.00'),
        current_balance=Decimal('239500.00'),
        annual_rate=Decimal('2.54'),
        monthly_payment=Decimal('800.00'),
        ltv_ratio=Decimal('70.0'),
        is_active=False,  # This product has ended
        is_current=False
    )
    
    db.session.add(product1)
    print(f"✓ Created product: {product1.lender} - {product1.product_name}")
    
    # Product 2: Nationwide - 2YR FIXED 68%
    product2 = MortgageProduct(
        property_id=demo_property.id,
        lender="Nationwide",
        product_name="2YR FIXED 68%",
        start_date=date(2024, 8, 1),
        end_date=date(2026, 7, 31),
        term_months=24,
        initial_balance=Decimal('239500.00'),
        current_balance=Decimal('235800.00'),
        annual_rate=Decimal('4.39'),
        monthly_payment=Decimal('1100.00'),
        ltv_ratio=Decimal('68.0'),
        is_active=True,
        is_current=True  # Currently active
    )
    
    db.session.add(product2)
    print(f"✓ Created product: {product2.lender} - {product2.product_name}")
    
    # Product 3: Nationwide - Variable (future/planned)
    product3 = MortgageProduct(
        property_id=demo_property.id,
        lender="Nationwide",
        product_name="Variable",
        start_date=date(2026, 8, 1),
        end_date=date(2027, 7, 31),
        term_months=12,
        initial_balance=Decimal('225000.00'),  # Estimated balance at start
        current_balance=Decimal('225000.00'),
        annual_rate=Decimal('6.74'),  # Estimated variable rate
        monthly_payment=Decimal('1200.00'),
        ltv_ratio=Decimal('60.0'),
        is_active=True,
        is_current=False  # Future product
    )
    
    db.session.add(product3)
    print(f"✓ Created product: {product3.lender} - {product3.product_name}")
    
    db.session.commit()
    print("\n✓ All demo data saved to database")
    
    # Generate projections
    print("\nGenerating projections...")
    scenarios = [
        {'name': 'base', 'overpayment': Decimal('0')},
        {'name': 'aggressive', 'overpayment': Decimal('500')},
    ]
    
    success = MortgageService.generate_projections(demo_property.id, scenarios)
    
    if success:
        print("✓ Projections generated successfully!")
        
        # Show some stats
        comparison = MortgageService.get_scenario_comparison(demo_property.id)
        print("\n--- Scenario Comparison ---")
        for scenario_name, data in comparison.items():
            print(f"\n{scenario_name.upper()}:")
            print(f"  Mortgage-free: {data['mortgage_free_date']}")
            print(f"  Total interest: £{data['total_interest']:,.2f}")
            if data['months_saved']:
                print(f"  Months saved: {data['months_saved']}")
    else:
        print("✗ Failed to generate projections")
    
    print("\n✓ Demo data setup complete!")
    print(f"\nProperty ID: {demo_property.id}")
    print(f"Visit: /mortgage/property/{demo_property.id}")
