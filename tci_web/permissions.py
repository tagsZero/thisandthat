"""Account ownership and explicit read grants, shared by both examination programs."""
from copy import deepcopy
import secrets
from uuid import UUID

from flask import abort, g, request, session
from sqlalchemy import and_, exists, or_, select

from .account_schema import exam_shares
from .db import reports


def _current_user_id(value=None):
    if value is not None:
        return value
    if not getattr(g, "user", None):
        abort(401)
    return g.user["id"]


def owner_condition(table, user_id=None):
    return table.c.owner_id == _current_user_id(user_id)


def readable_condition(table, kind, user_id=None):
    account_id = _current_user_id(user_id)
    if kind not in ("tci", "khtp"):
        raise ValueError("Invalid examination kind")
    key = exam_shares.c.report_id if kind == "tci" else exam_shares.c.job_id
    grant = exists(select(exam_shares.c.id).where(key == table.c.id, exam_shares.c.recipient_id == account_id))
    return and_(table.c.owner_id.is_not(None), or_(table.c.owner_id == account_id, grant))


def get_exam(connection, kind, exam_id, *, write=False, lock=False):
    if kind == "tci":
        if isinstance(exam_id, bool):
            abort(404)
        try:
            identifier = int(exam_id)
        except (ValueError, TypeError, OverflowError):
            abort(404)
        if identifier <= 0 or identifier > 2147483647 or str(identifier) != str(exam_id):
            abort(404)
        table = reports
    elif kind == "khtp":
        from khtp_web import jobs
        table = jobs
        try:
            identifier = str(UUID(str(exam_id)))
        except (ValueError, TypeError, AttributeError):
            abort(404)
    else:
        abort(404)
    condition = owner_condition(table) if write else readable_condition(table, kind)
    query = select(table).where(table.c.id == identifier, condition)
    if lock:
        query = query.with_for_update()
    row = connection.execute(query).mappings().first()
    if row is None:
        abort(404)
    if lock and not write and row["owner_id"] != _current_user_id():
        key = exam_shares.c.report_id if kind == "tci" else exam_shares.c.job_id
        grant = connection.execute(select(exam_shares.c.id).where(
            key == identifier, exam_shares.c.recipient_id == _current_user_id()).with_for_update()).first()
        if grant is None:
            abort(404)
    return deepcopy(dict(row))


def csrf_token():
    token = session.get("account_csrf")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session["account_csrf"] = token
    return token


def check_csrf():
    expected = session.get("account_csrf")
    supplied = request.form.get("_csrf", "")
    if not isinstance(expected, str) or not secrets.compare_digest(expected.encode("utf-8"), supplied.encode("utf-8")):
        abort(403)
