from models.users import User
from utils.db_helpers import family_get, family_query

UNSPECIFIED_MEMBER = object()


class MemberIdentityService:
    @staticmethod
    def member_id_for(person):
        key = (person or '').strip().lower()
        matches = {
            member.id for member in family_query(User).all()
            if key and key in {
                (member.member_name or '').strip().lower(),
                (member.name or '').strip().lower(),
            }
        }
        return next(iter(matches)) if len(matches) == 1 else None

    @staticmethod
    def resolve(data, record=None):
        """An explicit member ID wins over display text; old name-only callers still work."""
        person = (data.get('person') or (record.person if record else 'Household')).strip() or 'Household'
        if len(person) > 50:
            raise ValueError('Person must be 50 characters or fewer.')
        if 'member_id' not in data:
            if record and person == record.person and record.member_id is not None:
                return person, record.member_id
            return person, MemberIdentityService.member_id_for(person)
        raw_id = data.get('member_id')
        if raw_id == 'household':
            return 'Household', None
        if raw_id in ('', None):
            return person, None
        try:
            member_id = int(raw_id)
        except (ValueError, TypeError):
            raise ValueError('Choose a valid household member.') from None
        member = family_get(User, member_id)
        if member is None or (not member.is_active and (not record or record.member_id != member.id)):
            raise ValueError('Choose an active member of this household.')
        return (member.member_name or member.name).strip()[:50], member.id

    @staticmethod
    def options(record=None):
        members = family_query(User).order_by(User.member_name, User.name, User.id).all()
        return [
            (member.id, (member.member_name or member.name).strip(), member.is_active)
            for member in members
            if member.is_active or (record and record.member_id == member.id)
        ]

    @staticmethod
    def label(person, member_id):
        count = sum(
            (member.member_name or member.name).strip()[:50] == person
            for member in family_query(User).all()
        )
        if member_id is not None and count > 1:
            return f'{person} (member #{member_id})'
        if member_id is None and count:
            return f'{person} (unlinked)'
        return person
