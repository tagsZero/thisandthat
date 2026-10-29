"""Account-owned meetings with explicit read grants and separate conversations."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.exceptions import NotFound

from .auth import login_required
from .db import appointments, get_engine, reports, users, utc_now
from .permissions import check_csrf, csrf_token, get_exam, readable_condition as exam_readable
from .scheduler_schema import appointment_comments, appointment_shares


bp = Blueprint("scheduler", __name__)
STATUS_LABELS = {"scheduled": "예정", "completed": "완료", "cancelled": "취소"}
KEEP_LINK = "__keep__"


def today():
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def enabled(kind):
    return getattr(g, "features", {}).get(kind, True)


def readable_condition(user_id=None):
    account_id = g.user["id"] if user_id is None else user_id
    grant = exists(select(appointment_shares.c.id).where(
        appointment_shares.c.appointment_id == appointments.c.id,
        appointment_shares.c.recipient_id == account_id))
    return and_(appointments.c.owner_id.is_not(None), or_(appointments.c.owner_id == account_id, grant))


def _grant(connection, event_id, recipient_id, *, lock=False):
    query = select(appointment_shares).where(appointment_shares.c.appointment_id == event_id,
                                            appointment_shares.c.recipient_id == recipient_id)
    if lock:
        query = query.with_for_update()
    return connection.execute(query).mappings().first()


def get_event(connection, event_id, *, write=False, lock=False):
    if not isinstance(event_id, int) or isinstance(event_id, bool) or not 0 < event_id <= 2147483647:
        abort(404)
    permission = appointments.c.owner_id == g.user["id"] if write else readable_condition()
    query = select(appointments).where(appointments.c.id == event_id, permission)
    if lock:
        query = query.with_for_update()
    row = connection.execute(query).mappings().first()
    if row is None:
        abort(404)
    # A read observed before a concurrent revocation is not a mutation grant.
    if lock and row["owner_id"] != g.user["id"] and _grant(
            connection, event_id, g.user["id"], lock=True) is None:
        abort(404)
    return dict(row)


def _person(connection, person_id, user_id):
    from .db import people
    seen = set()
    while person_id and person_id not in seen:
        seen.add(person_id)
        row = connection.execute(select(people).where(people.c.id == person_id,
                                                      people.c.owner_id == user_id)).mappings().first()
        if row is None:
            return None
        if row["merged_into_id"]:
            person_id = row["merged_into_id"]
            continue
        value = dict(row)
        value["code"] = f'{value["code"]:04d}'
        value["registered_on"] = value["registered_on"].isoformat() if value["registered_on"] else ""
        return value
    return None


def _linked_exam(connection, event, user_id):
    """Return the currently readable link and an owner-only repair notice."""
    from khtp_web import jobs
    for kind, table, key in (("tci", reports, "report_id"), ("khtp", jobs, "job_id")):
        if event.get(key) and enabled(kind):
            row = connection.execute(select(table.c.id, table.c.name, table.c.reference, table.c.exam_date,
                                           table.c.owner_id, table.c.person_id)
                .where(table.c.id == event[key], exam_readable(table, kind, user_id))).mappings().first()
            if row is not None:
                # Identity codes belong to their account. A shared examination
                # cannot be compared with the recipient's own person IDs.
                if (row["owner_id"] == event["owner_id"] and row["person_id"]
                        and event.get("person_id")):
                    source_person = _person(connection, row["person_id"], event["owner_id"])
                    event_person = _person(connection, event["person_id"], event["owner_id"])
                    if not source_person or not event_person or source_person["id"] != event_person["id"]:
                        return None, event["owner_id"] == user_id
                return dict(row, kind=kind), False
    return None, False


def _decorate(connection, event, user_id):
    result = dict(event)
    result["is_owner"] = result["owner_id"] == user_id
    result["status_label"] = STATUS_LABELS.get(result["status"], "예정")
    result["end_at"] = (datetime.combine(result["day"], result["time"]) +
                        timedelta(minutes=result["duration_minutes"])) if result["duration_minutes"] else None
    result["linked_exam"], result["connection_needs_check"] = _linked_exam(connection, result, user_id)
    result["person"] = _person(connection, result.get("person_id"), user_id) if result["is_owner"] else None
    return result


def summary(connection, user_id, day, limit=5):
    """Current-day preview for the dashboard; no implicit examination disclosure."""
    rows = connection.execute(select(appointments, users.c.username.label("owner_username"))
        .join(users, users.c.id == appointments.c.owner_id)
        .where(readable_condition(user_id), appointments.c.day == day)
        .order_by(appointments.c.time, appointments.c.id).limit(limit)).mappings()
    return [_decorate(connection, row, user_id) for row in rows]


def _overlaps(connection, event, user_id):
    if event["status"] == "cancelled" or not event["duration_minutes"]:
        return []
    start = datetime.combine(event["day"], event["time"])
    end = start + timedelta(minutes=event["duration_minutes"])
    earliest = start.date() - timedelta(days=1) if start.date() > date.min else date.min
    query = select(appointments).where(appointments.c.owner_id == user_id,
        appointments.c.status != "cancelled", appointments.c.duration_minutes.is_not(None),
        appointments.c.day >= earliest, appointments.c.day <= end.date())
    if event.get("id"):
        query = query.where(appointments.c.id != event["id"])
    conflicts = []
    for row in connection.execute(query).mappings():
        other_start = datetime.combine(row["day"], row["time"])
        other_end = other_start + timedelta(minutes=row["duration_minutes"])
        if start < other_end and other_start < end:
            conflicts.append(dict(row))
    return conflicts


@bp.after_request
def private_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.errorhandler(SQLAlchemyError)
def storage_error(error):
    current_app.logger.warning("Schedule storage operation failed: %s", type(error).__name__)
    if request.method == "POST" and request.endpoint in {"scheduler.comment", "scheduler.edit_comment"}:
        # Recovery must work even when no database read succeeds. Echo only the
        # submitted draft; do not load or assume schedule/comment ownership here.
        # The unchanged POST endpoint rechecks current access and authorship.
        arguments = request.view_args or {}
        editing = request.endpoint == "scheduler.edit_comment"
        action = url_for(request.endpoint, **arguments)
        return render_template("scheduler/comment_recovery.html", active="schedule", editing=editing,
            action=action, event_id=arguments["event_id"], account_csrf=csrf_token(),
            body=request.form.get("body", ""), audience=request.form.get("audience", ""),
            recipient_id=request.form.get("recipient_id", "")), 503
    return "저장소에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.", 503


@bp.get("/schedule")
@login_required
def index():
    try:
        selected = date.fromisoformat(request.args.get("date", "")) if request.args.get("date") else today()
    except ValueError:
        selected = today()
        flash("날짜를 확인해 주세요. 오늘의 일정을 표시합니다.", "error")
    # Date navigation must have room for both previous/next links.
    selected = min(max(selected, date(1900, 1, 8)), date(9999, 12, 23))
    period = "week" if request.args.get("period") == "week" else "day"
    start = selected - timedelta(days=selected.weekday()) if period == "week" else selected
    end = start + timedelta(days=7 if period == "week" else 1)
    scope = request.args.get("scope", "all")
    if scope not in {"all", "own", "shared"}:
        scope = "all"
    query = select(appointments, users.c.username.label("owner_username")).join(
        users, users.c.id == appointments.c.owner_id).where(
        readable_condition(), appointments.c.day >= start, appointments.c.day < end)
    if scope == "own":
        query = query.where(appointments.c.owner_id == g.user["id"])
    elif scope == "shared":
        query = query.where(appointments.c.owner_id != g.user["id"])
    with get_engine().connect() as connection:
        events = [_decorate(connection, item, g.user["id"]) for item in connection.execute(
            query.order_by(appointments.c.day, appointments.c.time, appointments.c.id)).mappings()]
    return render_template("scheduler/index.html", active="schedule", events=events, selected=selected,
        start=start, last=end-timedelta(days=1), today=today(), period=period, scope=scope,
        previous=(selected-timedelta(days=7 if period == "week" else 1)).isoformat(),
        following=(selected+timedelta(days=7 if period == "week" else 1)).isoformat())


def _form_values(event=None):
    if event is None:
        return dict(day=request.args.get("date", today().isoformat()), time="09:00", title="", note="",
                    duration_minutes="60", status="scheduled", revision="", person_id="", exam_link="")
    return dict(day=event["day"].isoformat(), time=event["time"].strftime("%H:%M"),
        title=event["title"], note=event["note"], duration_minutes=str(event["duration_minutes"] or ""),
        status=event["status"], revision=str(event["revision"]), person_id=str(event["person_id"] or ""),
        exam_link=(f'tci:{event["report_id"]}' if event["report_id"] else
                   f'khtp:{event["job_id"]}' if event["job_id"] else ""))


def _posted_form(event=None, *, legacy=False):
    values = {key: request.form.get(key, "") for key in _form_values(event)}
    if "exam_link" not in request.form:
        values["exam_link"] = (f'tci:{request.form["report_id"]}' if request.form.get("report_id") else
                               f'khtp:{request.form["job_id"]}' if request.form.get("job_id") else "")
    if legacy:
        if "status" not in request.form:
            values["status"] = event["status"] if event else "scheduled"
        if "duration_minutes" not in request.form and event is None:
            values["duration_minutes"] = "60"
    return values


def _exam_choices(connection):
    from khtp_web import jobs
    values = []
    for kind, table in (("tci", reports), ("khtp", jobs)):
        if not enabled(kind):
            continue
        rows = connection.execute(select(table.c.id, table.c.name, table.c.reference, table.c.exam_date,
                                         table.c.owner_id).where(exam_readable(table, kind))
                                  .order_by(table.c.exam_date.desc(), table.c.id.desc())).mappings()
        values.extend(dict(row, kind=kind, value=f'{kind}:{row["id"]}') for row in rows)
    return values


def _render_form(form, event=None, *, errors=None, status=200, unavailable=False):
    person, choices = None, []
    if not unavailable:
        try:
            with get_engine().connect() as connection:
                choices = _exam_choices(connection)
                try:
                    person_id = int(form.get("person_id", ""))
                except (ValueError, TypeError, OverflowError):
                    person_id = None
                if person_id and 0 < person_id <= 2147483647:
                    person = _person(connection, person_id, g.user["id"])
        except SQLAlchemyError:
            unavailable = True
    return render_template("scheduler/form.html", active="schedule", form=form, event=event,
        errors=errors or {}, account_csrf=csrf_token(), person=person, choices=choices,
        statuses=STATUS_LABELS, unavailable=unavailable), status


def _parse(form):
    errors, values = {}, {}
    values["title"] = form["title"].strip()
    values["note"] = form["note"].strip()
    if not values["title"] or len(values["title"]) > 120:
        errors["title"] = "일정 이름을 1~120자로 입력해 주세요."
    if len(values["note"]) > 5000:
        errors["note"] = "일정 내용은 5000자 이내로 입력해 주세요."
    try:
        values["day"] = date.fromisoformat(form["day"])
        if not date(1900, 1, 1) <= values["day"] < date(9999, 12, 24):
            raise ValueError
    except ValueError:
        errors["day"] = "일정 날짜를 확인해 주세요."
    try:
        values["time"] = datetime.strptime(form["time"], "%H:%M").time()
    except ValueError:
        errors["time"] = "시작 시간을 확인해 주세요."
    try:
        values["duration_minutes"] = int(form["duration_minutes"])
        if not 5 <= values["duration_minutes"] <= 1440:
            raise ValueError
    except (ValueError, OverflowError):
        errors["duration_minutes"] = "소요 시간을 5~1440분으로 입력해 주세요."
    values["status"] = form["status"]
    if values["status"] not in STATUS_LABELS:
        errors["status"] = "일정 상태를 선택해 주세요."
    return values, errors


def _save(event_id=None, *, legacy=False):
    check_csrf()
    # Capture the submitted draft before the first database read. Recovery must
    # not need another query or imply that the submitted values were saved.
    form = _posted_form()
    event = None
    if event_id is not None:
        try:
            with get_engine().connect() as connection:
                event = get_event(connection, event_id, write=True)
        except SQLAlchemyError as error:
            current_app.logger.warning("Schedule initial read failed: %s", type(error).__name__)
            return render_template("scheduler/form_recovery.html", active="schedule",
                form=form, submitted=request.form, event_id=event_id,
                action=request.full_path.removesuffix("?"), account_csrf=csrf_token()), 503
    form = _posted_form(event, legacy=legacy)
    values, errors = _parse(form)
    if errors:
        return _render_form(form, event, errors=errors, status=422)
    try:
        with get_engine().begin() as connection:
            # Shared ordering with person merge: owner user -> person -> records.
            connection.scalar(select(users.c.id).where(users.c.id == g.user["id"]).with_for_update())
            from .people import resolve_person
            try:
                values["person_id"] = resolve_person(connection, g.user["id"], form["person_id"],
                    "", "", values["day"], create=False)
            except ValueError:
                errors["person_id"] = "등록된 대상자를 다시 선택해 주세요."
            values["report_id"], values["job_id"] = None, None
            current = None
            if form["exam_link"] == KEEP_LINK:
                # This token can only retain IDs already saved on an owned
                # appointment. It never grants access to the source record.
                current = get_event(connection, event_id, write=True, lock=True) if event_id is not None else None
                if not current or not (current["report_id"] or current["job_id"]):
                    errors["exam_link"] = "유지할 검사 연결이 없습니다. 연결할 검사를 다시 선택해 주세요."
                else:
                    previous_person = _person(connection, current["person_id"], g.user["id"])
                    previous_id = previous_person["id"] if previous_person else None
                    if values.get("person_id") != previous_id:
                        errors["person_id"] = "기존 검사 연결을 유지할 때 대상자를 바꿀 수 없습니다. 검사 연결을 해제하거나 다시 선택해 주세요."
                    values["report_id"], values["job_id"] = current["report_id"], current["job_id"]
            elif form["exam_link"]:
                kind, separator, identifier = form["exam_link"].partition(":")
                try:
                    if not separator or kind not in {"tci", "khtp"} or not enabled(kind):
                        raise NotFound()
                    linked = get_exam(connection, kind, identifier, lock=True)
                    values["report_id" if kind == "tci" else "job_id"] = linked["id"]
                    if linked["owner_id"] == g.user["id"] and linked.get("person_id"):
                        linked_person = resolve_person(connection, g.user["id"], linked["person_id"],
                                                       "", "", values["day"], create=False)
                        if values.get("person_id") is None:
                            values["person_id"] = linked_person
                        elif values["person_id"] != linked_person:
                            errors["person_id"] = "선택한 대상자와 연결 검사의 대상자가 다릅니다."
                except (NotFound, ValueError):
                    errors["exam_link"] = "연결할 검사를 다시 선택해 주세요. 현재 열람 가능한 검사만 연결할 수 있습니다."
            status = 422
            if event_id is not None and current is None:
                current = get_event(connection, event_id, write=True, lock=True)
            if current:
                try:
                    expected_revision = int(form["revision"])
                except (ValueError, OverflowError):
                    expected_revision = None
                if expected_revision != current["revision"]:
                    errors["conflict"] = "다른 화면에서 일정이 변경되었습니다. 입력은 유지됩니다. 최신 일정을 확인한 뒤 다시 작성해 주세요."
                    status = 409
            if not errors:
                values["updated_at"] = utc_now()
                if current:
                    changed = connection.execute(appointments.update().where(
                        appointments.c.id == event_id, appointments.c.owner_id == g.user["id"],
                        appointments.c.revision == expected_revision).values(**values, revision=expected_revision + 1))
                    if changed.rowcount != 1:
                        errors["conflict"] = "다른 화면에서 일정이 변경되었습니다. 입력은 유지됩니다. 최신 일정을 확인해 주세요."
                        status = 409
                else:
                    event_id = connection.execute(appointments.insert().values(
                        **values, owner_id=g.user["id"], revision=1)).inserted_primary_key[0]
                conflicts = _overlaps(connection, dict(values, id=event_id), g.user["id"]) if not errors else []
        if errors:
            return _render_form(form, event, errors=errors, status=status)
    except SQLAlchemyError as error:
        current_app.logger.warning("Schedule save failed: %s", type(error).__name__)
        return _render_form(form, event, errors={"save": "저장하지 못했습니다. 입력은 유지됩니다. 다시 시도해 주세요."},
                            status=503, unavailable=True)
    flash("일정을 저장했습니다.", "success")
    if conflicts:
        flash(f"내 일정 {len(conflicts)}건과 시간이 겹칩니다. 일정 내용을 확인해 주세요.", "warning")
    if legacy:
        return redirect(url_for("web.portal", date=values["day"].isoformat()), code=302)
    return redirect(url_for("scheduler.detail", event_id=event_id), code=303)


@bp.route("/schedule/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        return _save()
    form = _form_values()
    if request.args.get("kind") or request.args.get("exam_id"):
        kind = request.args.get("kind")
        if kind not in {"tci", "khtp"} or not enabled(kind):
            abort(404)
        with get_engine().connect() as connection:
            exam = get_exam(connection, kind, request.args.get("exam_id"))
            form["exam_link"] = f'{kind}:{exam["id"]}'
            # Identity remains a permission-checked link, not a copied title that
            # would survive revocation or reveal an exam through schedule sharing.
            form["title"] = f'{"TCI" if kind == "tci" else "K-HTP"} 결과 상담'
            if exam["owner_id"] == g.user["id"] and exam.get("person_id"):
                person = _person(connection, exam["person_id"], g.user["id"])
                form["person_id"] = str(person["id"]) if person else ""
    elif request.args.get("person_id"):
        try:
            identifier = int(request.args["person_id"])
        except (ValueError, OverflowError):
            abort(404)
        with get_engine().connect() as connection:
            person = _person(connection, identifier, g.user["id"]) if 0 < identifier <= 2147483647 else None
            if person is None:
                abort(404)
            form["person_id"] = str(person["id"])
            form["title"] = "상담"
    return _render_form(form)


@bp.route("/schedule/<int:event_id>/edit", methods=["GET", "POST"])
@login_required
def edit(event_id):
    if request.method == "POST":
        return _save(event_id)
    with get_engine().connect() as connection:
        event = get_event(connection, event_id, write=True)
        form = _form_values(event)
        # A former grant does not permit redisplaying the source's metadata.
        linked, needs_check = _linked_exam(connection, event, g.user["id"])
        if form["exam_link"] and linked is None:
            form["exam_link"] = KEEP_LINK
        event["connection_needs_check"] = needs_check
    return _render_form(form, event)


def save_legacy(event_id=None):
    return _save(event_id, legacy=True)


def _visible_comments(event):
    private = and_(appointment_comments.c.recipient_id.is_(None),
                   appointment_comments.c.author_id == g.user["id"])
    shared = (appointment_comments.c.recipient_id.is_not(None) if event["owner_id"] == g.user["id"]
              else appointment_comments.c.recipient_id == g.user["id"])
    return or_(private, shared)


def _detail_data(connection, event):
    is_owner = event["owner_id"] == g.user["id"]
    grants = [dict(row) for row in connection.execute(select(appointment_shares, users.c.username)
        .join(users, users.c.id == appointment_shares.c.recipient_id)
        .where(appointment_shares.c.appointment_id == event["id"])
        .order_by(appointment_shares.c.created_at, appointment_shares.c.id)).mappings()]
    active_recipients = {row["recipient_id"] for row in grants}
    author, recipient = users.alias("comment_author"), users.alias("comment_recipient")
    comments = []
    for row in connection.execute(select(appointment_comments, author.c.username.label("author_username"),
        recipient.c.username.label("recipient_username")).join(author, author.c.id == appointment_comments.c.author_id)
        .outerjoin(recipient, recipient.c.id == appointment_comments.c.recipient_id).where(
            appointment_comments.c.appointment_id == event["id"], _visible_comments(event))
        .order_by(appointment_comments.c.created_at, appointment_comments.c.id)).mappings():
        comments.append(dict(row, is_own=row["author_id"] == g.user["id"],
            thread_active=row["recipient_id"] is None or row["recipient_id"] in active_recipients))
    return dict(event=_decorate(connection, event, g.user["id"]), is_owner=is_owner,
        owner_username=connection.scalar(select(users.c.username).where(users.c.id == event["owner_id"])),
        shares=grants if is_owner else [], comments=comments,
        overlaps=_overlaps(connection, event, g.user["id"]) if is_owner else [],
        account_csrf=csrf_token(), error=None, draft_body="", draft_audience="private", draft_recipient_id="",
        draft_username="", editing_comment=None, comment_body="")


def _render_detail(event_id, *, error=None, status=200, editing_comment=None):
    with get_engine().connect() as connection:
        event = get_event(connection, event_id)
        data = _detail_data(connection, event)
    if error:
        data.update(error=error, draft_body=request.form.get("body", "") if editing_comment is None else "",
            draft_audience=request.form.get("audience", "private"),
            draft_recipient_id=request.form.get("recipient_id", ""), draft_username=request.form.get("username", ""),
            editing_comment=editing_comment, comment_body=request.form.get("body", ""))
    return render_template("scheduler/detail.html", active="schedule", **data), status


@bp.get("/schedule/<int:event_id>")
@login_required
def detail(event_id):
    return _render_detail(event_id)


def _back(event_id):
    return redirect(url_for("scheduler.detail", event_id=event_id, _anchor="schedule-notes"), code=303)


def _delete(event_id, *, legacy=False):
    check_csrf()
    error = None
    with get_engine().begin() as connection:
        event = get_event(connection, event_id, write=True, lock=True)
        try:
            revision = int(request.form.get("revision", ""))
        except (ValueError, OverflowError):
            revision = None
        if revision != event["revision"]:
            error = "일정이 변경되었거나 삭제 확인 정보가 없습니다. 최신 내용을 확인한 뒤 삭제해 주세요."
        else:
            connection.execute(appointment_comments.delete().where(appointment_comments.c.appointment_id == event_id))
            connection.execute(appointment_shares.delete().where(appointment_shares.c.appointment_id == event_id))
            connection.execute(appointments.delete().where(appointments.c.id == event_id,
                appointments.c.owner_id == g.user["id"], appointments.c.revision == revision))
    if error:
        return _render_detail(event_id, error=error, status=409)
    flash("일정과 해당 일정의 메모·댓글을 삭제했습니다.", "success")
    destination = "web.portal" if legacy else "scheduler.index"
    return redirect(url_for(destination, date=event["day"].isoformat()), code=302 if legacy else 303)


@bp.post("/schedule/<int:event_id>/delete")
@login_required
def delete(event_id):
    return _delete(event_id)


def delete_legacy(event_id):
    return _delete(event_id, legacy=True)


@bp.post("/schedule/<int:event_id>/shares")
@login_required
def share(event_id):
    check_csrf()
    error = None
    with get_engine().begin() as connection:
        get_event(connection, event_id, write=True, lock=True)
        username = request.form.get("username", "").strip()
        recipient = connection.execute(select(users.c.id, users.c.is_active).where(
            users.c.username == username)).mappings().first() if username else None
        if recipient is None or not recipient["is_active"]:
            error = "공유할 계정의 아이디를 정확히 입력해 주세요."
        elif recipient["id"] == g.user["id"]:
            error = "본인 계정에는 공유할 필요가 없습니다."
        elif _grant(connection, event_id, recipient["id"], lock=True) is None:
            try:
                with connection.begin_nested():
                    connection.execute(appointment_shares.insert().values(
                        appointment_id=event_id, recipient_id=recipient["id"]))
            except IntegrityError:
                if _grant(connection, event_id, recipient["id"]) is None:
                    raise
    if error:
        return _render_detail(event_id, error=error, status=422)
    flash("일정을 읽기 전용으로 공유했습니다. 연결 검사에는 별도 공유가 필요합니다.", "success")
    return _back(event_id)


@bp.post("/schedule/<int:event_id>/shares/<int:share_id>/revoke")
@login_required
def revoke(event_id, share_id):
    check_csrf()
    with get_engine().begin() as connection:
        get_event(connection, event_id, write=True, lock=True)
        grant = connection.execute(select(appointment_shares).where(
            appointment_shares.c.id == share_id, appointment_shares.c.appointment_id == event_id)
            .with_for_update()).mappings().first()
        if grant is None:
            abort(404)
        connection.execute(appointment_shares.delete().where(appointment_shares.c.id == share_id))
    flash("일정 공유를 회수했습니다. 기존 대화는 소유자 기록으로 보존됩니다.", "success")
    return _back(event_id)


def _body():
    value = request.form.get("body", "").strip()
    return value if 1 <= len(value) <= 5000 else None


@bp.post("/schedule/<int:event_id>/comments")
@login_required
def comment(event_id):
    check_csrf()
    error, recipient_id = None, None
    with get_engine().begin() as connection:
        event = get_event(connection, event_id, lock=True)
        body, audience = _body(), request.form.get("audience", "")
        if body is None:
            error = "메모와 댓글은 1~5000자로 입력해 주세요."
        elif audience not in {"private", "shared"}:
            error = "공개 범위를 선택해 주세요."
        elif audience == "shared":
            if event["owner_id"] == g.user["id"]:
                try:
                    recipient_id = int(request.form.get("recipient_id", ""))
                    if not 0 < recipient_id <= 2147483647:
                        recipient_id = None
                except (ValueError, OverflowError):
                    recipient_id = None
            else:
                recipient_id = g.user["id"]
            if recipient_id is None or _grant(connection, event_id, recipient_id, lock=True) is None:
                error = "현재 공유 중인 대화 상대를 선택해 주세요."
        if error is None:
            stamp = utc_now()
            connection.execute(appointment_comments.insert().values(appointment_id=event_id,
                author_id=g.user["id"], recipient_id=recipient_id, body=body, created_at=stamp, updated_at=stamp))
    if error:
        return _render_detail(event_id, error=error, status=422)
    flash("메모를 저장했습니다." if audience == "private" else "공유 댓글을 남겼습니다.", "success")
    return _back(event_id)


def _own_comment(connection, event, comment_id):
    row = connection.execute(select(appointment_comments).where(appointment_comments.c.id == comment_id,
        appointment_comments.c.appointment_id == event["id"], appointment_comments.c.author_id == g.user["id"],
        _visible_comments(event)).with_for_update()).mappings().first()
    if row is None:
        abort(404)
    return row


@bp.post("/schedule/<int:event_id>/comments/<int:comment_id>/edit")
@login_required
def edit_comment(event_id, comment_id):
    check_csrf()
    error = None
    with get_engine().begin() as connection:
        event = get_event(connection, event_id, lock=True)
        _own_comment(connection, event, comment_id)
        body = _body()
        if body is None:
            error = "메모와 댓글은 1~5000자로 입력해 주세요."
        else:
            connection.execute(appointment_comments.update().where(appointment_comments.c.id == comment_id)
                               .values(body=body, updated_at=utc_now()))
    if error:
        return _render_detail(event_id, error=error, status=422, editing_comment=comment_id)
    flash("작성한 메모·댓글을 수정했습니다.", "success")
    return _back(event_id)


@bp.post("/schedule/<int:event_id>/comments/<int:comment_id>/delete")
@login_required
def delete_comment(event_id, comment_id):
    check_csrf()
    with get_engine().begin() as connection:
        event = get_event(connection, event_id, lock=True)
        _own_comment(connection, event, comment_id)
        connection.execute(appointment_comments.delete().where(appointment_comments.c.id == comment_id))
    flash("작성한 메모·댓글을 삭제했습니다.", "success")
    return _back(event_id)


def init_app(app):
    if bp.name not in app.blueprints:
        app.register_blueprint(bp)
