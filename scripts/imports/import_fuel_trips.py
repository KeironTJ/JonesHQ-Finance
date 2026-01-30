"""
Import fuel/trip entries from CSV file into the trips table.
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
from models.trips import Trip

app = create_app()

def parse_date(date_str):
    """Parse date from DD/MM/YYYY format"""
    try:
        return datetime.strptime(date_str.strip(), '%d/%m/%Y').date()
    except:
        return None

def get_or_create_vehicle(registration):
    """Get existing vehicle or create a placeholder"""
    vehicle = Vehicle.query.filter_by(registration=registration).first()
    if not vehicle:
        print(f"Creating vehicle: {registration}")
        vehicle = Vehicle(
            name=registration,
            make="Unknown",  # Placeholder
            model="Unknown",  # Placeholder
            registration=registration,
            fuel_type='Petrol',
            tank_size=50.0,
            is_active=True
        )
        db.session.add(vehicle)
        db.session.flush()  # Flush but don't commit yet
    return vehicle

def import_trips(csv_path):
    """Import trip data from CSV"""
    
    with app.app_context():
        with open(csv_path, 'r', encoding='utf-8-sig') as f:  # utf-8-sig handles BOM
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
                    vehicle = get_or_create_vehicle(row['Vehicle'].strip())
                    
                    # Parse miles
                    personal_miles = float(row['Personal']) if row['Personal'].strip() else 0.0
                    business_miles = float(row['Business']) if row['Business'].strip() else 0.0
                    total_miles = float(row['Total']) if row['Total'].strip() else 0.0
                    
                    # Skip entries with no miles
                    if total_miles == 0:
                        skipped += 1
                        continue
                    
                    # Check if trip already exists
                    existing = Trip.query.filter_by(
                        vehicle_id=vehicle.id,
                        date=date
                    ).first()
                    
                    if existing:
                        skipped += 1
                        continue
                    
                    # Create trip
                    trip = Trip(
                        vehicle_id=vehicle.id,
                        date=date,
                        personal_miles=personal_miles,
                        business_miles=business_miles,
                        total_miles=total_miles,
                        journey_description=row['Journey'].strip() if row['Journey'].strip() else None,
                        school_holidays=row['School Holidays'].strip() if row['School Holidays'].strip() else None
                    )
                    
                    db.session.add(trip)
                    imported += 1
                    
                    if imported % 100 == 0:
                        db.session.commit()
                        print(f"Imported {imported} trips...")
                
                except Exception as e:
                    db.session.rollback()  # Rollback on error
                    print(f"Error processing row {imported + skipped + errors + 1}: {str(e)}")
                    if errors < 5:  # Show detail for first few errors
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
    csv_path = os.path.join(os.path.dirname(__file__), '../data/Fuelentries_ACTUAL.csv')
    
    if not os.path.exists(csv_path):
        print(f"CSV file not found: {csv_path}")
        sys.exit(1)
    
    print(f"Importing trips from: {csv_path}")
    import_trips(csv_path)
