import json

from extensions import db
from models.family_assignment_labels import FamilyAssignmentLabel
from models.family import HouseholdMembership
from models.users import User
from services.finance.income_service import IncomeService
from services.platform.security_event_service import SecurityEventService
from utils.db_helpers import family_get_or_404, family_query, get_current_user_id, get_family_id
from utils.permissions import SECTION_LABELS


class FinanceAccessService:
    @staticmethod
    def get_page_data():
        family_id = get_family_id()
        return {
            'members': HouseholdMembership.query.filter_by(
                family_id=family_id,
            ).join(User).order_by(User.name).all(),
            'assignment_labels': family_query(FamilyAssignmentLabel).filter_by(
                is_active=True,
            ).order_by(FamilyAssignmentLabel.sort_order, FamilyAssignmentLabel.name).all(),
        }

    @staticmethod
    def update_member(member_id, data):
        member = family_get_or_404(User, member_id)
        family_id = get_family_id()
        membership = HouseholdMembership.query.filter_by(
            user_id=member.id, family_id=family_id,
        ).first_or_404()
        if member.id == get_current_user_id():
            raise ValueError('You cannot edit your own Finance access here.')
        sections = data.get('sections', [])
        if not isinstance(sections, list) or any(
            not isinstance(section, str) or section not in SECTION_LABELS for section in sections
        ):
            raise ValueError('Choose supported Finance sections.')
        if membership.role == 'admin' and sections:
            raise ValueError('Household owners already have access to all Finance sections.')
        previous_names = (membership.member_name, member.name)
        membership.member_name = (data.get('member_name') or '').strip() or member.name
        if membership.role != 'admin':
            membership.allowed_sections = json.dumps(sorted(set(sections)))
        if member.family_id == family_id:
            member.member_name = membership.member_name
            member.allowed_sections = membership.allowed_sections
        IncomeService.sync_member_link(member, family_id, previous_names)
        db.session.commit()
        SecurityEventService.record('family_member_updated', details=f'{member.name} (Finance access)')
        return member
