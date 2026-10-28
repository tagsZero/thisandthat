from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import String, and_, cast, func, literal, or_, select, text, union_all
from sqlalchemy.exc import SQLAlchemyError

from .auth import login_required
from .composition import initial, material_status
from .library import SECTIONS
from .db import appointments, get_engine, reports, users, utc_now
from .permissions import check_csrf, csrf_token, get_exam, owner_condition, readable_condition
from .account_schema import exam_shares
from .exam_history import load_history, reference_key
from .scores import DEFAULT_SETTINGS, SCALES, SUBSCALES, parse_scores, parse_settings, report_types

bp = Blueprint("web", __name__)


@bp.app_context_processor
def score_form_metadata():
    return {"subscales": SUBSCALES, "composition_sections": SECTIONS}


def today():
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def find_report(report_id):
    """Original editor routes require ownership; grants use the common read view."""
    with get_engine().connect() as connection:
        return get_exam(connection, "tci", report_id, write=True)


@bp.get("/")
def index():
    return redirect(url_for("web.portal" if g.user else "auth.login"))


@bp.get("/dashboard")
@login_required
def portal():
    from khtp_web import jobs

    period = "week" if request.args.get("period") == "week" else "today"
    current_day = today()
    start = current_day - timedelta(days=current_day.weekday()) if period == "week" else current_day
    end = start + timedelta(days=7 if period == "week" else 1)
    with get_engine().connect() as connection:
        joined = appointments.outerjoin(reports, and_(appointments.c.report_id == reports.c.id,
                                                     readable_condition(reports, "tci")))
        rows = connection.execute(select(appointments, reports.c.id.label("visible_report_id"),
            reports.c.name.label("report_name"), reports.c.reference.label("report_reference"))
            .select_from(joined).where(owner_condition(appointments), appointments.c.day >= start,
                                      appointments.c.day < end)
            .order_by(appointments.c.day, appointments.c.time, appointments.c.id)).mappings().all()
        events = [dict(row) for row in rows]
        for event in events:
            if event.pop("visible_report_id") is None:
                event["report_id"] = None
        choices = connection.execute(select(reports.c.id, reports.c.name, reports.c.reference, reports.c.exam_date)
            .where(readable_condition(reports, "tci")).order_by(reports.c.updated_at.desc(), reports.c.id.desc())).mappings().all()
        editing = None
        editing_id = request.args.get("edit", type=int)
        if editing_id:
            editing = connection.execute(select(appointments).where(appointments.c.id == editing_id,
                                           owner_condition(appointments))).mappings().first()
            if editing is None:
                abort(404)
            editing = dict(editing)
            if editing["report_id"] is not None and not connection.scalar(select(reports.c.id).where(
                reports.c.id == editing["report_id"], readable_condition(reports, "tci"))):
                editing["report_id"] = None
        def shared_summary(table, kind, stamp, key):
            return select(cast(table.c.id, String).label("id"), literal(kind).label("kind"), table.c.name,
                          table.c.reference, table.c.exam_date, users.c.username.label("owner_username"),
                          stamp.label("updated_at")).select_from(table.join(users, users.c.id == table.c.owner_id)
                          .join(exam_shares, key == table.c.id)).where(
                          exam_shares.c.recipient_id == g.user["id"], table.c.owner_id != g.user["id"])
        combined = union_all(shared_summary(reports, "tci", reports.c.updated_at, exam_shares.c.report_id),
                             shared_summary(jobs, "khtp", jobs.c.last_used, exam_shares.c.job_id)).subquery()
        shared_records = connection.execute(select(combined).order_by(combined.c.updated_at.desc(),
                                                  combined.c.kind, combined.c.id)).mappings().all()
    return render_template("portal.html", active="portal", today=current_day, period=period,
                           events=events, editing=editing, choices=choices, shared_records=shared_records,
                           account_csrf=csrf_token())


@bp.get("/tci")
@login_required
def dashboard():
    query = request.args.get("q", "").strip()
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    period = "week" if request.args.get("period") == "week" else "today"
    criteria = [readable_condition(reports, "tci")]
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        match = f"%{escaped}%"
        choices = [reports.c.name.ilike(match, escape="\\"), reports.c.reference.ilike(match, escape="\\")]
        try:
            choices.append(reports.c.exam_date == date.fromisoformat(query.replace(".", "-").replace("/", "-")))
        except ValueError:
            pass
        criteria.append(or_(*choices))
    with get_engine().connect() as connection:
        total = connection.scalar(select(func.count()).select_from(reports).where(readable_condition(reports, "tci")))
        matched = connection.scalar(select(func.count()).select_from(reports).where(*criteria))
        pages = max(1, (matched + 9) // 10)
        page = min(page, pages)
        records = [dict(row) for row in connection.execute(
            select(reports, users.c.username.label("owner_username")).join(users, users.c.id == reports.c.owner_id)
            .where(*criteria).order_by(reports.c.updated_at.desc(), reports.c.id.desc())
            .limit(10).offset((page - 1) * 10)
        ).mappings()]
    for record in records:
        record['is_owner'] = record['owner_id'] == g.user['id']
        record['has_history_reference'] = bool(reference_key(record['reference']))
        record["types"] = report_types(record["scores"], record["settings"])
        record["composition_view"] = initial(record)
        record['progress'] = dict(t_count=sum(v is not None for v in record['types']['grades'].values()),
            blocks=sum(len(s['blocks']) for s in record['composition_view']['sections'].values()),
            opinions=sum(bool(s['opinion']) for s in record['composition_view']['sections'].values()))
        with get_engine().connect() as connection:
            record["block_status"] = material_status(connection, record["composition_view"], record)
    history = load_history('TCI', 'web.dashboard', dict(q=query, page=page, period=period))
    return render_template("tci_dashboard.html", active="tci", records=records, total=total, history=history,
                           matched=matched, query=query, page=page, pages=pages, period=period, scales=SCALES)


@bp.route("/tci/reports/new", methods=["GET", "POST"])
@bp.route("/tci/reports/<int:report_id>/edit", methods=["GET", "POST"])
@login_required
def edit_report(report_id=None):
    report = find_report(report_id) if report_id is not None else {
        "name": "", "reference": "", "exam_date": today(), "scores": {},
        "settings": dict(DEFAULT_SETTINGS), "body": "",
    }
    errors = {}
    if request.method == "GET" and request.args.get("compare") == "1":
        report["settings"], errors = parse_settings(request.args, report["settings"])
    if request.method == "POST":
        report["name"] = request.form.get("name", "").strip()
        report["reference"] = request.form.get("reference", "").strip()
        report["scores"], errors = parse_scores(request.form, report["scores"])
        if not report["name"] and not report["reference"]:
            errors["name"] = "이름 또는 관리번호 중 하나를 입력해 주세요."
        if len(report["name"]) > 100 or len(report["reference"]) > 100:
            errors["name"] = "이름과 관리번호는 각각 100자 이내로 입력해 주세요."
        date_value = request.form.get("exam_date", "")
        try:
            report["exam_date"] = date.fromisoformat(date_value) if date_value else None
        except ValueError:
            errors["exam_date"] = "검사일을 확인해 주세요."
        report["settings"], setting_errors = parse_settings(request.form, report["settings"])
        errors.update(setting_errors)
        if not errors and request.form.get("preview_only") != "1":
            new_entry = report_id is None and request.form.get('destination') == 'candidates'
            draft = None
            values = {key: report[key] for key in ("name", "reference", "exam_date", "scores", "settings")}
            values["updated_at"] = utc_now()
            try:
                with get_engine().begin() as connection:
                    if report_id is None:
                        report_id = connection.execute(reports.insert().values(**values, owner_id=g.user["id"], body="")).inserted_primary_key[0]
                    else:
                        connection.execute(reports.update().where(reports.c.id == report_id, owner_condition(reports)).values(**values))
                    if new_entry:
                        from .type_report import new_draft
                        saved_entry = dict(connection.execute(select(reports).where(reports.c.id == report_id, owner_condition(reports))).mappings().one())
                        draft = new_draft(connection, saved_entry, new_score_entry=True)['report']
            except SQLAlchemyError:
                errors['save'] = '저장하지 못했습니다. 입력은 유지됩니다. 다시 시도해 주세요.'
            if not errors:
                destination = url_for('candidates.index', report_id=report_id) if (
                    request.form.get('destination') == 'candidates' or (
                        request.args.get('return_to') == 'candidates' and request.form.get('destination') != 'dashboard')) else url_for('web.dashboard')
                if request.accept_mimetypes.best == 'application/json':
                    from .type_workspace import entry_ticket
                    return dict(save_state='saved', destination=destination,
                                draft_ticket=entry_ticket(draft, saved_entry) if draft is not None else None,
                                edit_url=url_for('web.edit_report', report_id=report_id, return_to='candidates'))
                if draft is not None:
                    from .type_workspace import render_workspace
                    return render_workspace(draft, saved_entry)
                flash('검사 결과를 저장했습니다.', 'success')
                return redirect(destination)
        if errors and request.accept_mimetypes.best == 'application/json':
            return dict(errors=errors, save_state='failed' if 'save' in errors else 'not_saved'), 503 if 'save' in errors else 422
    report["types"] = report_types(report["scores"], report["settings"]) if not errors else None
    preset = "custom"
    if report["settings"]["low"] == "45" and report["settings"]["high"] in ("55", "56"):
        preset = "t" + report["settings"]["high"]
    return render_template("score_input.html", active="tci", report=report, errors=errors,
                           scales=SCALES, preset=preset,
                           additional_errors=any(key.startswith("SC_") or key in {
                               f"{code}_raw" for items in SUBSCALES.values() for code, _ in items
                           } for key in errors))


@bp.post("/tci/classification-preview")
@login_required
def classification_preview():
    scores, errors = parse_scores(request.form)
    settings, setting_errors = parse_settings(request.form)
    errors.update(setting_errors)
    if errors:
        return {"errors": errors}, 422
    report = {"scores": scores, "settings": settings, "types": report_types(scores, settings), "body": ""}
    return {"errors": {}, "grades": report["types"]["grades"], "html": render_template("score_summary.html", report=report, scales=SCALES)}


@bp.get("/tci/reports/<int:report_id>")
@login_required
def review_report(report_id):
    report = find_report(report_id)
    report["types"] = report_types(report["scores"], report["settings"])
    report["composition_view"] = initial(report)
    with get_engine().connect() as connection:
        report["block_status"] = material_status(connection, report["composition_view"], report)
    return render_template("report_review.html", active="tci", report=report, scales=SCALES)


@bp.post("/tci/appointments")
@bp.post("/tci/appointments/<int:event_id>")
@login_required
def save_appointment(event_id=None):
    check_csrf()
    try:
        day = date.fromisoformat(request.form.get("day", ""))
        event_time = datetime.strptime(request.form.get("time", ""), "%H:%M").time()
        title = request.form.get("title", "").strip()
        if not title or len(title) > 120:
            raise ValueError
        report_id = request.form.get("report_id", "")
        report_id = int(report_id) if report_id else None
        if report_id is not None:
            with get_engine().connect() as connection:
                get_exam(connection, "tci", report_id)
    except ValueError:
        flash("일정의 날짜·시간·제목을 확인해 주세요.", "error")
        return redirect(url_for("web.portal", period=request.form.get("period", "today")) + "#schedule")
    with get_engine().begin() as connection:
        if report_id is not None:
            get_exam(connection, "tci", report_id, lock=True)
        values = dict(day=day, time=event_time, title=title, note=request.form.get("note", "").strip(), report_id=report_id)
        if event_id is None:
            connection.execute(appointments.insert().values(**values, owner_id=g.user["id"]))
        else:
            result = connection.execute(appointments.update().where(appointments.c.id == event_id, owner_condition(appointments)).values(**values))
            if result.rowcount == 0:
                abort(404)
    flash("일정을 저장했습니다.", "success")
    return redirect(url_for("web.portal", period=request.form.get("period", "today")) + "#schedule")


@bp.post("/tci/appointments/<int:event_id>/delete")
@login_required
def delete_appointment(event_id):
    check_csrf()
    with get_engine().begin() as connection:
        if connection.execute(appointments.delete().where(appointments.c.id == event_id, owner_condition(appointments))).rowcount == 0:
            abort(404)
    flash("일정을 삭제했습니다.", "success")
    return redirect(url_for("web.portal", period=request.form.get("period", "today")) + "#schedule")


@bp.get("/health/db")
@login_required
def database_health():
    with get_engine().connect() as connection:
        database_name = connection.execute(text("SELECT current_database()")).scalar_one()
    return {"status": "ok", "database": database_name}
