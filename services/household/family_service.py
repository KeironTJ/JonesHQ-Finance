import json
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models.family import Family, FamilyInvite
from models.family_assignment_labels import FamilyAssignmentLabel
from models.users import User, UserSession
from services.platform.security_event_service import SecurityEventService
from services.platform.user_session_service import UserSessionService
from utils.db_helpers import get_current_user_id


class FamilyService:
    @staticmethod
    def join_existing(user, data):
        if not user.is_active or user.id != get_current_user_id():
            raise ValueError('Sign in to join with your own account.')
        try:
            invite = FamilyInvite.query.filter_by(token=data.get('token') or '').first()
            if invite is None or not invite.is_valid:
                raise ValueError('This invite link has expired or has already been used.')
            db.session.execute(update(Family).where(
                Family.id == invite.family_id).values(id=Family.id))
            db.session.refresh(user)
            if user.family_id is not None:
                raise ValueError('You already belong to a household.')
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            claimed = db.session.execute(update(FamilyInvite).where(
                FamilyInvite.id == invite.id, FamilyInvite.used_at.is_(None),
                FamilyInvite.expires_at >= now,
            ).values(used_at=now, used_by_id=user.id))
            if claimed.rowcount != 1:
                raise ValueError('This invite link has expired or has already been used.')
            user.family_id = invite.family_id
            user.role = invite.role
            user.member_name = invite.member_name
            user.allowed_sections = invite.allowed_sections
            user.default_account_id = None
            user.onboarding_version = 0
            db.session.execute(update(UserSession).where(
                UserSession.user_id == user.id, UserSession.revoked_at.is_(None),
            ).values(revoked_at=now))
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
        member = User.query.filter_by(id=member_id, family_id=family_id).first_or_404()
        if member.id == current_user_id:
            return None

        member.role = role if role in ('admin', 'member') else 'member'
        member.member_name = member_name or member.name
        member.allowed_sections = None if member.role == 'admin' else None
        if member.role != 'admin':
            member.set_allowed_sections(sections)
        db.session.commit()
        SecurityEventService.record('family_member_updated', details=f'{member.name} ({member.role})')
        return member

    @staticmethod
    def remove_member(member_id, family_id, current_user_id):
        member = User.query.filter_by(id=member_id, family_id=family_id).first_or_404()
        if member.id == current_user_id:
            return None

        name = member.name
        member.family_id = None
        member.role = 'member'
        member.allowed_sections = None
        db.session.commit()
        UserSessionService.revoke_all(member, reason='removed from family')
        SecurityEventService.record('family_member_removed', details=name)
        return name
