from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from services.household.reward_achievement_service import RewardAchievementService
from services.household.reward_activity_service import RewardActivityService
from services.household.reward_service import RewardService
from . import household_bp


LEGACY_VIEWS = {
    'jobs': 'household.reward_chores', 'shop': 'household.reward_shop',
    'manage': 'household.reward_approvals', 'progress': 'household.reward_activity',
}
PAGES = {
    'household.rewards': ('household/rewards/overview.html', RewardService.overview_data),
    'household.reward_chores': ('household/rewards/chores.html', RewardService.chores_data),
    'household.reward_shop': ('household/rewards/shop.html', RewardService.shop_data),
    'household.reward_approvals': ('household/rewards/approvals.html', RewardService.approvals_data),
    'household.reward_settings': ('household/rewards/settings.html', RewardService.settings_data),
}


def _render(endpoint, **extra):
    template, loader = PAGES[endpoint]
    return render_template(template, **loader(), submitted=extra.pop('submitted', {}), active_page=endpoint, **extra)


def _safe_next():
    target = request.form.get('next') or ''
    if target.startswith('/household/') and '//' not in target and '\\' not in target:
        return target
    return None


@household_bp.route('/rewards')
@login_required
def rewards():
    view = request.args.get('view')
    if view in LEGACY_VIEWS:
        if view == 'manage' and current_user.is_managed_child:
            abort(403)
        return redirect(url_for(LEGACY_VIEWS[view]))
    return _render('household.rewards')


@household_bp.route('/rewards/chores')
@login_required
def reward_chores():
    return _render('household.reward_chores')


@household_bp.route('/rewards/shop')
@login_required
def reward_shop():
    try:
        context = RewardService.shop_data(request.args.get('category') or None)
    except (ValueError, TypeError) as error:
        flash(str(error) or 'Choose a reward category.', 'danger')
        return redirect(url_for('household.reward_shop'))
    return render_template('household/rewards/shop.html', **context, submitted={}, active_page='household.reward_shop')


@household_bp.route('/rewards/approvals')
@login_required
def reward_approvals():
    return _render('household.reward_approvals')


@household_bp.route('/rewards/activity')
@login_required
def reward_activity():
    try:
        context = RewardActivityService.page_data(request.args)
    except (ValueError, TypeError) as error:
        flash(str(error) or 'Check the activity filters.', 'danger')
        return redirect(url_for('household.reward_activity'))
    return render_template(
        'household/rewards/activity.html', **context, submitted={}, active_page='household.reward_activity',
    )


@household_bp.route('/rewards/members/<int:membership_id>')
@login_required
def reward_member(membership_id):
    context = RewardActivityService.member_data(membership_id)
    return render_template('household/rewards/member.html', **context, submitted={}, active_page='household.reward_member')


@household_bp.route('/rewards/settings')
@login_required
def reward_settings():
    return _render('household.reward_settings')


def _count_message(template):
    return lambda result: template.format(n=result, s='' if result == 1 else 's')


OPERATIONS = {
    'create-job': (RewardService.create_job, 'Chore added.', 'household.reward_chores'),
    'submit-job': (
        lambda form: RewardService.submit_job(form.get('job_id'), form),
        'Well done! Waiting for an adult to check.', 'household.reward_chores',
    ),
    'claim-job': (
        lambda form: RewardService.claim_job(form.get('job_id'), form),
        'Chore claimed! Complete it, then send it for approval.', 'household.reward_chores',
    ),
    'review-job': (
        lambda form: RewardService.review_job(form.get('job_id'), form), 'Chore reviewed.', 'household.reward_approvals',
    ),
    'bulk-review': (RewardService.bulk_review, _count_message('{n} item{s} reviewed.'), 'household.reward_approvals'),
    'save-reward': (
        lambda form: RewardService.save_reward(form, form.get('reward_id') or None),
        'Reward saved.', 'household.reward_settings',
    ),
    'request': (
        lambda form: RewardService.request_reward(form.get('reward_id'), form),
        'Reward requested! Your points are held until an adult decides.', 'household.reward_shop',
    ),
    'cancel-request': (
        lambda form: RewardService.cancel_request(form.get('request_id'), form),
        'Request cancelled. Your points are back.', 'household.reward_shop',
    ),
    'review-request': (
        lambda form: RewardService.review_request(form.get('request_id'), form),
        'Reward request reviewed.', 'household.reward_approvals',
    ),
    'fulfil': (RewardService.fulfil_requests, _count_message('{n} reward{s} marked as given.'), 'household.reward_approvals'),
    'goal': (RewardService.set_goal, 'Goals updated.', 'household.reward_shop'),
    'award': (RewardService.award_points, 'Points recorded.', 'household.rewards'),
    'set-board': (RewardService.set_board, 'Leaderboard sharing updated.', 'household.reward_settings'),
    'set-participation': (RewardService.set_participation, 'Points participation updated.', 'household.reward_settings'),
    'save-template': (
        lambda form: RewardService.save_template(form, form.get('template_id') or None),
        'Chore saved to the library.', 'household.reward_settings',
    ),
    'delete-template': (RewardService.delete_template, 'Chore removed from the library.', 'household.reward_settings'),
    'save-achievement': (
        lambda form: RewardAchievementService.save_achievement(form, form.get('achievement_id') or None),
        'Achievement saved.', 'household.reward_settings',
    ),
}


@household_bp.route('/rewards/actions/<action>', methods=['POST'])
@login_required
def reward_action(action):
    if action not in OPERATIONS:
        abort(404)
    operation, message, endpoint = OPERATIONS[action]
    try:
        result = operation(request.form)
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Check the reward details and try again.', 'danger')
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to save household rewards action: %s', action)
        flash('Unable to save the rewards change. No changes were saved.', 'danger')
    else:
        flash(message(result) if callable(message) else message, 'success')
        if request.form.get('return_to') == 'my-day' and current_user.is_managed_child:
            return redirect(url_for('household.my_day'))
        return redirect(_safe_next() or url_for(endpoint))
    if _safe_next():
        return redirect(_safe_next())
    if endpoint == 'household.reward_approvals' and current_user.is_managed_child:
        endpoint = 'household.rewards'
    if endpoint == 'household.reward_settings' and current_user.is_managed_child:
        abort(403)
    return _render(endpoint, submitted=request.form, failed_action=action)
