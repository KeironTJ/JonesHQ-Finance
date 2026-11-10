"""
Family blueprint routes.

Household-owner routes (require login + owner role):
  GET  /family               – management page (members, active invites)
  POST /family/invite        – create a new invite link
  POST /family/invite/<id>/revoke  – revoke an unused invite
  POST /family/members/<id>/update – update a member's sections
  POST /family/members/<id>/remove – remove a member from the family

Public route (no login required):
  GET  /family/join/<token>  – show join/register form
  POST /family/join/<token>  – complete registration and join
"""
import json
from datetime import datetime, timezone

from flask import render_template, redirect, url_for, flash, request, abort, current_app, session
from flask_login import login_required, current_user
from sqlalchemy.exc import SQLAlchemyError

from blueprints.core.family import family_bp
from blueprints.core.family.forms import DeleteHouseholdForm
from extensions import db, limiter
from models.family import Family, FamilyInvite
from models.users import User
from utils.permissions import SECTION_GROUPS, SECTION_LABELS, OWNER_ONLY_SECTIONS
from utils.db_helpers import family_query, get_family_id
from services.household.family_service import FamilyService
from services.household.household_deletion_service import HouseholdDeletionService
from services.household.membership_service import HouseholdMembershipService
from services.platform.auth_service import AuthService
from services.platform.email_verification_service import EmailVerificationService
from services.platform.user_session_service import UserSessionService
from utils.reauth import recent_auth_required


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_household_owner():
    """Abort with 403 unless the current user owns their household."""
    if not current_user.is_authenticated or not current_user.is_household_owner:
        abort(403)


# ── Household-owner routes ──────────────────────────────────────────────────────────────

@family_bp.route('/', methods=['GET'])
@login_required
def index():
    _require_household_owner()

    family = db.session.get(Family, get_family_id())
    if family is None:
        # Bootstrap: create a default family for this owner
        family = Family(name='My Family')
        db.session.add(family)
        db.session.flush()
        current_user.family_id = family.id
        db.session.commit()

    memberships = family.memberships
    active_invites = (
        FamilyInvite.query
        .filter_by(family_id=family.id)
        .filter(FamilyInvite.used_at.is_(None),
                FamilyInvite.expires_at >= datetime.now(timezone.utc).replace(tzinfo=None))
        .order_by(FamilyInvite.created_at.desc())
        .all()
    )
    expired_invites = (
        FamilyInvite.query
        .filter_by(family_id=family.id)
        .filter(
            (FamilyInvite.expires_at < datetime.now(timezone.utc).replace(tzinfo=None)) |
            FamilyInvite.used_at.isnot(None)
        )
        .order_by(FamilyInvite.created_at.desc())
        .limit(20)
        .all()
    )
    return render_template(
        'family/index.html',
        family=family,
        memberships=memberships,
        active_invites=active_invites,
        expired_invites=expired_invites,
        section_groups=SECTION_GROUPS,
        section_labels=SECTION_LABELS,
    )


@family_bp.route('/select', methods=['POST'])
@login_required
def select_household():
    family_id = request.form.get('family_id', type=int)
    try:
        membership = HouseholdMembershipService.select(current_user, family_id)
    except ValueError as error:
        flash(str(error) or 'Choose a household you belong to.', 'danger')
    else:
        flash(f'Switched to {membership.family.name}.', 'success')
    return redirect(url_for('central.hub'))


@family_bp.route('/members/<int:member_id>/role', methods=['POST'])
@login_required
@recent_auth_required
def update_role(member_id):
    _require_household_owner()
    try:
        member = FamilyService.update_role(member_id, request.form)
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Invalid household role.', 'danger')
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to update household role')
        flash('Unable to update household role. Please try again.', 'danger')
    else:
        flash(f'Updated household role for {member.name}.', 'success')
    return redirect(url_for('family.index'))


@family_bp.route('/assignment-labels', methods=['POST'])
@login_required
def create_assignment_label():
    """Create a custom family assignment label (e.g., child/non-login person)."""
    _require_household_owner()

    family = db.session.get(Family, get_family_id())
    if family is None:
        flash('No family found. Please visit the Family page first.', 'danger')
        return redirect(url_for('settings.finance_access'))

    name = (request.form.get('label_name') or '').strip()
    if not name:
        flash('Label name is required.', 'danger')
        return redirect(url_for('settings.finance_access'))

    try:
        label = FamilyService.create_assignment_label(family.id, name)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to create transaction assignment label')
        flash('Unable to add assignment label. Please try again.', 'danger')
        return redirect(url_for('settings.finance_access'))
    if label is None:
        flash('That assignment label already exists.', 'warning')
        return redirect(url_for('settings.finance_access'))

    flash(f'Added assignment label: {name}', 'success')
    return redirect(url_for('settings.finance_access'))


@family_bp.route('/assignment-labels/<int:label_id>/delete', methods=['POST'])
@login_required
def delete_assignment_label(label_id):
    """Delete a custom family assignment label."""
    _require_household_owner()

    try:
        name = FamilyService.delete_assignment_label(label_id, get_family_id())
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to remove transaction assignment label')
        flash('Unable to remove assignment label. Please try again.', 'danger')
        return redirect(url_for('settings.finance_access'))
    flash(f'Removed assignment label: {name}', 'success')
    return redirect(url_for('settings.finance_access'))


@family_bp.route('/invite', methods=['POST'])
@login_required
@recent_auth_required
def create_invite():
    _require_household_owner()

    family = db.session.get(Family, get_family_id())
    if family is None:
        flash('No family found. Please visit the Family page first.', 'danger')
        return redirect(url_for('family.index'))

    member_name = request.form.get('member_name', '').strip()
    role = request.form.get('role', 'member')
    selected_sections = request.form.getlist('sections')  # list of section keys

    if not member_name:
        flash('Member name is required.', 'danger')
        return redirect(url_for('family.index'))

    if role not in ('admin', 'member'):
        role = 'member'

    invite = FamilyService.create_invite(
        family.id,
        current_user.id,
        member_name,
        role,
        selected_sections,
    )

    flash(f'Invite link created for {member_name}.', 'success')
    return redirect(url_for('family.index'))


@family_bp.route('/invite/<int:invite_id>/revoke', methods=['POST'])
@login_required
@recent_auth_required
def revoke_invite(invite_id):
    _require_household_owner()

    FamilyService.revoke_invite(invite_id, get_family_id())
    flash('Invite revoked.', 'success')
    return redirect(url_for('family.index'))


@family_bp.route('/members/<int:member_id>/update', methods=['POST'])
@login_required
@recent_auth_required
def update_member(member_id):
    _require_household_owner()

    member_name = request.form.get('member_name', '').strip()
    selected_sections = request.form.getlist('sections')
    role = request.form.get('role', 'member')
    member = FamilyService.update_member(
        member_id,
        get_family_id(),
        current_user.id,
        role,
        member_name,
        selected_sections,
    )
    if member is None:
        flash('You cannot edit your own permissions here.', 'warning')
        return redirect(url_for('family.index'))
    flash(f'Updated permissions for {member.name}.', 'success')
    return redirect(url_for('family.index'))


@family_bp.route('/members/<int:member_id>/remove', methods=['POST'])
@login_required
@recent_auth_required
def remove_member(member_id):
    _require_household_owner()

    name = FamilyService.remove_member(
        member_id,
        get_family_id(),
        current_user.id,
    )
    if name is None:
        flash('You cannot remove yourself from the family.', 'warning')
        return redirect(url_for('family.index'))
    flash(f'{name} has been removed from the family.', 'success')
    return redirect(url_for('family.index'))


@family_bp.route('/delete', methods=['GET', 'POST'])
@login_required
@recent_auth_required
@limiter.limit(
    "3 per 15 minutes", key_func=lambda: f"household-delete:{current_user.id}", methods=["POST"])
def delete_household():
    _require_household_owner()
    if get_family_id() is None:
        abort(403)
    form = DeleteHouseholdForm()
    if request.method == 'GET':
        form.family_id.data = str(get_family_id())
    preview = {}
    blocked_reason = None
    try:
        preview = HouseholdDeletionService.preview(current_user)
    except ValueError as error:
        blocked_reason = str(error)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Household deletion preview failed.')
        blocked_reason = 'Unable to check household records. Please try again.'
    if blocked_reason is None and form.validate_on_submit():
        try:
            HouseholdDeletionService.delete_household(current_user, {
                'password': form.password.data, 'confirmation': form.confirmation.data,
                'family_id': form.family_id.data,
            })
        except ValueError as error:
            flash(str(error) or 'Unable to delete this household.', 'danger')
        except SQLAlchemyError:
            current_app.logger.exception('Household deletion failed.')
            flash('Unable to delete this household. No deletion was committed. Please try again.', 'danger')
        else:
            if HouseholdMembershipService.memberships_for(current_user):
                session.pop(HouseholdMembershipService.SESSION_KEY, None)
                flash('The household and its records have been deleted. Your other household access remains.', 'success')
                return redirect(url_for('central.hub'))
            from blueprints.core.auth.routes import _clear_browser_login
            _clear_browser_login()
            flash('The household and its records have been deleted. Login accounts remain. Everyone without another household has been signed out.', 'success')
            return redirect(url_for('auth.login'))
    return render_template(
        'family/delete_household.html', form=form, preview=preview, blocked_reason=blocked_reason)


# ── Public join route ─────────────────────────────────────────────────────────

@login_required
@recent_auth_required
def _join_existing(invite, token):
    if request.method == 'POST':
        user = db.session.get(User, current_user.id)
        if user is None:
            abort(401)
        try:
            FamilyService.join_existing(user, {'token': token})
        except ValueError as error:
            flash(str(error) or 'Unable to join this household.', 'danger')
        except SQLAlchemyError:
            current_app.logger.exception('Joining a household with an existing account failed.')
            flash('Unable to join this household. Please try again.', 'danger')
        else:
            HouseholdMembershipService.select(user, invite.family_id)
            UserSessionService.start(user, method='family invite')
            flash('You have joined the household using your existing account.', 'success')
            return redirect(url_for('central.hub'))
    return render_template('family/join.html', invite=invite, token=token)


@family_bp.route('/join/<token>', methods=['GET', 'POST'])
@limiter.limit("5 per hour", methods=["POST"])
def join(token):
    """Public registration page linked from an invite token."""
    invite = FamilyInvite.query.filter_by(token=token).first_or_404()

    if not invite.is_valid:
        flash('This invite link has expired or has already been used.', 'danger')
        return redirect(url_for('auth.login'))

    if current_user.is_authenticated:
        return _join_existing(invite, token)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        errors = []
        if not name:
            errors.append('Name is required.')
        if not email:
            errors.append('Email is required.')
        if not password:
            errors.append('Password is required.')
        if password != confirm:
            errors.append('Passwords do not match.')
        valid_password, password_error = AuthService.validate_password_strength(password)
        if not valid_password:
            errors.append(password_error)
        if User.query.filter_by(email=email).first():
            errors.append('An account with that email already exists.')

        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template('family/join.html', invite=invite, token=token)

        user = User(
            name=name,
            email=email,
            is_active=True,
            family_id=invite.family_id,
            role=invite.role,
            member_name=invite.member_name,
            allowed_sections=invite.allowed_sections,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        invite.mark_used(user)
        db.session.commit()

        UserSessionService.start(user, method='family invite')
        EmailVerificationService.send_verification(user)
        flash(f'Welcome to the family, {name}!', 'success')
        return redirect(url_for('central.hub'))

    return render_template('family/join.html', invite=invite, token=token)
