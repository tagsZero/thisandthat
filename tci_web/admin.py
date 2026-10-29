"""Small account administration and global feature switches; never bypass ownership."""
from functools import wraps

import click
from flask import Blueprint, abort, flash, g, has_app_context, redirect, render_template, request, url_for
from sqlalchemy import func, select

from .auth import login_required
from .db import feature_settings, get_engine, users
from .permissions import check_csrf, csrf_token

bp = Blueprint('admin', __name__, url_prefix='/admin')
FEATURES = {'tci': 'TCI', 'khtp': 'K-HTP', 'schedule': '스케줄러'}


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not g.user['is_admin']:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def feature_enabled(name):
    if not has_app_context():
        return True
    return getattr(g, 'features', {}).get(name, True)


def request_feature():
    endpoint = request.endpoint or ''
    if endpoint.startswith('khtp.'):
        return 'khtp'
    if endpoint.startswith('scheduler.') or endpoint in ('web.save_appointment', 'web.delete_appointment'):
        return 'schedule'
    if endpoint.startswith('collaboration.'):
        return (request.view_args or {}).get('kind')
    if endpoint.startswith(('candidates.', 'final_report.', 'pdf_export.', 'library.', 'type_library.')):
        return 'tci'
    if endpoint in ('web.dashboard', 'web.edit_report', 'web.review_report', 'web.classification_preview'):
        return 'tci'
    return None


@bp.before_app_request
def feature_access():
    g.features = dict.fromkeys(FEATURES, True)
    if not getattr(g, 'user', None):
        return None
    with get_engine().connect() as connection:
        g.features.update({row.key: row.enabled for row in connection.execute(select(feature_settings))
                           if row.key in FEATURES})
    feature = request_feature()
    if feature and not feature_enabled(feature):
        message = FEATURES[feature] + ' 기능은 현재 사용 중지 상태입니다.'
        if request.is_json or request.accept_mimetypes.best == 'application/json':
            return {'error': message, 'errors': {'feature': message}}, 403
        return render_template('feature_unavailable.html', message=message), 403
    # The reference library is global, so ordinary accounts cannot change it.
    if request.endpoint in ('library.edit_item', 'library.edit_source') and not g.user['is_admin']:
        abort(403)
    if (request.endpoint or '').startswith('library.') and request.method == 'POST':
        check_csrf()


@bp.get('')
@admin_required
def index():
    query = request.args.get('q', '').strip()[:80]
    page = max(1, request.args.get('page', 1, type=int))
    criteria = []
    if query:
        escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        criteria.append(users.c.username.ilike('%' + escaped + '%', escape='\\'))
    with get_engine().connect() as connection:
        count = connection.scalar(select(func.count()).select_from(users).where(*criteria))
        pages = max(1, (count + 49) // 50)
        page = min(page, pages)
        members = connection.execute(select(users.c.id, users.c.username, users.c.is_admin, users.c.is_active)
            .where(*criteria).order_by(users.c.id).limit(50).offset((page - 1) * 50)).mappings().all()
    return render_template('admin.html', active='admin', members=members, query=query, page=page,
                           pages=pages, feature_labels=FEATURES, account_csrf=csrf_token())


@bp.post('/members/<int:user_id>')
@admin_required
def member_status(user_id):
    check_csrf()
    if user_id == g.user['id']:
        abort(400, '자신의 계정은 이 화면에서 중지할 수 없습니다.')
    active = request.form.get('active') == '1'
    with get_engine().begin() as connection:
        # Serialize administration consistently; no records are deleted.
        admins = connection.execute(select(users).where(users.c.is_admin.is_(True))
                                    .order_by(users.c.id).with_for_update()).mappings().all()
        member = connection.execute(select(users).where(users.c.id == user_id).with_for_update()).mappings().first()
        if member is None:
            abort(404)
        if not active and member['is_admin'] and sum(row['is_active'] for row in admins) <= 1:
            abort(400, '마지막 활성 관리자는 중지할 수 없습니다.')
        if member['is_active'] != active:
            connection.execute(users.update().where(users.c.id == user_id).values(
                is_active=active, session_version=users.c.session_version + 1))
    flash('계정 상태를 변경했습니다. 기존 자료는 보존됩니다.', 'success')
    return redirect(url_for('admin.index'), 303)


@bp.post('/features')
@admin_required
def features():
    check_csrf()
    with get_engine().begin() as connection:
        connection.execute(select(users.c.id).where(users.c.is_admin.is_(True))
                           .order_by(users.c.id).with_for_update()).all()
        for key in FEATURES:
            enabled = request.form.get(key) == '1'
            present = connection.execute(select(feature_settings.c.key).where(feature_settings.c.key == key)).first()
            if present:
                connection.execute(feature_settings.update().where(feature_settings.c.key == key).values(enabled=enabled))
            else:
                connection.execute(feature_settings.insert().values(key=key, enabled=enabled))
    flash('기능 사용 설정을 저장했습니다. 저장된 자료는 보존됩니다.', 'success')
    return redirect(url_for('admin.index'), 303)


def init_app(app):
    app.register_blueprint(bp)
    app.context_processor(lambda: {'feature_enabled': feature_enabled, 'account_csrf_token': csrf_token})

    @app.cli.command('set-admin')
    @click.option('--username', required=True)
    def set_admin(username):
        """운영자가 지정한 기존 계정을 관리자로 설정한다. 가입 순서는 사용하지 않는다."""
        with get_engine().begin() as connection:
            row = connection.execute(select(users).where(users.c.username == username.strip()).with_for_update()).mappings().first()
            if row is None:
                raise click.ClickException('존재하지 않는 계정입니다. 먼저 계정을 생성해 주세요.')
            if not row['is_active']:
                raise click.ClickException('중지된 계정입니다. 활성 계정을 지정해 주세요.')
            connection.execute(users.update().where(users.c.id == row['id']).values(is_admin=True))
        click.echo('지정한 계정을 관리자로 설정했습니다. 개인 자료 접근 권한은 변경하지 않았습니다.')
