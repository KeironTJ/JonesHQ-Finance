from io import BytesIO
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask import g

from extensions import db, limiter
from models import Family, User
from models.forum import ForumAttachment, ForumCategory, ForumMention, ForumNotification, ForumPost, ForumReaction, ForumTopic
from services.household.family_service import FamilyService
from tests.auth_helpers import login_client


@pytest.fixture(autouse=True)
def isolate_login_state(app):
    g.pop('_login_user', None)
    limiter.reset()
    yield
    g.pop('_login_user', None)
    limiter.reset()


def client_for(app, actor):
    client = app.test_client()
    login_client(client, actor.id)
    return client


@pytest.fixture
def people(user, family):
    child = User(
        family_id=family.id, role='member', name='Child', email='child@example.com',
        password_hash=user.password_hash, account_type='child', guardian_id=user.id,
    )
    outsider_family = Family(name='Other household')
    db.session.add_all([child, outsider_family])
    db.session.flush()
    outsider = User(
        family_id=outsider_family.id, role='member', name='Outsider', email='other@example.com',
        password_hash=user.password_hash,
    )
    db.session.add(outsider)
    db.session.commit()
    return child, outsider


def test_child_posts_notifications_reactions_and_moderation(app, user, people):
    child, _ = people
    adult_client = client_for(app, user)
    child_client = client_for(app, child)
    assert child_client.post('/household/forum/new', data={'title': 'Hello', 'body': 'Hi family'}).status_code == 302
    topic = ForumTopic.query.one()
    first = ForumPost.query.one()
    g.pop('_login_user', None)
    assert b'Hi family' in adult_client.get(f'/household/forum/topics/{topic.id}').data
    assert b'Hello' in adult_client.get('/household/forum/notifications').data
    assert adult_client.post(f'/household/forum/posts/{first.id}/react').status_code == 302
    assert ForumReaction.query.count() == 1
    assert adult_client.post(f'/household/forum/posts/{first.id}/react').status_code == 302
    assert ForumReaction.query.count() == 0
    assert adult_client.post(f'/household/forum/topics/{topic.id}/moderate', data={'action': 'lock'}).status_code == 302
    g.pop('_login_user', None)
    assert child_client.post(f'/household/forum/topics/{topic.id}/moderate', data={'action': 'lock'}).status_code == 403
    child_client.post(f'/household/forum/topics/{topic.id}/reply', data={'body': 'Blocked'})
    assert ForumPost.query.count() == 1
    assert child_client.post('/household/forum/categories', data={'name': 'No'}).status_code == 403


def test_household_isolation_upload_and_access_revocation(app, user, people):
    child, outsider = people
    client = client_for(app, child)
    response = client.post('/household/forum/new', data={
        'title': 'Private household', 'body': 'Secret', 'attachment': (BytesIO(b'file'), 'notes.txt'),
    })
    assert response.status_code == 302
    topic = ForumTopic.query.one()
    post = ForumPost.query.one()
    attachment = ForumAttachment.query.one()
    other = client_for(app, outsider)
    for path in (
        f'/household/forum/topics/{topic.id}', f'/household/forum/attachments/{attachment.id}',
        f'/household/forum/posts/{post.id}/edit',
    ):
        g.pop('_login_user', None)
        assert other.get(path).status_code == 404
    assert b'Secret' not in other.get('/household/forum').data
    assert other.post(f'/household/forum/topics/{topic.id}/reply', data={'body': 'No'}).status_code == 404
    g.pop('_login_user', None)
    download = client.get(f'/household/forum/attachments/{attachment.id}')
    assert download.data == b'file' and 'attachment' in download.headers['Content-Disposition']
    assert download.headers['X-Content-Type-Options'] == 'nosniff'
    child.get_active_household_membership().allowed_modules = []
    db.session.commit()
    assert client.get('/household/forum').status_code == 403
    assert client.get(f'/household/forum/attachments/{attachment.id}').status_code == 403


def test_foreign_category_and_post_actions_are_rejected(app, user, people):
    child, outsider = people
    foreign_client = client_for(app, outsider)
    foreign_client.post('/household/forum/categories', data={'name': 'Foreign'})
    category = ForumCategory.query.one()
    foreign_client.post('/household/forum/new', data={'title': 'Foreign topic', 'body': 'Foreign body'})
    post = ForumPost.query.one()
    g.pop('_login_user', None)
    child_client = client_for(app, child)
    response = child_client.post('/household/forum/new', data={
        'title': 'Local', 'body': 'Local body', 'category_id': category.id,
    })
    assert b'Choose a category from this household' in response.data
    for action in ('react', 'delete', 'edit'):
        assert child_client.post(f'/household/forum/posts/{post.id}/{action}', data={'body': 'Tampered'}).status_code == 404
    assert ForumTopic.query.count() == 1
    assert ForumPost.query.one().body == 'Foreign body'


def test_validation_search_category_and_post_deletion(app, user, people):
    child, _ = people
    client = client_for(app, user)
    client.post('/household/forum/categories', data={'name': 'Ideas'})
    category = ForumCategory.query.one()
    client.post('/household/forum/new', data={
        'title': 'First', 'body': 'Needle in message', 'category_id': category.id,
        'attachment': (BytesIO(b'bad'), 'script.html'),
    })
    assert ForumTopic.query.count() == 0
    client.post('/household/forum/new', data={'title': 'First', 'body': 'Needle in message', 'category_id': category.id})
    topic = ForumTopic.query.one()
    assert b'First' in client.get('/household/forum?q=Needle').data
    assert b'First' not in client.get('/household/forum?q=missing').data
    client.post(f'/household/forum/categories/{category.id}/delete')
    assert ForumCategory.query.count() == 1
    client.post(f'/household/forum/topics/{topic.id}/reply', data={'body': 'Reply'})
    assert ForumNotification.query.count() == 2
    first = ForumPost.query.order_by(ForumPost.id).first()
    client.post(f'/household/forum/posts/{first.id}/delete')
    assert ForumTopic.query.count() == 0
    assert ForumPost.query.count() == 0
    assert ForumNotification.query.count() == 0


def test_member_departure_keeps_posts_anonymous_and_removes_private_state(app, user, people):
    child, _ = people
    client = client_for(app, child)
    client.post('/household/forum/new', data={'title': 'Remember', 'body': 'Still here'})
    post = ForumPost.query.one()
    client.post(f'/household/forum/posts/{post.id}/react')
    member_id = child.get_active_household_membership().id
    g.pop('_login_user', None)
    with app.test_request_context():
        from flask_login import login_user
        login_user(user)
        FamilyService.remove_member(child.id, user.family_id, user.id)
    db.session.expire_all()
    assert ForumPost.query.one().creator_membership_id is None
    assert ForumTopic.query.one().creator_membership_id is None
    assert ForumReaction.query.filter_by(membership_id=member_id).count() == 0
    assert b'Former member' in client_for(app, user).get(f'/household/forum/topics/{post.topic_id}').data


def test_child_deletes_opening_post_without_deleting_other_members_replies(app, user, people):
    child, _ = people
    child_client = client_for(app, child)
    child_client.post('/household/forum/new', data={
        'title': 'Original', 'body': 'Child text', 'attachment': (BytesIO(b'file'), 'notes.txt'),
    })
    topic = ForumTopic.query.one()
    first = ForumPost.query.one()
    adult_client = client_for(app, user)
    g.pop('_login_user', None)
    adult_client.post(f'/household/forum/topics/{topic.id}/reply', data={'body': 'Adult reply'})
    g.pop('_login_user', None)
    child_client.post(f'/household/forum/posts/{first.id}/delete')
    db.session.expire_all()
    assert ForumPost.query.count() == 2
    assert ForumPost.query.filter_by(body='Adult reply').one()
    assert ForumPost.query.filter_by(body='[Original post removed]').one()
    assert ForumAttachment.query.count() == 0
    assert ForumTopic.query.one().title == 'Removed topic'


def test_notifications_pagination_and_read_state(app, user, people):
    child, _ = people
    child_client = client_for(app, child)
    child_client.post('/household/forum/new', data={'title': 'Long topic', 'body': 'First'})
    topic = ForumTopic.query.one()
    adult_client = client_for(app, user)
    for index in range(20):
        g.pop('_login_user', None)
        adult_client.post(f'/household/forum/topics/{topic.id}/reply', data={'body': f'Reply {index}'})
    last = ForumPost.query.order_by(ForumPost.id.desc()).first()
    g.pop('_login_user', None)
    response = child_client.get('/household/forum/notifications')
    assert f'/household/forum/posts/{last.id}'.encode() in response.data
    assert child_client.get(f'/household/forum/posts/{last.id}').location.endswith(f'page=2#post-{last.id}')
    assert b'Forum notifications (20)' in response.data
    child_client.post('/household/forum/notifications/read')
    assert ForumNotification.query.filter_by(membership_id=child.get_active_household_membership().id, read_at=None).count() == 0
    assert b'Forum notifications (20)' not in child_client.get('/household/forum').data


def test_attachment_limits_and_reply_validation_preserve_text(app, user):
    client = client_for(app, user)
    client.post('/household/forum/new', data={'title': 'Topic', 'body': 'Hello'})
    topic = ForumTopic.query.one()
    response = client.post(f'/household/forum/topics/{topic.id}/reply', data={
        'body': 'Keep this text', 'attachment': (BytesIO(b'x' * (5 * 1024 * 1024 + 1)), 'test.pdf'),
    })
    assert response.status_code == 200 and b'no larger than 5 MB' in response.data
    assert b'Keep this text' in response.data
    assert ForumPost.query.count() == 1
    response = client.post('/household/forum/new', data={
        'title': 'Big', 'body': 'Hello', 'attachment': (BytesIO(b'x' * (7 * 1024 * 1024)), 'test.pdf'),
    })
    assert response.status_code == 413
    assert ForumTopic.query.count() == 1


def test_forum_mutations_require_csrf(app, user, monkeypatch):
    client = client_for(app, user)
    client.post('/household/forum/new', data={'title': 'Topic', 'body': 'Hello'})
    topic = ForumTopic.query.one()
    post = ForumPost.query.one()
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    g.pop('csrf_valid', None)
    g.pop('csrf_token', None)
    for path in (
        '/household/forum/new', '/household/forum/categories', '/household/forum/notifications/read',
        f'/household/forum/topics/{topic.id}/reply', f'/household/forum/topics/{topic.id}/moderate',
        f'/household/forum/posts/{post.id}/edit', f'/household/forum/posts/{post.id}/delete',
        f'/household/forum/posts/{post.id}/react',
        f'/household/forum/posts/{post.id}/pin',
    ):
        assert client.post(path, data={'body': 'Test'}).status_code == 400
    assert client.get(f'/household/forum/posts/{post.id}/delete').status_code == 405
    assert ForumPost.query.count() == 1


def test_post_pins_are_moderated_and_link_to_the_original_page(app, user, people):
    child, outsider = people
    adult_client = client_for(app, user)
    adult_client.post('/household/forum/new', data={'title': 'Topic', 'body': 'Opening'})
    topic = ForumTopic.query.one()
    for index in range(20):
        adult_client.post(f'/household/forum/topics/{topic.id}/reply', data={'body': f'Reply {index}'})
    last = ForumPost.query.order_by(ForumPost.id.desc()).first()
    child_client = client_for(app, child)
    g.pop('_login_user', None)
    assert child_client.post(f'/household/forum/posts/{last.id}/pin', data={'action': 'pin'}).status_code == 403
    foreign_client = client_for(app, outsider)
    g.pop('_login_user', None)
    assert foreign_client.post(f'/household/forum/posts/{last.id}/pin', data={'action': 'pin'}).status_code == 404
    g.pop('_login_user', None)
    assert adult_client.post(f'/household/forum/posts/{last.id}/pin', data={'action': 'pin'}).status_code == 302
    assert adult_client.post(f'/household/forum/posts/{last.id}/pin', data={'action': 'pin'}).status_code == 302
    assert last.pinned
    response = adult_client.get(f'/household/forum/topics/{topic.id}')
    assert b'Pinned posts' in response.data
    assert f'/household/forum/posts/{last.id}'.encode() in response.data
    assert adult_client.get(f'/household/forum/posts/{last.id}').location.endswith(f'page=2#post-{last.id}')
    assert adult_client.post(f'/household/forum/posts/{last.id}/pin', data={'action': 'unpin'}).status_code == 302
    assert not last.pinned


def test_mentions_are_scoped_notified_and_updated_without_duplicates(app, user, people):
    child, outsider = people
    child_id = child.get_active_household_membership().id
    outsider_id = outsider.get_active_household_membership().id
    client = client_for(app, user)
    form = {'title': 'Hello', 'body': f'Hello @[Child]({child_id})!'}
    assert client.post('/household/forum/new', data=form).status_code == 302
    topic = ForumTopic.query.one()
    post = ForumPost.query.one()
    assert ForumMention.query.filter_by(post_id=post.id, membership_id=child_id).count() == 1
    notification = ForumNotification.query.filter_by(post_id=post.id, membership_id=child_id).one()
    assert notification.mentioned
    child_client = client_for(app, child)
    g.pop('_login_user', None)
    assert b'You were tagged' in child_client.get('/household/forum/notifications').data
    assert b'@Child' in child_client.get(f'/household/forum/topics/{topic.id}').data
    child_client.post('/household/forum/notifications/read')
    db.session.refresh(notification)
    assert notification.read_at is not None
    old_notification_time = notification.created_at
    g.pop('_login_user', None)
    client.post(f'/household/forum/posts/{post.id}/edit', data={'title': 'Hello', 'body': 'No tag'})
    assert ForumMention.query.count() == 0
    assert not notification.mentioned
    client.post(f'/household/forum/posts/{post.id}/edit', data=form)
    assert ForumMention.query.count() == 1
    assert notification.mentioned and notification.read_at is None
    assert notification.created_at >= old_notification_time
    assert ForumNotification.query.filter_by(post_id=post.id, membership_id=child_id).count() == 1
    response = client.post('/household/forum/new', data={
        'title': 'Bad', 'body': f'@[Other]({outsider_id})',
    })
    assert b'Choose tagged members' in response.data
    assert ForumTopic.query.count() == 1
    child.get_active_household_membership().allowed_modules = []
    db.session.commit()
    response = client.post(f'/household/forum/topics/{topic.id}/reply', data={'body': f'@[Child]({child_id})'})
    assert b'Choose tagged members' in response.data
    assert ForumPost.query.count() == 1


def test_member_departure_removes_mention_identity_and_prevents_reuse(app, user, people):
    child, _ = people
    member_id = child.get_active_household_membership().id
    client = client_for(app, user)
    client.post('/household/forum/new', data={'title': 'Hello', 'body': f'Hi @[Child]({member_id})'})
    post = ForumPost.query.one()
    with app.test_request_context():
        from flask_login import login_user
        login_user(user)
        FamilyService.remove_member(child.id, user.family_id, user.id)
    db.session.expire_all()
    assert ForumMention.query.count() == 0
    assert post.body == 'Hi @Former member'
    assert ForumNotification.query.filter_by(membership_id=member_id).count() == 0


def test_new_forum_migration_round_trip():
    path = Path(__file__).resolve().parents[1] / 'migrations' / 'versions' / '91be0a73d426_forum_post_pins_and_mentions.py'
    spec = importlib.util.spec_from_file_location('forum_mentions_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE families (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('CREATE TABLE household_memberships (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('CREATE TABLE forum_posts (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('CREATE TABLE forum_notifications (id INTEGER PRIMARY KEY)'))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
            inspector = sa.inspect(connection)
            assert 'pinned' in {column['name'] for column in inspector.get_columns('forum_posts')}
            assert 'mentioned' in {column['name'] for column in inspector.get_columns('forum_notifications')}
            assert set(db.metadata.tables['forum_mentions'].c.keys()) == {
                column['name'] for column in inspector.get_columns('forum_mentions')
            }
            migration.downgrade()
        inspector = sa.inspect(connection)
        assert 'forum_mentions' not in inspector.get_table_names()
        assert 'pinned' not in {column['name'] for column in inspector.get_columns('forum_posts')}
    engine.dispose()


def test_forum_migration_round_trip():
    path = Path(__file__).resolve().parents[1] / 'migrations' / 'versions' / '4ca8e12f9b31_add_household_forum.py'
    spec = importlib.util.spec_from_file_location('forum_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE families (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('CREATE TABLE household_memberships (id INTEGER PRIMARY KEY)'))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
            inspector = sa.inspect(connection)
            for name in ('forum_categories', 'forum_topics', 'forum_posts', 'forum_attachments',
                         'forum_reactions', 'forum_notifications'):
                assert name in inspector.get_table_names()
                current = set(db.metadata.tables[name].c.keys())
                current -= {'pinned'} if name == 'forum_posts' else {'mentioned'} if name == 'forum_notifications' else set()
                assert {column['name'] for column in inspector.get_columns(name)} == current
            migration.downgrade()
        assert not any(name.startswith('forum_') for name in sa.inspect(connection).get_table_names())
    engine.dispose()
