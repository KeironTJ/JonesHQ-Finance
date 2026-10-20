from datetime import date, timedelta

from extensions import db
from models.accounts import Account
from models.credit_cards import CreditCard, CreditCardPromotion
from models.mortgage import MortgageProduct
from models.plans import Plan
from models.property import Property
from models.subscriptions import Subscription
from models.transactions import Transaction
from services.finance.subscription_service import SubscriptionService
from services.platform.preference_service import PreferenceService
from utils.permissions import can_access_section
from utils.db_helpers import family_query


class AttentionService:
    KINDS = {
        'transaction': ('Bank entries', 'bank'),
        'plan': ('Plans', 'journal-check'),
        'credit_card': ('Credit cards', 'credit-card'),
        'mortgage': ('Mortgages', 'house-door'),
        'subscription': ('Subscriptions', 'arrow-repeat'),
    }
    PAGE_SIZE = 10

    @staticmethod
    def get_data(today=None):
        today = today or date.today()
        days = PreferenceService.get_value('dashboard.attention_days')
        horizon = today + timedelta(days=days)
        items = []

        snoozes = PreferenceService._user().preferences or {}
        snoozes = snoozes.get('dashboard.attention_snoozes', {})

        def add(kind, record_key, title, message, due_date, endpoint, context='', **params):
            key = f'{kind}:{record_key}:{due_date.isoformat()}'
            snoozed_until = snoozes.get(key)
            items.append({
                'key': key,
                'kind': kind,
                'title': title,
                'message': message,
                'due_date': due_date,
                'days_remaining': (due_date - today).days,
                'endpoint': endpoint,
                'params': params,
                'context': context,
                'snoozed_until': (
                    date.fromisoformat(snoozed_until)
                    if snoozed_until and snoozed_until > today.isoformat() else None
                ),
            })

        if can_access_section('credit_cards'):
            cards = family_query(CreditCard).filter_by(is_active=True).all()
            cards_by_id = {card.id: card for card in cards}
            promotions = family_query(CreditCardPromotion).filter(
                CreditCardPromotion.credit_card_id.in_(cards_by_id),
                CreditCardPromotion.start_date <= today,
                CreditCardPromotion.end_date >= today,
                CreditCardPromotion.end_date <= horizon,
            ).all()
            seen = set()
            for promotion in promotions:
                key = (promotion.credit_card_id, promotion.promotion_type, promotion.end_date)
                if key in seen:
                    continue
                seen.add(key)
                card = cards_by_id[promotion.credit_card_id]
                label = promotion.promotion_type.replace('_', ' ')
                add('credit_card', f'{card.id}:{promotion.promotion_type}', card.card_name,
                    f'{label.title()} promotional rate ends. Review your repayment options.',
                    promotion.end_date, 'credit_cards.detail', id=card.id)
            for card in cards:
                for field, label in (
                    ('purchase_0_percent_until', 'Purchase'),
                    ('balance_transfer_0_percent_until', 'Balance transfer'),
                ):
                    end_date = getattr(card, field)
                    promotion_type = 'purchase' if field == 'purchase_0_percent_until' else 'balance_transfer'
                    if end_date and today <= end_date <= horizon and (
                        card.id, promotion_type, end_date
                    ) not in seen:
                        add('credit_card', f'{card.id}:{promotion_type}', card.card_name,
                            f'{label} 0% rate ends. Review your repayment options.',
                            end_date, 'credit_cards.detail', id=card.id)

        if can_access_section('mortgage'):
            property_ids = family_query(Property).filter_by(is_active=True).with_entities(Property.id)
            products = family_query(MortgageProduct).filter(
                MortgageProduct.is_active.is_(True),
                MortgageProduct.is_current.is_(True),
                MortgageProduct.property_id.in_(property_ids),
                MortgageProduct.end_date <= horizon,
            ).all()
            for product in products:
                add('mortgage', str(product.id), f'{product.lender}: {product.product_name}',
                    'Mortgage product end date. Review your next mortgage arrangement.',
                    product.end_date, 'mortgage.property_detail', property_id=product.property_id)

        if can_access_section('plans'):
            plans = family_query(Plan).filter(
                Plan.status == 'active', Plan.target_date <= horizon,
            ).all()
            for plan in plans:
                add('plan', str(plan.id), plan.title, 'Review this active plan and its target date.',
                    plan.target_date, 'plans.detail', plan_id=plan.id)

        if can_access_section('transactions'):
            subscriptions = family_query(Subscription).filter_by(is_active=True).all()
            for subscription in subscriptions:
                if (
                    subscription.account_id and not subscription.account.is_active
                ) or (
                    subscription.credit_card_id and not subscription.credit_card.is_active
                ):
                    continue
                due_date = next(
                    (
                        scheduled_date
                        for scheduled_date in SubscriptionService._scheduled_dates(
                            subscription, today
                        )
                        if scheduled_date <= horizon
                    ),
                    None,
                )
                if due_date:
                    add(
                        'subscription',
                        str(subscription.id),
                        subscription.name,
                        'Upcoming recurring charge. Review the amount and schedule.',
                        due_date,
                        'transactions.edit_subscription',
                        context=f'{subscription.target_name} / £{abs(subscription.amount):,.2f}',
                        id=subscription.id,
                    )

            accounts = {
                account.id: account
                for account in family_query(Account).filter_by(is_active=True).all()
            }
            transactions = family_query(Transaction).filter(
                Transaction.is_paid.is_(False),
                Transaction.transaction_date < today,
                Transaction.account_id.in_(accounts),
            ).all()
            for transaction in transactions:
                add('transaction', str(transaction.id), transaction.description or transaction.item or 'Pending bank entry',
                    'Still marked pending. Check whether this payment or deposit occurred; a forecast is not necessarily a missed bill.',
                    transaction.transaction_date, 'transactions.index',
                    context=f'{accounts[transaction.account_id].name} / £{transaction.amount:,.2f}',
                    id=transaction.id)

        items.sort(key=lambda item: (
            item['due_date'], item['kind'], item['title'].casefold(),
        ))
        return {'items': items, 'window_days': days}

    @staticmethod
    def get_queue(data, today=None):
        kind = data.get('attention_kind', 'all')
        timing = data.get('attention_timing', 'all')
        view = data.get('attention_view', 'active')
        if kind not in {'all', *AttentionService.KINDS}:
            raise ValueError('Choose a valid reminder category.')
        if timing not in {'all', 'past', 'today', 'upcoming'}:
            raise ValueError('Choose a valid reminder date filter.')
        if view not in {'active', 'snoozed'}:
            raise ValueError('Choose Active or Snoozed reminders.')
        try:
            page = int(data.get('attention_page', 1))
        except (TypeError, ValueError) as error:
            raise ValueError('Choose a valid reminder page.') from error
        if page < 1:
            raise ValueError('Choose a valid reminder page.')

        result = AttentionService.get_data(today)
        all_items = result['items']
        active_count = sum(item['snoozed_until'] is None for item in all_items)
        pool = [
            item for item in all_items
            if (item['snoozed_until'] is not None) == (view == 'snoozed')
        ]
        counts = {
            key: sum(item['kind'] == key for item in pool)
            for key in AttentionService.KINDS
        }
        filtered = [
            item for item in pool
            if (kind == 'all' or item['kind'] == kind)
            and (
                timing == 'all'
                or (timing == 'past' and item['days_remaining'] < 0)
                or (timing == 'today' and item['days_remaining'] == 0)
                or (timing == 'upcoming' and item['days_remaining'] > 0)
            )
        ]
        total = len(filtered)
        pages = max(1, (total + AttentionService.PAGE_SIZE - 1) // AttentionService.PAGE_SIZE)
        page = min(page, pages)
        start = (page - 1) * AttentionService.PAGE_SIZE
        return {
            **result,
            'items': filtered[start:start + AttentionService.PAGE_SIZE],
            'active_count': active_count,
            'snoozed_count': len(all_items) - active_count,
            'counts': counts,
            'pool_count': len(pool),
            'kinds': AttentionService.KINDS,
            'kind': kind,
            'timing': timing,
            'view': view,
            'page': page,
            'pages': pages,
            'total': total,
            'start': start + 1 if total else 0,
            'end': min(start + AttentionService.PAGE_SIZE, total),
        }

    @staticmethod
    def snooze(data, today=None):
        today = today or date.today()
        key = data.get('key')
        duration = data.get('days')
        if duration not in ('0', '1', '7', '30'):
            raise ValueError('Choose 1, 7 or 30 days, or restore the reminder.')
        if not isinstance(key, str) or not any(
            item['key'] == key for item in AttentionService.get_data(today)['items']
        ):
            raise ValueError('That reminder is no longer available.')
        user = PreferenceService._user()
        preferences = user.preferences or {}
        snoozes = {
            saved_key: until
            for saved_key, until in preferences.get('dashboard.attention_snoozes', {}).items()
            if until > today.isoformat()
        }
        if duration == '0':
            snoozes.pop(key, None)
        else:
            snoozes[key] = (today + timedelta(days=int(duration))).isoformat()
        user.preferences = {**preferences, 'dashboard.attention_snoozes': snoozes}
        db.session.commit()
