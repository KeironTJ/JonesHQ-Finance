from datetime import datetime, timezone

from flask_login import current_user

from extensions import db
from models.family import FamilyInvite, HouseholdMembership
from models.household_tasks import HouseholdTask, TaskList
from models.rewards import Reward
from services.household.household_access_service import HouseholdAccessService
from services.household.membership_service import HouseholdMembershipService
from services.platform.module_access_service import ModuleAccessService
from utils.db_helpers import family_query


class HouseholdSetupService:
    OPTIONAL_STEPS = {'people', 'jobs', 'rewards'}

    @staticmethod
    def _progress_state(family):
        state = family.setup_progress
        if not isinstance(state, dict):
            raise ValueError('Household setup progress is invalid. Please contact support.')
        skipped_steps = state.get('skipped_steps', [])
        if not isinstance(skipped_steps, list) or any(
            not isinstance(step, str) for step in skipped_steps
        ):
            raise ValueError('Household setup progress is invalid. Please contact support.')
        return {
            'access_reviewed': state.get('access_reviewed') is True,
            'skipped_steps': sorted(set(skipped_steps) & HouseholdSetupService.OPTIONAL_STEPS),
        }

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
        has_jobs = hub_enabled and family_query(HouseholdTask).join(TaskList).filter(
            TaskList.visibility == 'shared',
        ).first() is not None
        has_rewards = hub_enabled and family_query(Reward).first() is not None
        state = HouseholdSetupService._progress_state(membership.family)
        skipped_steps = state['skipped_steps']
        people_added = sum(not person.user.is_managed_child for person in people) > 1
        children = sum(person.user.is_managed_child for person in people)
        people_complete = bool(children or people_added or invites)
        access_reviewed = state['access_reviewed']
        addressed_steps = 1 + sum((
            people_complete or 'people' in skipped_steps,
            access_reviewed,
            has_jobs or 'jobs' in skipped_steps,
            has_rewards or 'rewards' in skipped_steps,
        ))
        return dict(
            family=membership.family,
            adults=sum(not person.user.is_managed_child for person in people),
            children=children,
            invites=invites,
            hub_enabled=hub_enabled,
            has_jobs=has_jobs,
            has_rewards=has_rewards,
            people_complete=people_complete,
            access_reviewed=access_reviewed,
            skipped_steps=skipped_steps,
            addressed_steps=addressed_steps,
        )

    @staticmethod
    def update_progress(data):
        HouseholdAccessService.require_owner()
        step = data.get('step')
        action = data.get('action')
        if not isinstance(step, str) or not isinstance(action, str):
            raise ValueError('Choose a valid household setup step and action.')
        valid_access_action = step == 'access' and action in ('review', 'reopen')
        valid_optional_action = (
            step in HouseholdSetupService.OPTIONAL_STEPS
            and action in ('skip', 'restore')
        )
        if not (valid_access_action or valid_optional_action):
            raise ValueError('Choose a valid household setup step and action.')

        membership = HouseholdMembershipService.get_membership(current_user)
        family = membership.family
        state = HouseholdSetupService._progress_state(family)
        skipped_steps = set(state['skipped_steps'])

        if step == 'access':
            state['access_reviewed'] = action == 'review'
        elif action == 'skip':
            skipped_steps.add(step)
            state['skipped_steps'] = sorted(skipped_steps)
        else:
            skipped_steps.discard(step)
            state['skipped_steps'] = sorted(skipped_steps)

        family.setup_progress = state
        db.session.commit()
        return state
