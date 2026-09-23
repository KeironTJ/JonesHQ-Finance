from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import flash, jsonify, redirect, render_template, request, url_for

from extensions import db
from models.plans import Plan, PlanItem
from models.transactions import Transaction
from models.credit_card_transactions import CreditCardTransaction
from models.credit_cards import CreditCard
from models.vendors import Vendor
from services.planning.plan_link_service import PlanLinkService
from utils.assignment_helpers import get_assignment_options
from utils.db_helpers import family_get, family_get_or_404, family_query, get_family_id, get_current_user_id

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


def _assignment_value(value):
    assigned_to = (value or '').strip()
    if not assigned_to:
        return None
    if assigned_to not in get_assignment_options():
        raise ValueError('Choose a valid family member or assignment label.')
    return assigned_to


def _link_transaction(item, transaction):
    if transaction is not None:
        existing_items = family_query(PlanItem).filter(
            PlanItem.transaction_id == transaction.id,
            PlanItem.id != item.id,
        ).all()
        for existing_item in existing_items:
            existing_item.transaction = None
    item.transaction = transaction


def _resolve_transaction_source(form):
    reference = (form.get('transaction_ref') or '').strip()
    if reference:
        try:
            source, record_id = reference.split(':', 1)
            record_id = int(record_id)
        except (ValueError, TypeError):
            raise ValueError('That transaction reference is invalid.')
        if source == 'bank':
            transaction = family_get(Transaction, record_id)
            if transaction is None:
                raise ValueError('That bank transaction is not available.')
            return transaction, None
        if source == 'card':
            transaction = family_get(CreditCardTransaction, record_id)
            if transaction is None:
                raise ValueError('That card transaction is not available.')
            return None, transaction
        raise ValueError('That transaction source is invalid.')

    transaction_id = form.get('transaction_id')
    if transaction_id:
        transaction = family_get(Transaction, int(transaction_id))
        if transaction is None:
            raise ValueError('That transaction is not available.')
        return transaction, None
    return None, None


def _link_item_source(item, bank_transaction=None, card_transaction=None):
    if bank_transaction is not None:
        _link_transaction(item, bank_transaction)
        item.credit_card_transaction = None
        return
    if card_transaction is not None:
        for existing_item in family_query(PlanItem).filter(
            PlanItem.credit_card_transaction_id == card_transaction.id,
            PlanItem.id != item.id,
        ).all():
            existing_item.credit_card_transaction = None
        item.transaction = None
        item.credit_card_transaction = card_transaction
        return
    item.transaction = None
    item.credit_card_transaction = None


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
            owner_id=get_current_user_id() if request.form.get('visibility') == 'private' else None,
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
        assignment_options=get_assignment_options(),
        today=date.today(),
    )


@plans_bp.route('/plans/api/transactions')
def transaction_search():
    search = request.args.get('q', '').strip()
    plan_type = request.args.get('plan_type', 'occasion')
    if not search:
        return jsonify([])

    bank_query = family_query(Transaction).filter(
        Transaction.is_forecasted.is_(False),
    )
    if plan_type != 'savings_goal':
        bank_query = bank_query.filter(Transaction.amount < 0)
    bank_query = bank_query.outerjoin(Vendor, Transaction.vendor_id == Vendor.id)
    bank_matches = [
        Transaction.description.ilike(f'%{search}%'),
        Transaction.item.ilike(f'%{search}%'),
        Vendor.name.ilike(f'%{search}%'),
    ]
    card_query = family_query(CreditCardTransaction).filter(
        CreditCardTransaction.transaction_type == 'Purchase',
        CreditCardTransaction.amount < 0,
    ).outerjoin(CreditCard, CreditCardTransaction.credit_card_id == CreditCard.id)
    card_matches = [
        CreditCardTransaction.item.ilike(f'%{search}%'),
        CreditCard.card_name.ilike(f'%{search}%'),
    ]
    try:
        amount = Decimal(search.replace('£', '').replace(',', ''))
        bank_matches.append(db.func.abs(Transaction.amount) == abs(amount))
        card_matches.append(db.func.abs(CreditCardTransaction.amount) == abs(amount))
    except InvalidOperation:
        pass
    for date_format in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            searched_date = datetime.strptime(search, date_format).date()
            bank_matches.append(Transaction.transaction_date == searched_date)
            card_matches.append(CreditCardTransaction.date == searched_date)
            break
        except ValueError:
            continue
    bank_transactions = bank_query.filter(db.or_(*bank_matches)).order_by(
        Transaction.transaction_date.desc(),
        Transaction.id.desc(),
    ).limit(30).all()
    card_transactions = card_query.filter(db.or_(*card_matches)).order_by(
        CreditCardTransaction.date.desc(),
        CreditCardTransaction.id.desc(),
    ).limit(30).all()
    bank_links = {
        item.transaction_id: item for item in family_query(PlanItem).filter(
            PlanItem.transaction_id.in_([transaction.id for transaction in bank_transactions]),
        ).all()
    } if bank_transactions else {}
    card_links = {
        item.credit_card_transaction_id: item for item in family_query(PlanItem).filter(
            PlanItem.credit_card_transaction_id.in_([transaction.id for transaction in card_transactions]),
        ).all()
    } if card_transactions else {}
    results = [
        {
            'id': f'bank:{transaction.id}',
            'date': transaction.transaction_date.isoformat(),
            'label': (
                f"Bank · {transaction.transaction_date.strftime('%d %b %Y')} · "
                f"{transaction.item or transaction.description or 'Transaction'} · "
                f"{'+' if transaction.amount > 0 else '-'}£{abs(transaction.amount):.2f}"
                f"{' · ' + transaction.vendor.name if transaction.vendor else ''}"
                f"{' · ' + transaction.account.name if transaction.account else ''}"
            ),
            'linked_to': (
                f'{bank_links[transaction.id].plan.title}: {bank_links[transaction.id].title}'
                if transaction.id in bank_links else None
            ),
        }
        for transaction in bank_transactions
    ]
    results.extend({
        'id': f'card:{transaction.id}',
        'date': transaction.date.isoformat(),
        'label': (
            f"Card · {transaction.date.strftime('%d %b %Y')} · "
            f"{transaction.item or 'Purchase'} · -£{abs(transaction.amount):.2f} · "
            f"{transaction.credit_card.card_name}"
        ),
        'linked_to': (
            f'{card_links[transaction.id].plan.title}: {card_links[transaction.id].title}'
            if transaction.id in card_links else None
        ),
    } for transaction in card_transactions)
    results.sort(key=lambda result: result['date'], reverse=True)
    return jsonify(results[:30])


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
        plan.owner_id = get_current_user_id() if request.form.get('visibility') == 'private' else None
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

    try:
        bank_transaction, card_transaction = _resolve_transaction_source(request.form)
    except (ValueError, TypeError) as error:
        flash(str(error), 'danger')
        return redirect(url_for('plans.detail', plan_id=plan.id))

    try:
        item = PlanItem(
            family_id=get_family_id(),
            plan_id=plan.id,
            title=title,
            assigned_to=_assignment_value(request.form.get('assigned_to')),
            estimated_cost=_money_value(request.form.get('estimated_cost')),
            actual_cost=_money_value(request.form.get('actual_cost')),
            priority=request.form.get('priority', 'normal'),
            status=request.form.get('status', 'idea'),
            notes=request.form.get('notes', '').strip() or None,
        )
        if item.priority not in ITEM_PRIORITIES or item.status not in ITEM_STATUSES:
            raise ValueError('Invalid item state.')
        _link_item_source(item, bank_transaction, card_transaction)
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

    try:
        bank_transaction, card_transaction = _resolve_transaction_source(request.form)
    except (ValueError, TypeError) as error:
        flash(str(error), 'danger')
        return redirect(url_for('plans.detail', plan_id=plan.id))

    try:
        title = request.form.get('title', '').strip()
        status = request.form.get('status', 'idea')
        priority = request.form.get('priority', 'normal')
        if not title or status not in ITEM_STATUSES or priority not in ITEM_PRIORITIES:
            raise ValueError('Invalid item details.')
        item.title = title
        item.assigned_to = _assignment_value(request.form.get('assigned_to'))
        item.estimated_cost = _money_value(request.form.get('estimated_cost'))
        item.actual_cost = _money_value(request.form.get('actual_cost'))
        _link_item_source(item, bank_transaction, card_transaction)
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
