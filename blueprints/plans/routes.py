from datetime import date

from flask import flash, jsonify, redirect, render_template, request, url_for

from extensions import db
from models.plans import Plan, PlanItem
from models.transactions import Transaction
from services.planning.plan_link_service import PlanLinkService
from services.planning.plan_service import PlanService, PLAN_TYPES
from utils.assignment_helpers import get_assignment_options
from utils.db_helpers import family_get_or_404

from . import plans_bp


@plans_bp.route('/plans')
def index():
    plans = PlanService.list_plans()
    return render_template(
        'plans/index.html',
        plans=plans,
        plan_types=PLAN_TYPES,
        today=date.today(),
    )


@plans_bp.route('/plans/add', methods=['POST'])
def add_plan():
    try:
        plan = PlanService.create_plan(request.form)
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Check the date and amount, then try again.', 'danger')
        return redirect(url_for('plans.index'))

    flash(f'{plan.title} created.', 'success')
    return redirect(url_for('plans.detail', plan_id=plan.id))


@plans_bp.route('/plans/<int:plan_id>')
def detail(plan_id):
    plan = family_get_or_404(Plan, plan_id)
    return render_template(
        'plans/detail.html',
        plan=plan,
        plan_types=PLAN_TYPES,
        assignment_options=get_assignment_options(),
        today=date.today(),
    )


@plans_bp.route('/plans/api/transactions')
def transaction_search():
    search = request.args.get('q', '').strip()
    plan_type = request.args.get('plan_type', 'occasion')
    if not search:
        return jsonify([])
    return jsonify(PlanService.search_transactions(search, plan_type))


@plans_bp.route('/plans/<int:plan_id>/update', methods=['POST'])
def update_plan(plan_id):
    plan = family_get_or_404(Plan, plan_id)
    try:
        PlanService.update_plan(plan, request.form)
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Check the date and amounts, then try again.', 'danger')
        return redirect(url_for('plans.detail', plan_id=plan.id))

    flash('Plan updated.', 'success')
    return redirect(url_for('plans.detail', plan_id=plan.id))


@plans_bp.route('/plans/<int:plan_id>/delete', methods=['POST'])
def delete_plan(plan_id):
    plan = family_get_or_404(Plan, plan_id)
    PlanService.delete_plan(plan)
    flash('Plan deleted.', 'success')
    return redirect(url_for('plans.index'))


@plans_bp.route('/plans/<int:plan_id>/items/add', methods=['POST'])
def add_item(plan_id):
    plan = family_get_or_404(Plan, plan_id)
    try:
        item = PlanService.add_item(plan, request.form)
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Check the item amounts and options, then try again.', 'danger')
        return redirect(url_for('plans.detail', plan_id=plan.id))

    flash(f'{item.title} added.', 'success')
    return redirect(url_for('plans.detail', plan_id=plan.id))


@plans_bp.route('/plans/<int:plan_id>/items/<int:item_id>/update', methods=['POST'])
def update_item(plan_id, item_id):
    plan = family_get_or_404(Plan, plan_id)
    item = family_get_or_404(PlanItem, item_id)
    if item.plan_id != plan.id:
        flash('That item does not belong to this plan.', 'danger')
        return redirect(url_for('plans.detail', plan_id=plan.id))

    try:
        PlanService.update_item(item, request.form)
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Check the item details and try again.', 'danger')

    return redirect(url_for('plans.detail', plan_id=plan.id))


@plans_bp.route('/plans/<int:plan_id>/items/<int:item_id>/delete', methods=['POST'])
def delete_item(plan_id, item_id):
    plan = family_get_or_404(Plan, plan_id)
    item = family_get_or_404(PlanItem, item_id)
    if item.plan_id != plan.id:
        flash('That item does not belong to this plan.', 'danger')
        return redirect(url_for('plans.detail', plan_id=plan.id))
    PlanService.delete_item(item)
    flash('Item removed.', 'success')
    return redirect(url_for('plans.detail', plan_id=plan.id))


@plans_bp.route('/plans/transactions/<int:transaction_id>/link', methods=['POST'])
def link_transaction(transaction_id):
    transaction = family_get_or_404(Transaction, transaction_id)
    try:
        item = PlanLinkService.sync(transaction, request.form)
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        flash(str(error), 'danger')
        return redirect(url_for('transactions.index', id=transaction.id))

    if item is None:
        flash('Transaction unlinked from its plan item.', 'success')
        return redirect(url_for('transactions.index', id=transaction.id))
    flash(f'Transaction linked to {item.plan.title}: {item.title}.', 'success')
    return redirect(url_for('transactions.index', id=transaction.id))

