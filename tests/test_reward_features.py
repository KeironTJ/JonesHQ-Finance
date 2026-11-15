from datetime import datetime, timedelta, timezone
from uuid import uuid4

from extensions import db
from models import (
    HouseholdTask, Reward, RewardAchievement, RewardAchievementUnlock, RewardChoreTemplate, RewardGoal, RewardJob,
    RewardPointEntry, RewardRequest,
)
from services.household.reward_achievement_service import RewardAchievementService
from services.household.reward_service import RewardService
from tests.test_household_rewards import (  # noqa: F401 - fixtures are imported for pytest
    act, client_for, earn, isolate_login_state, people,
)


def member_id(person):
    return person.get_active_household_membership().id


def balance(person):
    return sum(entry.points for entry in RewardPointEntry.query.filter_by(membership_id=member_id(person)))


def save_reward(app, adult, **values):
    data = dict(title='Cinema trip', description='', points_cost='5')
    data.update(values)
    assert act(app, adult, 'save-reward', **data).status_code == 302
    return Reward.query.order_by(Reward.id.desc()).first()


def request(app, person, reward):
    return act(app, person, 'request', reward_id=reward.id, request_key=str(uuid4()))


def make_job(app, adult, person, title='Feed the cat'):
    response = act(app, adult, 'create-job', title=title, reward_points='20', assigned_membership_id=member_id(person))
    assert response.status_code == 302, response.data
    return RewardJob.query.order_by(RewardJob.id.desc()).first()


def submitted_job(app, adult, person, title='Feed the cat'):
    job = make_job(app, adult, person, title)
    assert act(app, person, 'submit-job', job_id=job.id).status_code == 302
    return job


def test_nobody_approves_or_awards_points_to_themselves(app, user, people):
    adult, child, _ = people
    assert act(app, adult, 'set-participation', enabled='yes').status_code == 302
    job = submitted_job(app, user, adult)
    html = act(app, adult, 'review-job', job_id=job.id, action='approve').get_data(as_text=True)
    assert 'Another adult needs to approve your own chores.' in html
    assert job.state == 'submitted' and RewardPointEntry.query.count() == 0
    assert act(app, user, 'review-job', job_id=job.id, action='approve').status_code == 302
    assert job.state == 'approved' and balance(adult) == 20
    html = act(app, adult, 'award', membership_id=member_id(adult), points='50', reason='Great week').get_data(as_text=True)
    assert 'Another adult needs to give you bonus points or deductions.' in html
    reward = save_reward(app, user)
    assert request(app, adult, reward).status_code == 302
    reward_request = RewardRequest.query.one()
    html = act(app, adult, 'review-request', request_id=reward_request.id, action='approve').get_data(as_text=True)
    assert 'Another adult needs to approve your own reward requests.' in html
    assert reward_request.state == 'pending'
    html = client_for(app, adult).get('/household/rewards/approvals').get_data(as_text=True)
    assert 'Another adult needs to approve' in html
    assert act(app, user, 'review-request', request_id=reward_request.id, action='approve').status_code == 302
    assert reward_request.state == 'approved'


def test_reward_stock_cooldown_and_per_person_limits(app, user, people):
    adult, child, sibling = people
    earn(app, adult, child)
    earn(app, adult, sibling)
    stocked = save_reward(app, adult, title='Sticker', stock='1')
    assert request(app, child, stocked).status_code == 302
    assert stocked.stock == 0 and balance(child) == 15
    assert 'out of stock' in request(app, sibling, stocked).get_data(as_text=True)
    pending = RewardRequest.query.one()
    assert act(app, child, 'cancel-request', request_id=pending.id).status_code == 302
    assert pending.state == 'declined' and stocked.stock == 1 and balance(child) == 20
    assert act(app, sibling, 'cancel-request', request_id=pending.id).status_code == 404
    assert request(app, sibling, stocked).status_code == 302

    cooldown = save_reward(app, adult, title='Pizza night', points_cost='1', cooldown_days='7')
    assert request(app, child, cooldown).status_code == 302
    first = RewardRequest.query.order_by(RewardRequest.id.desc()).first()
    assert act(app, adult, 'review-request', request_id=first.id, action='approve').status_code == 302
    assert 'You can ask for this again from' in request(app, child, cooldown).get_data(as_text=True)

    limited = save_reward(app, adult, title='Late bedtime', points_cost='1', member_limit='1', limit_period='ever')
    assert request(app, child, limited).status_code == 302
    second = RewardRequest.query.order_by(RewardRequest.id.desc()).first()
    assert act(app, adult, 'review-request', request_id=second.id, action='approve').status_code == 302
    assert 'This reward is limited to 1 in total for each person.' in request(app, child, limited).get_data(as_text=True)
    assert request(app, sibling, limited).status_code == 302
    html = act(app, adult, 'save-reward', title='Broken', points_cost='1', member_limit='2').get_data(as_text=True)
    assert 'Choose how often the per-person limit resets.' in html


def test_bulk_review_is_all_or_nothing_and_given_rewards_are_tracked(app, user, people):
    adult, child, sibling = people
    jobs = [submitted_job(app, adult, child), submitted_job(app, adult, sibling, 'Walk the dog')]
    ids = [job.id for job in jobs]
    html = act(app, adult, 'bulk-review', kind='jobs', action='return', ids=ids).get_data(as_text=True)
    assert 'Add a helpful note' in html and all(job.state == 'submitted' for job in jobs)
    assert act(app, adult, 'set-participation', enabled='yes').status_code == 302
    own = submitted_job(app, user, adult, 'Wash the car')
    html = act(app, adult, 'bulk-review', kind='jobs', action='approve', ids=ids + [own.id]).get_data(as_text=True)
    assert 'Another adult needs to approve your own chores.' in html
    assert RewardPointEntry.query.count() == 0 and all(job.state == 'submitted' for job in jobs)
    response = act(app, adult, 'bulk-review', kind='jobs', action='approve', ids=ids)
    assert response.status_code == 302
    assert all(job.state == 'approved' for job in jobs) and balance(child) == balance(sibling) == 20
    assert child_client_cannot(app, child, 'bulk-review', kind='jobs', action='approve', ids=[own.id])

    reward = save_reward(app, adult)
    assert request(app, child, reward).status_code == 302
    assert request(app, sibling, reward).status_code == 302
    requests = RewardRequest.query.order_by(RewardRequest.id).all()
    html = act(app, adult, 'fulfil', ids=[item.id for item in requests]).get_data(as_text=True)
    assert 'Only approved rewards can be marked as given.' in html
    assert act(app, adult, 'bulk-review', kind='requests', action='approve', ids=[item.id for item in requests]).status_code == 302
    html = client_for(app, adult).get('/household/rewards/approvals').get_data(as_text=True)
    assert 'bulk-fulfil' in html
    assert act(app, adult, 'fulfil', ids=[item.id for item in requests]).status_code == 302
    assert all(item.fulfilled_at and item.fulfilled_by_membership_id == member_id(adult) for item in requests)
    html = client_for(app, child).get('/household/rewards/activity?type=rewards').get_data(as_text=True)
    assert 'Reward given' in html


def child_client_cannot(app, child, operation, **data):
    return act(app, child, operation, **data).status_code == 403


def test_bonuses_and_deductions_need_reasons_and_never_go_negative(app, user, people):
    adult, child, _ = people
    target = member_id(child)
    assert act(app, user, 'award', membership_id=target, points='10', reason='Spelling test', category='school').status_code == 302
    bonus = RewardPointEntry.query.filter_by(kind='bonus').one()
    assert bonus.points == 10 and bonus.category == 'school' and bonus.actor_membership_id == member_id(user)
    html = act(app, user, 'award', membership_id=target, points='5', reason='').get_data(as_text=True)
    assert 'Add a reason' in html
    html = act(app, user, 'award', kind='deduction', membership_id=target, points='25', reason='Broke a rule').get_data(as_text=True)
    assert 'Deductions cannot take a balance below zero.' in html
    assert act(app, user, 'award', kind='deduction', membership_id=target, points='4', reason='Broke a rule').status_code == 302
    assert balance(child) == 6
    assert child_client_cannot(app, child, 'award', membership_id=member_id(people[2]), points='5', reason='Nice')
    html = client_for(app, child).get('/household/rewards/activity').get_data(as_text=True)
    assert 'Spelling test' in html and 'Broke a rule' in html and 'School' in html


def test_custom_achievement_unlocks_once_and_pays_its_bonus(app, user, people):
    adult, child, _ = people
    response = act(
        app, adult, 'save-achievement', title='Star pupil', description='Recognised for school work', icon='trophy',
        metric='recognition', threshold='1', bonus_points='15', active='yes',
    )
    assert response.status_code == 302
    assert act(app, adult, 'award', membership_id=member_id(child), points='5', reason='Reading award', category='school').status_code == 302
    titles = sorted(row.title for row in RewardAchievementUnlock.query.filter_by(membership_id=member_id(child)))
    assert titles == ['Proud moment', 'Star pupil']
    milestone = RewardPointEntry.query.filter_by(kind='milestone').one()
    assert milestone.points == 15 and balance(child) == 20
    assert act(app, adult, 'award', membership_id=member_id(child), points='5', reason='Another award').status_code == 302
    assert RewardAchievementUnlock.query.filter_by(membership_id=member_id(child)).count() == 2
    assert RewardPointEntry.query.filter_by(kind='milestone').count() == 1
    html = client_for(app, child).get(f'/household/rewards/members/{member_id(child)}').get_data(as_text=True)
    assert 'Star pupil' in html
    achievement = RewardAchievement.query.filter_by(title='Star pupil').one()
    html = act(app, adult, 'save-achievement', achievement_id=achievement.id, title='x' * 65, metric='points', threshold='1').get_data(as_text=True)
    assert 'Enter an achievement name up to 64 characters' in html
    assert child_client_cannot(app, child, 'save-achievement', title='Mine', metric='points', threshold='1')


def test_streaks_count_consecutive_london_days(app, user, people, monkeypatch):
    _, child, sibling = people
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: user.family_id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for days_ago in (0, 1, 2, 5, 6, 7, 8):
        db.session.add(RewardPointEntry(
            family_id=user.family_id, membership_id=member_id(child), kind='earned', points=1,
            description='Chore', created_at=now - timedelta(days=days_ago),
        ))
    db.session.add(RewardPointEntry(
        family_id=user.family_id, membership_id=member_id(sibling), kind='earned', points=1,
        description='Chore', created_at=now - timedelta(days=3),
    ))
    db.session.add(RewardPointEntry(
        family_id=user.family_id, membership_id=member_id(sibling), kind='bonus', points=1,
        description='Bonus', created_at=now,
    ))
    db.session.commit()
    streaks = RewardAchievementService.streaks([member_id(child), member_id(sibling)])
    assert streaks[member_id(child)] == (3, 4)
    assert streaks[member_id(sibling)] == (0, 1)


def test_activity_filters_and_member_pages_respect_privacy(app, user, people):
    adult, child, sibling = people
    earn(app, adult, child)
    job = make_job(app, adult, sibling, 'Walk the dog')
    assert act(app, sibling, 'submit-job', job_id=job.id).status_code == 302
    assert act(app, adult, 'review-job', job_id=job.id, action='approve').status_code == 302
    html = client_for(app, child).get(f'/household/rewards/activity?member={member_id(sibling)}').get_data(as_text=True)
    assert 'Feed the cat' in html and 'Walk the dog' not in html
    html = client_for(app, adult).get(f'/household/rewards/activity?member={member_id(sibling)}').get_data(as_text=True)
    assert 'Walk the dog' in html and 'Feed the cat' not in html
    html = client_for(app, adult).get('/household/rewards/activity?type=bonuses').get_data(as_text=True)
    assert 'Walk the dog' not in html and 'Feed the cat' not in html
    assert client_for(app, adult).get('/household/rewards/activity?type=nope').status_code == 302
    assert client_for(app, adult).get('/household/rewards/activity?from=2026-02-10&to=2026-02-01').status_code == 302
    assert client_for(app, child).get(f'/household/rewards/members/{member_id(sibling)}').status_code == 403
    assert client_for(app, child).get(f'/household/rewards/members/{member_id(child)}').status_code == 200
    assert client_for(app, adult).get(f'/household/rewards/members/{member_id(user)}').status_code == 404
    html = client_for(app, adult).get(f'/household/rewards/members/{member_id(child)}').get_data(as_text=True)
    assert 'id="give-bonus"' in html and child.name in html


def test_adult_participation_rules(app, user, people):
    adult, child, _ = people
    assert not RewardService.is_participant(adult.get_active_household_membership())
    assert act(app, adult, 'set-participation', membership_id=member_id(user), enabled='yes').status_code == 403
    assert child_client_cannot(app, child, 'set-participation', enabled='yes')
    html = act(app, user, 'set-participation', membership_id=member_id(child), enabled='no').get_data(as_text=True)
    assert 'Choose an adult in this household.' in html
    assert act(app, user, 'set-participation', membership_id=member_id(adult), enabled='yes').status_code == 302
    assert adult.get_active_household_membership().rewards_participant
    make_job(app, user, adult)
    html = act(app, user, 'set-participation', membership_id=member_id(adult), enabled='no').get_data(as_text=True)
    assert 'Finish or close their open chores and reward requests first.' in html
    assert adult.get_active_household_membership().rewards_participant
    html = client_for(app, user).get('/household/rewards/settings').get_data(as_text=True)
    assert adult.name in html


def test_chore_library_templates_prefill_new_chores(app, user, people):
    adult, child, _ = people
    assert act(app, adult, 'save-template', title='Water plants', notes='Both pots', points='7').status_code == 302
    template = RewardChoreTemplate.query.one()
    assert act(app, adult, 'save-template', template_id=template.id, title='Water the plants', notes='All pots', points='8').status_code == 302
    assert (template.title, template.notes, template.points) == ('Water the plants', 'All pots', 8)
    response = act(app, adult, 'create-job', template_id=template.id, title='', assigned_membership_id=member_id(child))
    assert response.status_code == 302
    job = RewardJob.query.one()
    assert job.title == 'Water the plants' and job.points == 8 and job.task.notes == 'All pots'
    assert act(app, adult, 'create-job', template_id='99999', assigned_membership_id=member_id(child)).status_code == 200
    assert RewardJob.query.count() == 1
    assert child_client_cannot(app, child, 'save-template', title='Mine', points='5')
    assert act(app, adult, 'delete-template', template_id=template.id).status_code == 302
    assert RewardChoreTemplate.query.count() == 0 and HouseholdTask.query.count() == 1


def test_people_can_save_several_goals_up_to_the_limit(app, user, people):
    adult, child, _ = people
    rewards = [save_reward(app, adult, title=f'Reward {index}') for index in range(6)]
    for reward in rewards[:5]:
        assert act(app, child, 'goal', reward_id=reward.id).status_code == 302
    html = act(app, child, 'goal', reward_id=rewards[5].id).get_data(as_text=True)
    assert 'Choose up to 5 goals.' in html and RewardGoal.query.count() == 5
    assert act(app, child, 'goal', reward_id=rewards[0].id, action='remove').status_code == 302
    assert RewardGoal.query.count() == 4
    assert act(app, adult, 'goal', reward_id=rewards[5].id, membership_id=member_id(child)).status_code == 302
    assert {goal.reward_id for goal in RewardGoal.query} == {reward.id for reward in rewards[1:]}
    assert act(app, adult, 'goal', reward_id=rewards[0].id).status_code == 403
