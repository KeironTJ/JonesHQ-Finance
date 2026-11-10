import json
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models.family import Family, FamilyInvite, HouseholdMembership
from models.family_assignment_labels import FamilyAssignmentLabel
from models.users import User
from services.finance.income_service import IncomeService
from services.household.membership_service import HouseholdMembershipService
from services.platform.security_event_service import SecurityEventService
from utils.db_helpers import get_current_user_id, get_family_id, family_get_or_404


class FamilyService:
    @staticmethod
    def update_role(member_id, data):
        member = family_get_or_404(User, member_id)
        if member.id == get_current_user_id():
            raise ValueError('You cannot edit your own household role here.')
        role = data.get('role')
        if role not in ('admin', 'member'):
            raise ValueError('Choose Owner or Member as the household role.')
        if member.is_managed_child and role == 'admin':
            raise ValueError('Managed child accounts cannot become household owners.')
        membership = HouseholdMembershipService.get_membership(member, get_family_id())
        if membership is None:
            raise ValueError('This member is no longer in the selected household.')
        membership.role = role
        if member.family_id == membership.family_id:
            member.role = role
        db.session.commit()
        SecurityEventService.record('family_member_updated', details=f'{member.name} ({role})')
        return member

    @staticmethod
    def join_existing(user, data):
        if not user.is_active or user.id != get_current_user_id():
            raise ValueError('Sign in to join with your own account.')
        if user.is_managed_child:
            raise ValueError('Your guardian manages your household membership.')
        try:
            invite = FamilyInvite.query.filter_by(token=data.get('token') or '').first()
            if invite is None or not invite.is_valid:
                raise ValueError('This invite link has expired or has already been used.')
            db.session.execute(update(Family).where(
                Family.id == invite.family_id).values(id=Family.id))
            db.session.refresh(user)
            if HouseholdMembership.query.filter_by(
                user_id=user.id, family_id=invite.family_id,
            ).first() is not None:
                raise ValueError('You already belong to this household.')
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            claimed = db.session.execute(update(FamilyInvite).where(
                FamilyInvite.id == invite.id, FamilyInvite.used_at.is_(None),
                FamilyInvite.expires_at >= now,
            ).values(used_at=now, used_by_id=user.id))
            if claimed.rowcount != 1:
                raise ValueError('This invite link has expired or has already been used.')
            if user.family_id is None:
                user.family_id = invite.family_id
                user.role = invite.role
                user.member_name = invite.member_name
                user.allowed_sections = invite.allowed_sections
                user.default_account_id = None
                user.onboarding_version = 0
            else:
                db.session.add(HouseholdMembership(
                    user_id=user.id,
                    family_id=invite.family_id,
                    role=invite.role,
                    member_name=invite.member_name,
                    allowed_sections=invite.allowed_sections,
                ))
            IncomeService.sync_member_link(user, invite.family_id)
            db.session.commit()
            db.session.expire(user, ['family'])
        except (SQLAlchemyError, ValueError):
            db.session.rollback()
            raise

    @staticmethod
    def create_assignment_label(family_id, name):
        existing = FamilyAssignmentLabel.query.filter_by(
            family_id=family_id,
            name=name,
            is_active=True,
        ).first()
        if existing:
            return None

        max_sort = FamilyAssignmentLabel.query.filter_by(
            family_id=family_id
        ).with_entities(db.func.max(FamilyAssignmentLabel.sort_order)).scalar()
        label = FamilyAssignmentLabel(
            family_id=family_id,
            name=name,
            is_active=True,
            sort_order=(max_sort or 0) + 1,
        )
        db.session.add(label)
        db.session.commit()
        return label

    @staticmethod
    def delete_assignment_label(label_id, family_id):
        label = FamilyAssignmentLabel.query.filter_by(
            id=label_id, family_id=family_id
        ).first_or_404()
        name = label.name
        db.session.delete(label)
        db.session.commit()
        return name

    @staticmethod
    def create_invite(family_id, created_by_id, member_name, role, selected_sections):
        sections_json = None if role == 'admin' else json.dumps(sorted(set(selected_sections)))
        invite = FamilyInvite(
            family_id=family_id,
            member_name=member_name,
            role=role,
            allowed_sections=sections_json,
            created_by_id=created_by_id,
        )
        db.session.add(invite)
        db.session.commit()
        SecurityEventService.record('family_invite_created', details=f'{member_name} ({role})')
        return invite

    @staticmethod
    def revoke_invite(invite_id, family_id):
        invite = FamilyInvite.query.filter_by(
            id=invite_id, family_id=family_id
        ).first_or_404()
        member_name = invite.member_name
        db.session.delete(invite)
        db.session.commit()
        SecurityEventService.record('family_invite_revoked', details=member_name)

    @staticmethod
    def update_member(member_id, family_id, current_user_id, role, member_name, sections):
        membership = HouseholdMembership.query.filter_by(
            user_id=member_id, family_id=family_id,
        ).first_or_404()
        member = membership.user
        if member.id == current_user_id:
            return None

        role = role if role in ('admin', 'member') else 'member'
        if member.is_managed_child and (role == 'admin' or sections):
            raise ValueError('Managed child accounts cannot receive ownership or Finance permissions.')
        previous_names = (membership.member_name, member.name)
        membership.role = role
        membership.member_name = member_name or member.name
        membership.allowed_sections = None if role == 'admin' else json.dumps(sorted(set(sections)))
        if member.family_id == family_id:
            member.role = membership.role
            member.member_name = membership.member_name
            member.allowed_sections = membership.allowed_sections
        IncomeService.sync_member_link(member, family_id, previous_names)
        db.session.commit()
        SecurityEventService.record('family_member_updated', details=f'{member.name} ({role})')
        return member

    @staticmethod
    def remove_member(member_id, family_id, current_user_id):
        membership = HouseholdMembership.query.filter_by(
            user_id=member_id, family_id=family_id,
        ).first_or_404()
        member = membership.user
        if member.id == current_user_id:
            return None

        name = member.name
        from services.household.calendar_service import CalendarService
        CalendarService.detach_membership(membership)
        from services.household.activity_service import ActivityService
        ActivityService.detach_membership(membership)
        from services.household.task_service import TaskService
        TaskService.detach_membership(membership)
        from models.meals import PlannedMeal
        from utils.db_helpers import family_query
        family_query(PlannedMeal).filter_by(creator_membership_id=membership.id).update(
            {'creator_membership_id': None}, synchronize_session=False,
        )
        IncomeService.unlink_member(member.id, family_id)
        HouseholdMembership.query.filter_by(
            user_id=member.id, family_id=family_id,
        ).delete(synchronize_session=False)
        remaining_membership = HouseholdMembership.query.filter_by(
            user_id=member.id,
        ).order_by(HouseholdMembership.created_at, HouseholdMembership.id).first()
        if member.family_id == family_id:
            if remaining_membership is None:
                member.family_id = None
                member.role = 'member'
                member.member_name = None
                member.allowed_sections = None
            else:
                member.family_id = remaining_membership.family_id
                member.role = remaining_membership.role
                member.member_name = remaining_membership.member_name
                member.allowed_sections = remaining_membership.allowed_sections
        if remaining_membership is None:
            from services.platform.user_session_service import UserSessionService
            UserSessionService.revoke_all(member, reason='removed from household')
        db.session.commit()
        SecurityEventService.record('family_member_removed', details=name)
        return name
