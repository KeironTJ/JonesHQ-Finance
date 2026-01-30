"""Test forecasting logic"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from extensions import db
from models.vehicles import Vehicle
from models.transactions import Transaction
from services.fuel_forecasting_service import FuelForecastingService

app = create_app()

with app.app_context():
    # Test predict_refills
    vehicle = Vehicle.query.filter_by(registration='MV15LZJ').first()
    if vehicle:
        refills = FuelForecastingService.predict_refills(vehicle.id)
        future_refills = [r for r in refills if r['date'] >= date(2026, 1, 30)]
        print(f"Future refills predicted: {len(future_refills)}")
        if future_refills:
            print(f"Next 5 refills:")
            for r in future_refills[:5]:
                print(f"  {r['date']}: {r['gallons']} gal, £{r['cost']:.2f}")
    
    # Check transactions
    forecasted_count = Transaction.query.filter_by(is_forecasted=True).count()
    print(f"\nForecasted transactions in DB: {forecasted_count}")
    
    # Check if Fuel category exists
    from models.categories import Category
    fuel_cat = Category.query.filter_by(name='Fuel').first()
    print(f"Fuel category exists: {fuel_cat is not None}")
    if fuel_cat:
        print(f"  ID: {fuel_cat.id}, Name: {fuel_cat.name}")
