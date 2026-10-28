from functools import wraps
import secrets

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_engine, users

bp = Blueprint("auth", __name__)


def registration_errors(username, password, confirmation):
    errors = {}
    if not username or len(username) > 80:
        errors["username"] = "아이디는 1~80자로 입력해 주세요."
    elif not username.isprintable() or any(char.isspace() for char in username):
        errors["username"] = "아이디에는 공백이나 제어문자를 사용할 수 없습니다."
    if not 8 <= len(password) <= 128 or not password.strip():
        errors["password"] = "비밀번호는 공백만 사용하지 않고 8~128자로 입력해 주세요."
    if password != confirmation:
        errors["password_confirm"] = "비밀번호가 일치하지 않습니다."
    elif not confirmation:
        errors["password_confirm"] = "비밀번호 확인을 입력해 주세요."
    return errors


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("web.portal"))

    request.max_content_length = 16 * 1024
    token = session.get("registration_csrf")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session["registration_csrf"] = token
    invite = current_app.config.get("REGISTRATION_INVITE_CODE") or ""
    registration_enabled = bool(invite) or current_app.config.get("REGISTRATION_OPEN", False)
    username, errors, status = "", {}, 200
    if not registration_enabled:
        errors["form"] = "현재는 회원가입을 받지 않습니다. 가입 안내를 확인해 주세요."

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirmation = request.form.get("password_confirm", "")
        supplied_token = request.form.get("csrf_token", "")
        if not registration_enabled:
            status = 503
        elif not secrets.compare_digest(token.encode("utf-8"), supplied_token.encode("utf-8")):
            errors["form"] = "가입 화면이 만료되었습니다. 아래 내용을 다시 입력해 주세요."
            status = 403
        else:
            errors = registration_errors(username, password, confirmation)
            if invite and not secrets.compare_digest(
                invite.encode("utf-8"), request.form.get("invite_code", "").encode("utf-8")
            ):
                errors["invite_code"] = "초대 코드를 확인해 주세요."
            if errors:
                status = 422
            else:
                try:
                    with get_engine().begin() as connection:
                        if connection.execute(select(users.c.id).where(users.c.username == username)).first():
                            errors["username"] = "이미 사용 중인 아이디입니다."
                        else:
                            connection.execute(users.insert().values(
                                username=username, password_hash=generate_password_hash(password),
                            ))
                except IntegrityError:
                    # The unique constraint also protects simultaneous registrations.
                    errors["username"] = "이미 사용 중인 아이디입니다."
                except SQLAlchemyError:
                    current_app.logger.warning("Registration database operation failed")
                    errors["form"] = "가입 정보를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요."
                    status = 503
                if errors:
                    if status == 200:
                        status = 409
                else:
                    session.pop("registration_csrf", None)
                    flash("회원가입이 완료되었습니다. 새 계정으로 로그인해 주세요.", "success")
                    return redirect(url_for("auth.login"), code=303)

    response = current_app.make_response((render_template(
        "register.html", username=username, errors=errors, csrf_token=token,
        invite_required=bool(invite), registration_enabled=registration_enabled,
    ), status))
    response.headers["Cache-Control"] = "no-store"
    return response


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
