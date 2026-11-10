from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from services.household.calendar_service import CalendarService
from services.household.task_service import COLOURS, FILTERS, ICONS, TaskService
from . import household_bp


@household_bp.route('/tasks')
@login_required
def tasks():
    try:
        context = TaskService.hub(request.args)
    except (ValueError, TypeError) as error:
        flash(str(error) or 'Invalid task filter.', 'danger')
        return redirect(url_for('household.tasks'))
    return render_template('household/tasks.html', **context)


def _list_form(task_list=None):
    CalendarService.require_access()
    if task_list is not None and not TaskService.can_manage_list(task_list):
        abort(403)
    if request.method == 'POST':
        try:
            saved = TaskService.update_list(task_list.id, request.form) if task_list else TaskService.create_list(request.form)
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Invalid task list.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Unable to save household task list')
            flash('Unable to save the task list. No changes were saved.', 'danger')
        else:
            flash('Task list saved.', 'success')
            return redirect(url_for('household.tasks', list_id=saved.id))
    return render_template(
        'household/task_list_form.html', task_list=task_list, icons=ICONS, colours=COLOURS,
        is_child=current_user.is_managed_child,
        submitted=request.form if request.method == 'POST' else {},
    )


@household_bp.route('/tasks/lists/new', methods=['GET', 'POST'])
@login_required
def create_task_list():
    return _list_form()


@household_bp.route('/tasks/lists/<int:list_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_task_list(list_id):
    return _list_form(TaskService.get_list(list_id))


@household_bp.route('/tasks/lists/<int:list_id>/delete', methods=['POST'])
@login_required
def delete_task_list(list_id):
    try:
        TaskService.delete_list(list_id)
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Invalid task list deletion.', 'danger')
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to delete household task list')
        flash('Unable to delete the task list. No changes were saved.', 'danger')
    else:
        flash('Task list and its tasks deleted.', 'success')
    return redirect(url_for('household.tasks'))


def _task_form(task=None):
    CalendarService.require_access()
    if request.method == 'POST':
        try:
            saved = TaskService.update_task(task.id, request.form) if task else TaskService.create_task(request.form)
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Invalid task details.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Unable to save household task')
            flash('Unable to save the task. No changes were saved.', 'danger')
        else:
            flash('Task saved.', 'success')
            return redirect(url_for('household.task', task_id=saved.id))
    context = TaskService.form_data(task)
    submitted = request.form if request.method == 'POST' else {}
    if task is None and request.method == 'GET':
        if request.args.get('list_id'):
            selected = TaskService.get_list(request.args['list_id'])
            if not TaskService.can_manage_list(selected):
                abort(403)
            submitted = {'list_id': str(selected.id)}
        if request.args.get('date'):
            try:
                due_date = TaskService.parse_date(request.args['date'])
            except (ValueError, TypeError) as error:
                flash(str(error), 'danger')
                return redirect(url_for('household.tasks'))
            submitted = {**submitted, 'due_date': due_date.isoformat()}
    return render_template('household/task.html', **context, submitted=submitted)


@household_bp.route('/tasks/new', methods=['GET', 'POST'])
@login_required
def create_task():
    return _task_form()


@household_bp.route('/tasks/<int:task_id>', methods=['GET', 'POST'])
@login_required
def task(task_id):
    return _task_form(TaskService.get_task(task_id))


@household_bp.route('/tasks/<int:task_id>/completion', methods=['POST'])
@login_required
def complete_task(task_id):
    task = TaskService.get_task(task_id)
    filt = request.form.get('filter') or 'active'
    try:
        if filt not in FILTERS:
            raise ValueError('Choose a supported task filter.')
        TaskService.set_completion(task_id, request.form)
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Invalid completion action.', 'danger')
        return redirect(url_for('household.task', task_id=task_id))
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to change household task completion')
        flash('Unable to change task completion. No changes were saved.', 'danger')
        return redirect(url_for('household.task', task_id=task_id))
    flash('Task completed.' if task.completed else 'Task reopened.', 'success')
    return redirect(url_for('household.tasks', list_id=task.list_id, filter=filt))


@household_bp.route('/tasks/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    try:
        list_id = TaskService.delete_task(task_id)
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Invalid task deletion.', 'danger')
        return redirect(url_for('household.task', task_id=task_id))
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to delete household task')
        flash('Unable to delete the task. No changes were saved.', 'danger')
        return redirect(url_for('household.task', task_id=task_id))
    flash('Task deleted.', 'success')
    return redirect(url_for('household.tasks', list_id=list_id))
