from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from services.household.meal_service import MealService
from . import household_bp


@household_bp.route('/meals')
@login_required
def meals():
    try:
        context = MealService.library(request.args)
    except (ValueError, TypeError) as error:
        flash(str(error) or 'Invalid meal filter.', 'danger')
        return redirect(url_for('household.meals'))
    return render_template('household/meals.html', **context)


@household_bp.route('/meals/new', methods=['GET', 'POST'])
@login_required
def create_meal():
    MealService.require_manage()
    if request.method == 'POST':
        try:
            meal = MealService.create_meal(request.form)
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Invalid meal details.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Unable to create household meal')
            flash('Unable to save the meal. No changes were saved.', 'danger')
        else:
            flash('Meal added to the household library.', 'success')
            return redirect(url_for('household.meal', meal_id=meal.id))
    return render_template(
        'household/meal_form.html', meal=None,
        submitted=request.form if request.method == 'POST' else {},
    )


@household_bp.route('/meals/<int:meal_id>')
@login_required
def meal(meal_id):
    return render_template(
        'household/meal.html', meal=MealService.get_meal(meal_id),
        can_manage=MealService.can_manage(),
    )


@household_bp.route('/meals/<int:meal_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_meal(meal_id):
    MealService.require_manage()
    meal = MealService.get_meal(meal_id)
    if request.method == 'POST':
        try:
            MealService.update_meal(meal_id, request.form)
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Invalid meal details.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Unable to update household meal')
            flash('Unable to save the meal. No changes were saved.', 'danger')
        else:
            flash('Household meal updated.', 'success')
            return redirect(url_for('household.meal', meal_id=meal.id))
    return render_template(
        'household/meal_form.html', meal=meal,
        submitted=request.form if request.method == 'POST' else {},
    )


@household_bp.route('/meals/<int:meal_id>/archive', methods=['POST'])
@login_required
def archive_meal(meal_id):
    try:
        meal = MealService.set_archived(meal_id, request.form)
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Invalid archive action.', 'danger')
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to change household meal archive status')
        flash('Unable to change the meal. No changes were saved.', 'danger')
    else:
        flash('Meal archived. Existing plans are kept.' if meal.is_archived else 'Meal restored.', 'success')
    return redirect(url_for('household.meal', meal_id=meal_id))


@household_bp.route('/meal-planner')
@login_required
def meal_planner():
    try:
        context = MealService.planner(request.args)
    except (ValueError, TypeError) as error:
        flash(str(error) or 'Invalid planner week.', 'danger')
        return redirect(url_for('household.meal_planner'))
    return render_template('household/meal_planner.html', **context)


@household_bp.route('/meal-planner/add', methods=['GET', 'POST'])
@login_required
def add_planned_meal():
    MealService.require_manage()
    view = 'week'
    if request.method == 'POST':
        try:
            view = MealService.planner_view(request.form)
            plan = MealService.create_plan(request.form)
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Invalid meal plan.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Unable to add planned meal')
            flash('Unable to plan the meal. No changes were saved.', 'danger')
        else:
            flash('Meal added to the plan.', 'success')
            return redirect(url_for(
                'household.meal_planner', **MealService.planner_values(plan.date, view),
            ))
        context = MealService.plan_form(data={'view': view})
    else:
        try:
            context = MealService.plan_form(data=request.args)
        except (ValueError, TypeError) as error:
            flash(str(error) or 'Invalid meal date.', 'danger')
            return redirect(url_for('household.meal_planner'))
    return render_template(
        'household/planned_meal.html', **context,
        submitted=request.form if request.method == 'POST' else {},
    )


@household_bp.route('/meal-planner/<int:plan_id>', methods=['GET', 'POST'])
@login_required
def planned_meal(plan_id):
    if request.method == 'POST':
        MealService.require_manage()
    plan = MealService.get_plan(plan_id)
    try:
        view = MealService.planner_view(request.form if request.method == 'POST' else request.args)
    except ValueError as error:
        flash(str(error), 'danger')
        return redirect(url_for('household.planned_meal', plan_id=plan_id))
    if request.method == 'POST':
        try:
            MealService.update_plan(plan_id, request.form)
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Invalid meal plan.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Unable to update planned meal')
            flash('Unable to change the plan. No changes were saved.', 'danger')
        else:
            flash('Planned meal updated.', 'success')
            return redirect(url_for(
                'household.meal_planner', **MealService.planner_values(plan.date, view),
            ))
    return render_template(
        'household/planned_meal.html', **MealService.plan_form(plan, {'view': view}),
        submitted=request.form if request.method == 'POST' else {},
    )


@household_bp.route('/meal-planner/<int:plan_id>/remove', methods=['POST'])
@login_required
def remove_planned_meal(plan_id):
    MealService.require_manage()
    try:
        view = MealService.planner_view(request.form)
        selected = MealService.remove_plan(plan_id)
    except ValueError as error:
        flash(str(error), 'danger')
        return redirect(url_for('household.planned_meal', plan_id=plan_id))
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to remove planned meal')
        flash('Unable to remove the meal. No changes were saved.', 'danger')
        return redirect(url_for('household.planned_meal', plan_id=plan_id))
    flash('Meal removed from the plan.', 'success')
    return redirect(url_for('household.meal_planner', **MealService.planner_values(selected, view)))
