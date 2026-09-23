from decimal import Decimal

from extensions import db
from models.accounts import Account
from models.transactions import Transaction
from models.users import User
from utils import db_helpers
from utils.db_helpers import family_get_or_404, family_query


class AccountService:
    @staticmethod
    def get_active_accounts_with_balances():
        accounts = family_query(Account).filter_by(
            is_active=True
        ).order_by(Account.name).all()
        for account in accounts:
            paid_transactions = family_query(Transaction).filter_by(
                account_id=account.id,
                is_paid=True,
            ).all()
            account.calculated_balance = float(sum(
                (Decimal(str(transaction.amount)) for transaction in paid_transactions),
                Decimal('0.00'),
            ))
        return accounts

    @staticmethod
    def get_overview():
        """Return accounts grouped with balances calculated from paid transactions."""
        accounts = family_query(Account).all()

        for account in accounts:
            paid_transactions = family_query(Transaction).filter_by(
                account_id=account.id,
                is_paid=True,
            ).all()
            balance = sum(
                (Decimal(str(transaction.amount)) for transaction in paid_transactions),
                Decimal('0.00'),
            )
            account.calculated_balance = float(balance)

        active_accounts = [account for account in accounts if account.is_active]
        inactive_accounts = [account for account in accounts if not account.is_active]
        accounts_by_type = {}
        for account in active_accounts:
            accounts_by_type.setdefault(account.account_type, []).append(account)

        type_totals = {
            account_type: sum(account.calculated_balance for account in grouped_accounts)
            for account_type, grouped_accounts in accounts_by_type.items()
        }

        return {
            'accounts': accounts,
            'active_accounts': active_accounts,
            'inactive_accounts': inactive_accounts,
            'accounts_by_type': accounts_by_type,
            'type_totals': type_totals,
            'total_balance': sum(account.calculated_balance for account in active_accounts),
            'family_members': User.query.filter_by(family_id=db_helpers.get_family_id()).order_by(User.name).all(),
        }

    @staticmethod
    def create_account(name, account_type, balance, is_active, is_private=False):
        account = Account(
            family_id=db_helpers.get_family_id(),
            name=name,
            account_type=account_type,
            balance=float(balance),
            is_active=is_active,
            owner_id=db_helpers.get_current_user_id() if is_private else None,
        )
        db.session.add(account)
        db.session.commit()
        return account

    @staticmethod
    def update_account(account_id, name, account_type, balance, is_active, is_private=None):
        account = family_get_or_404(Account, account_id)
        account.name = name
        account.account_type = account_type
        account.balance = float(balance)
        account.is_active = is_active
        if is_private is not None:
            account.owner_id = db_helpers.get_current_user_id() if is_private else None
        db.session.commit()
        return account

    @staticmethod
    def delete_account(account_id):
        account = family_get_or_404(Account, account_id)
        name = account.name
        db.session.delete(account)
        db.session.commit()
        return name
