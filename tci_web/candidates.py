"""읽기 전용 후보 평가. 자료 관리의 version=1 AND 계약을 사용한다."""
import re
import json
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from flask import Blueprint, render_template, request, url_for, redirect, flash
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .auth import login_required
from .db import get_engine, interpretations, sources, reports, utc_now
from . import composition as comp
from .library import EDITIONS, FAMILIES, MAIN, METRICS, SECTIONS, STATUS, context, validate_numeric
from .scores import SCALES, parse_settings, report_types, profile_rows
from .selection import TOPICS, group_id, item_topic
from .views import find_report
from .permissions import owner_condition

bp = Blueprint('candidates', __name__)

# TYPE-01 R3/R4: 이전57개 팩의 잔존 행도 새 후보에서는 제외한다.
# 행과 과거 보고서의 근거는 수정하지 않는다.
NON_REPORT_KEYS = frozenset({
    'type01-additional-character-mhm-tci-hwpx',
    'type01-additional-character-lml-tci-hwpx',
})


def provided_integrated(item):
    """승인된 TYPE-01 통합54개의 기존 식별/연결만 허용한다. 참고 전체의 승격이 아니다."""
    pair, link = item.get('related_type') or {}, item.get('selection') or {}
    if not isinstance(pair, dict) or not isinstance(link, dict):
        return False
    family, code = pair.get('family'), pair.get('code')
    return (family in FAMILIES and isinstance(code, str) and bool(re.fullmatch('[HML]{3}', code))
            and item.get('seed_key') == f'type01-integrated-{family}-{code.lower()}'
            and link.get('topic') == family + ':' + code
            and link.get('group') == 'type01-integrated' and link.get('relation') == 'common')


def evaluate_clause(clause, scores, types):
    """(충족 여부, 표시할 이유). 지원하지 않는 절은 호출자에서 참고로 격리한다."""
    if not isinstance(clause, dict):
        raise ValueError('조건 절 형식')
    kind = clause.get('kind')
    if kind == 'type':
        family, expected = clause.get('family'), clause.get('code')
        if family not in FAMILIES or not isinstance(expected, str) or not re.fullmatch('[HML]{3}', expected):
            raise ValueError('유형 조건')
        value = types[family]
        return value == expected, f'{FAMILIES[family]}: 현재 {value or "미입력 (유형 미완성)"} / 조건 {expected}'
    if kind == 'grade':
        scale, expected = clause.get('scale'), clause.get('value')
        if scale not in MAIN or expected not in ('H', 'M', 'L'):
            raise ValueError('주척도 H/M/L 조건')
        value = types['grades'][scale]
        return value == expected, f'{scale} H/M/L: 현재 {value or "미입력"} / 조건 {expected}'
    if kind != 'numeric':
        raise ValueError('미지원 조건 종류')
    # 관리 화면과 같은 metric·구간 검증을 거친다. JSON boolean을 문자열로 오인하지 않는다.
    if any(type(clause.get(key + '_inclusive')) is not bool for key in ('lower', 'upper')):
        raise ValueError('경계 포함 형식')
    row = {key: clause[key] for key in ('scale', 'metric')}
    for key in ('lower', 'upper'):
        bound = clause[key]
        if bound is not None and not isinstance(bound, str):
            raise ValueError('수치 경계 형식')
        row[key] = bound or ''
        row[key + '_inclusive'] = '1' if clause[key + '_inclusive'] else '0'
    validate_numeric(row)
    scale, metric = row['scale'], row['metric']
    if metric == 'applied_t':
        value = types['applied'].get(scale)
    else:
        target = scores.get(scale, {}) if scale in MAIN or scale == 'SC' else scores.get('subscales', {}).get(scale, {})
        value = target.get({'raw': 'raw', 'original_t': 't', 'percentile': 'percentile'}[metric])
    bounds = []
    matched = True
    for key, symbol in (('lower', '≥' if clause['lower_inclusive'] else '>'),
                        ('upper', '≤' if clause['upper_inclusive'] else '<')):
        if clause[key] is not None:
            bounds.append(f'{symbol} {clause[key]}')
    message = f'{scale} {METRICS[metric]}: 현재 {value if value is not None and value != "" else "미입력"} / 조건 {" 및 ".join(bounds)}'
    if value is None or value == '':
        return False, message + ' · 필요한 점수 미입력'
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('유효하지 않은 입력 점수')
    for key in ('lower', 'upper'):
        if clause[key] is None:
            continue
        bound = Decimal(clause[key])
        inclusive = clause[key + '_inclusive']
        matched &= (number >= bound if inclusive else number > bound) if key == 'lower' else (
            number <= bound if inclusive else number < bound)
    return matched, message


def evaluate_item(item, source, scores, types):
    reasons, checks, notes = [], [], []
    supplied = provided_integrated(item)
    edition, source_edition = item.get('edition'), source.get('edition')
    if edition not in ('adult', 'common'):
        (notes if supplied and edition == 'unknown' else reasons).append(
            '항목 검사판 미확인' if edition == 'unknown' else '항목이 성인 TCI-RS 적용 범위가 아님')
    if source_edition not in EDITIONS:
        reasons.append('소스 검사판 확인 필요')
    elif source_edition in ('youth', 'child'):
        reasons.append('소스 검사판이 성인 입력 양식과 다름 · 항목 검사판과 충돌 여부 확인 필요')
    elif edition in ('youth', 'child') and source_edition == 'adult':
        reasons.append('소스와 항목 검사판 충돌')
    condition = item.get('conditions')
    if not isinstance(condition, dict):
        condition = {}
    status = condition.get('status')
    if not isinstance(status, str):
        status = None
    if status != 'match':
        (notes if supplied and status == 'reference' else reasons).append(STATUS.get(status, '조건 상태 확인 필요'))
    if item.get('active') is False or source.get('active') is False:
        reasons.append('자료 사용 중지')
    if (type(condition.get('version')) is not int or condition.get('version') != 1
            or condition.get('operator') != 'and' or condition.get('missing') != 'not_matched'
            or status not in STATUS or not isinstance(condition.get('clauses'), list)):
        reasons.append('조건 확인 필요 · 미지원 또는 손상된 조건 계약')
    else:
        for clause in condition['clauses']:
            try:
                matched, message = evaluate_clause(clause, scores, types)
                checks.append({'matched': matched, 'message': message})
            except (ValueError, KeyError, TypeError, InvalidOperation):
                checks.append({'matched': False, 'message': '조건 확인 필요 · 미지원 또는 손상된 조건 절'})
        if any(not check['matched'] for check in checks):
            reasons.append('AND 조건 불충족 · 불충족 또는 미확인 절을 확인하세요')
    # 연결 메타데이터만으로 다른 유형이나 유형 조건 누락을 자동 허용하지 않는다.
    if supplied:
        expected = dict(kind='type', **item['related_type'])
        clauses = condition.get('clauses')
        if not isinstance(clauses, list) or expected not in clauses:
            reasons.append('통합 설명의 필수 유형 조건 확인 필요')
        notes.append('제공 자료 기반 해석 초안 · 검사판·성인 적용 근거 미확인 · 공식 성인용 검증 완료 아님')
    return dict(category='reference' if reasons else 'match', reasons=reasons, checks=checks,
                general=not checks and not reasons, provided_draft=supplied, notes=notes)


def collect_candidates(connection, scores, types, item_filter=None, separate_common=False):
    source_map = {r['id']: dict(r) for r in connection.execute(select(sources).where(sources.c.active.is_(True))).mappings()}
    items = [dict(r) for r in connection.execute(select(interpretations).where(
        interpretations.c.active.is_(True), interpretations.c.source_id.in_(source_map))).mappings()]
    # 고정 순서: 보고서 항목 → 관점(문자열) → 수동 정렬값 → ID.
    items.sort(key=lambda r: (list(SECTIONS).index(r['section']) if r['section'] in SECTIONS else len(SECTIONS),
                              r['perspective'], r['sort_order'], r['id']))
    sections = {key: {'label': label, 'match': [], 'reference': []} for key, label in SECTIONS.items()}
    grouped = {}
    for item in items:
        if item.get('seed_key') in NON_REPORT_KEYS or (item_filter and not item_filter(item)):
            continue
        source = source_map[item['source_id']]
        evaluation = evaluate_item(item, source, scores, types)
        member = dict(item=item, source=source, **evaluation)
        section = item['section']
        if section not in sections:
            sections.setdefault(section, {'label': '보고서 항목 확인 필요', 'match': [], 'reference': []})
            member['category'] = 'reference'
            member['reasons'].append('보고서 항목 확인 필요')
        # 자동 구성에서는 같은 본문의 추가문이 공통 원고의 자격·근거에 섞이지 않게 한다.
        key = (' '.join(item['description'].split()),
               (item.get('selection') or {}).get('relation') == 'common' if separate_common else None)
        if key not in grouped:
            card = dict(description=item['description'], members=[], anchor=f'candidate-{item["id"]}')
            grouped[key] = card
        grouped[key]['members'].append(member)
    for card in grouped.values():
        first = card['members'][0]['item']
        # 교체 범위는 topic/group이다. 출처마다 다른 관계·대조 근거는 members에 보존한다.
        selection = first.get('selection')
        group = group_id(selection)
        card['selection'] = deepcopy(selection) if group and all(
            group_id(m['item'].get('selection')) == group for m in card['members']) else None
        category = 'reference' if any(m['category'] == 'reference' for m in card['members']) else 'match'
        sections[first['section']][category].append(card)
        card['topics'] = sorted({item_topic(m['item']) for m in card['members']} |
                                {'scale:' + code for m in card['members'] for code in m['item'].get('related_scales', [])})
        keys = {m['item']['group_key'] for m in card['members'] if m['item']['group_key']}
        card['similar'] = [dict(anchor=other['anchor'], title=other['members'][0]['item']['title'])
                           for other in grouped.values() if other is not card and any(
                               m['item']['group_key'] in keys for m in other['members'])]
    return list(sections.values())


def settings_query(settings):
    query = dict(compare='1', preset='custom', **{key: settings[key] for key in ('low', 'high', 'rounding')})
    for code, bounds in settings.get('overrides', {}).items():
        query.update({f'{code}_override': '1', f'{code}_low': bounds['low'], f'{code}_high': bounds['high']})
    return urlencode(query)


def topic_views(sections, report):
    cards = [c for s in sections for c in s['match'] + s['reference']]
    keys = {key for key in TOPICS if key.startswith('scale:')}
    keys |= {topic for card in cards for topic in card['topics']}
    keys |= {family + ':' + (report['types'][family] or 'unknown') for family in FAMILIES}
    keys |= {'combined:general', 'combined:SC'}
    result = []
    for key in sorted(keys, key=lambda key: list(TOPICS).index(key) if key in TOPICS else len(TOPICS)):
        family, code = key.split(':')
        view = 'candidates' if family == 'scale' else 'temperament' if family == 'temperament' else 'character'
        related = [c for c in cards if key in c['topics']]
        related.sort(key=lambda c: (c['members'][0]['item']['perspective'],
                                    c['members'][0]['item']['sort_order'], c['members'][0]['item']['id']))
        subscale = family == 'scale' and code not in MAIN and code != 'SC'
        raw = report['scores'].get('subscales', {}).get(code, {}).get('raw')
        current = family in FAMILIES and code == (report['types'][family] or 'unknown')
        result.append(dict(key=key, label=TOPICS.get(key, FAMILIES.get(family, family) + ' 미완성'),
            view=view, cards=related, current=current, subscale=subscale, raw=raw,
            relevance='현재 ' + FAMILIES[family] + '유형과 연결' if current else
                '현재 유형과 다름 · 비교 참고' if family in FAMILIES else '현재 검토 주제와 연결 · 개인 조건은 별도 확인'))
    return result


def query_failure(form, save_state='not_saved', value=None, saved_settings=None):
    """DB를 다시 읽지 않고 제출 내용과 확인된 저장 상태를 반환한다."""
    message = {
        'saved': '현재 해석·기준은 저장되었습니다. 이후 후보 조회에 실패했습니다. 입력은 유지됩니다. 비교 화면을 다시 열어 주세요.',
        'failed': '저장하지 못했습니다. 후보 조회도 실패했습니다. 입력은 유지됩니다. 다시 시도해 주세요.',
        'not_saved': '후보 조회에 실패했습니다. 이번 제출 내용은 저장하지 않았습니다. 입력은 유지됩니다. 다시 시도해 주세요.',
    }[save_state]
    if request.accept_mimetypes.best == 'application/json':
        return dict(errors={'query': message}, message=message, save_state=save_state,
                    saved_settings=saved_settings, request_id=form.get('_request_id')), 503
    recovery = form.copy() if request.method == 'POST' else None
    if recovery is not None and value is not None:
        # 선택·순서 조작까지 반영된 유효 본문도 복구한다. 이름 있는 편집 필드는 그대로 유지한다.
        recovery['composition'] = json.dumps(value, ensure_ascii=False)
    return render_template('composition_recovery.html', recovery=recovery, message=message,
                           save_state=save_state), 503


@bp.route('/tci/reports/<int:report_id>/candidates', methods=['GET', 'POST'])
@login_required
def index(report_id):
    if request.method == 'POST' and request.form.get('type_workspace') == '1':
        from .type_workspace import handle
        return handle(report_id)
    if request.method == 'GET' and request.args.get('compare') != '1' and request.accept_mimetypes.best != 'application/json':
        from .type_workspace import render_workspace
        try:
            return render_workspace(find_report(report_id))
        except SQLAlchemyError:
            return query_failure(request.args)
    if request.method == 'POST' and request.form.get('action') == 'pdf':
        from .pdf_export import save_editor
        return save_editor(report_id)
    form = request.form if request.method == 'POST' else request.args
    try:
        report = find_report(report_id)
    except SQLAlchemyError:
        return query_failure(form)
    saved_settings = deepcopy(report['settings'])
    comparing = request.method == 'POST' or form.get('compare') == '1'
    settings, errors = parse_settings(form, saved_settings) if comparing else (saved_settings, {})
    report['settings'] = settings
    value = comp.initial(report)
    action = form.get('action', 'compare')
    destination = None
    message = '저장된 내용을 열었습니다.' if request.method == 'GET' else '미저장 · 현재 작성 내용은 유지됩니다.'
    status_code = 422 if errors else 200
    save_state = 'not_saved'
    if request.method == 'POST':
        try:
            value = comp.read_form(form, report)
            value = comp.apply_action(value, action, report)
        except ValueError as error:
            if request.accept_mimetypes.best != 'application/json':
                return render_template('composition_recovery.html', recovery=form,
                                       message=str(error) + ' · 제출한 원본 입력을 유지했습니다. 수정 후 다시 제출하세요.'), 422
            errors['composition'] = str(error)
            status_code = 422
        if not errors and action in ('save', 'edit', 'dashboard', 'report'):
            try:
                with get_engine().begin() as connection:
                    comp.material_status(connection, value, report, validate_new=True)
                    connection.execute(reports.update().where(reports.c.id == report_id, owner_condition(reports)).values(
                        settings=settings, composition=value, updated_at=utc_now()))
                message = '현재 해석·기준을 저장했습니다.'
                save_state = 'saved'
                saved_settings = deepcopy(settings)
                if action == 'report':
                    destination = url_for('final_report.show', report_id=report_id)
                    flash(message, 'success')
                else:
                    destination = url_for('web.edit_report', report_id=report_id, return_to='candidates') if action == 'edit' else url_for('web.dashboard') if action == 'dashboard' else None
                if destination and request.accept_mimetypes.best != 'application/json':
                    return redirect(destination)
            except ValueError as error:
                errors['composition'] = str(error)
                status_code = 422
            except SQLAlchemyError:
                save_state = 'failed'
                errors['composition'] = '저장하지 못했습니다. 입력은 유지됩니다. 다시 저장해 주세요.'
                status_code = 503
    preset = 't' + settings['high'] if settings['low'] == '45' and settings['high'] in ('55', '56') else 'custom'
    from .final_report import display_options
    data = dict(active='tci', report=report, errors=errors, scales=SCALES, preset=preset,
                output_options=display_options(value, report['scores']),
                saved_settings=saved_settings, composition=value, block_status={}, message=message, **context())
    setting_errors = {k: v for k, v in errors.items() if k != 'composition'}
    # 잘못된 입력은 폼에 남기고, 표시 결과에는 마지막으로 확인한 유효 기준만 사용한다.
    valid_settings = saved_settings
    if setting_errors and form.get('valid_settings'):
        try:
            previous = json.loads(form['valid_settings'])
            previous_form = dict(previous, preset='custom')
            for code, bounds in previous.get('overrides', {}).items():
                previous_form.update({f'{code}_override': '1', f'{code}_low': bounds['low'], f'{code}_high': bounds['high']})
            parsed, invalid = parse_settings(previous_form)
            if not invalid:
                valid_settings = parsed
        except (ValueError, TypeError, KeyError, AttributeError):
            pass
    if not setting_errors:
        valid_settings = settings
    display_report = dict(report, settings=valid_settings,
                          types=report_types(report['scores'], valid_settings))
    try:
        with get_engine().connect() as connection:
            sections = collect_candidates(connection, report['scores'], display_report['types'])
            statuses = comp.material_status(connection, value, display_report)
    except SQLAlchemyError:
        return query_failure(form, save_state, value, saved_settings)
    for section in sections:
        for card in section['match'] + section['reference']:
            if card['members'][0]['item']['section'] in SECTIONS:
                card['offer'] = comp.offer(card, display_report)
                card['selected'] = any(set(b['item_ids']) & set(card['offer']['item_ids'])
                    or ' '.join(b['evidence']['description'].split()) == ' '.join(card['description'].split())
                    for s in value['sections'].values() for b in s['blocks'])
    data.update(candidate_sections=sections, block_status=statuses,
                topic_sections=topic_views(sections, display_report),
                changed=settings_query(valid_settings) != settings_query(saved_settings),
                workspace_report=display_report,
                profile_rows=profile_rows(report['scores'], display_report['types']),
                saved_types=report_types(report['scores'], saved_settings),
                valid_settings=valid_settings,
                edit_url=url_for('web.edit_report', report_id=report_id) + '?' + settings_query(settings),
                match_count=sum(len(s['match']) for s in sections),
                reference_count=sum(len(s['reference']) for s in sections))
    if request.accept_mimetypes.best == 'application/json':
        return dict(errors=errors, html=render_template('candidate_results.html', **data) if not setting_errors else '',
                    profile_html=render_template('workspace_profile.html', **data) if not setting_errors else '',
                    block_status=data['block_status'], settings=settings, scores=report['scores'],
                    saved_settings=saved_settings, request_id=form.get('_request_id'),
                    message=message, save_state=save_state, destination=destination), status_code
    from .type_workspace import model
    with get_engine().connect() as connection:
        page_data = model(connection, dict(display_report, composition=value), find_report(report_id))
    page_data.update(errors=errors, preset=preset, input_settings=settings)
    return render_template('type_workspace.html', **page_data), status_code if request.method == 'POST' else 200
