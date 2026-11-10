from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from services.household.reward_service import RewardService
from . import household_bp


@household_bp.route('/rewards')
@login_required
def rewards():
    view = request.args.get('view') or 'home'
    try:
        context = RewardService.page_data(view)
    except (ValueError, TypeError) as error:
        flash(str(error) or 'Choose a rewards page.', 'danger')
        return redirect(url_for('household.rewards'))
    return render_template('household/rewards.html', **context, submitted={})


@household_bp.route('/rewards/actions/<action>', methods=['POST'])
@login_required
def reward_action(action):
    operations = {
        'create-job': (RewardService.create_job, 'Job added.', 'manage'),
        'submit-job': (RewardService.submit_job, 'Well done! Waiting for an adult to check.', 'jobs'),
        'claim-job': (RewardService.claim_job, 'Job claimed! Complete it, then send it for approval.', 'jobs'),
        'review-job': (RewardService.review_job, 'Job reviewed.', 'manage'),
        'save-reward': (RewardService.save_reward, 'Reward saved.', 'manage'),
        'request': (RewardService.request_reward, 'Reward requested! Your points are held until an adult decides.', 'shop'),
        'review-request': (RewardService.review_request, 'Reward request reviewed.', 'manage'),
        'goal': (RewardService.set_goal, 'Your reward goal was updated.', 'shop'),
        'set-board': (RewardService.set_board, 'Celebration board sharing updated.', 'manage'),
    }
    if action not in operations:
        abort(404)
    operation, message, view = operations[action]
    try:
        if action in ('submit-job', 'review-job', 'claim-job'):
            operation(request.form.get('job_id'), request.form)
        elif action == 'save-reward':
            operation(request.form, request.form.get('reward_id') or None)
        elif action == 'request':
            operation(request.form.get('reward_id'), request.form)
        elif action == 'review-request':
            operation(request.form.get('request_id'), request.form)
        else:
            operation(request.form)
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Check the reward details and try again.', 'danger')
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to save household rewards action: %s', action)
        flash('Unable to save the rewards change. No changes were saved.', 'danger')
    else:
        flash(message, 'success')
        if current_user.is_managed_child and request.form.get('return_to') == 'my-day':
            return redirect(url_for('household.my_day'))
        return redirect(url_for('household.rewards', view=view))
    context = RewardService.page_data(view)
    return render_template('household/rewards.html', **context, submitted=request.form, failed_action=action)
