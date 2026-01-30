"""
Recalculate actual_miles and cumulative_miles for all fuel records.
This script processes fuel records in date order and calculates:
- actual_miles: difference between current and previous mileage
- actual_cumulative_miles: running total of actual miles
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from extensions import db
from models.fuel import FuelRecord
from models.vehicles import Vehicle

app = create_app()

def recalculate_fuel_metrics():
    """Recalculate metrics for all fuel records"""
    
    with app.app_context():
        vehicles = Vehicle.query.all()
        
        for vehicle in vehicles:
            print(f"\nProcessing vehicle: {vehicle.registration}")
            
            # Get all fuel records for this vehicle in date order
            fuel_records = FuelRecord.query.filter_by(
                vehicle_id=vehicle.id
            ).order_by(FuelRecord.date.asc()).all()
            
            if not fuel_records:
                print(f"  No fuel records found")
                continue
            
            # Set starting mileage from first fuel record if not already set
            if not vehicle.starting_mileage and fuel_records:
                vehicle.starting_mileage = fuel_records[0].mileage
                print(f"  Set starting mileage: {vehicle.starting_mileage}")
            
            cumulative_miles = 0
            previous_mileage = vehicle.starting_mileage or 0
            
            for i, record in enumerate(fuel_records):
                # Calculate actual miles since last fill
                if i == 0:
                    # First record - miles since vehicle start
                    record.actual_miles = record.mileage - previous_mileage if previous_mileage else 0
                else:
                    # Subsequent records - miles since last fill
                    record.actual_miles = record.mileage - previous_mileage
                
                # Calculate cumulative miles
                cumulative_miles += record.actual_miles
                record.actual_cumulative_miles = cumulative_miles
                
                # Calculate MPG if we have gallons and actual miles
                if record.gallons and record.gallons > 0 and record.actual_miles > 0:
                    record.mpg = round(record.actual_miles / float(record.gallons), 1)
                else:
                    record.mpg = None
                
                # Calculate price per mile
                if record.actual_miles > 0:
                    record.price_per_mile = round(float(record.cost) / record.actual_miles, 3)
                else:
                    record.price_per_mile = None
                
                # Store last fill date
                if i > 0:
                    record.last_fill_date = fuel_records[i-1].date
                
                previous_mileage = record.mileage
                
                print(f"  {record.date}: Mileage={record.mileage}, Actual={record.actual_miles}, "
                      f"Cumulative={record.actual_cumulative_miles}, MPG={record.mpg}")
            
            db.session.commit()
            print(f"  Updated {len(fuel_records)} fuel records")

if __name__ == '__main__':
    print("Recalculating fuel metrics for all vehicles...")
    recalculate_fuel_metrics()
    print("\n=== Complete ===")
