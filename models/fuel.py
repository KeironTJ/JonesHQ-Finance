from extensions import db
from datetime import datetime


class FuelRecord(db.Model):
    __tablename__ = 'fuel_records'
    
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    price_per_litre = db.Column(db.Numeric(6, 2))  # Price in pence
    mileage = db.Column(db.Integer, nullable=False)  # Odometer reading
    cost = db.Column(db.Numeric(10, 2), nullable=False)
    gallons = db.Column(db.Numeric(8, 2), nullable=False)
    actual_miles = db.Column(db.Integer)  # Miles since last fill
    actual_cumulative_miles = db.Column(db.Integer)  # Total miles tracked
    mpg = db.Column(db.Numeric(6, 2))  # Calculated MPG
    price_per_mile = db.Column(db.Numeric(6, 2))  # Cost per mile
    last_fill_date = db.Column(db.Date)  # Previous fill date
    linked_transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'))  # Link to actual transaction
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    trips = db.relationship('Trip', backref='fuel_record', lazy=True)
    
    def __repr__(self):
        return f'<FuelRecord {self.date}: {self.vehicle.registration} - £{self.cost}>'
