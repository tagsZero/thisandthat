"""Saved examination readers, owner grants and separate private/shared notes."""
from copy import deepcopy

from flask import Blueprint, abort, current_app, flash, g, make_response, redirect, render_template, request, url_for
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .account_schema import exam_comments, exam_shares
from .auth import login_required
from .db import get_engine, users, utc_now
from .permissions import check_csrf, csrf_token, get_exam


bp = Blueprint("collaboration", __name__)


@bp.after_request
def private_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.errorhandler(SQLAlchemyError)
def storage_error(error):
    current_app.logger.warning("Examination collaboration storage operation failed: %s", type(error).__name__)
    if request.method == "POST" and request.endpoint in {
            "collaboration.comment", "collaboration.edit_comment"}:
        # Recover only what was submitted. This must not need another database
        # read or imply that the examination/thread was successfully authorized.
        # Retrying the original endpoint rechecks access, authorship and CSRF.
        arguments = request.view_args or {}
        kind = arguments["kind"]
        return render_template("exam_comment_recovery.html",
            active=kind if kind in ("tci", "khtp") else "",
            kind=kind, exam_id=arguments["exam_id"],
            editing=request.endpoint == "collaboration.edit_comment",
            action=request.full_path.removesuffix("?"), account_csrf=csrf_token(),
            body=request.form.get("body", ""),
            audience=request.form.get("audience", "private"),
            recipient_id=request.form.get("recipient_id", "")), 503
    return "저장소에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.", 503


def _exam_key(kind, exam):
    return {"report_id": exam["id"], "job_id": None} if kind == "tci" else {
        "report_id": None, "job_id": exam["id"]}


def _exam_condition(table, kind, exam):
    key = table.c.report_id if kind == "tci" else table.c.job_id
    return key == exam["id"]


def _grant(connection, kind, exam, recipient_id, *, lock=False):
    query = select(exam_shares).where(
        _exam_condition(exam_shares, kind, exam), exam_shares.c.recipient_id == recipient_id)
    if lock:
        query = query.with_for_update()
    return connection.execute(query).mappings().first()


def _mutation_exam(connection, kind, exam_id, *, owner_only=False):
    # Every mutation uses examination -> grant -> comment lock order. A recipient
    # rechecks the grant after obtaining the examination lock, rather than relying
    # on a grant observed before a concurrent revocation finished.
    exam = get_exam(connection, kind, exam_id, write=owner_only, lock=True)
    if exam["owner_id"] != g.user["id"] and _grant(
            connection, kind, exam, g.user["id"], lock=True) is None:
        abort(404)
    return exam


def _visible_comments(exam):
    private = and_(exam_comments.c.recipient_id.is_(None), exam_comments.c.author_id == g.user["id"])
    shared = exam_comments.c.recipient_id.is_not(None) if exam["owner_id"] == g.user["id"] else (
        exam_comments.c.recipient_id == g.user["id"])
    return or_(private, shared)


def _detail_data(connection, kind, exam):
    is_owner = exam["owner_id"] == g.user["id"]
    owner_username = connection.scalar(select(users.c.username).where(users.c.id == exam["owner_id"]))
    grants = [dict(row) for row in connection.execute(select(
        exam_shares, users.c.username).join(users, users.c.id == exam_shares.c.recipient_id).where(
            _exam_condition(exam_shares, kind, exam)).order_by(exam_shares.c.created_at, exam_shares.c.id)).mappings()]
    active_recipients = {row["recipient_id"] for row in grants}
    author = users.alias("comment_author")
    recipient = users.alias("comment_recipient")
    comments = []
    for item in connection.execute(select(
        exam_comments, author.c.username.label("author_username"),
        recipient.c.username.label("recipient_username"),
    ).join(author, author.c.id == exam_comments.c.author_id).outerjoin(
        recipient, recipient.c.id == exam_comments.c.recipient_id).where(
            _exam_condition(exam_comments, kind, exam), _visible_comments(exam)).order_by(
                exam_comments.c.created_at, exam_comments.c.id)).mappings():
        value = dict(item)
        value.update(is_own=value["author_id"] == g.user["id"],
                     audience="private" if value["recipient_id"] is None else "shared",
                     thread_active=value["recipient_id"] is None or value["recipient_id"] in active_recipients)
        comments.append(value)
    if kind == "tci":
        from .final_report import read_model
        view = read_model(exam)
    else:
        from khtp_web import subject_view
        view = deepcopy(exam)
        view["subject"] = subject_view(view)
    return dict(exam=exam, kind=kind, is_owner=is_owner, owner_username=owner_username,
                account_csrf=csrf_token(), shares=grants if is_owner else [], comments=comments,
                thread_options=grants if is_owner else [], view=view, error=None,
                draft_body="", draft_audience="private", draft_recipient_id="")


def _render_detail(kind, exam_id, *, error=None, status=200):
    with get_engine().connect() as connection:
        exam = get_exam(connection, kind, exam_id)
        data = _detail_data(connection, kind, exam)
    if error:
        data.update(error=error, draft_body=request.form.get("body", ""),
                    draft_audience=request.form.get("audience", "private"),
                    draft_recipient_id=request.form.get("recipient_id", ""))
    return render_template("exam_detail.html", active="tci" if kind == "tci" else "khtp", **data), status


def _back(kind, exam_id):
    return redirect(url_for("collaboration.detail", kind=kind, exam_id=exam_id, _anchor="exam-notes"), code=303)


@bp.get("/exams/<kind>/<exam_id>")
@login_required
def detail(kind, exam_id):
    return _render_detail(kind, exam_id)


@bp.get("/exams/<kind>/<exam_id>/pdf")
@login_required
def pdf(kind, exam_id):
    with get_engine().connect() as connection:
        snapshot = get_exam(connection, kind, exam_id)
    try:
        if kind == "tci":
            from .pdf_export import download
            response = download(snapshot)
        else:
            from khtp_web import pdf_bytes, subject_view
            snapshot["subject"] = subject_view(snapshot)
            response = make_response(pdf_bytes(snapshot))
            response.headers.update({
                "Content-Type": "application/pdf",
                "Content-Disposition": f'attachment; filename="KHTP-observation-{snapshot["id"]}.pdf"',
                "X-KHTP-Revision": str(snapshot["revision"]),
            })
    except Exception:
        current_app.logger.warning("Read-only examination PDF generation failed")
        abort(503, description="PDF를 생성하지 못했습니다. 검사 내용은 변경되지 않았습니다.")
    response.headers["X-Exam-Access"] = "read-only"
    return response


@bp.post("/exams/<kind>/<exam_id>/shares")
@login_required
def share(kind, exam_id):
    check_csrf()
    error = None
    with get_engine().begin() as connection:
        exam = _mutation_exam(connection, kind, exam_id, owner_only=True)
        username = request.form.get("username", "").strip()
        recipient_id = connection.scalar(select(users.c.id).where(users.c.username == username)) if username else None
        if recipient_id is None:
            error = "공유할 계정의 아이디를 정확히 입력해 주세요."
        elif recipient_id == g.user["id"]:
            error = "본인 계정에는 공유할 필요가 없습니다."
        elif _grant(connection, kind, exam, recipient_id, lock=True) is None:
            try:
                with connection.begin_nested():
                    connection.execute(exam_shares.insert().values(
                        **_exam_key(kind, exam), recipient_id=recipient_id))
            except IntegrityError:
                # A duplicate concurrent grant is harmless; a different constraint
                # failure must still be reported as a storage error.
                if _grant(connection, kind, exam, recipient_id) is None:
                    raise
    if error:
        return _render_detail(kind, exam_id, error=error, status=422)
    flash("검사를 읽기 전용으로 공유했습니다.", "success")
    return _back(kind, exam_id)


@bp.post("/exams/<kind>/<exam_id>/shares/<int:share_id>/revoke")
@login_required
def revoke(kind, exam_id, share_id):
    check_csrf()
    with get_engine().begin() as connection:
        exam = _mutation_exam(connection, kind, exam_id, owner_only=True)
        row = connection.execute(select(exam_shares).where(
            exam_shares.c.id == share_id, _exam_condition(exam_shares, kind, exam)).with_for_update()).mappings().first()
        if row is None:
            abort(404)
        connection.execute(exam_shares.delete().where(exam_shares.c.id == share_id))
    flash("공유를 회수했습니다. 기존 대화는 보존됩니다.", "success")
    return _back(kind, exam_id)


def _body():
    value = request.form.get("body", "").strip()
    if not value or len(value) > 5000:
        return None
    return value


@bp.post("/exams/<kind>/<exam_id>/comments")
@login_required
def comment(kind, exam_id):
    check_csrf()
    error = None
    with get_engine().begin() as connection:
        exam = _mutation_exam(connection, kind, exam_id)
        body = _body()
        audience = request.form.get("audience", "private")
        recipient_id = None
        if body is None:
            error = "메모와 댓글은 1~5000자로 입력해 주세요."
        elif audience not in ("private", "shared"):
            error = "메모와 공유 대화의 공개 범위를 확인해 주세요."
        elif audience == "shared":
            if exam["owner_id"] == g.user["id"]:
                try:
                    recipient_id = int(request.form.get("recipient_id", ""))
                except (ValueError, TypeError, OverflowError):
                    recipient_id = None
            else:
                recipient_id = g.user["id"]
            if recipient_id is None or _grant(connection, kind, exam, recipient_id, lock=True) is None:
                error = "현재 공유 중인 대화 상대를 선택해 주세요."
        if error is None:
            stamp = utc_now()
            connection.execute(exam_comments.insert().values(
                **_exam_key(kind, exam), author_id=g.user["id"], recipient_id=recipient_id, body=body,
                created_at=stamp, updated_at=stamp))
    if error:
        return _render_detail(kind, exam_id, error=error, status=422)
    flash("메모를 저장했습니다." if audience == "private" else "공유 댓글을 남겼습니다.", "success")
    return _back(kind, exam_id)


def _own_comment(connection, kind, exam, comment_id):
    row = connection.execute(select(exam_comments).where(
        exam_comments.c.id == comment_id, _exam_condition(exam_comments, kind, exam),
        exam_comments.c.author_id == g.user["id"], _visible_comments(exam)).with_for_update()).mappings().first()
    if row is None:
        abort(404)
    return row


@bp.post("/exams/<kind>/<exam_id>/comments/<int:comment_id>/edit")
@login_required
def edit_comment(kind, exam_id, comment_id):
    check_csrf()
    error = None
    with get_engine().begin() as connection:
        exam = _mutation_exam(connection, kind, exam_id)
        _own_comment(connection, kind, exam, comment_id)
        body = _body()
        if body is None:
            error = "메모와 댓글은 1~5000자로 입력해 주세요."
        else:
            connection.execute(exam_comments.update().where(exam_comments.c.id == comment_id).values(
                body=body, updated_at=utc_now()))
    if error:
        return _render_detail(kind, exam_id, error=error, status=422)
    flash("작성한 메모와 댓글을 수정했습니다.", "success")
    return _back(kind, exam_id)


@bp.post("/exams/<kind>/<exam_id>/comments/<int:comment_id>/delete")
@login_required
def delete_comment(kind, exam_id, comment_id):
    check_csrf()
    with get_engine().begin() as connection:
        exam = _mutation_exam(connection, kind, exam_id)
        _own_comment(connection, kind, exam, comment_id)
        connection.execute(exam_comments.delete().where(exam_comments.c.id == comment_id))
    flash("작성한 메모와 댓글을 삭제했습니다.", "success")
    return _back(kind, exam_id)


def init_app(app):
    if bp.name not in app.blueprints:
        app.register_blueprint(bp)
