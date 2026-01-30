from extensions import db
from datetime import datetime


class Trip(db.Model):
    __tablename__ = 'trips'
    
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    
    date = db.Column(db.Date, nullable=False)
    month = db.Column(db.String(7))  # 2025-11
    week = db.Column(db.String(7))  # 49-2025
    day_name = db.Column(db.String(10))  # Monday, Tuesday, etc.
    
    # Miles breakdown
    personal_miles = db.Column(db.Integer, default=0)
    business_miles = db.Column(db.Integer, default=0)
    total_miles = db.Column(db.Integer, nullable=False)
    cumulative_total_miles = db.Column(db.Integer)
    
    journey_description = db.Column(db.String(255))  # Daily Commute, GIRLS DANCING, etc.
    school_holidays = db.Column(db.String(50))
    
    # Fuel calculation
    approx_mpg = db.Column(db.Numeric(6, 2))
    gallons_used = db.Column(db.Numeric(8, 2))
    cumulative_gallons = db.Column(db.Numeric(8, 2))
    trip_cost = db.Column(db.Numeric(10, 2))
    fuel_cost = db.Column(db.Numeric(10, 2))
    
    # Reference to fuel fill
    fuel_log_entry_id = db.Column(db.Integer, db.ForeignKey('fuel_records.id'), nullable=True)
    vehicle_last_fill = db.Column(db.Date)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    fuel_record = db.relationship('FuelRecord', foreign_keys=[fuel_log_entry_id], back_populates='trips')
    
    def __repr__(self):
        return f'<Trip {self.date}: {self.vehicle.registration} - {self.total_miles}mi>'
