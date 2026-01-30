"""
Import fuel log entries from CSV file into the fuel_records table.
"""
import sys
import os
from datetime import datetime
import csv

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from extensions import db
from models.vehicles import Vehicle
from models.fuel import FuelRecord

app = create_app()

def parse_date(date_str):
    """Parse date from DD/MM/YYYY format"""
    try:
        return datetime.strptime(date_str.strip(), '%d/%m/%Y').date()
    except:
        return None

def get_vehicle(registration):
    """Get vehicle by registration"""
    return Vehicle.query.filter_by(registration=registration).first()

def import_fuel_records(csv_path):
    """Import fuel records from CSV"""
    
    with app.app_context():
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            # Debug: print headers
            print(f"CSV Headers: {reader.fieldnames}")
            
            imported = 0
            skipped = 0
            errors = 0
            
            for row in reader:
                try:
                    date = parse_date(row['Date'])
                    if not date:
                        skipped += 1
                        continue
                    
                    # Get vehicle
                    vehicle = get_vehicle(row['Vehicle'].strip())
                    if not vehicle:
                        print(f"Vehicle not found: {row['Vehicle']}")
                        skipped += 1
                        continue
                    
                    # Parse fuel data
                    price_per_litre = float(row['Price']) if row['Price'].strip() else 0.0
                    mileage = int(float(row['Mileage'])) if row['Mileage'].strip() else 0
                    cost = float(row['Cost']) if row['Cost'].strip() else 0.0
                    
                    # Handle zero cost entries - these are starting mileages
                    if cost == 0:
                        # Update vehicle starting mileage if not already set
                        if not vehicle.starting_mileage:
                            vehicle.starting_mileage = mileage
                            print(f"Set starting mileage for {vehicle.registration}: {mileage}")
                        skipped += 1
                        continue
                    
                    # Calculate gallons from cost and price per litre
                    if price_per_litre > 0 and cost > 0:
                        litres = cost / (price_per_litre / 100)  # Price is in pence
                        gallons = litres / 4.54609  # UK gallon conversion
                    else:
                        gallons = 0.0
                    
                    # Check if fuel record already exists
                    existing = FuelRecord.query.filter_by(
                        vehicle_id=vehicle.id,
                        date=date
                    ).first()
                    
                    if existing:
                        skipped += 1
                        continue
                    
                    # Create fuel record (metrics will be calculated by service layer if needed)
                    fuel_record = FuelRecord(
                        vehicle_id=vehicle.id,
                        date=date,
                        price_per_litre=price_per_litre,
                        mileage=mileage,
                        cost=cost,
                        gallons=round(gallons, 2)
                    )
                    
                    db.session.add(fuel_record)
                    imported += 1
                    
                    if imported % 50 == 0:
                        db.session.commit()
                        print(f"Imported {imported} fuel records...")
                
                except Exception as e:
                    db.session.rollback()
                    print(f"Error processing row {imported + skipped + errors + 1}: {str(e)}")
                    if errors < 5:
                        print(f"Row data: {row}")
                    errors += 1
                    continue
            
            # Final commit
            db.session.commit()
            
            print(f"\n=== Import Complete ===")
            print(f"Imported: {imported}")
            print(f"Skipped: {skipped}")
            print(f"Errors: {errors}")

if __name__ == '__main__':
    csv_path = os.path.join(os.path.dirname(__file__), '../data/fuellog_ACTUAL.csv')
    
    if not os.path.exists(csv_path):
        print(f"CSV file not found: {csv_path}")
        sys.exit(1)
    
    print(f"Importing fuel records from: {csv_path}")
    import_fuel_records(csv_path)
