"""Make planned meals independent and library selection optional.

Revision ID: f94a0c6e123d
Revises: e83f9b5d012c
"""
from alembic import op
import sqlalchemy as sa


revision = 'f94a0c6e123d'
down_revision = 'e83f9b5d012c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('meals') as batch:
        batch.add_column(sa.Column('source', sa.String(500), nullable=False, server_default=''))
    with op.batch_alter_table('planned_meals') as batch:
        batch.alter_column('meal_id', existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column('title', sa.String(200), nullable=False, server_default=''))
        batch.add_column(sa.Column('description', sa.Text(), nullable=False, server_default=''))
        batch.add_column(sa.Column('source', sa.String(500), nullable=False, server_default=''))
        batch.add_column(sa.Column('creator_membership_id', sa.Integer(), nullable=True))
        batch.create_foreign_key(
            'fk_planned_meals_creator_membership', 'household_memberships',
            ['creator_membership_id'], ['id'], ondelete='SET NULL',
        )
        batch.create_index('ix_planned_meals_creator_membership_id', ['creator_membership_id'])
    connection = op.get_bind()
    meals = sa.table(
        'meals', sa.column('id'), sa.column('family_id'), sa.column('name'),
        sa.column('instructions'), sa.column('source'),
    )
    plans = sa.table(
        'planned_meals', sa.column('meal_id'), sa.column('family_id'),
        sa.column('title'), sa.column('description'), sa.column('source'),
    )
    for target, source in (
        ('title', meals.c.name), ('description', meals.c.instructions), ('source', meals.c.source),
    ):
        connection.execute(plans.update().values({
            target: sa.select(source).where(
                meals.c.id == plans.c.meal_id, meals.c.family_id == plans.c.family_id,
            ).scalar_subquery(),
        }))


def downgrade():
    connection = op.get_bind()
    metadata = sa.MetaData()
    meals = sa.Table('meals', metadata, autoload_with=connection)
    plans = sa.Table('planned_meals', metadata, autoload_with=connection)
    # Older schemas require a library entry; preserve independent details there.
    for plan in connection.execute(sa.select(plans)).mappings().all():
        instructions = plan['description']
        if plan['source']:
            instructions += '\nRecipe source: ' + plan['source']
        meal_id = connection.execute(meals.insert().values(
            family_id=plan['family_id'], name=plan['title'],
            instructions=instructions,
        )).inserted_primary_key[0]
        connection.execute(plans.update().where(plans.c.id == plan['id']).values(meal_id=meal_id))
    with op.batch_alter_table('planned_meals') as batch:
        batch.drop_index('ix_planned_meals_creator_membership_id')
        batch.drop_constraint('fk_planned_meals_creator_membership', type_='foreignkey')
        batch.drop_column('creator_membership_id')
        batch.drop_column('source')
        batch.drop_column('description')
        batch.drop_column('title')
        batch.alter_column('meal_id', existing_type=sa.Integer(), nullable=False)
    # Native DROP COLUMN avoids rebuilding a parent table referenced by plans.
    op.drop_column('meals', 'source')
