"""
Flask-Admin operator console for Family HQ, at /admin.

Operator-only: users, households, invites, sessions, security events and the
global UK tax-year templates. Household financial data is deliberately not
exposed here; households manage their own data in the app. Access requires a
site admin with two-factor login and a recent password confirmation.
"""
from flask import flash, redirect, url_for
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.actions import action
from flask_admin.contrib.sqla import ModelView
from flask_admin.form import SecureForm
from flask_admin.theme import Bootstrap4Theme
from flask_login import current_user


def _is_two_factor_site_admin():
    return current_user.is_authenticated and current_user.is_site_admin and current_user.two_factor_enabled


def _is_verified_site_admin():
    from services.platform.user_session_service import UserSessionService
    return _is_two_factor_site_admin() and UserSessionService.is_recently_authenticated(current_user)


def _deny_admin_access():
    if _is_two_factor_site_admin():
        from utils.reauth import reauthentication_redirect
        return reauthentication_redirect()
    flash('Admin access required.', 'danger')
    return redirect(url_for('auth.intro'))


class SecureAdminIndexView(AdminIndexView):
    @expose('/')
    def index(self):
        if not _is_verified_site_admin():
            return _deny_admin_access()
        return super().index()

    def is_accessible(self):
        return _is_verified_site_admin()

    def inaccessible_callback(self, name, **kwargs):
        return _deny_admin_access()


class OperatorView(ModelView):
    """Read-only by default; every form (incl. actions) carries a CSRF token."""

    form_base_class = SecureForm
    can_create = False
    can_edit = False
    can_delete = False
    can_export = False
    can_view_details = True
    page_size = 50
    column_display_pk = True

    def __init__(self, model, session, **kwargs):
        # Prefix endpoints so they don't clash with app blueprints of the same name.
        kwargs.setdefault('endpoint', f'admin_{model.__name__.lower()}')
        super().__init__(model, session, **kwargs)

    def is_accessible(self):
        return _is_verified_site_admin()

    def inaccessible_callback(self, name, **kwargs):
        return _deny_admin_access()


class UserAdminView(OperatorView):
    """Users. Changes go through actions so they are audited and revoke sessions."""

    _secret_columns = ['password_hash', 'totp_secret', 'totp_last_step', 'recovery_codes', 'sessions']
    column_exclude_list = _secret_columns
    column_details_exclude_list = _secret_columns
    column_export_exclude_list = _secret_columns
    can_export = True
    column_searchable_list = ['email', 'name', 'member_name']
    column_filters = ['role', 'is_active', 'is_site_admin', 'family_id']
    column_list = [
        'id', 'name', 'email', 'role', 'is_active', 'is_site_admin',
        'family_id', 'member_name', 'last_login', 'created_at',
        'failed_login_attempts', 'locked_until', 'totp_enabled_at',
    ]
    column_export_list = column_list
    column_details_list = column_list + ['email_verified_at', 'onboarding_version']
    column_labels = {'totp_enabled_at': '2FA enabled'}

    def _apply(self, ids, change, event_type, message):
        from extensions import db
        from models.users import User
        from services.platform.security_event_service import SecurityEventService
        from services.platform.user_session_service import UserSessionService

        changed = 0
        for user in User.query.filter(User.id.in_([int(i) for i in ids])).all():
            if user.id == current_user.id and event_type == 'account_deactivated':
                flash('You cannot deactivate your own account here.', 'warning')
                continue
            if not change(user):
                continue
            db.session.commit()
            details = f'by site admin {current_user.id}'
            SecurityEventService.record(event_type, user=user, details=details)
            if event_type in ('account_deactivated', 'all_sessions_revoked'):
                UserSessionService.revoke_all(user, reason=f'site admin {current_user.id}')
            changed += 1
        flash(f'{message}: {changed} user(s).', 'success')

    @action('deactivate', 'Deactivate', 'Deactivate the selected users and sign them out everywhere?')
    def action_deactivate(self, ids):
        def change(user):
            if not user.is_active:
                return False
            user.is_active = False
            return True
        self._apply(ids, change, 'account_deactivated', 'Deactivated')

    @action('reactivate', 'Reactivate', 'Reactivate the selected users?')
    def action_reactivate(self, ids):
        def change(user):
            if user.is_active:
                return False
            user.is_active = True
            return True
        self._apply(ids, change, 'account_reactivated', 'Reactivated')

    @action('unlock', 'Unlock sign-in', 'Clear failed sign-in lockouts for the selected users?')
    def action_unlock(self, ids):
        def change(user):
            if not user.failed_login_attempts and not user.locked_until:
                return False
            user.failed_login_attempts = 0
            user.locked_until = None
            return True
        self._apply(ids, change, 'account_unlocked', 'Unlocked')

    @action('sign_out', 'Sign out everywhere', 'Sign the selected users out of every device?')
    def action_sign_out(self, ids):
        from extensions import db
        from models.users import User
        from services.platform.user_session_service import UserSessionService

        users = User.query.filter(User.id.in_([int(i) for i in ids])).all()
        for user in users:
            UserSessionService.revoke_all(user, reason=f'site admin {current_user.id}')
        db.session.commit()
        flash(f'Signed out: {len(users)} user(s).', 'success')


class FamilyAdminView(OperatorView):
    column_searchable_list = ['name']
    column_list = ['id', 'name', 'onboarding_version', 'created_at']


class FamilyInviteAdminView(OperatorView):
    # The raw token would let the operator join the household; never show it.
    column_list = ['id', 'family_id', 'role', 'member_name', 'created_by_id', 'created_at',
                   'expires_at', 'used_at', 'used_by_id']
    column_details_list = column_list
    column_filters = ['family_id']


class HouseholdInviteAdminView(OperatorView):
    column_list = ['id', 'email', 'note', 'created_by_id', 'created_at', 'expires_at',
                   'used_at', 'used_by_id', 'revoked_at']
    column_details_list = column_list


class UserSessionAdminView(OperatorView):
    column_list = ['id', 'user', 'remember', 'created_at', 'last_seen_at', 'expires_at',
                   'revoked_at', 'ip_address', 'user_agent']
    column_details_list = column_list
    column_default_sort = ('last_seen_at', True)


class SecurityEventAdminView(OperatorView):
    can_export = True
    column_list = ['created_at', 'event_type', 'user', 'family_id', 'details', 'ip_address', 'user_agent']
    column_export_list = column_list
    column_filters = ['event_type', 'user_id', 'family_id', 'created_at']
    column_searchable_list = ['event_type', 'details', 'ip_address']
    column_default_sort = ('created_at', True)


class TaxTemplateAdminView(OperatorView):
    """Global UK tax-year defaults (family_id NULL) used by households without their own copy."""

    can_create = True
    can_edit = True
    form_excluded_columns = ['family_id', 'created_at', 'updated_at']
    column_exclude_list = ['family_id']
    column_default_sort = ('effective_from', True)

    def get_query(self):
        return super().get_query().filter(self.model.family_id.is_(None))

    def get_count_query(self):
        return super().get_count_query().filter(self.model.family_id.is_(None))

    def get_one(self, id):
        record = super().get_one(id)
        return record if record is not None and record.family_id is None else None

    def on_model_change(self, form, model, is_created):
        model.family_id = None
        # Stops the app's before_flush auto-stamp assigning the operator's household.
        model._global_record = True


def init_admin(app, db):
    """Create the Flask-Admin instance and register the operator views."""
    from models.family import Family, FamilyInvite, HouseholdInvite
    from models.tax_settings import TaxSettings
    from models.users import SecurityEvent, User, UserSession

    admin = Admin(
        app,
        name='FamilyHQ Admin',
        theme=Bootstrap4Theme(),
        index_view=SecureAdminIndexView(),
        url='/admin',
    )
    admin.add_view(UserAdminView(User, db.session, name='Users', category='Operator'))
    admin.add_view(FamilyAdminView(Family, db.session, name='Households', category='Operator'))
    admin.add_view(FamilyInviteAdminView(FamilyInvite, db.session, name='Member invites', category='Operator'))
    admin.add_view(HouseholdInviteAdminView(HouseholdInvite, db.session, name='Household invites', category='Operator'))
    admin.add_view(UserSessionAdminView(UserSession, db.session, name='Sessions', category='Operator'))
    admin.add_view(SecurityEventAdminView(SecurityEvent, db.session, name='Security events', category='Operator'))
    admin.add_view(TaxTemplateAdminView(TaxSettings, db.session, name='Tax year templates',
                                        category='Reference', endpoint='admin_taxtemplate'))
    return admin