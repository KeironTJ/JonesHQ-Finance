from io import BytesIO

from flask import current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import login_required
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from services.household.forum_service import ForumService
from . import household_bp


def _failure(error):
    db.session.rollback()
    if isinstance(error, (ValueError, TypeError)):
        flash(str(error) or 'Invalid forum details.', 'danger')
    else:
        current_app.logger.exception('Unable to save forum changes')
        flash('Unable to save forum changes. No changes were saved.', 'danger')


def _topic_page(topic, page, submitted=None):
    return render_template(
        'household/forum/topic.html', topic=topic, posts=ForumService.posts(topic.id, page),
        categories=ForumService.categories(), membership=ForumService.membership(),
        moderator=ForumService.moderator(), forum_service=ForumService, submitted=submitted or {},
        pinned_posts=ForumService.pinned_posts(topic.id), mention_members=ForumService.mention_members(),
    )


@household_bp.route('/forum')
@login_required
def forum():
    try:
        topics = ForumService.topics(request.args)
    except (ValueError, TypeError) as error:
        flash(str(error), 'danger')
        return redirect(url_for('household.forum'))
    return render_template(
        'household/forum/index.html', topics=topics, categories=ForumService.categories(),
        moderator=ForumService.moderator(), search=request.args.get('q', ''),
        selected_category=request.args.get('category_id', ''),
    )


@household_bp.route('/forum/new', methods=['GET', 'POST'])
@login_required
def forum_new_topic():
    ForumService.membership()
    if request.method == 'POST':
        try:
            topic = ForumService.create_topic(request.form, request.files.get('attachment'))
        except (ValueError, TypeError, SQLAlchemyError) as error:
            _failure(error)
        else:
            flash('Topic created.', 'success')
            return redirect(url_for('household.forum_topic', topic_id=topic.id))
    return render_template(
        'household/forum/new.html', categories=ForumService.categories(), submitted=request.form,
        mention_members=ForumService.mention_members(),
    )


@household_bp.route('/forum/topics/<int:topic_id>')
@login_required
def forum_topic(topic_id):
    topic = ForumService.topic(topic_id)
    page = request.args.get('page', 1, type=int)
    return _topic_page(topic, page)


@household_bp.route('/forum/topics/<int:topic_id>/reply', methods=['POST'])
@login_required
def forum_reply(topic_id):
    try:
        post = ForumService.reply(topic_id, request.form, request.files.get('attachment'))
    except (ValueError, TypeError, SQLAlchemyError) as error:
        _failure(error)
        topic = ForumService.topic(topic_id)
        total = ForumService.posts(topic_id, 1).total
        return _topic_page(topic, max(1, (total + 19) // 20), request.form)
    count = ForumService.posts(topic_id, 1).total
    return redirect(url_for('household.forum_topic', topic_id=topic_id, page=(count + 19) // 20, _anchor=f'post-{post.id}'))


@household_bp.route('/forum/posts/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def forum_edit_post(post_id):
    post = ForumService.post(post_id)
    if not ForumService.can_edit(post):
        from flask import abort
        abort(403)
    posts = ForumService.posts(post.topic_id, 1)
    is_first = bool(posts.items and posts.items[0].id == post.id)
    if request.method == 'POST':
        try:
            ForumService.update_post(post_id, request.form)
        except (ValueError, TypeError, SQLAlchemyError) as error:
            _failure(error)
        else:
            flash('Post updated.', 'success')
            return redirect(url_for('household.forum_topic', topic_id=post.topic_id, page=ForumService.post_page(post), _anchor=f'post-{post.id}'))
    return render_template(
        'household/forum/edit.html', post=post, is_first=is_first, submitted=request.form,
        mention_members=ForumService.mention_members(),
    )


@household_bp.route('/forum/posts/<int:post_id>')
@login_required
def forum_post_link(post_id):
    post = ForumService.post(post_id)
    return redirect(url_for(
        'household.forum_topic', topic_id=post.topic_id,
        page=ForumService.post_page(post), _anchor=f'post-{post.id}',
    ))


@household_bp.route('/forum/posts/<int:post_id>/pin', methods=['POST'])
@login_required
def forum_pin_post(post_id):
    post = ForumService.post(post_id)
    try:
        ForumService.set_post_pin(post_id, request.form)
    except (ValueError, TypeError, SQLAlchemyError) as error:
        _failure(error)
    else:
        flash('Post pin updated.', 'success')
    return redirect(url_for('household.forum_post_link', post_id=post.id))


@household_bp.route('/forum/posts/<int:post_id>/delete', methods=['POST'])
@login_required
def forum_delete_post(post_id):
    post = ForumService.post(post_id)
    topic_id = post.topic_id
    try:
        topic_id = ForumService.delete_post(post_id)
    except (ValueError, TypeError, SQLAlchemyError) as error:
        _failure(error)
    else:
        flash('Post removed.', 'success')
    return redirect(url_for('household.forum_topic', topic_id=topic_id) if topic_id else url_for('household.forum'))


@household_bp.route('/forum/topics/<int:topic_id>/moderate', methods=['POST'])
@login_required
def forum_moderate(topic_id):
    try:
        ForumService.moderate_topic(topic_id, request.form)
    except (ValueError, TypeError, SQLAlchemyError) as error:
        _failure(error)
    else:
        flash('Topic updated.', 'success')
    return redirect(url_for('household.forum_topic', topic_id=topic_id))


@household_bp.route('/forum/posts/<int:post_id>/react', methods=['POST'])
@login_required
def forum_react(post_id):
    post = ForumService.post(post_id)
    try:
        ForumService.react(post_id)
    except (ValueError, TypeError, SQLAlchemyError) as error:
        _failure(error)
    return redirect(url_for('household.forum_topic', topic_id=post.topic_id, page=ForumService.post_page(post), _anchor=f'post-{post_id}'))


@household_bp.route('/forum/categories', methods=['GET', 'POST'])
@login_required
def forum_categories():
    ForumService.require_moderator()
    if request.method == 'POST':
        try:
            ForumService.create_category(request.form)
        except (ValueError, TypeError, SQLAlchemyError) as error:
            _failure(error)
        else:
            flash('Category created.', 'success')
            return redirect(url_for('household.forum_categories'))
    return render_template('household/forum/categories.html', categories=ForumService.categories())


@household_bp.route('/forum/categories/<int:category_id>/delete', methods=['POST'])
@login_required
def forum_delete_category(category_id):
    try:
        ForumService.delete_category(category_id)
    except (ValueError, TypeError, SQLAlchemyError) as error:
        _failure(error)
    else:
        flash('Category removed.', 'success')
    return redirect(url_for('household.forum_categories'))


@household_bp.route('/forum/notifications')
@login_required
def forum_notifications():
    return render_template('household/forum/notifications.html', notifications=ForumService.notifications())


@household_bp.route('/forum/notifications/read', methods=['POST'])
@login_required
def forum_mark_read():
    try:
        ForumService.mark_read()
    except SQLAlchemyError as error:
        _failure(error)
    return redirect(url_for('household.forum_notifications'))


@household_bp.route('/forum/attachments/<int:attachment_id>')
@login_required
def forum_attachment(attachment_id):
    attachment = ForumService.attachment(attachment_id)
    response = send_file(
        BytesIO(attachment.content), mimetype='application/octet-stream',
        as_attachment=True, download_name=attachment.filename, max_age=0,
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@household_bp.route('/forum/attachments/<int:attachment_id>/delete', methods=['POST'])
@login_required
def forum_delete_attachment(attachment_id):
    attachment = ForumService.attachment(attachment_id)
    topic_id = attachment.post.topic_id
    try:
        ForumService.delete_attachment(attachment_id)
    except (ValueError, TypeError, SQLAlchemyError) as error:
        _failure(error)
    else:
        flash('Attachment removed.', 'success')
    return redirect(url_for('household.forum_topic', topic_id=topic_id))
