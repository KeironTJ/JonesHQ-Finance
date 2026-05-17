from datetime import datetime, timezone

from extensions import db


class FamilyAssignmentLabel(db.Model):
    """Custom assignment labels for a family (e.g., children/non-login people)."""
    __tablename__ = 'family_assignment_labels'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )

    family = db.relationship('Family', backref=db.backref('assignment_labels', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('family_id', 'name', name='uq_family_assignment_label_name'),
    )

    def __repr__(self):
        return f'<FamilyAssignmentLabel family={self.family_id} name={self.name!r}>'
