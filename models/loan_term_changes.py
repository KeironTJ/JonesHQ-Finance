from extensions import db
from datetime import datetime, timezone


class LoanTermChange(db.Model):
    """
    Tracks mid-loan term changes (payment amount, APR, payment day, term extension).

    When loan terms change part-way through the loan lifecycle, a record is created
    here capturing what changed and when.  The loan service uses ``effective_date``
    to delete and regenerate future payments from that point forward.
    """
    __tablename__ = 'loan_term_changes'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('loans.id'), nullable=False)

    effective_date = db.Column(db.Date, nullable=False)

    # What changed (can be multiple fields in one change event)
    previous_monthly_payment = db.Column(db.Numeric(10, 2), nullable=True)
    new_monthly_payment = db.Column(db.Numeric(10, 2), nullable=True)

    previous_annual_apr = db.Column(db.Numeric(5, 2), nullable=True)
    new_annual_apr = db.Column(db.Numeric(5, 2), nullable=True)

    previous_payment_day = db.Column(db.Integer, nullable=True)   # 1-31
    new_payment_day = db.Column(db.Integer, nullable=True)

    previous_term_months = db.Column(db.Integer, nullable=True)
    new_term_months = db.Column(db.Integer, nullable=True)

    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    # Relationship
    loan = db.relationship('Loan', back_populates='term_changes')

    def __repr__(self):
        return f'<LoanTermChange loan_id={self.loan_id} effective={self.effective_date}>'

    @property
    def change_summary(self):
        """Human-readable summary of what changed in this record."""
        parts = []
        if self.previous_monthly_payment is not None and self.new_monthly_payment is not None:
            parts.append(
                f"Payment £{self.previous_monthly_payment} → £{self.new_monthly_payment}"
            )
        if self.previous_annual_apr is not None and self.new_annual_apr is not None:
            parts.append(
                f"APR {self.previous_annual_apr}% → {self.new_annual_apr}%"
            )
        if self.previous_payment_day is not None and self.new_payment_day is not None:
            parts.append(
                f"Payment day {self.previous_payment_day} → {self.new_payment_day}"
            )
        if self.previous_term_months is not None and self.new_term_months is not None:
            parts.append(
                f"Term {self.previous_term_months} → {self.new_term_months} months"
            )
        return "; ".join(parts) if parts else "No changes recorded"
