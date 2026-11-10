from datetime import datetime, timezone

from flask_login import current_user

from models.family import FamilyInvite, HouseholdMembership
from models.household_tasks import HouseholdTask, TaskList
from models.rewards import Reward
from services.household.household_access_service import HouseholdAccessService
from services.household.membership_service import HouseholdMembershipService
from services.platform.module_access_service import ModuleAccessService
from utils.db_helpers import family_query


class HouseholdSetupService:
    @staticmethod
    def page_data():
        HouseholdAccessService.require_owner()
        membership = HouseholdMembershipService.get_membership(current_user)
        people = family_query(HouseholdMembership).all()
        invites = family_query(FamilyInvite).filter(
            FamilyInvite.used_at.is_(None),
            FamilyInvite.expires_at >= datetime.now(timezone.utc).replace(tzinfo=None),
        ).count()
        hub_enabled = ModuleAccessService.can_access(current_user, 'household')
        return dict(
            family=membership.family,
            adults=sum(not person.user.is_managed_child for person in people),
            children=sum(person.user.is_managed_child for person in people),
            invites=invites, hub_enabled=hub_enabled,
            has_jobs=hub_enabled and family_query(HouseholdTask).join(TaskList).filter(
                TaskList.visibility == 'shared',
            ).first() is not None,
            has_rewards=hub_enabled and family_query(Reward).first() is not None,
        )
