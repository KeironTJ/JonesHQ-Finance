from flask import redirect, render_template, url_for
from flask_login import current_user, login_required
from services.platform.landing_service import LandingService

from . import central_bp


@central_bp.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('auth.intro'))
    return redirect(LandingService.resolve(current_user))


@central_bp.route('/hub')
@login_required
def hub():
    return render_template('central/index.html')
