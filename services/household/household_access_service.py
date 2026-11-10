from datetime import datetime, timezone

from email_validator import EmailNotValidError, validate_email
from flask import abort
from flask_login import current_user
from sqlalchemy import select

from extensions import db
from models.family import HouseholdMembership
from models.users import SecurityEvent, User
from services.household.membership_service import HouseholdMembershipService
from services.platform.auth_service import AuthService
from services.platform.module_access_service import ModuleAccessService
from utils.db_helpers import family_get_or_404, get_current_user_id, get_family_id


class HouseholdAccessService:
    @staticmethod
    def require_owner():
        if (
            not current_user.is_authenticated or not current_user.is_active
            or not current_user.is_household_owner or get_family_id() is None
        ):
            abort(403)

    @staticmethod
    def _audit(event_type, details):
        db.session.add(SecurityEvent(
            user_id=get_current_user_id(), family_id=get_family_id(),
            event_type=event_type, details=details,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ))

    @staticmethod
    def get_page_data():
        HouseholdAccessService.require_owner()
        return {
            'memberships': HouseholdMembership.query.filter_by(
                family_id=get_family_id(),
            ).join(User).order_by(User.name).all(),
            'module_labels': ModuleAccessService.MODULE_LABELS,
        }

    @staticmethod
    def update_modules(member_id, data):
        HouseholdAccessService.require_owner()
        member = family_get_or_404(User, member_id)
        modules = data.get('modules')
        if not isinstance(modules, list) or any(
            not isinstance(key, str) or key not in ModuleAccessService.MODULE_LABELS for key in modules
        ):
            raise ValueError('Choose supported modules.')
        if member.is_managed_child and 'finance' in modules:
            raise ValueError('Managed child accounts cannot access Finance in any household.')
        membership = HouseholdMembershipService.get_membership(member, get_family_id())
        membership.allowed_modules = sorted(set(modules))
        HouseholdAccessService._audit(
            'module_access_updated',
            f'member={member.id}; modules={",".join(membership.allowed_modules) or "none"}',
        )
        db.session.commit()
        return member

    @staticmethod
    def create_child(data):
        HouseholdAccessService.require_owner()
        family_id = get_family_id()
        name = (data.get('name') or '').strip()
        if not name or len(name) > 100:
            raise ValueError('Enter a child account name of up to 100 characters.')
        try:
            email = validate_email(
                data.get('email') or '', check_deliverability=False,
            ).normalized.lower()
        except EmailNotValidError as error:
            raise ValueError('Enter a valid sign-in email address.') from error
        if len(email) > 120:
            raise ValueError('The sign-in email address is too long.')
        if User.query.filter_by(email=email).first():
            raise ValueError('An account already uses this email. Existing accounts cannot be taken over as child accounts.')
        password = data.get('password') or ''
        if password != data.get('confirm_password'):
            raise ValueError('The passwords do not match.')
        valid, error = AuthService.validate_password_strength(password)
        if not valid:
            raise ValueError(error)
        child = User(
            name=name, email=email, family_id=family_id, role='member',
            account_type='child', guardian_id=current_user.id,
            allowed_sections='[]', member_name=name,
        )
        child.set_password(password)
        db.session.add(child)
        db.session.add(HouseholdMembership(
            user=child, family_id=family_id, role='member',
            allowed_sections='[]', member_name=name, allowed_modules=['household'],
        ))
        db.session.flush()
        HouseholdAccessService._audit('managed_child_created', f'child={child.id}; guardian={current_user.id}')
        db.session.commit()
        return child

    @staticmethod
    def managed_children():
        if not current_user.is_authenticated or current_user.is_managed_child:
            abort(403)
        return User.query.filter_by(
            guardian_id=current_user.id, account_type='child',
        ).order_by(User.name).all()

    @staticmethod
    def guardians_for(child):
        households = select(HouseholdMembership.family_id).where(
            HouseholdMembership.user_id == child.id,
        )
        return User.query.filter(
            User.id.in_(select(HouseholdMembership.user_id).where(
                HouseholdMembership.family_id.in_(households),
            )),
            User.account_type == 'adult', User.is_active.is_(True),
            User.id != child.guardian_id,
        ).order_by(User.name).all()

    @staticmethod
    def update_child(child_id, data):
        if not current_user.is_authenticated or current_user.is_managed_child:
            abort(403)
        child = User.query.filter_by(
            id=child_id, guardian_id=current_user.id, account_type='child',
        ).first_or_404()
        action = data.get('action')
        if action == 'release':
            child.account_type = 'adult'
            child.guardian_id = None
            # Existing household grants stay restricted; release never grants Finance.
            HouseholdAccessService._audit('managed_child_released', f'child={child.id}')
        elif action == 'transfer':
            guardian_id = data.get('guardian_id')
            guardian = next((
                user for user in HouseholdAccessService.guardians_for(child)
                if str(user.id) == str(guardian_id)
            ), None)
            if guardian is None:
                raise ValueError('Choose an active adult in one of the child account households.')
            child.guardian_id = guardian.id
            HouseholdAccessService._audit(
                'child_guardian_updated', f'child={child.id}; guardian={guardian.id}',
            )
        else:
            raise ValueError('Choose a supported child-account action.')
        db.session.commit()
        return child
