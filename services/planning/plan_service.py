"""
Plan Service
============
CRUD and transaction-linking logic for savings goals / occasion plans (Plan, PlanItem).

Primary entry points
--------------------
  list_plans()          — all plans for the current family, ordered for the index page
  create_plan()          — new Plan from validated form data
  update_plan()          — mutate an existing Plan from form data
  delete_plan()          — remove a Plan (and its items, via cascade)
  add_item()             — new PlanItem under a Plan
  update_item()          — mutate an existing PlanItem
  delete_item()          — remove a PlanItem
  search_transactions()  — bank/credit-card transaction search for the "link a transaction" picker
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from extensions import db
from models.plans import Plan, PlanItem
from models.transactions import Transaction
from models.credit_card_transactions import CreditCardTransaction
from models.credit_cards import CreditCard
from models.vendors import Vendor
from utils.assignment_helpers import get_assignment_options
from utils.db_helpers import family_get, family_query, get_family_id, get_current_user_id


PLAN_TYPES = {
    'occasion': 'Occasion',
    'wish_list': 'Wish list',
    'savings_goal': 'Savings goal',
    'other': 'Other',
}
PLAN_STATUSES = {'active', 'draft', 'completed', 'archived'}
ITEM_STATUSES = {'idea', 'planned', 'purchased', 'skipped'}
ITEM_PRIORITIES = {'low', 'normal', 'high'}


class PlanService:
    @staticmethod
    def _date_value(value):
        return datetime.strptime(value, '%Y-%m-%d').date() if value else None

    @staticmethod
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

    @staticmethod
    def _assignment_value(value):
        assigned_to = (value or '').strip()
        if not assigned_to:
            return None
        if assigned_to not in get_assignment_options():
            raise ValueError('Choose a valid family member or assignment label.')
        return assigned_to

    @staticmethod
    def _link_transaction(item, transaction):
        if transaction is not None:
            for existing_item in family_query(PlanItem).filter(
                PlanItem.transaction_id == transaction.id,
                PlanItem.id != item.id,
            ).all():
                existing_item.transaction = None
        item.transaction = transaction

    @staticmethod
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

    @staticmethod
    def _link_item_source(item, bank_transaction=None, card_transaction=None):
        if bank_transaction is not None:
            PlanService._link_transaction(item, bank_transaction)
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

    @staticmethod
    def list_plans():
        return family_query(Plan).order_by(
            Plan.status == 'archived',
            Plan.target_date.is_(None),
            Plan.target_date,
            Plan.created_at.desc(),
        ).all()

    @staticmethod
    def create_plan(data):
        """Create a Plan from form data. Raises ValueError/TypeError on bad input."""
        title = (data.get('title') or '').strip()
        if not title:
            raise ValueError('Give the plan a name.')
        plan_type = data.get('plan_type', 'occasion')
        if plan_type not in PLAN_TYPES:
            plan_type = 'other'

        plan = Plan(
            family_id=get_family_id(),
            title=title,
            plan_type=plan_type,
            person=(data.get('person') or '').strip() or None,
            target_date=PlanService._date_value(data.get('target_date')),
            target_amount=PlanService._money_value(data.get('target_amount')),
            notes=(data.get('notes') or '').strip() or None,
            owner_id=get_current_user_id() if data.get('visibility') == 'private' else None,
        )
        db.session.add(plan)
        db.session.commit()
        return plan

    @staticmethod
    def update_plan(plan, data):
        """Mutate an existing Plan from form data. Raises ValueError/TypeError on bad input."""
        title = (data.get('title') or '').strip()
        status = data.get('status', 'active')
        plan_type = data.get('plan_type', 'occasion')
        if not title or status not in PLAN_STATUSES or plan_type not in PLAN_TYPES:
            raise ValueError('Check the plan details and try again.')

        plan.title = title
        plan.plan_type = plan_type
        plan.person = (data.get('person') or '').strip() or None
        plan.target_date = PlanService._date_value(data.get('target_date'))
        plan.target_amount = PlanService._money_value(data.get('target_amount'))
        plan.saved_amount = PlanService._money_value(data.get('saved_amount')) or Decimal('0')
        plan.status = status
        plan.notes = (data.get('notes') or '').strip() or None
        plan.owner_id = get_current_user_id() if data.get('visibility') == 'private' else None
        db.session.commit()
        return plan

    @staticmethod
    def delete_plan(plan):
        db.session.delete(plan)
        db.session.commit()

    @staticmethod
    def add_item(plan, data):
        """Create a PlanItem under *plan* from form data. Raises ValueError/TypeError on bad input."""
        title = (data.get('title') or '').strip()
        if not title:
            raise ValueError('Give the item a name.')
        bank_transaction, card_transaction = PlanService._resolve_transaction_source(data)

        item = PlanItem(
            family_id=get_family_id(),
            plan_id=plan.id,
            title=title,
            assigned_to=PlanService._assignment_value(data.get('assigned_to')),
            estimated_cost=PlanService._money_value(data.get('estimated_cost')),
            actual_cost=PlanService._money_value(data.get('actual_cost')),
            priority=data.get('priority', 'normal'),
            status=data.get('status', 'idea'),
            notes=(data.get('notes') or '').strip() or None,
        )
        if item.priority not in ITEM_PRIORITIES or item.status not in ITEM_STATUSES:
            raise ValueError('Invalid item state.')
        PlanService._link_item_source(item, bank_transaction, card_transaction)
        db.session.add(item)
        db.session.commit()
        return item

    @staticmethod
    def update_item(item, data):
        """Mutate an existing PlanItem from form data. Raises ValueError/TypeError on bad input."""
        bank_transaction, card_transaction = PlanService._resolve_transaction_source(data)

        title = (data.get('title') or '').strip()
        status = data.get('status', 'idea')
        priority = data.get('priority', 'normal')
        if not title or status not in ITEM_STATUSES or priority not in ITEM_PRIORITIES:
            raise ValueError('Invalid item details.')
        item.title = title
        item.assigned_to = PlanService._assignment_value(data.get('assigned_to'))
        item.estimated_cost = PlanService._money_value(data.get('estimated_cost'))
        item.actual_cost = PlanService._money_value(data.get('actual_cost'))
        PlanService._link_item_source(item, bank_transaction, card_transaction)
        item.status = status
        item.priority = priority
        item.notes = (data.get('notes') or '').strip() or None
        db.session.commit()
        return item

    @staticmethod
    def delete_item(item):
        db.session.delete(item)
        db.session.commit()

    @staticmethod
    def search_transactions(search, plan_type):
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
        return results[:30]
