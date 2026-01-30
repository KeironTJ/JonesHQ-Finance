"""
Initialize fuel forecasting for all vehicles.
Creates forecasted transactions based on existing trip data.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from extensions import db
from models.vehicles import Vehicle
from services.fuel_forecasting_service import FuelForecastingService

app = create_app()

def initialize_forecasting():
    """Initialize fuel forecasting for all active vehicles"""
    
    with app.app_context():
        vehicles = Vehicle.query.filter_by(is_active=True).all()
        
        print(f"Initializing fuel forecasting for {len(vehicles)} vehicles...")
        
        for vehicle in vehicles:
            print(f"\nProcessing {vehicle.name} ({vehicle.registration})...")
            
            # Calculate consumption
            consumption = FuelForecastingService.calculate_trip_fuel_consumption(vehicle.id)
            print(f"  Found {len(consumption)} trip dates with fuel consumption data")
            
            # Predict refills
            refills = FuelForecastingService.predict_refills(vehicle.id)
            print(f"  Predicted {len(refills)} refills")
            
            for refill in refills:
                print(f"    {refill['date']}: {refill['gallons']} gal, £{refill['cost']:.2f}")
            
            # Sync forecasted transactions
            FuelForecastingService.sync_forecasted_transactions(vehicle.id)
            print(f"  Forecasted transactions synced")
        
        print(f"\n=== Complete ===")

if __name__ == '__main__':
    initialize_forecasting()
