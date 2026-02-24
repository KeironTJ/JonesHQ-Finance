"""
Family blueprint routes.

Admin-only routes (require login + admin role):
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

from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user, login_user

from blueprints.family import family_bp
from extensions import db
from models.family import Family, FamilyInvite
from models.users import User
from utils.permissions import SECTION_GROUPS, SECTION_LABELS, ADMIN_ONLY_SECTIONS


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_admin():
    """Abort with 403 if the current user is not an admin."""
    if not current_user.is_authenticated or not current_user.is_admin:
        abort(403)


# ── Admin routes ──────────────────────────────────────────────────────────────

@family_bp.route('/', methods=['GET'])
@login_required
def index():
    _require_admin()

    family = current_user.family
    if family is None:
        # Bootstrap: create a default family for this admin
        family = Family(name='My Family')
        db.session.add(family)
        db.session.flush()
        current_user.family_id = family.id
        db.session.commit()

    members = family.members.all()
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
        members=members,
        active_invites=active_invites,
        expired_invites=expired_invites,
        section_groups=SECTION_GROUPS,
        section_labels=SECTION_LABELS,
    )


@family_bp.route('/invite', methods=['POST'])
@login_required
def create_invite():
    _require_admin()

    family = current_user.family
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

    # Admins get no section restriction; members get the chosen list
    sections_json = None if role == 'admin' else json.dumps(sorted(selected_sections))

    invite = FamilyInvite(
        family_id=family.id,
        member_name=member_name,
        role=role,
        allowed_sections=sections_json,
        created_by_id=current_user.id,
    )
    db.session.add(invite)
    db.session.commit()

    flash(f'Invite link created for {member_name}.', 'success')
    return redirect(url_for('family.index'))


@family_bp.route('/invite/<int:invite_id>/revoke', methods=['POST'])
@login_required
def revoke_invite(invite_id):
    _require_admin()

    invite = FamilyInvite.query.get_or_404(invite_id)
    if invite.family_id != current_user.family_id:
        abort(403)

    db.session.delete(invite)
    db.session.commit()
    flash('Invite revoked.', 'success')
    return redirect(url_for('family.index'))


@family_bp.route('/members/<int:member_id>/update', methods=['POST'])
@login_required
def update_member(member_id):
    _require_admin()

    member = User.query.get_or_404(member_id)
    if member.family_id != current_user.family_id:
        abort(403)
    if member.id == current_user.id:
        flash('You cannot edit your own permissions here.', 'warning')
        return redirect(url_for('family.index'))

    selected_sections = request.form.getlist('sections')
    role = request.form.get('role', member.role)
    member_name = request.form.get('member_name', member.member_name or '').strip()

    if role not in ('admin', 'member'):
        role = 'member'

    member.role = role
    member.member_name = member_name or member.name
    if role == 'admin':
        member.allowed_sections = None
    else:
        member.set_allowed_sections(selected_sections)

    db.session.commit()
    flash(f'Updated permissions for {member.name}.', 'success')
    return redirect(url_for('family.index'))


@family_bp.route('/members/<int:member_id>/remove', methods=['POST'])
@login_required
def remove_member(member_id):
    _require_admin()

    member = User.query.get_or_404(member_id)
    if member.family_id != current_user.family_id:
        abort(403)
    if member.id == current_user.id:
        flash('You cannot remove yourself from the family.', 'warning')
        return redirect(url_for('family.index'))

    member.family_id = None
    member.role = 'member'
    member.allowed_sections = None
    db.session.commit()
    flash(f'{member.name} has been removed from the family.', 'success')
    return redirect(url_for('family.index'))


# ── Public join route ─────────────────────────────────────────────────────────

@family_bp.route('/join/<token>', methods=['GET', 'POST'])
def join(token):
    """Public registration page linked from an invite token."""
    invite = FamilyInvite.query.filter_by(token=token).first_or_404()

    if not invite.is_valid:
        flash('This invite link has expired or has already been used.', 'danger')
        return redirect(url_for('auth.login'))

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
        if len(password) < 8:
            errors.append('Password must be at least 8 characters.')
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

        login_user(user)
        flash(f'Welcome to the family, {name}!', 'success')
        return redirect(url_for('dashboard.index'))

    return render_template('family/join.html', invite=invite, token=token)
