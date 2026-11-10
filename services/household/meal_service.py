from datetime import date, datetime

from flask import abort
from flask_login import current_user
from sqlalchemy import case
from sqlalchemy.orm import joinedload

from extensions import db
from models.meals import Meal, PlannedMeal
from services.household.calendar_service import LONDON
from services.household.membership_service import HouseholdMembershipService
from services.household.planner_helpers import planner_period, planner_values, planner_view
from services.platform.module_access_service import ModuleAccessService
from utils.db_helpers import family_get, family_get_or_404, family_query, get_family_id


SLOTS = {'breakfast': 'Breakfast', 'lunch': 'Lunch', 'dinner': 'Dinner'}


class MealService:
    @staticmethod
    def require_access():
        if not ModuleAccessService.can_access(current_user, 'household'):
            abort(403)

    @staticmethod
    def can_manage():
        return (
            ModuleAccessService.can_access(current_user, 'household')
            and not current_user.is_managed_child
        )

    @staticmethod
    def require_manage():
        if not MealService.can_manage():
            abort(403)

    @staticmethod
    def parse_date(value):
        try:
            selected = date.fromisoformat(value)
        except (ValueError, TypeError) as error:
            raise ValueError('Choose a valid meal date.') from error
        if not 1900 <= selected.year <= 2100:
            raise ValueError('Choose a meal date between 1900 and 2100.')
        return selected

    @staticmethod
    def library(data):
        MealService.require_access()
        status = data.get('status') or 'active'
        if status not in ('active', 'archived'):
            raise ValueError('Choose active or archived meals.')
        return dict(
            meals=family_query(Meal).filter_by(is_archived=status == 'archived')
            .order_by(Meal.name, Meal.id).all(),
            status=status, can_manage=MealService.can_manage(),
        )

    @staticmethod
    def get_meal(meal_id):
        MealService.require_access()
        return family_get_or_404(Meal, meal_id)

    @staticmethod
    def _meal_values(data):
        values = {
            key: (data.get(key) or '').strip()
            for key in ('name', 'ingredients', 'instructions', 'source')
        }
        if not values['name'] or len(values['name']) > 200:
            raise ValueError('Enter a meal name of up to 200 characters.')
        if len(values['ingredients']) > 10000 or len(values['instructions']) > 10000:
            raise ValueError('Use up to 10,000 characters each for ingredients and instructions.')
        if len(values['source']) > 500:
            raise ValueError('Use up to 500 characters for the recipe source.')
        return values

    @staticmethod
    def create_meal(data):
        MealService.require_manage()
        meal = Meal(family_id=get_family_id(), **MealService._meal_values(data))
        db.session.add(meal)
        db.session.commit()
        return meal

    @staticmethod
    def update_meal(meal_id, data):
        MealService.require_manage()
        meal = MealService.get_meal(meal_id)
        values = MealService._meal_values(data)
        for key, value in values.items():
            setattr(meal, key, value)
        db.session.commit()
        return meal

    @staticmethod
    def set_archived(meal_id, data):
        MealService.require_manage()
        meal = MealService.get_meal(meal_id)
        action = data.get('action')
        if action not in ('archive', 'restore'):
            raise ValueError('Choose archive or restore.')
        meal.is_archived = action == 'archive'
        db.session.commit()
        return meal

    @staticmethod
    def plans_between(first, last):
        MealService.require_access()
        return family_query(PlannedMeal).outerjoin(Meal).filter(
            (PlannedMeal.meal_id.is_(None)) | (Meal.family_id == get_family_id()),
            PlannedMeal.date >= first, PlannedMeal.date <= last,
        ).options(
            joinedload(PlannedMeal.meal),
            joinedload(PlannedMeal.creator_membership),
        ).order_by(
            PlannedMeal.date,
            case({slot: index for index, slot in enumerate(SLOTS)}, value=PlannedMeal.slot),
            PlannedMeal.id,
        ).all()

    @staticmethod
    def get_plan(plan_id):
        MealService.require_access()
        plan = family_get_or_404(PlannedMeal, plan_id)
        if plan.meal_id is not None and family_get(Meal, plan.meal_id) is None:
            abort(404)
        return plan

    @staticmethod
    def _plan_values(data, existing=None):
        selected = MealService.parse_date(data.get('date'))
        slot = data.get('slot')
        if slot not in SLOTS:
            raise ValueError('Choose breakfast, lunch or dinner.')
        notes = (data.get('notes') or '').strip()
        if len(notes) > 2000:
            raise ValueError('Use up to 2,000 characters for planning notes.')
        meal_id = data.get('meal_id', existing.meal_id if existing else None)
        meal = None
        if meal_id not in (None, ''):
            try:
                meal = family_get(Meal, meal_id)
            except ValueError as error:
                raise ValueError('Choose a meal from your household library.') from error
            if meal is None:
                raise ValueError('Choose a meal from your household library.')
            if meal.is_archived and (existing is None or existing.meal_id != meal.id):
                raise ValueError('Restore this archived meal before adding it to a plan.')
        changed_recipe = meal is not None and (existing is None or existing.meal_id != meal.id)
        defaults = {
            'title': meal.name if changed_recipe else existing.title if existing else '',
            'description': meal.instructions if changed_recipe else existing.description if existing else '',
            'source': meal.source if changed_recipe else existing.source if existing else '',
        }
        details = {key: (data.get(key, default) or '').strip() for key, default in defaults.items()}
        if not details['title'] or len(details['title']) > 200:
            raise ValueError('Enter a meal title of up to 200 characters.')
        if len(details['description']) > 10000:
            raise ValueError('Use up to 10,000 characters for the meal description.')
        if len(details['source']) > 500:
            raise ValueError('Use up to 500 characters for the recipe source.')
        return dict(
            date=selected, slot=slot, notes=notes, meal_id=meal.id if meal else None, **details,
        )

    @staticmethod
    def create_plan(data):
        MealService.require_manage()
        membership = HouseholdMembershipService.get_membership(current_user)
        plan = PlannedMeal(
            family_id=get_family_id(), creator_membership_id=membership.id,
            **MealService._plan_values(data),
        )
        db.session.add(plan)
        db.session.commit()
        return plan

    @staticmethod
    def update_plan(plan_id, data):
        MealService.require_manage()
        plan = MealService.get_plan(plan_id)
        values = MealService._plan_values(data, plan)
        for key, value in values.items():
            setattr(plan, key, value)
        db.session.commit()
        return plan

    @staticmethod
    def remove_plan(plan_id):
        MealService.require_manage()
        plan = MealService.get_plan(plan_id)
        selected = plan.date
        db.session.delete(plan)
        db.session.commit()
        return selected

    @staticmethod
    def planner(data):
        MealService.require_access()
        context = planner_period(data, MealService.parse_date)
        plans = MealService.plans_between(context['first'], context['last'])
        return dict(
            **context, slots=SLOTS,
            plans_by_slot={
                (day, slot): [plan for plan in plans if plan.date == day and plan.slot == slot]
                for day in context['days'] for slot in SLOTS
            },
            meals=family_query(Meal).filter_by(is_archived=False).order_by(Meal.name, Meal.id).all(),
            can_manage=MealService.can_manage(),
            meal_service=MealService, plan=None, submitted={},
        )

    @staticmethod
    def planner_view(data):
        return planner_view(data)

    @staticmethod
    def planner_values(selected, view):
        return planner_values(selected, view)

    @staticmethod
    def plan_form(plan=None, data=None):
        MealService.require_access()
        data = data if data is not None else {}
        view = MealService.planner_view(data)
        selected = MealService.parse_date(
            data.get('date') or (plan.date.isoformat() if plan else datetime.now(LONDON).date().isoformat()),
        )
        meals = family_query(Meal).filter(
            (Meal.is_archived.is_(False)) | (Meal.id == plan.meal_id if plan else False),
        ).order_by(Meal.name, Meal.id).all()
        return dict(
            plan=plan, meals=meals, slots=SLOTS, can_manage=MealService.can_manage(),
            selected=selected, view=view, meal_service=MealService,
        )
