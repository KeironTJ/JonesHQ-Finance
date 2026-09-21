from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import flash, jsonify, redirect, render_template, request, url_for

from extensions import db
from models.plans import Plan, PlanItem
from models.transactions import Transaction
from models.vendors import Vendor
from utils.db_helpers import family_get, family_get_or_404, family_query, get_family_id

from . import plans_bp


PLAN_TYPES = {
    'occasion': 'Occasion',
    'wish_list': 'Wish list',
    'savings_goal': 'Savings goal',
    'other': 'Other',
}
PLAN_STATUSES = {'active', 'draft', 'completed', 'archived'}
ITEM_STATUSES = {'idea', 'planned', 'purchased', 'skipped'}
ITEM_PRIORITIES = {'low', 'normal', 'high'}


def _date_value(value):
    return datetime.strptime(value, '%Y-%m-%d').date() if value else None


def _money_value(value):
    if not value:
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('Enter a valid amount.') from exc
    if amount < 0:
        raise ValueError('Amounts cannot be negative.')
    return amount


def _link_transaction(item, transaction):
    if transaction is not None:
        existing_items = family_query(PlanItem).filter(
            PlanItem.transaction_id == transaction.id,
            PlanItem.id != item.id,
        ).all()
        for existing_item in existing_items:
            existing_item.transaction = None
    item.transaction = transaction


@plans_bp.route('/plans')
def index():
    plans = family_query(Plan).order_by(
        Plan.status == 'archived',
        Plan.target_date.is_(None),
        Plan.target_date,
        Plan.created_at.desc(),
    ).all()
    return render_template(
        'plans/index.html',
        plans=plans,
        plan_types=PLAN_TYPES,
        today=date.today(),
    )


@plans_bp.route('/plans/add', methods=['POST'])
def add_plan():
    title = request.form.get('title', '').strip()
    if not title:
        flash('Give the plan a name.', 'danger')
        return redirect(url_for('plans.index'))

    plan_type = request.form.get('plan_type', 'occasion')
    if plan_type not in PLAN_TYPES:
        plan_type = 'other'

    try:
        plan = Plan(
            family_id=get_family_id(),
            title=title,
            plan_type=plan_type,
            person=request.form.get('person', '').strip() or None,
            target_date=_date_value(request.form.get('target_date')),
            target_amount=_money_value(request.form.get('target_amount')),
            notes=request.form.get('notes', '').strip() or None,
        )
        db.session.add(plan)
        db.session.commit()
    except (ValueError, TypeError):
        db.session.rollback()
        flash('Check the date and amount, then try again.', 'danger')
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
        today=date.today(),
    )


@plans_bp.route('/plans/api/transactions')
def transaction_search():
    search = request.args.get('q', '').strip()
    plan_type = request.args.get('plan_type', 'occasion')
    if not search:
        return jsonify([])

    query = family_query(Transaction).filter(
        Transaction.is_forecasted.is_(False),
    )
    if plan_type != 'savings_goal':
        query = query.filter(Transaction.amount < 0)
    query = query.outerjoin(Vendor, Transaction.vendor_id == Vendor.id)
    matches = [
        Transaction.description.ilike(f'%{search}%'),
        Transaction.item.ilike(f'%{search}%'),
        Vendor.name.ilike(f'%{search}%'),
    ]
    try:
        amount = Decimal(search.replace('£', '').replace(',', ''))
        matches.append(db.func.abs(Transaction.amount) == abs(amount))
    except InvalidOperation:
        pass
    for date_format in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            matches.append(Transaction.transaction_date == datetime.strptime(search, date_format).date())
            break
        except ValueError:
            continue
    query = query.filter(db.or_(*matches))
    transactions = query.order_by(
        Transaction.transaction_date.desc(),
        Transaction.id.desc(),
    ).limit(30).all()
    linked_items = family_query(PlanItem).filter(
        PlanItem.transaction_id.in_([transaction.id for transaction in transactions]),
    ).all() if transactions else []
    links = {item.transaction_id: item for item in linked_items}
    return jsonify([
        {
            'id': transaction.id,
            'label': (
                f"{transaction.transaction_date.strftime('%d %b %Y')} · "
                f"{transaction.item or transaction.description or 'Transaction'} · "
                f"{'+' if transaction.amount > 0 else '-'}£{abs(transaction.amount):.2f}"
                f"{' · ' + transaction.vendor.name if transaction.vendor else ''}"
                f"{' · ' + transaction.account.name if transaction.account else ''}"
            ),
            'linked_to': (
                f'{links[transaction.id].plan.title}: {links[transaction.id].title}'
                if transaction.id in links else None
            ),
        }
        for transaction in transactions
    ])


@plans_bp.route('/plans/<int:plan_id>/update', methods=['POST'])
def update_plan(plan_id):
    plan = family_get_or_404(Plan, plan_id)
    title = request.form.get('title', '').strip()
    status = request.form.get('status', 'active')
    plan_type = request.form.get('plan_type', 'occasion')
    if not title or status not in PLAN_STATUSES or plan_type not in PLAN_TYPES:
        flash('Check the plan details and try again.', 'danger')
        return redirect(url_for('plans.detail', plan_id=plan.id))

    try:
        plan.title = title
        plan.plan_type = plan_type
        plan.person = request.form.get('person', '').strip() or None
        plan.target_date = _date_value(request.form.get('target_date'))
        plan.target_amount = _money_value(request.form.get('target_amount'))
        plan.saved_amount = _money_value(request.form.get('saved_amount')) or Decimal('0')
        plan.status = status
        plan.notes = request.form.get('notes', '').strip() or None
        db.session.commit()
    except (ValueError, TypeError):
        db.session.rollback()
        flash('Check the date and amounts, then try again.', 'danger')
        return redirect(url_for('plans.detail', plan_id=plan.id))

    flash('Plan updated.', 'success')
    return redirect(url_for('plans.detail', plan_id=plan.id))


@plans_bp.route('/plans/<int:plan_id>/delete', methods=['POST'])
def delete_plan(plan_id):
    plan = family_get_or_404(Plan, plan_id)
    db.session.delete(plan)
    db.session.commit()
    flash('Plan deleted.', 'success')
    return redirect(url_for('plans.index'))


@plans_bp.route('/plans/<int:plan_id>/items/add', methods=['POST'])
def add_item(plan_id):
    plan = family_get_or_404(Plan, plan_id)
    title = request.form.get('title', '').strip()
    if not title:
        flash('Give the item a name.', 'danger')
        return redirect(url_for('plans.detail', plan_id=plan.id))

    transaction_id = request.form.get('transaction_id')
    transaction = family_get(Transaction, int(transaction_id)) if transaction_id else None
    if transaction_id and transaction is None:
        flash('That transaction is not available.', 'danger')
        return redirect(url_for('plans.detail', plan_id=plan.id))

    try:
        item = PlanItem(
            family_id=get_family_id(),
            plan_id=plan.id,
            title=title,
            estimated_cost=_money_value(request.form.get('estimated_cost')),
            actual_cost=_money_value(request.form.get('actual_cost')),
            priority=request.form.get('priority', 'normal'),
            status=request.form.get('status', 'idea'),
            notes=request.form.get('notes', '').strip() or None,
        )
        if item.priority not in ITEM_PRIORITIES or item.status not in ITEM_STATUSES:
            raise ValueError('Invalid item state.')
        _link_transaction(item, transaction)
        db.session.add(item)
        db.session.commit()
    except (ValueError, TypeError):
        db.session.rollback()
        flash('Check the item amounts and options, then try again.', 'danger')
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

    transaction_id = request.form.get('transaction_id')
    transaction = family_get(Transaction, int(transaction_id)) if transaction_id else None
    if transaction_id and transaction is None:
        flash('That transaction is not available.', 'danger')
        return redirect(url_for('plans.detail', plan_id=plan.id))

    try:
        title = request.form.get('title', '').strip()
        status = request.form.get('status', 'idea')
        priority = request.form.get('priority', 'normal')
        if not title or status not in ITEM_STATUSES or priority not in ITEM_PRIORITIES:
            raise ValueError('Invalid item details.')
        item.title = title
        item.estimated_cost = _money_value(request.form.get('estimated_cost'))
        item.actual_cost = _money_value(request.form.get('actual_cost'))
        _link_transaction(item, transaction)
        item.status = status
        item.priority = priority
        item.notes = request.form.get('notes', '').strip() or None
        db.session.commit()
    except (ValueError, TypeError):
        db.session.rollback()
        flash('Check the item details and try again.', 'danger')

    return redirect(url_for('plans.detail', plan_id=plan.id))


@plans_bp.route('/plans/<int:plan_id>/items/<int:item_id>/delete', methods=['POST'])
def delete_item(plan_id, item_id):
    plan = family_get_or_404(Plan, plan_id)
    item = family_get_or_404(PlanItem, item_id)
    if item.plan_id != plan.id:
        flash('That item does not belong to this plan.', 'danger')
        return redirect(url_for('plans.detail', plan_id=plan.id))
    db.session.delete(item)
    db.session.commit()
    flash('Item removed.', 'success')
    return redirect(url_for('plans.detail', plan_id=plan.id))


@plans_bp.route('/plans/transactions/<int:transaction_id>/link', methods=['POST'])
def link_transaction(transaction_id):
    transaction = family_get_or_404(Transaction, transaction_id)
    item_id = request.form.get('item_id', type=int)
    plan_id = request.form.get('plan_id', type=int)
    new_item_title = request.form.get('new_item_title', '').strip()

    if new_item_title:
        plan = family_get_or_404(Plan, plan_id)
        item = PlanItem(
            family_id=get_family_id(),
            plan_id=plan.id,
            title=new_item_title,
            estimated_cost=abs(Decimal(str(transaction.amount))),
            status='purchased',
        )
        db.session.add(item)
    elif item_id:
        item = family_get_or_404(PlanItem, item_id)
    else:
        linked_items = family_query(PlanItem).filter_by(transaction_id=transaction.id).all()
        for linked_item in linked_items:
            linked_item.transaction = None
        db.session.commit()
        flash('Transaction unlinked from its plan item.', 'success')
        return redirect(url_for('transactions.index', id=transaction.id))

    _link_transaction(item, transaction)
    db.session.commit()
    flash(f'Transaction linked to {item.plan.title}: {item.title}.', 'success')
    return redirect(url_for('transactions.index', id=transaction.id))
