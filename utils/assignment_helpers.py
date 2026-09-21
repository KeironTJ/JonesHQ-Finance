from models.family_assignment_labels import FamilyAssignmentLabel
from models.users import User
from utils.db_helpers import family_query


def get_assignment_options():
    """Return active family members and custom labels as unique display names."""
    options = []
    seen = set()

    members = family_query(User).filter(User.is_active.is_(True)).all()
    for member in members:
        display_name = (member.member_name or member.name or '').strip()
        if display_name and display_name not in seen:
            seen.add(display_name)
            options.append(display_name)

    labels = family_query(FamilyAssignmentLabel).filter(
        FamilyAssignmentLabel.is_active.is_(True),
    ).order_by(
        FamilyAssignmentLabel.sort_order,
        FamilyAssignmentLabel.name,
    ).all()
    for label in labels:
        name = (label.name or '').strip()
        if name and name not in seen:
            seen.add(name)
            options.append(name)

    return options or ['Household']
