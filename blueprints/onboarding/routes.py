from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required

from extensions import db
from services.platform.onboarding_service import OnboardingService
from . import onboarding_bp


@onboarding_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    context = OnboardingService.get_context()
    if context['mode'] == 'complete':
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        try:
            if context['mode'] == 'household':
                OnboardingService.complete_household(request.form)
                flash('Household setup complete. You are ready to start tracking.', 'success')
            else:
                OnboardingService.complete_personal(request.form)
                flash('Your default account has been saved.', 'success')
            return redirect(url_for('dashboard.index'))
        except (TypeError, ValueError) as error:
            db.session.rollback()
            flash(str(error) or 'Unable to complete setup.', 'danger')

    return render_template('onboarding/index.html', **context)


@onboarding_bp.route('/skip', methods=['POST'])
@login_required
def skip():
    context = OnboardingService.get_context()
    if context['mode'] == 'complete':
        return redirect(url_for('dashboard.index'))
    flash('Setup paused. You can continue from the dashboard when you are ready.', 'info')
    return redirect(url_for('dashboard.index'))