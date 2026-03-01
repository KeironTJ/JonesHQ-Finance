from extensions import db
from datetime import datetime, timezone


class PropertyValuationSnapshot(db.Model):
    """
    Point-in-time property valuation record.

    Actual snapshots (is_projection=False) are entered manually when a new
    valuation is obtained (e.g. estate agent estimate, remortgage survey).
    Projection snapshots (is_projection=True) are generated automatically by
    compounding annual_appreciation_rate forward from the latest actual.

    NetWorthService uses these to give historically accurate property values
    in the timeline instead of always showing today's current_valuation.
    """
    __tablename__ = 'property_valuation_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=False)

    valuation_date = db.Column(db.Date, nullable=False)
    value = db.Column(db.Numeric(12, 2), nullable=False)

    # % change since previous actual snapshot (calculated on save)
    change_percent = db.Column(db.Numeric(10, 4))

    # Projection fields
    is_projection = db.Column(db.Boolean, default=False)
    appreciation_rate_used = db.Column(db.Numeric(5, 2))  # annual % used for this projection

    source = db.Column(db.String(100))  # e.g. 'manual', 'zoopla', 'estate_agent', 'remortgage'
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def __repr__(self):
        flag = ' (Projected)' if self.is_projection else ''
        return f'<PropertyValuationSnapshot {self.valuation_date}: £{self.value}{flag}>'
