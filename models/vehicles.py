from extensions import db
from datetime import datetime, timezone


class Vehicle(db.Model):
    __tablename__ = 'vehicles'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    name = db.Column(db.String(100))  # Vauxhall Zafira, Audi A6
    make = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    year = db.Column(db.Integer)
    registration = db.Column(db.String(20), nullable=False, unique=True)  # VRN
    tank_size = db.Column(db.Numeric(5, 2))  # Gallons
    fuel_type = db.Column(db.String(20))  # Diesel, Petrol
    refuel_threshold_pct = db.Column(db.Numeric(4, 1), default=95.0)  # % tank capacity that triggers refuel forecast
    starting_mileage = db.Column(db.Integer)  # Initial odometer reading
    fuel_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))  # Default account for fuel transactions
    purchase_date = db.Column(db.Date)
    purchase_price = db.Column(db.Numeric(10, 2))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    # Relationships
    fuel_records = db.relationship('FuelRecord', backref='vehicle', lazy=True)
    trips = db.relationship('Trip', backref='vehicle', lazy=True)
    
    def __repr__(self):
        return f'<Vehicle {self.registration}: {self.name}>'
