from pathlib import PurePath
import re

from flask import abort
from flask_login import current_user
from markupsafe import Markup, escape
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from extensions import db
from models.family import HouseholdMembership
from models.forum import ForumAttachment, ForumCategory, ForumMention, ForumNotification, ForumPost, ForumReaction, ForumTopic, _now
from services.household.membership_service import HouseholdMembershipService
from services.platform.module_access_service import ModuleAccessService
from utils.db_helpers import family_get, family_get_or_404, family_query


MAX_ATTACHMENT_SIZE = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'pdf', 'txt', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'}
MENTION = re.compile(r'@\[[^\]\r\n]{1,200}\]\(([0-9]+)\)')


class ForumService:
    @staticmethod
    def membership():
        if not ModuleAccessService.can_access(current_user, 'household'):
            abort(403)
        return HouseholdMembershipService.get_membership(current_user)

    @staticmethod
    def moderator():
        ForumService.membership()
        return not current_user.is_managed_child

    @staticmethod
    def require_moderator():
        if not ForumService.moderator():
            abort(403)

    @staticmethod
    def _text(data, key, limit, label):
        value = (data.get(key) or '').strip()
        if not value or len(value) > limit:
            raise ValueError(f'Enter {label} of up to {limit:,} characters.')
        return value

    @staticmethod
    def categories():
        ForumService.membership()
        return family_query(ForumCategory).order_by(ForumCategory.name).all()

    @staticmethod
    def create_category(data):
        membership = ForumService.membership()
        ForumService.require_moderator()
        name = ForumService._text(data, 'name', 80, 'a category name')
        if family_query(ForumCategory).filter(ForumCategory.name.ilike(name)).first():
            raise ValueError('That category already exists.')
        category = ForumCategory(family_id=membership.family_id, name=name)
        db.session.add(category)
        db.session.commit()

    @staticmethod
    def delete_category(category_id):
        ForumService.require_moderator()
        category = family_get_or_404(ForumCategory, category_id)
        if family_query(ForumTopic).filter_by(category_id=category.id).first():
            raise ValueError('Move or delete the topics in this category first.')
        db.session.delete(category)
        db.session.commit()

    @staticmethod
    def _category(data):
        value = data.get('category_id')
        if not value:
            return None
        try:
            category = family_get(ForumCategory, value)
        except ValueError as error:
            raise ValueError('Choose a category from this household.') from error
        if category is None:
            raise ValueError('Choose a category from this household.')
        return category.id

    @staticmethod
    def _attachment(upload, family_id):
        if upload is None or not upload.filename:
            return None
        name = secure_filename(PurePath(upload.filename.replace('\\', '/')).name)
        extension = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
        if not name or len(name) > 255 or extension not in ALLOWED_EXTENSIONS:
            raise ValueError('Choose an image, PDF, text file or common Office document.')
        content = upload.stream.read(MAX_ATTACHMENT_SIZE + 1)
        if not content or len(content) > MAX_ATTACHMENT_SIZE:
            raise ValueError('Attachments must be non-empty and no larger than 5 MB.')
        return ForumAttachment(family_id=family_id, filename=name, content=content)

    @staticmethod
    def mention_members():
        ForumService.membership()
        members = family_query(HouseholdMembership).options(
            selectinload(HouseholdMembership.user),
        ).all()
        return [
            {'id': member.id, 'name': member.user.name}
            for member in members
            if member.user.is_active and isinstance(member.allowed_modules, list)
            and 'household' in member.allowed_modules
        ]

    @staticmethod
    def _mention_values(body, existing_ids=()):
        ids = {int(match.group(1)) for match in MENTION.finditer(body)}
        members = {
            member.id: member for member in family_query(HouseholdMembership).filter(
                HouseholdMembership.id.in_(ids),
            ).options(selectinload(HouseholdMembership.user)).all()
        }
        for member_id in ids:
            member = members.get(member_id)
            if member is None or (
                member_id not in existing_ids and (
                    not member.user.is_active or not isinstance(member.allowed_modules, list)
                    or 'household' not in member.allowed_modules
                )
            ):
                raise ValueError('Choose tagged members who have access to this household forum.')

        def canonical(match):
            member = members[int(match.group(1))]
            name = re.sub(r'[\]\r\n]', ' ', member.user.name).strip() or 'Member'
            return f'@[{name}]({member.id})'

        body = MENTION.sub(canonical, body)
        if len(body) > 10000:
            raise ValueError('Enter a message of up to 10,000 characters.')
        return body, ids

    @staticmethod
    def render_body(post):
        names = {
            mention.membership_id: mention.membership.user.name
            for mention in post.mentions
            if mention.family_id == post.family_id and mention.membership
            and mention.membership.family_id == post.family_id
        }
        parts = []
        cursor = 0
        for match in MENTION.finditer(post.body):
            parts.append(escape(post.body[cursor:match.start()]))
            name = names.get(int(match.group(1)))
            if name is None:
                parts.append(escape(match.group()))
            else:
                parts.append(Markup('<span class="badge text-bg-primary">@{}</span>').format(escape(name)))
            cursor = match.end()
        parts.append(escape(post.body[cursor:]))
        return Markup('').join(parts)

    @staticmethod
    def _set_mentions(post, ids):
        old_ids = {mention.membership_id for mention in post.mentions if mention.membership_id is not None}
        for mention in list(post.mentions):
            if mention.membership_id not in ids:
                post.mentions.remove(mention)
        for member_id in ids - old_ids:
            post.mentions.append(ForumMention(family_id=post.family_id, membership_id=member_id))
        return old_ids

    @staticmethod
    def _notify(post, actor, mentioned_ids):
        members = family_query(HouseholdMembership).filter(HouseholdMembership.id != actor.id).all()
        for member in members:
            if member.user.is_active and isinstance(member.allowed_modules, list) and 'household' in member.allowed_modules:
                db.session.add(ForumNotification(
                    family_id=actor.family_id, membership_id=member.id, post=post,
                    mentioned=member.id in mentioned_ids,
                ))

    @staticmethod
    def topics(data):
        ForumService.membership()
        search = (data.get('q') or '').strip()
        if len(search) > 200:
            raise ValueError('Search must be no more than 200 characters.')
        query = family_query(ForumTopic).options(selectinload(ForumTopic.category))
        category = ForumService._category(data)
        if category:
            query = query.filter_by(category_id=category)
        if search:
            pattern = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            post_match = family_query(ForumPost).filter(
                ForumPost.topic_id == ForumTopic.id, ForumPost.body.ilike(pattern, escape='\\'),
            ).exists()
            query = query.filter(or_(ForumTopic.title.ilike(pattern, escape='\\'), post_match))
        try:
            page = int(data.get('page') or 1)
        except (TypeError, ValueError):
            raise ValueError('Choose a valid page number.')
        return query.order_by(ForumTopic.pinned.desc(), ForumTopic.updated_at.desc(), ForumTopic.id.desc()).paginate(
            page=page, per_page=20, error_out=False,
        )

    @staticmethod
    def topic(topic_id):
        ForumService.membership()
        return family_get_or_404(ForumTopic, topic_id)

    @staticmethod
    def posts(topic_id, page):
        topic = ForumService.topic(topic_id)
        return family_query(ForumPost).filter_by(topic_id=topic.id).options(
            selectinload(ForumPost.creator).selectinload(HouseholdMembership.user),
            selectinload(ForumPost.attachments).defer(ForumAttachment.content),
            selectinload(ForumPost.reactions),
            selectinload(ForumPost.mentions).selectinload(ForumMention.membership).selectinload(HouseholdMembership.user),
        ).order_by(ForumPost.created_at, ForumPost.id).paginate(page=page, per_page=20, error_out=False)

    @staticmethod
    def pinned_posts(topic_id):
        topic = ForumService.topic(topic_id)
        return family_query(ForumPost).filter_by(topic_id=topic.id, pinned=True).options(
            selectinload(ForumPost.creator).selectinload(HouseholdMembership.user),
        ).order_by(ForumPost.created_at, ForumPost.id).all()

    @staticmethod
    def set_post_pin(post_id, data):
        ForumService.require_moderator()
        post = ForumService.post(post_id)
        action = data.get('action')
        if action not in ('pin', 'unpin'):
            raise ValueError('Choose whether to pin or unpin the post.')
        post.pinned = action == 'pin'
        db.session.commit()
        return post

    @staticmethod
    def create_topic(data, upload=None):
        member = ForumService.membership()
        title = ForumService._text(data, 'title', 200, 'a topic title')
        body = ForumService._text(data, 'body', 10000, 'a message')
        body, mention_ids = ForumService._mention_values(body)
        category_id = ForumService._category(data)
        attachment = ForumService._attachment(upload, member.family_id)
        topic = ForumTopic(family_id=member.family_id, creator_membership_id=member.id, title=title, category_id=category_id)
        post = ForumPost(family_id=member.family_id, creator_membership_id=member.id, body=body)
        topic.posts.append(post)
        ForumService._set_mentions(post, mention_ids)
        if attachment:
            post.attachments.append(attachment)
        db.session.add(topic)
        ForumService._notify(post, member, mention_ids)
        db.session.commit()
        return topic

    @staticmethod
    def reply(topic_id, data, upload=None):
        member = ForumService.membership()
        topic = ForumService.topic(topic_id)
        if topic.locked:
            raise ValueError('This topic is locked.')
        body = ForumService._text(data, 'body', 10000, 'a message')
        body, mention_ids = ForumService._mention_values(body)
        attachment = ForumService._attachment(upload, member.family_id)
        post = ForumPost(family_id=member.family_id, topic=topic, creator_membership_id=member.id, body=body)
        ForumService._set_mentions(post, mention_ids)
        if attachment:
            post.attachments.append(attachment)
        topic.updated_at = _now()
        db.session.add(post)
        ForumService._notify(post, member, mention_ids)
        db.session.commit()
        return post

    @staticmethod
    def post(post_id):
        ForumService.membership()
        post = family_get_or_404(ForumPost, post_id)
        ForumService.topic(post.topic_id)
        return post

    @staticmethod
    def can_edit(post):
        member = ForumService.membership()
        return post.creator_membership_id == member.id or ForumService.moderator()

    @staticmethod
    def update_post(post_id, data):
        post = ForumService.post(post_id)
        if not ForumService.can_edit(post):
            abort(403)
        member = ForumService.membership()
        existing_ids = {mention.membership_id for mention in post.mentions if mention.membership_id is not None}
        body, mention_ids = ForumService._mention_values(
            ForumService._text(data, 'body', 10000, 'a message'), existing_ids,
        )
        first = family_query(ForumPost).filter_by(topic_id=post.topic_id).order_by(
            ForumPost.created_at, ForumPost.id,
        ).first()
        if first.id == post.id:
            post.topic.title = ForumService._text(data, 'title', 200, 'a topic title')
        post.body = body
        ForumService._set_mentions(post, mention_ids)
        notifications = family_query(ForumNotification).filter_by(post_id=post.id).all()
        by_member = {notification.membership_id: notification for notification in notifications}
        for member_id in existing_ids - mention_ids:
            if member_id in by_member:
                by_member[member_id].mentioned = False
        for member_id in mention_ids - existing_ids - {member.id}:
            notification = by_member.get(member_id)
            if notification is None:
                db.session.add(ForumNotification(
                    family_id=member.family_id, post_id=post.id, membership_id=member_id, mentioned=True,
                ))
            else:
                notification.mentioned = True
                notification.read_at = None
                notification.created_at = _now()
        post.edited_at = _now()
        db.session.commit()
        return post

    @staticmethod
    def delete_post(post_id):
        post = ForumService.post(post_id)
        if not ForumService.can_edit(post):
            abort(403)
        topic = ForumService.topic(post.topic_id)
        first = family_query(ForumPost).filter_by(topic_id=topic.id).order_by(ForumPost.created_at, ForumPost.id).first()
        topic_id = topic.id
        if first.id == post.id and not ForumService.moderator() and family_query(ForumPost).filter(
            ForumPost.topic_id == topic.id, ForumPost.id != post.id,
        ).first():
            post.body = '[Original post removed]'
            post.creator_membership_id = None
            topic.creator_membership_id = None
            topic.title = 'Removed topic'
            post.attachments.clear()
            post.reactions.clear()
            post.notifications.clear()
            post.mentions.clear()
            post.pinned = False
        elif first.id == post.id:
            db.session.delete(topic)
            topic_id = None
        else:
            db.session.delete(post)
        db.session.commit()
        return topic_id

    @staticmethod
    def moderate_topic(topic_id, data):
        ForumService.require_moderator()
        topic = ForumService.topic(topic_id)
        action = data.get('action')
        if action == 'pin':
            topic.pinned = not topic.pinned
        elif action == 'lock':
            topic.locked = not topic.locked
        elif action == 'category':
            topic.category_id = ForumService._category(data)
        else:
            raise ValueError('Choose a valid moderation action.')
        db.session.commit()

    @staticmethod
    def react(post_id):
        member = ForumService.membership()
        post = ForumService.post(post_id)
        reaction = family_query(ForumReaction).filter_by(post_id=post.id, membership_id=member.id).first()
        if reaction:
            db.session.delete(reaction)
        else:
            db.session.add(ForumReaction(family_id=member.family_id, post_id=post.id, membership_id=member.id))
        db.session.commit()
        return post.topic_id

    @staticmethod
    def notifications():
        member = ForumService.membership()
        return family_query(ForumNotification).join(
            ForumPost, (ForumPost.id == ForumNotification.post_id) & (ForumPost.family_id == ForumNotification.family_id),
        ).join(
            ForumTopic, (ForumTopic.id == ForumPost.topic_id) & (ForumTopic.family_id == ForumPost.family_id),
        ).filter(ForumNotification.membership_id == member.id).options(
            selectinload(ForumNotification.post).selectinload(ForumPost.topic),
        ).order_by(ForumNotification.created_at.desc(), ForumNotification.id.desc()).limit(100).all()

    @staticmethod
    def unread_count():
        member = ForumService.membership()
        return family_query(ForumNotification).filter_by(membership_id=member.id, read_at=None).count()

    @staticmethod
    def post_page(post):
        count = family_query(ForumPost).filter(
            ForumPost.topic_id == post.topic_id,
            or_(ForumPost.created_at < post.created_at,
                (ForumPost.created_at == post.created_at) & (ForumPost.id <= post.id)),
        ).count()
        return max(1, (count + 19) // 20)

    @staticmethod
    def mark_read():
        member = ForumService.membership()
        family_query(ForumNotification).filter_by(membership_id=member.id, read_at=None).update(
            {'read_at': _now()}, synchronize_session=False,
        )
        db.session.commit()

    @staticmethod
    def attachment(attachment_id):
        ForumService.membership()
        attachment = family_get_or_404(ForumAttachment, attachment_id)
        ForumService.post(attachment.post_id)
        return attachment

    @staticmethod
    def delete_attachment(attachment_id):
        attachment = ForumService.attachment(attachment_id)
        if not ForumService.can_edit(attachment.post):
            abort(403)
        topic_id = attachment.post.topic_id
        db.session.delete(attachment)
        db.session.commit()
        return topic_id

    @staticmethod
    def detach_membership(membership):
        ForumService.remove_member_mentions({membership.id: membership.family_id})
        for model in (ForumReaction, ForumNotification):
            family_query(model).filter_by(membership_id=membership.id).delete(synchronize_session=False)
        for model in (ForumTopic, ForumPost):
            family_query(model).filter_by(creator_membership_id=membership.id).update(
                {'creator_membership_id': None}, synchronize_session=False,
            )

    @staticmethod
    def remove_member_mentions(memberships):
        for member_id, family_id in memberships.items():
            mentions = db.session.query(ForumMention).filter_by(
                family_id=family_id, membership_id=member_id,
            ).all()
            for mention in mentions:
                post = mention.post
                if post is None or post.family_id != family_id:
                    raise ValueError('Linked household data is inconsistent. Contact the service operator.')
                post.body = MENTION.sub(
                    lambda match: '@Former member' if int(match.group(1)) == member_id else match.group(),
                    post.body,
                )
                db.session.delete(mention)
