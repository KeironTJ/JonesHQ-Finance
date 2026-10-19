from datetime import date
import logging

from dateutil.relativedelta import relativedelta
from sqlalchemy import select

from extensions import db
from models.settings import Settings
from services.household.member_identity_service import MemberIdentityService, UNSPECIFIED_MEMBER


DEFAULT_RETIREMENT_AGE = 67
MIN_RETIREMENT_AGE = 50
MAX_RETIREMENT_AGE = 80


class RetirementService:
    @staticmethod
    def keys(person, member_id=UNSPECIFIED_MEMBER):
        if member_id is UNSPECIFIED_MEMBER:
            member_id = MemberIdentityService.member_id_for(person)
        if member_id is not None:
            prefix = f'retirement.member.{member_id}'
            return f'{prefix}.date_of_birth', f'{prefix}.retirement_age'
        prefix = person.strip().lower()
        return f'{prefix}_date_of_birth', f'{prefix}_retirement_age'

    @staticmethod
    def age_for(person, member_id=UNSPECIFIED_MEMBER, default=DEFAULT_RETIREMENT_AGE):
        _, key = RetirementService.keys(person, member_id)
        value = Settings.get_value(key, default)
        return default if value in ('', None) else int(value)

    @staticmethod
    def profile(person, member_id=UNSPECIFIED_MEMBER):
        dob_key, _ = RetirementService.keys(person, member_id)
        raw_dob = Settings.get_value(dob_key)
        if not raw_dob:
            return None
        try:
            dob = date.fromisoformat(str(raw_dob))
            age = RetirementService.age_for(person, member_id)
        except (TypeError, ValueError):
            raise ValueError(f'Correct the retirement settings for {person}.') from None
        try:
            retire_on = dob.replace(year=dob.year + age)
        except ValueError:
            retire_on = date(dob.year + age, 3, 1)
        return {'date_of_birth': dob, 'age': age, 'date': retire_on}

    @staticmethod
    def save_age(person, age, member_id=UNSPECIFIED_MEMBER):
        try:
            age = int(age)
        except (TypeError, ValueError):
            raise ValueError('Enter a whole-number retirement age.') from None
        if not MIN_RETIREMENT_AGE <= age <= MAX_RETIREMENT_AGE:
            raise ValueError(f'Retirement age must be between {MIN_RETIREMENT_AGE} and {MAX_RETIREMENT_AGE}.')
        _, age_key = RetirementService.keys(person, member_id)
        Settings.set_value(age_key, age, f'Target retirement age: {person}', 'int')
        return age

    @staticmethod
    def save(person, data, member_id=UNSPECIFIED_MEMBER, today=None, commit=True):
        today = today or date.today()
        dob_key, age_key = RetirementService.keys(person, member_id)
        raw_dob = (data.get('date_of_birth') or '').strip()
        if not raw_dob:
            # Keep empty keys so a later rename/join cannot re-import cleared legacy values.
            Settings.set_value(dob_key, '', f'Date of birth: {person}', 'string')
            Settings.set_value(age_key, '', f'Target retirement age: {person}', 'string')
            if commit:
                db.session.commit()
            return None
        try:
            dob = date.fromisoformat(raw_dob)
        except ValueError:
            raise ValueError('Enter a valid date of birth.') from None
        if not date(today.year - 100, 1, 1) <= dob <= today - relativedelta(years=16):
            raise ValueError('Date of birth must be 16 to 100 years ago.')
        RetirementService.save_age(
            person, data.get('retirement_age') or DEFAULT_RETIREMENT_AGE, member_id)
        Settings.set_value(dob_key, dob.isoformat(), f'Date of birth: {person}', 'string')
        if commit:
            db.session.commit()
        return RetirementService.profile(person, member_id)

    @staticmethod
    def link_legacy(member, family_id, names):
        """Copy unambiguous legacy values without overwriting an existing member profile."""
        for suffix in ('date_of_birth', 'retirement_age'):
            key = f'retirement.member.{member.id}.{suffix}'
            # Invite joins have no current household yet; scope this lifecycle operation explicitly.
            settings = select(Settings).where(Settings.family_id == family_id)
            if db.session.execute(settings.where(Settings.key == key)).scalar_one_or_none():
                continue
            candidates = db.session.execute(settings.where(Settings.key.in_(
                [f'{name}_{suffix}' for name in names]))).scalars().all()
            values = {row.value for row in candidates}
            if len(values) == 1:
                original = candidates[0]
                try:
                    if original.value:
                        if suffix == 'date_of_birth':
                            date.fromisoformat(original.value)
                        elif not MIN_RETIREMENT_AGE <= int(original.value) <= MAX_RETIREMENT_AGE:
                            raise ValueError('Retirement age out of range.')
                except (TypeError, ValueError):
                    logging.getLogger(__name__).warning(
                        'Invalid legacy retirement %s for member %s; review their profile.', suffix, member.id)
                    continue
                db.session.add(Settings(
                    family_id=family_id, key=key, value=original.value,
                    description=original.description,
                    setting_type='int' if suffix == 'retirement_age' and original.value else 'string',
                ))
            elif len(values) > 1:
                logging.getLogger(__name__).warning(
                    'Conflicting legacy retirement %s for member %s; review their profile.', suffix, member.id)
