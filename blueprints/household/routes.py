from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from services.household.calendar_service import CalendarService
from services.household.my_day_service import MyDayService
from . import household_bp


@household_bp.route('/my-day')
@login_required
def my_day():
    return render_template('household/my_day.html', **MyDayService.page_data())


def _event_data():
    data = request.form.to_dict()
    for action in ('edit', 'delete'):
        if f'{action}_policy' in data:
            data[f'{action}_members'] = request.form.getlist(f'{action}_members')
    return data


@household_bp.route('/')
@login_required
def calendar():
    try:
        context = CalendarService.page_data(request.args)
    except (ValueError, TypeError) as error:
        flash(str(error) or 'Invalid calendar selection.', 'danger')
        return redirect(url_for('household.calendar'))
    return render_template('household/calendar.html', **context)


@household_bp.route('/settings')
@login_required
def settings():
    return render_template('household/settings.html')


@household_bp.route('/events/new', methods=['GET', 'POST'])
@login_required
def create_event():
    if request.method == 'POST':
        try:
            event = CalendarService.create(_event_data())
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Invalid event details.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Unable to create calendar event')
            flash('Unable to save the event. No changes were saved.', 'danger')
        else:
            flash('Calendar event created.', 'success')
            return redirect(url_for('household.event', event_id=event.id))
    return render_template(
        'household/event_form.html', **CalendarService.form_data(),
        submitted=_event_data() if request.method == 'POST' else None,
    )


@household_bp.route('/events/<int:event_id>')
@login_required
def event(event_id):
    event = CalendarService.get(event_id)
    return render_template('household/event.html', event=event, calendar_service=CalendarService)


@household_bp.route('/events/<int:event_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_event(event_id):
    from flask import abort
    event = CalendarService.get(event_id)
    if not CalendarService.can_act(event, 'edit'):
        abort(403)
    if request.method == 'POST':
        try:
            CalendarService.update(event_id, _event_data())
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Invalid event details.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Unable to update calendar event')
            flash('Unable to save the event. No changes were saved.', 'danger')
        else:
            flash('Calendar event updated.', 'success')
            return redirect(url_for('household.event', event_id=event.id))
    return render_template(
        'household/event_form.html', **CalendarService.form_data(event),
        submitted=_event_data() if request.method == 'POST' else None,
    )


@household_bp.route('/events/<int:event_id>/delete', methods=['POST'])
@login_required
def delete_event(event_id):
    try:
        CalendarService.delete(event_id)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to delete calendar event')
        flash('Unable to delete the event. No changes were saved.', 'danger')
        return redirect(url_for('household.event', event_id=event_id))
    flash('Calendar event deleted.', 'success')
    return redirect(url_for('household.calendar'))
