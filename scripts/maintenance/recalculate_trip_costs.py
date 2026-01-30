"""
Recalculate MPG, Gallons, and Trip Cost for all existing trip records
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import create_app
from extensions import db
from models.trips import Trip
from services.vehicle_service import VehicleService
from decimal import Decimal


def recalculate_all_trips():
    """Recalculate fuel metrics for all trip records"""
    app = create_app()
    
    with app.app_context():
        trips = Trip.query.order_by(Trip.vehicle_id, Trip.date).all()
        
        print(f"Found {len(trips)} trips to recalculate")
        
        updated_count = 0
        skipped_count = 0
        
        for trip in trips:
            try:
                # Calculate fuel cost based on historical data
                trip_cost, gallons_used, approx_mpg = VehicleService.calculate_trip_cost(
                    trip.vehicle_id, 
                    trip.total_miles, 
                    trip.date
                )
                
                # Only update if we got valid calculations
                if approx_mpg > 0:
                    trip.trip_cost = trip_cost
                    trip.gallons_used = gallons_used
                    trip.approx_mpg = approx_mpg
                    
                    # Recalculate cumulative gallons
                    previous_trip = Trip.query.filter(
                        Trip.vehicle_id == trip.vehicle_id,
                        Trip.date < trip.date
                    ).order_by(Trip.date.desc()).first()
                    
                    previous_cumulative = previous_trip.cumulative_gallons or Decimal('0') if previous_trip else Decimal('0')
                    trip.cumulative_gallons = previous_cumulative + gallons_used
                    
                    updated_count += 1
                    print(f"✓ Updated trip {trip.id}: {trip.date} - {trip.vehicle.name} - {trip.total_miles}mi = £{trip_cost:.2f} ({approx_mpg:.1f} MPG, {gallons_used:.2f} gal)")
                else:
                    skipped_count += 1
                    print(f"⚠ Skipped trip {trip.id}: {trip.date} - {trip.vehicle.name} - No fuel data available")
                    
            except Exception as e:
                print(f"✗ Error processing trip {trip.id}: {str(e)}")
                skipped_count += 1
        
        if updated_count > 0:
            db.session.commit()
            print(f"\n✓ Successfully updated {updated_count} trips")
        else:
            print(f"\nNo trips were updated")
        
        if skipped_count > 0:
            print(f"⚠ Skipped {skipped_count} trips (no fuel data)")


if __name__ == '__main__':
    recalculate_all_trips()
