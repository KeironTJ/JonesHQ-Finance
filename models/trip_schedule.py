from datetime import datetime, timezone

from extensions import db


_WEEKDAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')


class TripSchedule(db.Model):
    __tablename__ = 'trip_schedules'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    trip_type = db.Column(db.String(20), nullable=False, default='personal')
    miles = db.Column(db.Integer, nullable=False, default=0)
    journey_description = db.Column(db.String(255))
    weekdays = db.Column(db.String(13), nullable=False)
    frequency = db.Column(db.String(20), nullable=False, default='weekly')
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    vehicle = db.relationship('Vehicle', back_populates='trip_schedules')
    trips = db.relationship('Trip', back_populates='schedule', passive_deletes=True)

    @property
    def weekday_names(self):
        return ', '.join(
            _WEEKDAYS[int(value)]
            for value in self.weekdays.split(',')
            if value.isdigit() and 0 <= int(value) < len(_WEEKDAYS)
        )
