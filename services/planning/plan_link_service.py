from decimal import Decimal

from extensions import db
from models.plans import Plan, PlanItem
from utils.assignment_helpers import get_assignment_options
from utils.db_helpers import family_get, family_get_or_404, family_query, get_family_id


class PlanLinkService:
    @staticmethod
    def get_options():
        plans = family_query(Plan).filter(
            Plan.status.in_(['active', 'draft']),
        ).order_by(Plan.target_date.is_(None), Plan.target_date, Plan.title).all()
        items = family_query(PlanItem).join(Plan).filter(
            Plan.status.in_(['active', 'draft']),
            PlanItem.status != 'skipped',
        ).order_by(Plan.title, PlanItem.title).all()
        return plans, items

    @staticmethod
    def current_item(transaction_id):
        return family_query(PlanItem).filter_by(transaction_id=transaction_id).first()

    @staticmethod
    def validate_form(data):
        item_id = data.get('plan_item_id') or data.get('item_id')
        plan_id = data.get('plan_id')
        new_title = (data.get('new_plan_item_title') or data.get('new_item_title') or '').strip()
        assigned_to = (data.get('plan_assigned_to') or '').strip()

        if item_id:
            family_get_or_404(PlanItem, int(item_id))
        if new_title:
            if not plan_id:
                raise ValueError('Choose a valid plan for the new item.')
            family_get_or_404(Plan, int(plan_id))
        if assigned_to and assigned_to not in get_assignment_options():
            raise ValueError('Choose a valid family member or assignment label.')

    @staticmethod
    def sync(transaction, data):
        PlanLinkService.validate_form(data)
        item_id = data.get('plan_item_id') or data.get('item_id')
        plan_id = data.get('plan_id')
        new_title = (data.get('new_plan_item_title') or data.get('new_item_title') or '').strip()
        requested_assignee = (data.get('plan_assigned_to') or '').strip()

        if new_title:
            assigned_to = requested_assignee or transaction.assigned_to or None
            if assigned_to not in get_assignment_options():
                assigned_to = None
            item = PlanItem(
                family_id=get_family_id(),
                plan_id=int(plan_id),
                title=new_title,
                assigned_to=assigned_to,
                estimated_cost=abs(Decimal(str(transaction.amount))),
                status='purchased',
            )
            db.session.add(item)
        elif item_id:
            item = family_get_or_404(PlanItem, int(item_id))
        else:
            for linked_item in family_query(PlanItem).filter_by(transaction_id=transaction.id).all():
                linked_item.transaction = None
            return None

        for linked_item in family_query(PlanItem).filter(
            PlanItem.transaction_id == transaction.id,
            PlanItem.id != item.id,
        ).all():
            linked_item.transaction = None
        item.transaction = transaction
        return item
