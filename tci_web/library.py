"""자료 관리와 조건 계약. 후보 평가는 후속 작업에서 구현한다."""
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import click
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import or_, select

from .auth import login_required
from .db import get_engine, interpretations, sources
from .scores import SCALES, SUBSCALES
from .selection import TOPICS, RELATIONS, validate_selection

bp = Blueprint('library', __name__, url_prefix='/tci/library')
EDITIONS = {'adult': '성인 TCI-RS', 'youth': '청소년 JTCI', 'child': '아동/유아',
            'common': '공통 (근거 확인)', 'unknown': '미확인'}
SECTIONS = {key: label for key, label in (
    ('innate', '타고난 특성'), ('relationships', '대인관계 특성'), ('acceptance', '기질 수용하기'),
    ('outlook', '삶을 바라보는 방식'), ('growth', '성격 가꾸기'), ('subscales', '하위척도 상세'),
    ('combined', '기질/성격 연계'), ('summary', '종합 소견'))}
STATUS = {'match': '조건 확인', 'reference': '참고용', 'unverified': '조건 미확인'}
FAMILIES = {'temperament': '기질 NS-HA-RD', 'character': '성격 SD-CO-ST'}
MAIN = {code: f'{code} {label}' for code, label, _ in SCALES}
SCALE_OPTIONS = {**MAIN, 'SC': 'SC 자율성 및 연대감',
                 **{code: f'{code} {label}' for rows in SUBSCALES.values() for code, label in rows}}
METRICS = {'raw': '입력 원점수', 'original_t': '원본 T점수',
           'applied_t': '분류 적용 T점수', 'percentile': '백분위'}
# SC에는 분류 적용 T가 없고 하위척도는 원점수만 있다.
ALLOWED_METRICS = {code: tuple(METRICS) if code in MAIN else
                   ('raw', 'original_t', 'percentile') if code == 'SC' else ('raw',)
                   for code in SCALE_OPTIONS}
NUMERIC_FIELDS = ('scale', 'metric', 'lower', 'upper', 'lower_inclusive', 'upper_inclusive')


def context():
    return dict(editions=EDITIONS, sections=SECTIONS, statuses=STATUS, families=FAMILIES,
                main_scales=MAIN, scale_options=SCALE_OPTIONS, metrics=METRICS,
                allowed_metrics=ALLOWED_METRICS, topics=TOPICS, relations=RELATIONS)


def get_record(table, record_id):
    with get_engine().connect() as conn:
        row = conn.execute(select(table).where(table.c.id == record_id)).mappings().first()
    if row is None:
        abort(404)
    return dict(row)


def form_text(form, key):
    return form.get(key, '').strip()


def parse_source(form):
    values = {key: form_text(form, key) for key in (
        'title', 'author', 'perspective', 'filename', 'alternate_filename', 'edition', 'scope')}
    values['active'] = form.get('active') == '1'
    errors = {}
    if form.get('active') not in ('0', '1'):
        errors['active'] = '사용 여부를 선택해 주세요.'
    for key in ('title', 'filename', 'scope'):
        if not values[key]:
            errors[key] = '필수 내용을 입력해 주세요.'
    if values['edition'] not in EDITIONS:
        errors['edition'] = '검사판을 선택해 주세요.'
    return values, errors


def numeric_rows(form):
    columns = [form.getlist('numeric_' + key) for key in NUMERIC_FIELDS]
    if len({len(col) for col in columns}) > 1:
        raise ValueError('수치 조건의 입력 구성이 올바르지 않습니다.')
    return [dict(zip(NUMERIC_FIELDS, row)) for row in zip(*columns)]


def validate_numeric(row):
    scale, metric = row['scale'], row['metric']
    if scale not in ALLOWED_METRICS or metric not in ALLOWED_METRICS[scale]:
        raise ValueError('해당 척도에서 사용할 수 없는 점수 종류입니다.')
    result = {'kind': 'numeric', 'scale': scale, 'metric': metric}
    bounds = []
    for key in ('lower', 'upper'):
        raw = row[key].strip()
        inclusive = row[key + '_inclusive']
        if inclusive not in ('0', '1'):
            raise ValueError('경계 포함 여부를 선택해 주세요.')
        value = None
        if raw:
            try:
                value = Decimal(raw)
                if not value.is_finite():
                    raise ValueError
                if metric == 'percentile' and not 0 <= value <= 100:
                    raise ValueError
                if metric == 'raw' and (value < 0 or value != value.to_integral_value()):
                    raise ValueError
            except (InvalidOperation, ValueError):
                raise ValueError('유한한 수치가 필요합니다. 백분위는 0~100, 원점수는 0 이상의 정수입니다.') from None
        bounds.append(value)
        result[key] = raw or None  # Decimal 정확도를 유지하는 문자열 / null
        result[key + '_inclusive'] = inclusive == '1'
    low, high = bounds
    if low is None and high is None:
        raise ValueError('하한 또는 상한을 입력해 주세요.')
    if low is not None and high is not None:
        if low > high or (low == high and not (result['lower_inclusive'] and result['upper_inclusive'])):
            raise ValueError('빈 구간입니다. 같은 경계는 양쪽 포함일 때만 허용합니다.')
    return result


def parse_item(form, source_ids):
    errors = {}
    if form.get('active') not in ('0', '1'):
        errors['active'] = '사용 여부를 선택해 주세요.'
    values = {key: form_text(form, key) for key in (
        'title', 'section', 'perspective', 'location', 'original', 'description', 'edition',
        'scope', 'original_criteria', 'group_key', 'conflict')}
    values['active'] = form.get('active') == '1'
    link = {key: form_text(form, 'selection_' + key) for key in ('topic', 'group', 'relation', 'basis')}
    values['selection'] = None
    if any(link.values()):
        try:
            values['selection'] = validate_selection(link)
        except ValueError as exc:
            errors['selection_topic'] = str(exc)
    for key in ('title', 'perspective', 'location', 'original', 'description', 'scope', 'original_criteria'):
        if not values[key]:
            errors[key] = '필수 내용을 입력해 주세요. 확인되지 않은 기준은 미확인이라고 적어 주세요.'
    for key, options in (('edition', EDITIONS), ('section', SECTIONS)):
        if values[key] not in options:
            errors[key] = '허용된 항목을 선택해 주세요.'
    try:
        values['source_id'] = int(form.get('source_id', ''))
        if values['source_id'] not in source_ids:
            raise ValueError
    except ValueError:
        errors['source_id'] = '등록된 소스를 선택해 주세요.'
    try:
        order = form_text(form, 'sort_order')
        if not re.fullmatch(r'-?\d+', order) or not -2147483648 <= int(order) <= 2147483647:
            raise ValueError
        values['sort_order'] = int(order)
    except ValueError:
        errors['sort_order'] = '정렬값은 32비트 정수로 입력해 주세요.'
    values['related_scales'] = form.getlist('related_scales')
    if any(code not in SCALE_OPTIONS for code in values['related_scales']):
        errors['related_scales'] = '등록된 척도만 연결할 수 있습니다.'
    family, code = form_text(form, 'related_family'), form_text(form, 'related_code')
    values['related_type'] = {'family': family, 'code': code} if family or code else None
    if (family or code) and (family not in FAMILIES or not re.fullmatch('[HML]{3}', code)):
        errors['related_code'] = '기질/성격 종류와 H·M·L 세 글자를 함께 입력해 주세요.'
    status = form.get('condition_status', '')
    clauses = []
    if status not in STATUS:
        errors['condition_status'] = '조건 확인 상태를 선택해 주세요.'
    if status == 'match' and values['edition'] == 'unknown':
        errors['condition_status'] = '검사판 미확인 자료는 참고용 또는 조건 미확인으로 저장해 주세요.'
    for family in FAMILIES:
        code = form_text(form, 'condition_' + family)
        if code:
            if not re.fullmatch('[HML]{3}', code):
                errors['condition_' + family] = 'H·M·L 세 글자로 입력해 주세요.'
            clauses.append({'kind': 'type', 'family': family, 'code': code})
    for scale in MAIN:
        grade = form_text(form, 'grade_' + scale)
        if grade:
            if grade not in ('H', 'M', 'L'):
                errors['grade_' + scale] = 'H·M·L 중에서 선택해 주세요.'
            clauses.append({'kind': 'grade', 'scale': scale, 'value': grade})
    # 위조된 SC/하위척도 HML 필드도 조용히 무시하지 않는다.
    if any(key.startswith('grade_') and key[6:] not in MAIN for key in form):
        errors['conditions'] = 'H/M/L 조건은 7개 주척도에만 사용할 수 있습니다.'
    try:
        rows = numeric_rows(form)
        for index, row in enumerate(rows):
            try:
                clauses.append(validate_numeric(row))
            except ValueError as exc:
                errors[f'numeric_{index}'] = str(exc)
    except ValueError as exc:
        errors['conditions'] = str(exc)
    values['conditions'] = {'version': 1, 'status': status, 'operator': 'and',
                            'missing': 'not_matched', 'clauses': clauses}
    return values, errors


def item_form(item):
    form = {key: '' if value is None else str(value) for key, value in item.items()
            if key not in ('conditions', 'related_scales', 'related_type', 'selection')}
    form.update({'selection_' + key: value for key, value in (item.get('selection') or {}).items()})
    form['active'] = '1' if item.get('active', True) else '0'
    form['sort_order'] = str(item.get('sort_order', 0))
    related = item.get('related_type') or {}
    form.update(related_family=related.get('family', ''), related_code=related.get('code', ''))
    condition = item.get('conditions') or {}
    form['condition_status'] = condition.get('status', 'unverified')
    rows = []
    for clause in condition.get('clauses', []):
        if clause['kind'] == 'type':
            form['condition_' + clause['family']] = clause['code']
        elif clause['kind'] == 'grade':
            form['grade_' + clause['scale']] = clause['value']
        else:
            rows.append({key: ('1' if clause[key] else '0') if key.endswith('_inclusive')
                         else clause[key] or '' for key in NUMERIC_FIELDS})
    return form, item.get('related_scales', []), rows


@bp.get('')
@login_required
def index():
    source_filter = request.args.get('source', '')
    state = request.args.get('state', 'all')
    query = request.args.get('q', '').strip()
    criteria = []
    if source_filter:
        try:
            criteria.append(interpretations.c.source_id == int(source_filter))
        except ValueError:
            abort(400)
    if state in ('active', 'inactive'):
        criteria.append(interpretations.c.active == (state == 'active'))
    if query:
        escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        criteria.append(or_(interpretations.c.title.ilike('%' + escaped + '%', escape='\\'),
                             interpretations.c.description.ilike('%' + escaped + '%', escape='\\')))
    with get_engine().connect() as conn:
        source_list = conn.execute(select(sources).order_by(sources.c.id)).mappings().all()
        items = conn.execute(select(interpretations, sources.c.title.label('source_title'),
                                    sources.c.active.label('source_active'))
                             .join(sources).where(*criteria)
                             .order_by(interpretations.c.sort_order, interpretations.c.id)).mappings().all()
    return render_template('library.html', active='tci', source_list=source_list, items=items,
                           source_filter=source_filter, state=state, query=query, **context())


@bp.route('/sources/new', methods=['GET', 'POST'])
@bp.route('/sources/<int:record_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_source(record_id=None):
    item = get_record(sources, record_id) if record_id else {}
    form = {**item, 'active': '1' if item.get('active', True) else '0'}
    errors = {}
    if request.method == 'POST':
        form = request.form
        values, errors = parse_source(form)
        if not errors:
            with get_engine().begin() as conn:
                if record_id:
                    conn.execute(sources.update().where(sources.c.id == record_id).values(**values))
                else:
                    record_id = conn.execute(sources.insert().values(**values)).inserted_primary_key[0]
            flash('소스를 저장했습니다.', 'success')
            return redirect(url_for('library.index', source=record_id))
    return render_template('library_source.html', active='tci', form=form, errors=errors, **context())


@bp.route('/items/new', methods=['GET', 'POST'])
@bp.route('/items/<int:record_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_item(record_id=None):
    item = get_record(interpretations, record_id) if record_id else {'source_id': request.args.get('source', '')}
    form, related_scales, rows = item_form(item)
    errors = {}
    with get_engine().connect() as conn:
        source_list = conn.execute(select(sources).order_by(sources.c.id)).mappings().all()
    if request.method == 'POST':
        form = request.form
        related_scales = form.getlist('related_scales')
        try:
            rows = numeric_rows(form)
        except ValueError:
            # 잘못 구성된 요청에서도 전달된 입력을 보여준다.
            rows = [{key: form.getlist('numeric_' + key)[i] if i < len(form.getlist('numeric_' + key)) else ''
                     for key in NUMERIC_FIELDS} for i in range(max(
                         [len(form.getlist('numeric_' + key)) for key in NUMERIC_FIELDS], default=0))]
        values, errors = parse_item(form, {s['id'] for s in source_list})
        if not errors:
            with get_engine().begin() as conn:
                if record_id:
                    conn.execute(interpretations.update().where(interpretations.c.id == record_id).values(**values))
                else:
                    conn.execute(interpretations.insert().values(**values))
            flash('해석 자료를 저장했습니다.', 'success')
            return redirect(url_for('library.index', source=values['source_id']))
    return render_template('library_item.html', active='tci', form=form, errors=errors,
                           related_scales=related_scales, numeric_rows=rows, source_list=source_list, **context())


def seed_library(connection, path=None):
    """안정적 키는 초기 데이터만 식별하며 기존 행은 수정하지 않는다."""
    path = path or Path(__file__).resolve().parent.parent / 'data' / 'interpretations.json'
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    added_sources = added_items = 0
    source_ids = {}
    for row in data['sources']:
        existing = connection.scalar(select(sources.c.id).where(sources.c.seed_key == row['seed_key']))
        if existing is None:
            existing = connection.execute(sources.insert().values(**row)).inserted_primary_key[0]
            added_sources += 1
        source_ids[row['seed_key']] = existing
    for raw in data['interpretations']:
        row = dict(raw)
        row['source_id'] = source_ids[row.pop('source_key')]
        if connection.scalar(select(interpretations.c.id).where(interpretations.c.seed_key == row['seed_key'])) is None:
            connection.execute(interpretations.insert().values(**row))
            added_items += 1
    return added_sources, added_items


def link_initial_selection(connection):
    """최초 문단이 그대로인 행의 비어 있는 연결만 명시적으로 보강한다."""
    path = Path(__file__).resolve().parent.parent / 'data' / 'interpretations.json'
    data = json.loads(path.read_text(encoding='utf8'))
    added = skipped = 0
    for expected in data['interpretations']:
        row = connection.execute(select(interpretations).where(
            interpretations.c.seed_key == expected['seed_key']).with_for_update()).mappings().first()
        if row is None or row['selection'] is not None:
            skipped += 1
            continue
        if any(row[key] != value for key, value in expected.items() if key not in ('selection', 'source_key')):
            skipped += 1
            continue
        source_id = connection.scalar(select(sources.c.id).where(sources.c.seed_key == expected['source_key']))
        if row['source_id'] != source_id:
            skipped += 1
            continue
        connection.execute(interpretations.update().where(interpretations.c.id == row['id']).values(
            selection=validate_selection(expected['selection'])))
        added += 1
    return added, skipped


def init_app(app):
    app.register_blueprint(bp)

    @app.cli.command('link-initial-selection')
    def link_command():
        """변경되지 않은 최초 8개 문단의 빈 연결만 보강한다. 기존 본문은 유지한다."""
        with get_engine().begin() as connection:
            added, skipped = link_initial_selection(connection)
        click.echo(f'초기 해석 연결 {added}개 추가 · 기존 연결/편집/미등록 {skipped}개 유지')

    @app.cli.command('seed-library')
    def seed_command():
        """제공 자료의 최초 소스와 실제 8개 문단을 명시적으로 등록한다."""
        with get_engine().begin() as conn:
            # 동시에 두 번 실행해도 PostgreSQL의 최초 키 경쟁을 피한다.
            if conn.dialect.name == 'postgresql':
                from sqlalchemy import text
                conn.execute(text('SELECT pg_advisory_xact_lock(7403103)'))
            source_count, item_count = seed_library(conn)
        click.echo(f'초기 자료 등록: 소스 {source_count}개, 해석 {item_count}개 추가 (기존 항목 유지)')
