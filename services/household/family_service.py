import json

from extensions import db
from models.family import FamilyInvite
from models.family_assignment_labels import FamilyAssignmentLabel
from models.users import User


class FamilyService:
    @staticmethod
    def create_assignment_label(family_id, name):
        existing = FamilyAssignmentLabel.query.filter_by(
            family_id=family_id,
            name=name,
            is_active=True,
        ).first()
        if existing:
            return None

        max_sort = FamilyAssignmentLabel.query.filter_by(
            family_id=family_id
        ).with_entities(db.func.max(FamilyAssignmentLabel.sort_order)).scalar()
        label = FamilyAssignmentLabel(
            family_id=family_id,
            name=name,
            is_active=True,
            sort_order=(max_sort or 0) + 1,
        )
        db.session.add(label)
        db.session.commit()
        return label

    @staticmethod
    def delete_assignment_label(label_id, family_id):
        label = FamilyAssignmentLabel.query.get_or_404(label_id)
        if label.family_id != family_id:
            from flask import abort
            abort(403)
        name = label.name
        db.session.delete(label)
        db.session.commit()
        return name

    @staticmethod
    def create_invite(family_id, created_by_id, member_name, role, selected_sections):
        sections_json = None if role == 'admin' else json.dumps(sorted(set(selected_sections)))
        invite = FamilyInvite(
            family_id=family_id,
            member_name=member_name,
            role=role,
            allowed_sections=sections_json,
            created_by_id=created_by_id,
        )
        db.session.add(invite)
        db.session.commit()
        return invite

    @staticmethod
    def revoke_invite(invite_id, family_id):
        invite = FamilyInvite.query.get_or_404(invite_id)
        if invite.family_id != family_id:
            from flask import abort
            abort(403)
        db.session.delete(invite)
        db.session.commit()

    @staticmethod
    def update_member(member_id, family_id, current_user_id, role, member_name, sections):
        member = User.query.get_or_404(member_id)
        if member.family_id != family_id:
            from flask import abort
            abort(403)
        if member.id == current_user_id:
            return None

        member.role = role if role in ('admin', 'member') else 'member'
        member.member_name = member_name or member.name
        member.allowed_sections = None if member.role == 'admin' else None
        if member.role != 'admin':
            member.set_allowed_sections(sections)
        db.session.commit()
        return member

    @staticmethod
    def remove_member(member_id, family_id, current_user_id):
        member = User.query.get_or_404(member_id)
        if member.family_id != family_id:
            from flask import abort
            abort(403)
        if member.id == current_user_id:
            return None

        name = member.name
        member.family_id = None
        member.role = 'member'
        member.allowed_sections = None
        db.session.commit()
        return name
