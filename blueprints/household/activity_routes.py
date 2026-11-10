from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from services.household.activity_service import ActivityService
from services.household.planner_helpers import planner_values, planner_view
from . import household_bp


def _activity_data():
    data = request.form.to_dict()
    data['attendee_ids'] = request.form.getlist('attendee_ids')
    return data


@household_bp.route('/activities')
@login_required
def activity_planner():
    try:
        context = ActivityService.planner(request.args)
    except (ValueError, TypeError) as error:
        flash(str(error) or 'Invalid activity planner date.', 'danger')
        return redirect(url_for('household.activity_planner'))
    return render_template('household/activity_planner.html', **context, planner_values=planner_values)


@household_bp.route('/activities/new', methods=['GET', 'POST'])
@login_required
def create_activity():
    view = 'week'
    if request.method == 'POST':
        try:
            view = planner_view(request.form)
            activity = ActivityService.create(_activity_data())
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Invalid activity details.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Unable to create household activity')
            flash('Unable to save the activity. No changes were saved.', 'danger')
        else:
            flash('Activity published.' if activity.status == 'approved' else 'Suggestion sent for adult approval.', 'success')
            return redirect(url_for('household.activity', activity_id=activity.id, view=view))
        context = ActivityService.form_data(data={'view': view})
    else:
        try:
            context = ActivityService.form_data(data=request.args)
        except (ValueError, TypeError) as error:
            flash(str(error) or 'Invalid activity date.', 'danger')
            return redirect(url_for('household.activity_planner'))
    return render_template(
        'household/activity.html', **context,
        submitted=_activity_data() if request.method == 'POST' else {},
        planner_values=planner_values,
    )


@household_bp.route('/activities/<int:activity_id>', methods=['GET', 'POST'])
@login_required
def activity(activity_id):
    activity = ActivityService.get(activity_id)
    try:
        view = planner_view(request.form if request.method == 'POST' else request.args)
    except ValueError as error:
        flash(str(error), 'danger')
        return redirect(url_for('household.activity', activity_id=activity_id))
    if request.method == 'POST':
        try:
            ActivityService.update(activity_id, _activity_data())
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Invalid activity details.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Unable to update household activity')
            flash('Unable to save the activity. No changes were saved.', 'danger')
        else:
            flash('Activity saved.' if activity.status == 'approved' else 'Suggestion saved for adult approval.', 'success')
            return redirect(url_for('household.activity', activity_id=activity_id, view=view))
    return render_template(
        'household/activity.html', **ActivityService.form_data(activity, {'view': view}),
        submitted=_activity_data() if request.method == 'POST' else {},
        planner_values=planner_values,
    )


@household_bp.route('/activities/<int:activity_id>/review', methods=['POST'])
@login_required
def review_activity(activity_id):
    ActivityService.require_manage()
    try:
        view = planner_view(request.form)
        activity = ActivityService.review(activity_id, request.form)
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Invalid activity review.', 'danger')
        view = 'week'
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to review household activity')
        flash('Unable to review the suggestion. No changes were saved.', 'danger')
        view = 'week'
    else:
        flash('Suggestion approved and added to the calendar.' if activity.status == 'approved' else 'Suggestion rejected.', 'success')
    return redirect(url_for('household.activity', activity_id=activity_id, view=view))


@household_bp.route('/activities/<int:activity_id>/delete', methods=['POST'])
@login_required
def delete_activity(activity_id):
    try:
        view = planner_view(request.form)
        selected = ActivityService.delete(activity_id)
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Invalid activity deletion.', 'danger')
        return redirect(url_for('household.activity', activity_id=activity_id))
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to delete household activity')
        flash('Unable to delete the activity. No changes were saved.', 'danger')
        return redirect(url_for('household.activity', activity_id=activity_id))
    flash('Activity and its entire series removed.', 'success')
    return redirect(url_for('household.activity_planner', **planner_values(selected, view)))
