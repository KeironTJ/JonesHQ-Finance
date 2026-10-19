from datetime import date
from decimal import Decimal
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from alembic.migration import MigrationContext
from alembic.operations import Operations

from extensions import db
from models.family import Family
from models.income import Income
from models.pensions import Pension
from models.settings import Settings
from models.users import User
from services.finance.income_projection_service import IncomeProjectionService
from services.finance.income_service import IncomeService
from services.household.family_service import FamilyService
from services.household.member_identity_service import MemberIdentityService
from services.planning.pension_service import PensionService
from services.planning.retirement_service import RetirementService
from services.platform.account_deletion_service import AccountDeletionService


@pytest.fixture
def scoped(app, family, user, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)
    return family


def member(family, name='Sam', alias=None):
    user = User(family_id=family.id, name=name, member_name=alias,
                email=f'{name}-{User.query.count()}@example.com', role='member')
    user.set_password('TestPass1!')
    db.session.add(user)
    db.session.commit()
    return user


def source(member_id, **overrides):
    data = dict(member_id=str(member_id), person='ignored text', source='Job', start_date='2026-01-01',
                pay_day='15', gross_annual='36000', tax_code='1257L')
    data.update(overrides)
    return IncomeService.save_income_source(data)


def pension(member_id, **overrides):
    data = dict(member_id=str(member_id), provider='Pot', current_value='10000', is_active='on')
    data.update(overrides)
    return PensionService.create_pension(data)


def test_ids_disambiguate_members_and_survive_a_rename(scoped, user):
    one = member(scoped, 'Sam One', 'Sam')
    two = member(scoped, 'Sam Two', 'Sam')
    job = source(two.id)
    pot = pension(two.id)
    info = IncomeProjectionService.set_retirement('ignored', {
        'member_id': str(two.id), 'date_of_birth': '1980-03-04', 'retirement_age': '68',
    })
    assert info['age'] == 68
    assert RetirementService.profile('Sam', one.id) is None
    assert PensionService.get_person_age('Sam', two.id) is not None
    FamilyService.update_member(two.id, scoped.id, user.id, 'member', 'Samantha', [])
    db.session.expire_all()
    assert job.person == pot.person == 'Samantha'
    assert RetirementService.profile('Samantha', two.id) == info
    assert set(i.member_id for i in Income.query.filter_by(recurring_income_id=job.id)) == {two.id}
    plan = IncomeProjectionService.build_plan()
    assert plan['retirements']['Samantha']['age'] == 68


def test_duplicate_names_have_separate_retirement_profiles_in_plan(scoped):
    one = member(scoped, 'Sam One', 'Sam')
    two = member(scoped, 'Sam Two', 'Sam')
    source(one.id)
    source(two.id)
    for user, age in ((one, 60), (two, 70)):
        IncomeProjectionService.set_retirement('Sam', {
            'member_id': str(user.id), 'date_of_birth': '1980-01-01', 'retirement_age': str(age),
        })
    plan = IncomeProjectionService.build_plan(until_year=2052)
    assert {info['age'] for info in plan['retirements'].values()} == {60, 70}
    assert len(plan['people']) == 2


@pytest.mark.parametrize('bad_id', ['not-a-number', '-1', '99999'])
def test_invalid_explicit_member_ids_fail(scoped, bad_id):
    with pytest.raises(ValueError, match='member'):
        source(bad_id)
    with pytest.raises(ValueError, match='member'):
        pension(bad_id)


def test_foreign_household_member_is_rejected(scoped):
    other_family = Family(name='Other')
    db.session.add(other_family)
    db.session.commit()
    outsider = member(other_family)
    with pytest.raises(ValueError, match='this household'):
        source(outsider.id)
    with pytest.raises(ValueError, match='this household'):
        pension(outsider.id)


def test_unlinked_legacy_label_and_household_are_explicit_choices(scoped):
    person = member(scoped)
    pot = pension(person.id)
    result = MemberIdentityService.resolve({'member_id': '', 'person': 'Sam'}, pot)
    assert result == ('Sam', None)
    assert MemberIdentityService.resolve({'member_id': 'household', 'person': 'Sam'}, pot) == ('Household', None)
    job = source(person.id)
    saved = IncomeService.update_income_record(
        Income.query.filter_by(recurring_income_id=job.id).first().id,
        {'member_id': '', 'person': 'Sam', 'pay_date': date.today().isoformat(),
         'gross_annual': '36000', 'tax_code': '1257L'},
    )
    assert saved.member_id is None


def test_shared_age_controls_all_pension_projections(scoped):
    person = member(scoped)
    source(person.id)
    first = pension(person.id, retirement_age='60')
    second = pension(person.id, retirement_age='70')
    IncomeProjectionService.set_retirement('Sam', {
        'member_id': str(person.id), 'date_of_birth': '1980-01-01', 'retirement_age': '68',
    })
    assert first.retirement_age != second.retirement_age
    assert len(PensionService.generate_projections(first)) == len(PensionService.generate_projections(second))
    PensionService.update_pension(second.id, {
        'member_id': str(person.id), 'provider': 'Pot', 'retirement_age': '66',
    })
    assert IncomeProjectionService.retirement_for('Sam', person.id)['age'] == 66


def test_linked_and_unlinked_names_do_not_share_profiles(scoped):
    person = member(scoped)
    source(person.id)
    source('', person='Sam')
    RetirementService.save('Sam', {
        'date_of_birth': '1980-01-01', 'retirement_age': '60',
    }, person.id)
    RetirementService.save('Sam', {
        'date_of_birth': '1980-01-01', 'retirement_age': '70',
    }, None)
    plan = IncomeProjectionService.build_plan()
    assert plan['retirements']['Sam']['age'] == 60
    assert plan['retirements']['Sam (unlinked)']['age'] == 70


def test_removal_detaches_pensions_without_losing_values(scoped, user):
    person = member(scoped)
    pot = pension(person.id)
    FamilyService.remove_member(person.id, scoped.id, user.id)
    db.session.expire_all()
    assert pot.member_id is None
    assert pot.person == 'Sam'
    assert pot.current_value == Decimal('10000')


def test_profile_dates_are_validated_and_clear_does_not_resurrect_legacy(scoped, user):
    person = member(scoped)
    Settings.set_value('sam_date_of_birth', '1980-01-01')
    db.session.commit()
    RetirementService.save('Sam', {'date_of_birth': '1981-02-03', 'retirement_age': '68'}, person.id)
    with pytest.raises(ValueError, match='valid date'):
        RetirementService.save('Sam', {'date_of_birth': 'bad'}, person.id)
    db.session.rollback()
    RetirementService.save('Sam', {'date_of_birth': ''}, person.id)
    FamilyService.update_member(person.id, scoped.id, user.id, 'member', 'Samantha', [])
    assert RetirementService.profile('Sam', person.id) is None


def test_account_deletion_clears_pension_link_and_member_profile(scoped, monkeypatch):
    person = member(scoped)
    pot = pension(person.id)
    RetirementService.save('Sam', {
        'date_of_birth': '1980-01-01', 'retirement_age': '68',
    }, person.id)
    person_id = person.id
    monkeypatch.setattr('services.platform.account_deletion_service.get_current_user_id', lambda: person_id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: person_id)
    AccountDeletionService.delete_account(person, {
        'confirmation': 'DELETE MY ACCOUNT', 'password': 'TestPass1!',
    })
    db.session.expire_all()
    assert pot.member_id is None
    assert Settings.query.filter(Settings.key.like(f'retirement.member.{person_id}.%')).count() == 0


def test_pension_link_cannot_point_to_another_members_pot(scoped):
    one, two = member(scoped, 'One'), member(scoped, 'Two')
    pot = pension(two.id)
    with pytest.raises(ValueError, match='same household member'):
        source(one.id, pension_id=str(pot.id))


def test_member_forms_and_retirement_routes(scoped, user, app):
    from tests.auth_helpers import login_client
    person = member(scoped)
    job = source(person.id)
    pot = pension(person.id)
    RetirementService.save_age('Sam', 63, person.id)
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    income = Income.query.filter_by(recurring_income_id=job.id).first()
    for url in ('/income/add', f'/income/{income.id}/edit',
                '/income/recurring/add', f'/income/recurring/{job.id}/edit',
                '/pensions/add', f'/pensions/{pot.id}/edit'):
        response = client.get(url)
        assert response.status_code == 200
        assert f'value="{person.id}"' in response.text
        assert 'name="member_id"' in response.text
    assert 'value="63"' in client.get('/income/plan').text
    response = client.post('/income/add', data={
        'member_id': str(person.id), 'person': 'forged display text',
        'pay_date': date.today().isoformat(), 'gross_annual': '12000', 'tax_code': '1257L',
    })
    assert response.status_code == 302
    assert Income.query.filter_by(recurring_income_id=None, member_id=person.id, person='Sam').count() == 1
    response = client.post(f'/pensions/{pot.id}/retirement', data={
        'date_of_birth': '1980-01-01', 'retirement_age': '69',
    })
    assert response.status_code == 302
    assert IncomeProjectionService.retirement_for('Sam', person.id)['age'] == 69
    for url in ('/income/plan', '/pensions/retirement-summary'):
        response = client.get(url)
        assert response.status_code == 200
        assert '69' in response.text


def test_migration_backfills_unique_names_and_preserves_conflicts():
    path = Path(__file__).resolve().parents[1] / 'migrations' / 'versions' / 'f7c2e5a9b3d4_pension_member_and_retirement_profiles.py'
    spec = importlib.util.spec_from_file_location('member_profile_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, family_id INTEGER, name TEXT, member_name TEXT)'))
        connection.execute(text('CREATE TABLE pensions (id INTEGER PRIMARY KEY, family_id INTEGER, person TEXT, retirement_age INTEGER)'))
        connection.execute(text('CREATE TABLE settings (id INTEGER PRIMARY KEY, family_id INTEGER, key TEXT, value TEXT, description TEXT, setting_type TEXT)'))
        connection.execute(text("INSERT INTO users VALUES (1,1,'Account','Sam'),(2,1,'Two','Alex'),(3,1,'Three','Alex'),(4,2,'Sam',NULL)"))
        connection.execute(text("INSERT INTO pensions VALUES (1,1,' SAM ',65),(2,1,'Alex',66),(3,2,'Sam',70),(4,1,'Unknown',68)"))
        connection.execute(text("INSERT INTO settings VALUES (1,1,'sam_date_of_birth','1980-01-01','','string'),(2,2,'sam_date_of_birth','1990-01-01','','string'),(3,1,'alex_date_of_birth','1970-01-01','','string')"))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            assert connection.execute(text('SELECT member_id FROM pensions ORDER BY id')).scalars().all() == [1, None, 4, None]
            assert connection.execute(text("SELECT value FROM settings WHERE family_id=1 AND key='retirement.member.1.date_of_birth'")).scalar() == '1980-01-01'
            assert connection.execute(text("SELECT value FROM settings WHERE family_id=2 AND key='retirement.member.4.date_of_birth'")).scalar() == '1990-01-01'
            assert connection.execute(text("SELECT count(*) FROM settings WHERE key='retirement.member.2.date_of_birth'")).scalar() == 0
            module.downgrade()
            module.upgrade()
            assert connection.execute(text('SELECT count(*) FROM pensions')).scalar() == 4
            connection.execute(text("DELETE FROM settings WHERE key='retirement.member.1.date_of_birth'"))
            connection.execute(text("INSERT INTO settings (family_id,key,value,setting_type) VALUES (1,'account_date_of_birth','1981-01-01','string')"))
            module._profiles(connection, *module._members(connection))
            assert connection.execute(text("SELECT count(*) FROM settings WHERE key='retirement.member.1.date_of_birth'")).scalar() == 0
            connection.execute(text("UPDATE settings SET value='invalid' WHERE family_id=2 AND key='sam_date_of_birth'"))
            connection.execute(text("DELETE FROM settings WHERE key='retirement.member.4.date_of_birth'"))
            module._profiles(connection, *module._members(connection))
            assert connection.execute(text("SELECT count(*) FROM settings WHERE key='retirement.member.4.date_of_birth'")).scalar() == 0
    engine.dispose()
