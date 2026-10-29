from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError

from .auth import login_required
from .composition import initial, material_status
from .library import SECTIONS
from .db import get_engine, people, reports, users, utc_now
from .permissions import check_csrf, csrf_token, get_exam, owner_condition, readable_condition
from .exam_history import load_history, reference_key
from .scores import DEFAULT_SETTINGS, SCALES, SUBSCALES, parse_scores, parse_settings, report_types

bp = Blueprint("web", __name__)


def score_context(report):
    from datetime import timezone
    stamp = report.get('updated_at')
    if stamp is not None:
        stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
    return URLSafeSerializer(current_app.secret_key, salt='score-edit').dumps(
        {'id': report.get('id'), 'stamp': stamp.isoformat() if stamp else None})


class ScoreConflict(ValueError):
    pass


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
    from .admin import feature_enabled
    from .scheduler import summary
    editing_id = request.args.get('edit', type=int)
    if editing_id:
        from .scheduler import get_event
        with get_engine().connect() as connection:
            get_event(connection, editing_id, write=True)
        return redirect(url_for('scheduler.edit', event_id=editing_id))
    try:
        current_day = date.fromisoformat(request.args.get('date', ''))
    except ValueError:
        current_day = today()
    with get_engine().connect() as connection:
        events = summary(connection, g.user['id'], current_day) if feature_enabled('schedule') else []
    return render_template('portal.html', active='portal', today=current_day, events=events,
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
        code = query.lower().removeprefix('code:').strip()
        if code.isascii() and code.isdecimal() and len(code) <= 10 and int(code) <= 2147483647:
            choices.append(reports.c.person_id.in_(select(people.c.id).where(
                people.c.owner_id == g.user['id'], people.c.code == int(code))))
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
            select(reports, users.c.username.label("owner_username"), people.c.code.label('person_code'))
            .join(users, users.c.id == reports.c.owner_id).outerjoin(people,
                and_(people.c.id == reports.c.person_id, people.c.owner_id == g.user['id']))
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
    from .people import get_person, person_summary, resolve_person
    from .schedule_links import detach_mismatched_links, reassignment_notice
    report = find_report(report_id) if report_id is not None else {
        "name": "", "reference": "", "exam_date": today(), "scores": {},
        "settings": dict(DEFAULT_SETTINGS), "body": "",
    }
    errors = {}
    prior_person_id = report.get('person_id')
    status = 200
    context = score_context(report)
    if request.method == "GET" and request.args.get("compare") == "1":
        report["settings"], errors = parse_settings(request.args, report["settings"])
    if request.method == "POST":
        check_csrf()
        context = request.form.get('score_context', '')
        if report_id is not None:
            try:
                signer = URLSafeSerializer(current_app.secret_key, salt='score-edit')
                if signer.loads(context) != signer.loads(score_context(report)):
                    raise BadSignature('stale')
            except BadSignature:
                errors['conflict'] = '다른 화면에서 이 검사가 변경되었습니다. 입력을 보관하고 새 탭에서 최신 검사를 확인해 주세요.'
                status = 409
        report["name"] = request.form.get("name", "").strip()
        report["reference"] = request.form.get("reference", "").strip()
        report['person_id'] = request.form.get('person_id', report.get('person_id'))
        report["scores"], score_errors = parse_scores(request.form, report["scores"])
        errors.update(score_errors)
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
            detached_count = 0
            values = {key: report[key] for key in ("name", "reference", "exam_date", "scores", "settings")}
            values["updated_at"] = utc_now()
            try:
                with get_engine().begin() as connection:
                    values['person_id'] = resolve_person(connection, g.user['id'], report.get('person_id'),
                        report['name'], report['reference'], report['exam_date'] or today())
                    if report_id is None:
                        report_id = connection.execute(reports.insert().values(**values, owner_id=g.user["id"], body="")).inserted_primary_key[0]
                    else:
                        result = connection.execute(reports.update().where(reports.c.id == report_id,
                            owner_condition(reports), reports.c.updated_at == report['updated_at']).values(**values))
                        if result.rowcount != 1:
                            raise ScoreConflict('다른 화면에서 이 검사가 변경되었습니다. 입력을 보관하고 최신 검사를 확인해 주세요.')
                        if values['person_id'] != prior_person_id:
                            detached_count = detach_mismatched_links(connection, 'tci', report_id,
                                g.user['id'], values['person_id'])
                    saved_entry = dict(connection.execute(select(reports).where(reports.c.id == report_id,
                        owner_condition(reports))).mappings().one())
                    saved_person = person_summary(get_person(connection, g.user['id'], values['person_id']))
                    if new_entry:
                        from .type_report import new_draft
                        draft = new_draft(connection, saved_entry, new_score_entry=True)['report']
            except ScoreConflict as exc:
                errors['conflict'] = str(exc)
                status = 409
            except ValueError as exc:
                errors['person_id'] = str(exc)
            except SQLAlchemyError:
                errors['save'] = '저장하지 못했습니다. 입력은 유지됩니다. 다시 시도해 주세요.'
            if not errors:
                notice = reassignment_notice(detached_count)
                if notice:
                    flash(notice, 'warning')
                destination = url_for('candidates.index', report_id=report_id) if (
                    request.form.get('destination') == 'candidates' or (
                        request.args.get('return_to') == 'candidates' and request.form.get('destination') != 'dashboard')) else url_for('web.dashboard')
                if request.accept_mimetypes.best == 'application/json':
                    from .type_workspace import entry_ticket
                    return dict(save_state='saved', destination=destination,
                                notice=notice, detached_schedules=detached_count,
                                person=saved_person, score_context=score_context(saved_entry),
                                draft_ticket=entry_ticket(draft, saved_entry) if draft is not None else None,
                                edit_url=url_for('web.edit_report', report_id=report_id, return_to='candidates'))
                if draft is not None:
                    from .type_workspace import render_workspace
                    return render_workspace(draft, saved_entry)
                flash('검사 결과를 저장했습니다.', 'success')
                return redirect(destination)
        if errors and request.accept_mimetypes.best == 'application/json':
            return dict(errors=errors, save_state='failed' if 'save' in errors else 'not_saved'), 503 if 'save' in errors else (409 if 'conflict' in errors else 422)
    person = None
    if report.get('person_id'):
        try:
            with get_engine().connect() as connection:
                person = person_summary(get_person(connection, g.user['id'], report['person_id']))
        except ValueError:
            errors['person_id'] = '선택한 대상자를 확인해 주세요.'
    report["types"] = report_types(report["scores"], report["settings"]) if not errors else None
    preset = "custom"
    if report["settings"]["low"] == "45" and report["settings"]["high"] in ("55", "56"):
        preset = "t" + report["settings"]["high"]
    return render_template("score_input.html", active="tci", report=report, errors=errors,
                           scales=SCALES, preset=preset, person=person, score_context=context,
                           additional_errors=any(key.startswith("SC_") or key in {
                               f"{code}_raw" for items in SUBSCALES.values() for code, _ in items
                           } for key in errors)), status


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
    from .scheduler import save_legacy
    return save_legacy(event_id)


@bp.post("/tci/appointments/<int:event_id>/delete")
@login_required
def delete_appointment(event_id):
    from .scheduler import delete_legacy
    return delete_legacy(event_id)


@bp.get("/health/db")
@login_required
def database_health():
    with get_engine().connect() as connection:
        database_name = connection.execute(text("SELECT current_database()")).scalar_one()
    return {"status": "ok", "database": database_name}
