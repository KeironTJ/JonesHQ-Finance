from datetime import datetime, timezone

from extensions import db


class TripTemplate(db.Model):
    __tablename__ = 'trip_templates'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    trip_type = db.Column(db.String(20), nullable=False, default='personal')
    miles = db.Column(db.Integer, nullable=False, default=0)
    journey_description = db.Column(db.String(255))
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    vehicle = db.relationship('Vehicle', back_populates='trip_templates')
