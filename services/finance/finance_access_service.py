from extensions import db
from models.family_assignment_labels import FamilyAssignmentLabel
from models.users import User
from services.finance.income_service import IncomeService
from services.platform.security_event_service import SecurityEventService
from utils.db_helpers import family_get_or_404, family_query, get_current_user_id
from utils.permissions import SECTION_LABELS


class FinanceAccessService:
    @staticmethod
    def get_page_data():
        return {
            'members': family_query(User).order_by(User.name).all(),
            'assignment_labels': family_query(FamilyAssignmentLabel).filter_by(
                is_active=True,
            ).order_by(FamilyAssignmentLabel.sort_order, FamilyAssignmentLabel.name).all(),
        }

    @staticmethod
    def update_member(member_id, data):
        member = family_get_or_404(User, member_id)
        if member.id == get_current_user_id():
            raise ValueError('You cannot edit your own Finance access here.')
        sections = data.get('sections', [])
        if not isinstance(sections, list) or any(
            not isinstance(section, str) or section not in SECTION_LABELS for section in sections
        ):
            raise ValueError('Choose supported Finance sections.')
        if member.is_household_owner and sections:
            raise ValueError('Household owners already have access to all Finance sections.')
        previous_names = (member.member_name, member.name)
        member.member_name = (data.get('member_name') or '').strip() or member.name
        if not member.is_household_owner:
            member.set_allowed_sections(sections)
        IncomeService.sync_member_link(member, member.family_id, previous_names)
        db.session.commit()
        SecurityEventService.record('family_member_updated', details=f'{member.name} (Finance access)')
        return member
