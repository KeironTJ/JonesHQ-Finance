from datetime import date
from decimal import Decimal, InvalidOperation

from dateutil.relativedelta import relativedelta

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.credit_card_transactions import CreditCardTransaction
from models.credit_cards import CreditCard
from models.subscriptions import Subscription
from models.transactions import Transaction
from models.vendors import Vendor
from services.finance.payday_service import PaydayService
from utils import db_helpers
from utils.db_helpers import family_get, family_get_or_404, family_query


class SubscriptionService:
    FREQUENCIES = {
        'weekly': relativedelta(weeks=1),
        '4weekly': relativedelta(weeks=4),
        'monthly': relativedelta(months=1),
        'quarterly': relativedelta(months=3),
        'yearly': relativedelta(years=1),
    }

    @staticmethod
    def _parse_data(data):
        name = (data.get('name') or '').strip()
        if not name:
            raise ValueError('Subscription name is required')

        try:
            amount = Decimal(str(data.get('amount', '')).strip())
        except (InvalidOperation, ValueError):
            raise ValueError('Enter a valid subscription amount') from None
        if not amount.is_finite() or amount <= 0:
            raise ValueError('Subscription amount must be greater than zero')

        frequency = data.get('frequency')
        if frequency not in SubscriptionService.FREQUENCIES:
            raise ValueError('Select a valid subscription frequency')

        try:
            start_date = date.fromisoformat(data.get('start_date', ''))
            end_date = (
                date.fromisoformat(data['end_date'])
                if data.get('end_date')
                else None
            )
        except ValueError:
            raise ValueError('Enter valid subscription dates') from None
        if end_date and end_date < start_date:
            raise ValueError('End date cannot be before the start date')

        try:
            horizon_years = int(data.get('horizon_years', '1'))
        except (ValueError, TypeError):
            raise ValueError('Choose a planning horizon from 1 to 5 years') from None
        if horizon_years not in range(1, 6):
            raise ValueError('Choose a planning horizon from 1 to 5 years')

        target_type = data.get('target_type')
        if target_type == 'bank':
            account = family_get(Account, data.get('account_id', type=int))
            category = family_get(Category, data.get('category_id', type=int))
            if not account or not account.is_active or not category:
                raise ValueError('Select a valid account and category')
            card = None
        elif target_type == 'credit_card':
            card = family_get(CreditCard, data.get('credit_card_id', type=int))
            if not card or not card.is_active:
                raise ValueError('Select a valid credit card')
            account = None
            category_id = data.get('category_id', type=int)
            category = family_get(Category, category_id) if category_id else None
            if category_id and not category:
                raise ValueError('Select a valid category')
        else:
            raise ValueError('Select a bank account or credit card')

        vendor_id = data.get('vendor_id', type=int)
        vendor = family_get(Vendor, vendor_id) if vendor_id else None
        if vendor_id and not vendor:
            raise ValueError('Select a valid vendor')

        return {
            'name': name,
            'amount': -amount,
            'frequency': frequency,
            'start_date': start_date,
            'end_date': end_date,
            'horizon_years': horizon_years,
            'account': account,
            'credit_card': card,
            'category': category,
            'vendor': vendor,
        }

    @staticmethod
    def create(data):
        values = SubscriptionService._parse_data(data)
        subscription = Subscription(
            family_id=db_helpers.get_family_id(),
            name=values['name'],
            amount=values['amount'],
            frequency=values['frequency'],
            start_date=values['start_date'],
            end_date=values['end_date'],
            horizon_years=values['horizon_years'],
            account_id=values['account'].id if values['account'] else None,
            credit_card_id=values['credit_card'].id if values['credit_card'] else None,
            category_id=values['category'].id if values['category'] else None,
            vendor_id=values['vendor'].id if values['vendor'] else None,
        )
        db.session.add(subscription)
        db.session.flush()
        SubscriptionService.sync_pending(subscription, values)
        return subscription

    @staticmethod
    def update(subscription_id, data):
        subscription = family_get_or_404(Subscription, subscription_id)
        values = SubscriptionService._parse_data(data)
        new_account_id = values['account'].id if values['account'] else None
        new_card_id = values['credit_card'].id if values['credit_card'] else None
        if (
            subscription.account_id != new_account_id
            or subscription.credit_card_id != new_card_id
        ):
            SubscriptionService._remove_pending(subscription)
        subscription.name = values['name']
        subscription.amount = values['amount']
        subscription.frequency = values['frequency']
        subscription.start_date = values['start_date']
        subscription.end_date = values['end_date']
        subscription.horizon_years = values['horizon_years']
        subscription.account_id = values['account'].id if values['account'] else None
        subscription.credit_card_id = (
            values['credit_card'].id if values['credit_card'] else None
        )
        subscription.category_id = values['category'].id if values['category'] else None
        subscription.vendor_id = values['vendor'].id if values['vendor'] else None
        SubscriptionService.sync_pending(subscription, values)
        return subscription

    @staticmethod
    def _scheduled_dates(subscription, today):
        horizon_end = today + relativedelta(years=subscription.horizon_years)
        last_date = min(
            (d for d in (horizon_end, subscription.end_date) if d is not None),
            default=horizon_end,
        )
        interval = SubscriptionService.FREQUENCIES[subscription.frequency]
        occurrence = 0
        while True:
            planned_date = subscription.start_date + occurrence * interval
            if planned_date > last_date:
                break
            if planned_date >= today:
                yield planned_date
            occurrence += 1

    @staticmethod
    def sync_pending(subscription, values=None, today=None):
        today = today or date.today()
        values = values or {
            'account': subscription.account,
            'credit_card': subscription.credit_card,
            'category': subscription.category,
            'vendor': subscription.vendor,
            'amount': subscription.amount,
        }
        dates = set(SubscriptionService._scheduled_dates(subscription, today))

        if subscription.account_id:
            transactions = family_query(Transaction).filter_by(
                subscription_id=subscription.id,
                account_id=subscription.account_id,
                is_paid=False,
            ).all()
            SubscriptionService._sync_bank_transactions(
                subscription,
                transactions,
                dates,
                values,
                today,
                create_missing=subscription.is_active,
            )
            Transaction.recalculate_account_balance(subscription.account_id)
        else:
            transactions = family_query(CreditCardTransaction).filter_by(
                subscription_id=subscription.id,
                credit_card_id=subscription.credit_card_id,
                is_paid=False,
            ).all()
            SubscriptionService._sync_card_transactions(
                subscription,
                transactions,
                dates,
                values,
                today,
                create_missing=subscription.is_active,
            )
            CreditCardTransaction.recalculate_card_balance(
                subscription.credit_card_id, commit=False
            )

    @staticmethod
    def _sync_bank_transactions(
        subscription, transactions, dates, values, today, create_missing
    ):
        paid_dates = {
            transaction.transaction_date
            for transaction in family_query(Transaction).filter_by(
                subscription_id=subscription.id,
                account_id=subscription.account_id,
            ).filter(
                db.or_(Transaction.is_paid.is_(True), Transaction.is_fixed.is_(True))
            ).all()
        }
        pending_by_date = {}
        for transaction in transactions:
            if transaction.transaction_date < today:
                if not transaction.is_fixed:
                    transaction.category_id = subscription.category_id
                    transaction.vendor_id = subscription.vendor_id
                    transaction.description = subscription.name
                    transaction.amount = values['amount']
                continue
            if transaction.transaction_date in pending_by_date:
                if transaction.is_fixed:
                    current = pending_by_date[transaction.transaction_date]
                    if not current.is_fixed:
                        db.session.delete(current)
                        pending_by_date[transaction.transaction_date] = transaction
                else:
                    db.session.delete(transaction)
            else:
                pending_by_date[transaction.transaction_date] = transaction

        for transaction_date in set(pending_by_date) - dates:
            if not pending_by_date[transaction_date].is_fixed:
                db.session.delete(pending_by_date[transaction_date])

        for transaction_date in sorted(dates - paid_dates):
            transaction = pending_by_date.get(transaction_date)
            if transaction is None:
                if not create_missing:
                    continue
                transaction = Transaction(
                    family_id=subscription.family_id,
                    subscription_id=subscription.id,
                    account_id=subscription.account_id,
                    transaction_date=transaction_date,
                    amount=values['amount'],
                    is_paid=False,
                )
                db.session.add(transaction)
            elif transaction.is_fixed:
                continue
            transaction.category_id = subscription.category_id
            transaction.vendor_id = subscription.vendor_id
            transaction.description = subscription.name
            transaction.amount = values['amount']
            transaction.is_paid = False
            transaction.year_month = transaction_date.strftime('%Y-%m')
            transaction.week_year = (
                f'{transaction_date.isocalendar()[1]:02d}-{transaction_date.year}'
            )
            transaction.day_name = transaction_date.strftime('%a')
            transaction.payday_period = PaydayService.get_period_for_date(
                transaction_date
            )

    @staticmethod
    def _sync_card_transactions(
        subscription, transactions, dates, values, today, create_missing
    ):
        paid_dates = {
            transaction.date
            for transaction in family_query(CreditCardTransaction).filter_by(
                subscription_id=subscription.id,
                credit_card_id=subscription.credit_card_id,
            ).filter(
                db.or_(
                    CreditCardTransaction.is_paid.is_(True),
                    CreditCardTransaction.is_fixed.is_(True),
                )
            ).all()
        }
        pending_by_date = {}
        for transaction in transactions:
            if transaction.date < today:
                if not transaction.is_fixed:
                    category = values['category']
                    vendor = values['vendor']
                    transaction.category_id = subscription.category_id
                    transaction.vendor_id = subscription.vendor_id
                    transaction.head_budget = category.head_budget if category else None
                    transaction.sub_budget = category.sub_budget if category else None
                    transaction.item = subscription.name
                    transaction.amount = values['amount']
                continue
            if transaction.date in pending_by_date:
                if transaction.is_fixed:
                    current = pending_by_date[transaction.date]
                    if not current.is_fixed:
                        db.session.delete(current)
                        pending_by_date[transaction.date] = transaction
                else:
                    db.session.delete(transaction)
            else:
                pending_by_date[transaction.date] = transaction

        for transaction_date in set(pending_by_date) - dates:
            if not pending_by_date[transaction_date].is_fixed:
                db.session.delete(pending_by_date[transaction_date])

        category = values['category']
        vendor = values['vendor']
        for transaction_date in sorted(dates - paid_dates):
            transaction = pending_by_date.get(transaction_date)
            if transaction is None:
                if not create_missing:
                    continue
                transaction = CreditCardTransaction(
                    family_id=subscription.family_id,
                    subscription_id=subscription.id,
                    credit_card_id=subscription.credit_card_id,
                    date=transaction_date,
                    transaction_type='Purchase',
                    is_paid=False,
                )
                db.session.add(transaction)
            elif transaction.is_fixed:
                continue
            transaction.category_id = subscription.category_id
            transaction.vendor_id = subscription.vendor_id
            transaction.date = transaction_date
            transaction.day_name = transaction_date.strftime('%A')
            transaction.week = (
                f'{transaction_date.isocalendar()[1]:02d}-{transaction_date.year}'
            )
            transaction.month = transaction_date.strftime('%Y-%m')
            transaction.head_budget = category.head_budget if category else None
            transaction.sub_budget = category.sub_budget if category else None
            transaction.item = subscription.name
            transaction.vendor_id = vendor.id if vendor else None
            transaction.amount = values['amount']
            transaction.transaction_type = 'Purchase'
            transaction.is_paid = False

    @staticmethod
    def set_active(subscription_id, is_active):
        subscription = family_get_or_404(Subscription, subscription_id)
        subscription.is_active = is_active
        if is_active:
            SubscriptionService.sync_pending(subscription)
        return subscription

    @staticmethod
    def _remove_pending(subscription):
        pending_bank = family_query(Transaction).filter_by(
            subscription_id=subscription.id, is_paid=False
        ).all()
        pending_card = family_query(CreditCardTransaction).filter_by(
            subscription_id=subscription.id, is_paid=False
        ).all()
        account_ids = {transaction.account_id for transaction in pending_bank}
        card_ids = {transaction.credit_card_id for transaction in pending_card}
        if subscription.account_id:
            account_ids.add(subscription.account_id)
        if subscription.credit_card_id:
            card_ids.add(subscription.credit_card_id)
        for transaction in pending_bank + pending_card:
            db.session.delete(transaction)
        for account_id in account_ids:
            if account_id:
                Transaction.recalculate_account_balance(account_id)
        for card_id in card_ids:
            if card_id:
                CreditCardTransaction.recalculate_card_balance(card_id, commit=False)

    @staticmethod
    def cancel(subscription_id):
        subscription = family_get_or_404(Subscription, subscription_id)
        SubscriptionService._remove_pending(subscription)
        subscription.is_active = False
        return subscription
