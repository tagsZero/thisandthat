from functools import wraps

from flask import Blueprint, g, redirect, render_template, request, session, url_for
from sqlalchemy import select
from werkzeug.security import check_password_hash

from .db import get_engine, users

bp = Blueprint("auth", __name__)


@bp.before_app_request
def load_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        with get_engine().connect() as connection:
            g.user = connection.execute(
                select(users.c.id, users.c.username).where(users.c.id == user_id)
            ).mappings().first()
        if g.user is None:
            session.clear()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if request.endpoint in ('pdf_export.save_output', 'pdf_export.retry'):
                from .pdf_export import failure
                return failure('로그인이 만료되었습니다. 다른 탭에서 로그인한 뒤 다시 제출하세요.',
                               code=401, recovery=request.form if request.method == 'POST' else None)
            if request.method == 'POST' and request.endpoint == 'final_report.show':
                return render_template('final_report_error.html', save_state='not_saved',
                    session_expired=True, message='로그인이 만료되었습니다. 다른 탭에서 로그인한 뒤 표시 설정을 다시 제출하세요.',
                    options={key: request.form.get('include_' + key) == '1'
                             for key in ('subscales', 'combined', 'summary')}), 401
            if request.method == 'POST' and request.endpoint == 'candidates.index':
                if request.accept_mimetypes.best == 'application/json':
                    return {'errors': {'session': '로그인이 만료되었습니다. 현재 입력은 유지됩니다. 로그인 후 다시 저장해 주세요.'}}, 401
                return render_template('composition_recovery.html', recovery=request.form,
                                       pdf_retry=request.form.get('action') == 'pdf',
                                       message='로그인이 만료되었습니다. 다른 탭에서 로그인한 뒤 다시 제출하세요.'), 401
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("web.portal"))
    error = None
    username = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with get_engine().connect() as connection:
            user = connection.execute(
                select(users).where(users.c.username == username)
            ).mappings().first()
        if not user or not check_password_hash(user["password_hash"], password):
            error = "아이디 또는 비밀번호를 확인해 주세요."
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("web.portal"))
    return render_template("login.html", error=error, username=username)


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
