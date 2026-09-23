from decimal import Decimal, InvalidOperation

from extensions import db
from models.accounts import Account
from models.family import Family
from models.settings import Settings
from models.users import User
from services.finance.vendor_service import VendorService
from services.platform.settings_service import SettingsService
from utils import db_helpers
from utils.db_helpers import family_query


ONBOARDING_VERSION = 1
ACCOUNT_TYPES = (
    'Current',
    'Joint',
    'Savings',
    'Personal',
    'Credit Card',
    'Loan',
    'Investment',
)


class OnboardingService:
    @staticmethod
    def _current_user_and_family():
        user_id = db_helpers.get_current_user_id()
        user = db.session.get(User, user_id) if user_id else None
        family = db.session.get(Family, user.family_id) if user and user.family_id else None
        if not user or not family:
            raise ValueError('Unable to identify your household.')
        return user, family

    @staticmethod
    def get_context():
        user, family = OnboardingService._current_user_and_family()
        if user.is_admin and family.onboarding_version < ONBOARDING_VERSION:
            mode = 'household'
        elif user.onboarding_version < ONBOARDING_VERSION:
            mode = 'personal'
        else:
            mode = 'complete'

        return {
            'mode': mode,
            'accounts': family_query(Account).filter_by(is_active=True).order_by(Account.name).all(),
            'account_types': ACCOUNT_TYPES,
            'payday_day': Settings.get_value('payday_day', 15),
        }

    @staticmethod
    def complete_household(data):
        user, family = OnboardingService._current_user_and_family()
        if not user.is_admin:
            raise ValueError('Only a household admin can complete household setup.')

        try:
            payday_day = int(data.get('payday_day', 15))
        except (TypeError, ValueError) as error:
            raise ValueError('Payday must be a day between 1 and 31.') from error
        if not 1 <= payday_day <= 31:
            raise ValueError('Payday must be a day between 1 and 31.')

        Settings.set_value(
            'payday_day',
            payday_day,
            'Day of month when payday occurs (adjusted for weekends)',
            'int',
        )

        account = None
        if data.get('create_account') == '1':
            account_name = (data.get('account_name') or '').strip()
            account_type = data.get('account_type')
            if not account_name:
                raise ValueError('Enter a name for your first account.')
            if account_type not in ACCOUNT_TYPES:
                raise ValueError('Select a valid account type.')
            try:
                opening_balance = Decimal(data.get('opening_balance') or '0')
            except InvalidOperation as error:
                raise ValueError('Opening balance must be a valid amount.') from error

            account = Account(
                family_id=family.id,
                name=account_name,
                account_type=account_type,
                balance=opening_balance,
                is_active=True,
                owner_id=user.id if data.get('visibility') == 'private' else None,
            )
            db.session.add(account)
            db.session.flush()
            user.default_account_id = account.id

        if data.get('seed_vendor_types') == '1':
            VendorService.seed_types(commit=False)

        family.onboarding_version = ONBOARDING_VERSION
        user.onboarding_version = ONBOARDING_VERSION
        db.session.commit()
        return account

    @staticmethod
    def complete_personal(data):
        user, _ = OnboardingService._current_user_and_family()
        SettingsService.update_default_account(data)
        user.onboarding_version = ONBOARDING_VERSION
        db.session.commit()
        return user

