"""
Site admin (service operator) routes, under /site-admin.

Separate from household management: nothing here shows household financial
records. Every route requires a site admin with TOTP or a verified passkey session
(enforced app-wide) and recent password/passkey authentication.
"""
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from blueprints.site_admin import site_admin_bp
from blueprints.site_admin.forms import HouseholdInviteForm, SiteSettingsForm
from extensions import login_manager
from services.platform.household_invite_service import HouseholdInviteService
from services.platform.security_event_service import SecurityEventService
from services.platform.site_admin_service import SiteAdminService
from services.platform.site_settings_service import SiteSettingsService
from services.platform.user_session_service import UserSessionService
from utils.reauth import reauthentication_redirect


@site_admin_bp.before_request
def require_verified_site_admin():
    if not current_user.is_authenticated:
        return login_manager.unauthorized()
    if not current_user.is_site_admin:
        abort(403)
    if not UserSessionService.is_recently_authenticated(current_user):
        return reauthentication_redirect()


@site_admin_bp.route('/')
def index():
    return render_template(
        'site_admin/index.html',
        stats=SiteAdminService.overview(),
        site_settings=SiteSettingsService.get(),
        configuration=SiteAdminService.configuration(),
    )


@site_admin_bp.route('/settings', methods=['GET', 'POST'])
def settings():
    current = SiteSettingsService.get()
    form = SiteSettingsForm(obj=current)
    if form.validate_on_submit():
        try:
            changed = SiteSettingsService.update(request.form)
        except ValueError as error:
            flash(str(error) or 'Unable to save settings.', 'danger')
        else:
            flash('Site settings saved.' if changed else 'No changes to save.', 'success' if changed else 'info')
            return redirect(url_for('site_admin.settings'))
    return render_template('site_admin/settings.html', form=form, site_settings=current)


@site_admin_bp.route('/household-invites', methods=['GET', 'POST'])
def household_invites():
    """Issue one-time links that let a new household register"""
    form = HouseholdInviteForm()
    new_link = None

    if form.validate_on_submit():
        try:
            _, token = HouseholdInviteService.create_invite({
                'email': form.email.data,
                'note': form.note.data,
                'days': form.days.data,
            }, created_by_id=current_user.id)
        except ValueError as error:
            flash(str(error) or 'Unable to create invite.', 'danger')
        else:
            SecurityEventService.record('household_invite_created', details=form.email.data or form.note.data)
            new_link = url_for('auth.register', invite=token, _external=True)
            form = HouseholdInviteForm(formdata=None)

    return render_template(
        'site_admin/household_invites.html',
        form=form,
        invites=HouseholdInviteService.list_invites(),
        new_link=new_link,
    )


@site_admin_bp.route('/household-invites/<int:invite_id>/revoke', methods=['POST'])
def revoke_household_invite(invite_id):
    try:
        HouseholdInviteService.revoke_invite(invite_id)
    except ValueError as error:
        flash(str(error) or 'Unable to revoke invite.', 'danger')
    else:
        SecurityEventService.record('household_invite_revoked', details=f'invite {invite_id}')
        flash('Invite revoked.', 'success')
    return redirect(url_for('site_admin.household_invites'))
