from extensions import db


class Meal(db.Model):
    __tablename__ = 'meals'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    ingredients = db.Column(db.Text, nullable=False, default='', server_default='')
    instructions = db.Column(db.Text, nullable=False, default='', server_default='')
    source = db.Column(db.String(500), nullable=False, default='', server_default='')
    is_archived = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())


class PlannedMeal(db.Model):
    __tablename__ = 'planned_meals'
    __table_args__ = (
        db.CheckConstraint("slot IN ('breakfast', 'lunch', 'dinner')", name='ck_planned_meal_slot'),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    meal_id = db.Column(db.Integer, db.ForeignKey('meals.id'), nullable=True, index=True)
    title = db.Column(db.String(200), nullable=False, default='', server_default='')
    description = db.Column(db.Text, nullable=False, default='', server_default='')
    source = db.Column(db.String(500), nullable=False, default='', server_default='')
    creator_membership_id = db.Column(
        db.Integer, db.ForeignKey(
            'household_memberships.id', name='fk_planned_meals_creator_membership',
            ondelete='SET NULL',
        ), nullable=True, index=True,
    )
    creator_membership = db.relationship('HouseholdMembership')
    date = db.Column(db.Date, nullable=False, index=True)
    slot = db.Column(db.String(10), nullable=False, default='dinner', server_default='dinner')
    notes = db.Column(db.Text, nullable=False, default='', server_default='')
    meal = db.relationship('Meal')
