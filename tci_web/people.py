"""Account-owned identities. Names and exam snapshots never decide identity."""
from datetime import date, datetime
import hashlib
import json
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import String, cast, func, literal, or_, select, union_all
from sqlalchemy.exc import SQLAlchemyError

from .auth import login_required
from .db import appointments, feature_settings, get_engine, people, reports, users, utc_now
from .permissions import check_csrf, csrf_token

bp = Blueprint("people", __name__, url_prefix="/people")
PAGE_SIZE = 20
SELECTION_ERROR = "대상자를 다시 검색해서 선택해 주세요."


def _identifier(value):
    if isinstance(value, bool):
        raise ValueError(SELECTION_ERROR)
    try:
        identity = int(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(SELECTION_ERROR) from None
    if identity <= 0 or identity > 2147483647 or str(identity) != str(value):
        raise ValueError(SELECTION_ERROR)
    return identity


def lock_owner(connection, owner_id):
    """All identity mutations lock user -> person -> linked record, in that order."""
    identity = _identifier(owner_id)
    row = connection.execute(select(users.c.id, users.c.is_active).where(
        users.c.id == identity).with_for_update()).first()
    if row is None or not row.is_active:
        raise ValueError(SELECTION_ERROR)
    return identity


def get_person(connection, owner_id, person_id, *, canonical=True, lock=False):
    identity = _identifier(person_id)
    visited = set()
    while identity not in visited:
        visited.add(identity)
        statement = select(people).where(people.c.id == identity, people.c.owner_id == owner_id)
        if lock:
            statement = statement.with_for_update()
        row = connection.execute(statement).mappings().first()
        if row is None:
            raise ValueError(SELECTION_ERROR)
        if not canonical or row["merged_into_id"] is None:
            return dict(row)
        identity = row["merged_into_id"]
    raise ValueError(SELECTION_ERROR)


def person_summary(row):
    return {"id": row["id"], "code": f'{row["code"]:04d}', "name": row["name"],
            "reference": row["reference"], "registered_on": row["registered_on"].isoformat()}


def resolve_person(connection, owner_id, person_id, name, reference, registered_on, create=True):
    """Resolve a selected identity or allocate one in the caller's save transaction.

    Existing selection changes no demographic fields. The form's name/reference/date
    remain independent examination snapshots. Call before locking the examination.
    """
    if person_id not in (None, ""):
        lock_owner(connection, owner_id)
        return get_person(connection, owner_id, person_id, lock=True)["id"]
    if not create:
        return None
    name, reference = str(name or "").strip(), str(reference or "").strip()
    if not name and not reference:
        raise ValueError("이름 또는 관리번호를 입력해 주세요.")
    if len(name) > 100 or len(reference) > 100:
        raise ValueError("이름과 관리번호는 각각 100자 이내로 입력해 주세요.")
    if registered_on in (None, ""):
        registered_on = datetime.now(ZoneInfo("Asia/Seoul")).date()
    elif isinstance(registered_on, datetime):
        registered_on = registered_on.date()
    elif not isinstance(registered_on, date):
        try:
            registered_on = date.fromisoformat(registered_on)
        except (TypeError, ValueError):
            raise ValueError("등록일을 확인해 주세요.") from None
    lock_owner(connection, owner_id)
    code = connection.scalar(users.update().where(users.c.id == owner_id,
        users.c.next_person_code < 2147483647).values(next_person_code=users.c.next_person_code + 1)
        .returning(users.c.next_person_code))
    if code is None:
        raise ValueError("대상자 코드 발급 한도를 확인해 주세요.")
    return connection.execute(people.insert().values(owner_id=owner_id, code=code, name=name,
        reference=reference, registered_on=registered_on)).inserted_primary_key[0]


def _search(connection, owner_id, query, exclude=None):
    conditions = [people.c.owner_id == owner_id, people.c.merged_into_id.is_(None)]
    if exclude:
        conditions.append(people.c.id != exclude)
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        code_query = query.removeprefix("code:")
        code = int(code_query) if code_query.isascii() and code_query.isdecimal() and len(code_query) <= 10 else None
        if code is not None and code > 2147483647:
            code = None

        def matches(table):
            return or_(table.c.name.ilike(f"%{escaped}%", escape="\\"),
                       table.c.reference.ilike(f"%{escaped}%", escape="\\"),
                       table.c.code == code if code is not None else literal(False))

        aliases = people.alias("matched_aliases")
        alias_target = select(aliases.c.merged_into_id).where(aliases.c.owner_id == owner_id,
            aliases.c.merged_into_id.is_not(None), matches(aliases))
        conditions.append(or_(matches(people), people.c.id.in_(alias_target)))
    return connection.execute(select(people).where(*conditions).order_by(
        people.c.code.desc()).limit(20)).mappings().all()


@bp.get("/search")
@login_required
def search():
    query = request.args.get("q", "").strip()[:100]
    with get_engine().connect() as connection:
        items = [person_summary(row) for row in _search(connection, g.user["id"], query)]
    return {"items": items}


def _feature_flags(connection):
    if hasattr(g, "features"):
        return g.features
    flags = {"tci": True, "khtp": True, "schedule": True}
    flags.update(dict(connection.execute(select(feature_settings.c.key, feature_settings.c.enabled)).all()))
    return flags


def _history(connection, person_id, owner_id, page):
    from khtp_web import jobs

    flags = _feature_flags(connection)
    queries = []
    for kind, table, day, title, reference in (
        ("tci", reports, reports.c.exam_date, reports.c.name, reports.c.reference),
        ("khtp", jobs, jobs.c.exam_date, jobs.c.name, jobs.c.reference),
        ("schedule", appointments, appointments.c.day, appointments.c.title, literal("")),
    ):
        if flags.get(kind, True):
            queries.append(select(literal(kind).label("kind"), cast(table.c.id, String).label("id"),
                day.label("day"), title.label("title"), reference.label("reference")).where(
                table.c.owner_id == owner_id, table.c.person_id == person_id))
    if not queries:
        return [], 1, 1, 0
    combined = union_all(*queries).subquery()
    total = connection.scalar(select(func.count()).select_from(combined))
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(1, page), pages)
    records = connection.execute(select(combined).order_by(combined.c.day.desc().nullslast(),
        combined.c.kind, combined.c.id.desc()).limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE)).mappings().all()
    return records, page, pages, total


@bp.get("/<int:person_id>")
@login_required
def detail(person_id):
    with get_engine().connect() as connection:
        try:
            original = get_person(connection, g.user["id"], person_id, canonical=False)
            person = get_person(connection, g.user["id"], person_id)
        except ValueError:
            abort(404)
        records, page, pages, total = _history(connection, person["id"], g.user["id"],
            request.args.get("page", 1, type=int) or 1)
        aliases = connection.execute(select(people.c.code, people.c.name).where(
            people.c.owner_id == g.user["id"], people.c.merged_into_id == person["id"])
            .order_by(people.c.code)).mappings().all()
    return render_template("people/detail.html", active="", person=person, original=original,
        aliases=aliases, records=records, page=page, pages=pages, total=total)


def _linked_snapshot(connection, owner_id, source_id):
    from khtp_web import jobs

    identities = {}
    for kind, table in (("tci", reports), ("khtp", jobs), ("schedule", appointments)):
        identities[kind] = [str(identity) for identity in connection.scalars(select(table.c.id).where(
            table.c.owner_id == owner_id, table.c.person_id == source_id).order_by(table.c.id))]
    fingerprint = hashlib.sha256(json.dumps(identities, sort_keys=True).encode("utf-8")).hexdigest()
    return {kind: len(ids) for kind, ids in identities.items()}, fingerprint


def _serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt="haeseok-person-merge-v1")


def _merge_payload(source, target, fingerprint):
    return {"owner": source["owner_id"], "source": source["id"], "target": target["id"],
            "source_stamp": source["updated_at"].isoformat(), "target_stamp": target["updated_at"].isoformat(),
            "links": fingerprint}


def _merge_view(source_id, target_id=None, *, error=None, status=200):
    with get_engine().connect() as connection:
        try:
            source = get_person(connection, g.user["id"], source_id, canonical=False)
            if source["merged_into_id"] is not None:
                return redirect(url_for("people.detail", person_id=source_id), code=303)
            target = get_person(connection, g.user["id"], target_id, canonical=False) if target_id else None
            if target and (target["id"] == source["id"] or target["merged_into_id"] is not None):
                raise ValueError(SELECTION_ERROR)
        except ValueError:
            abort(404)
        query = request.args.get("q", "").strip()[:100]
        choices = _search(connection, g.user["id"], query, exclude=source_id) if target is None else []
        counts, fingerprint = _linked_snapshot(connection, g.user["id"], source_id)
        token = _serializer().dumps(_merge_payload(source, target, fingerprint)) if target else None
    return render_template("people/merge.html", active="", source=source, target=target, choices=choices,
        query=query, counts=counts, merge_token=token, account_csrf=csrf_token(), error=error), status


@bp.route("/<int:person_id>/merge", methods=["GET", "POST"])
@login_required
def merge(person_id):
    if request.method == "GET":
        return _merge_view(person_id, request.args.get("target_id", type=int))
    check_csrf()
    try:
        target_id = _identifier(request.form.get("target_id"))
        proof = _serializer().loads(request.form.get("merge_token", ""), max_age=1800)
    except (ValueError, BadSignature, SignatureExpired):
        return _merge_view(person_id, error="확인 화면이 만료되었습니다. 남길 대상자를 다시 선택해 주세요.", status=409)
    if request.form.get("confirm") != "merge":
        return _merge_view(person_id, target_id, error="두 코드가 같은 사람인지 확인해 주세요.", status=422)
    conflict = False
    try:
        with get_engine().begin() as connection:
            lock_owner(connection, g.user["id"])
            source = get_person(connection, g.user["id"], person_id, canonical=False, lock=True)
            target = get_person(connection, g.user["id"], target_id, canonical=False, lock=True)
            if source["id"] == target["id"] or source["merged_into_id"] or target["merged_into_id"]:
                abort(409, description="대상자 연결이 변경되었습니다. 확인 화면을 다시 열어 주세요.")
            counts, fingerprint = _linked_snapshot(connection, g.user["id"], source["id"])
            if proof != _merge_payload(source, target, fingerprint):
                conflict = True
            else:
                from khtp_web import jobs
                now = utc_now()
                connection.execute(reports.update().where(reports.c.owner_id == g.user["id"],
                    reports.c.person_id == source["id"]).values(person_id=target["id"], updated_at=now))
                connection.execute(jobs.update().where(jobs.c.owner_id == g.user["id"],
                    jobs.c.person_id == source["id"]).values(person_id=target["id"], revision=jobs.c.revision + 1))
                connection.execute(appointments.update().where(appointments.c.owner_id == g.user["id"],
                    appointments.c.person_id == source["id"]).values(person_id=target["id"],
                    revision=appointments.c.revision + 1, updated_at=now))
                # Flatten previous aliases so every retired code resolves in one hop.
                connection.execute(people.update().where(people.c.owner_id == g.user["id"],
                    or_(people.c.id == source["id"], people.c.merged_into_id == source["id"]))
                    .values(merged_into_id=target["id"], updated_at=now))
                connection.execute(people.update().where(people.c.id == target["id"],
                    people.c.owner_id == g.user["id"]).values(updated_at=now))
    except ValueError:
        abort(404)
    except SQLAlchemyError:
        current_app.logger.warning("Person merge storage failure", exc_info=False)
        return _merge_view(person_id, target_id, error="병합하지 못했습니다. 확인 후 다시 시도해 주세요.", status=503)
    if conflict:
        return _merge_view(person_id, target_id,
            error="연결된 기록이 변경되었습니다. 아래 내용을 다시 확인해 주세요.", status=409)
    flash("대상자 연결을 병합했습니다. 열려 있던 검사·일정 편집 화면은 다시 열어 주세요.", "success")
    return redirect(url_for("people.detail", person_id=target_id), code=303)
