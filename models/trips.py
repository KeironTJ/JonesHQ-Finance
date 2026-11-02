from extensions import db
from datetime import datetime, timezone
from sqlalchemy import UniqueConstraint


class Trip(db.Model):
    __tablename__ = 'trips'
    __table_args__ = (
        UniqueConstraint('schedule_id', 'scheduled_date', name='uq_trips_schedule_scheduled_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    vehicle_id= db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    schedule_id = db.Column(
        db.Integer,
        db.ForeignKey(
            'trip_schedules.id',
            name='fk_trips_schedule_id_trip_schedules',
            ondelete='SET NULL',
        ),
        nullable=True,
        index=True,
    )
    scheduled_date = db.Column(db.Date)
    trip_status = db.Column(
        db.String(20),
        nullable=False,
        default='actual',
        server_default='actual',
        index=True,
    )
    # A routine occurrence edited for one day; routine changes leave it untouched.
    is_modified = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    
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
    approx_mpg = db.Column(db.Numeric(12, 8))
    gallons_used = db.Column(db.Numeric(14, 8))
    cumulative_gallons = db.Column(db.Numeric(14, 8))
    trip_cost = db.Column(db.Numeric(10, 2))
    fuel_cost = db.Column(db.Numeric(10, 2))
    
    # Reference to fuel fill
    fuel_log_entry_id = db.Column(db.Integer, db.ForeignKey('fuel_records.id'), nullable=True)
    vehicle_last_fill = db.Column(db.Date)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    # Relationships
    fuel_record = db.relationship('FuelRecord', foreign_keys=[fuel_log_entry_id], back_populates='trips')
    schedule = db.relationship('TripSchedule', back_populates='trips')
    
    def __repr__(self):
        return f'<Trip {self.date}: {self.vehicle.registration} - {self.total_miles}mi>'
