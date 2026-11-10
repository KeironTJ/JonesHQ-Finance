from flask import has_request_context, session

from models.family import HouseholdMembership


class HouseholdMembershipService:
    SESSION_KEY = 'active_household_id'

    @staticmethod
    def memberships_for(user):
        if not user or not user.is_authenticated:
            return []
        return HouseholdMembership.query.filter_by(
            user_id=user.id,
        ).order_by(HouseholdMembership.created_at, HouseholdMembership.id).all()

    @staticmethod
    def get_membership(user, family_id=None):
        if not user or not user.is_authenticated:
            return None
        if family_id is None:
            family_id = HouseholdMembershipService.active_family_id(user)
        if family_id is None:
            return None
        return HouseholdMembership.query.filter_by(
            user_id=user.id, family_id=family_id,
        ).first()

    @staticmethod
    def active_family_id(user):
        if not user or not user.is_authenticated:
            return None
        selected_id = (
            session.get(HouseholdMembershipService.SESSION_KEY)
            if has_request_context() else None
        )
        if selected_id is not None and HouseholdMembership.query.filter_by(
            user_id=user.id, family_id=selected_id,
        ).first() is not None:
            return selected_id
        default_id = user.family_id
        if default_id is not None and HouseholdMembership.query.filter_by(
            user_id=user.id, family_id=default_id,
        ).first() is not None:
            return default_id
        membership = HouseholdMembership.query.filter_by(
            user_id=user.id,
        ).order_by(HouseholdMembership.created_at, HouseholdMembership.id).first()
        return membership.family_id if membership else None

    @staticmethod
    def select(user, family_id):
        if not user or not user.is_authenticated:
            raise ValueError('Sign in to select a household.')
        if not isinstance(family_id, int) or isinstance(family_id, bool):
            raise ValueError('Choose a household you belong to.')
        membership = HouseholdMembership.query.filter_by(
            user_id=user.id, family_id=family_id,
        ).first()
        if membership is None:
            raise ValueError('Choose a household you belong to.')
        session[HouseholdMembershipService.SESSION_KEY] = family_id
        return membership
