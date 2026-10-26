"""TYPE-03 화면 어댑터. 신규 점수 POST의 초안과 저장본 조회를 구별한다."""
from copy import deepcopy
from datetime import timezone
import json

from flask import render_template, request, url_for, redirect, make_response, flash
from itsdangerous import BadSignature
from sqlalchemy.exc import SQLAlchemyError

from . import composition as comp, type_report
from .candidates import collect_candidates
from .db import get_engine, reports, utc_now
from .library import FAMILIES, SECTIONS, context
from .scores import SCALES, parse_settings, profile_rows, report_types
from .views import find_report


def context_token(report, saved):
    # 본문/검사정보를 localStorage나 세션 쿠키에 보관하지 않는다.
    return comp.serializer().dumps(dict(kind='type-workspace', report_id=saved['id'],
        baseline=baseline(saved), settings=report['settings'],
        slots=report.get('_type_draft')))


def baseline(saved):
    stamp = saved['updated_at']
    if stamp.tzinfo:
        stamp = stamp.astimezone(timezone.utc).replace(tzinfo=None)
    return stamp.isoformat()


def entry_ticket(report, saved):
    """새 점수 저장 POST에서만 발급. 열기에서는 이미 만든 사본을 복원한다."""
    return comp.serializer().dumps(dict(kind='type-entry', context=context_token(report, saved),
                                       composition=report['composition']))


def restore_context(token, saved):
    try:
        state = comp.serializer().loads(token)
        if (state['kind'] != 'type-workspace' or state['report_id'] != saved['id']
                or state['baseline'] != baseline(saved)):
            raise ValueError
        report = dict(saved, settings=state['settings'])
        if state['slots'] is not None:
            report['_type_draft'] = deepcopy(state['slots'])
        return report
    except (BadSignature, KeyError, TypeError, ValueError):
        raise ValueError('검사 기록이 변경되었거나 작성 연결이 만료되었습니다. 현재 편집문을 유지하고 저장본을 확인해 주세요.') from None


def model(connection, report, saved, found=None):
    found = found or type_report.new_draft(connection, report)
    report = found['report']
    # 별도 세부자료는 실제 조건이 맞는 항목만 같은 본문에서 읽고 추가한다.
    details = collect_candidates(connection, report['scores'], found['types'],
        item_filter=lambda item: not item.get('related_type'), separate_common=True)
    additions = list(found['additions'])
    for section in details:
        for card in section['match']:
            additions.append(dict(card=card, offer=comp.offer(card, report), differences=[]))
    flags = comp.material_status(connection, report['composition'], report)
    for key, status in found['block_status'].items():
        flags[key].update(status)
    groups = []
    # 반영 위치와 순서는 composition 계약 그대로 보존한다.
    for family, keys in [('temperament', ('innate', 'relationships', 'acceptance')),
                         ('character', ('outlook', 'growth')),
                         ('details', ('subscales', 'combined', 'summary'))]:
        groups.append(dict(family=family, label={'temperament':'기질', 'character':'성격'}.get(family, '세부 설명·직접 소견'),
            keys=[key for key in keys if key in SECTIONS],
            additions=[a for a in additions if (
                (a['card']['members'][0]['item'].get('related_type') or {}).get('family') == family
                or (family == 'details' and not a['card']['members'][0]['item'].get('related_type')))]))
    settings = report['settings']
    return dict(active='tci', report=report, workspace_report=report,
        composition=report['composition'], block_status=flags, type_groups=groups,
        unavailable=found['unavailable'], draft_context=context_token(report, saved),
        is_fresh='_type_draft' in report, valid_settings=settings,
        saved_settings=saved['settings'], saved_types=report_types(saved['scores'], saved['settings']),
        profile_rows=profile_rows(report['scores'], found['types']),
        changed=settings != saved['settings'], scales=SCALES, errors={},
        preset='t' + settings['high'] if settings['low'] == '45' and settings['high'] in ('55', '56') else 'custom',
        **context())


def render_workspace(report, saved=None, found=None):
    saved = saved or report
    with get_engine().connect() as connection:
        data = model(connection, report, saved, found)
    return render_template('type_workspace.html', **data)


def save_baseline(saved, report):
    """서명으로 복원한 신규 자동 사본만 저장 검증의 보존 대상으로 인정한다.

    일반 추가 후보는 계속 최신 자료를 검증한다. 슬롯 ID뿐 아니라 token의
    해시까지 연결해 다른 후보/자동 토큰을 같은 ID로 바꾸는 우회를 막는다.
    이 검증용 사본은 DB에 쓰지 않는다.
    """
    from hashlib import sha256
    value = comp.initial(saved)
    slots = report.get('_type_draft', {})
    for key, section in report['composition']['sections'].items():
        for block in section['blocks']:
            family = comp._automatic_family(block)
            if (family and slots.get(family) == block['id']
                    and block['id'] == 'b-' + sha256(block['token'].encode()).hexdigest()[:32]):
                value['sections'][key]['blocks'].append(deepcopy(block))
    return dict(saved, composition=value)


def handle(report_id):
    """표시와 기준 변경은 읽기 전용. 기존 명시적 저장/이동 계약만 재사용한다."""
    form = request.form
    def failure(errors, status, save_state='not_saved'):
        if request.accept_mimetypes.best != 'application/json':
            return render_template('composition_recovery.html', recovery=form,
                message=' '.join(errors.values()) + ' · 제출한 입력을 유지했습니다.', save_state=save_state,
                pdf_retry=form.get('action') == 'pdf'), status
        return dict(errors=errors, save_state=save_state, request_id=form.get('_request_id')), status
    try:
        saved = find_report(report_id)
        if form.get('action') == 'open_draft':
            ticket = comp.serializer().loads(form.get('draft_ticket', ''))
            if ticket.get('kind') != 'type-entry':
                raise ValueError('새 작성 연결을 확인해 주세요.')
            report = restore_context(ticket['context'], saved)
            report['composition'] = comp.decode(json.dumps(ticket['composition']), saved)
            return render_workspace(report, saved)
        report = restore_context(form.get('type_context', ''), saved)
        # 새 근거는 실제 report id의 서명으로 검증하며 저장본 사본도 유지한다.
        report['composition'] = comp.read_form(form, saved)
        settings, errors = parse_settings(form, report['settings'])
        if errors:
            return failure(errors, 422)
        action = form.get('action', 'compare')
        if action not in ('compare', 'save', 'edit', 'dashboard', 'report', 'pdf'):
            raise ValueError('지원하지 않는 동작입니다.')
        with get_engine().connect() as connection:
            found = type_report.change_settings(connection, report, settings, new_score_entry='_type_draft' in report)
        report = found['report']
        save_state, destination = 'not_saved', None
        if action != 'compare':
            if action == 'pdf':
                from .pdf_export import validate_report
                validate_report(report)
            with get_engine().begin() as connection:
                comp.material_status(connection, report['composition'], save_baseline(saved, report), validate_new=True)
                stamp = utc_now()
                # 조회 이후 다른 저장이 먼저 커밋됐다면 오래된 요청으로 덮어쓰지 않는다.
                result = connection.execute(reports.update().where(
                    reports.c.id == report_id, reports.c.updated_at == saved['updated_at']).values(
                    settings=settings, composition=report['composition'], updated_at=stamp))
                if result.rowcount != 1:
                    raise ValueError('검사 기록이 먼저 변경되었습니다. 현재 편집문을 유지하고 저장본을 확인해 주세요.')
            saved = dict(saved, settings=settings, composition=deepcopy(report['composition']), updated_at=stamp)
            report.pop('_type_draft', None)
            save_state = 'saved'
            if action == 'pdf':
                from .pdf_export import saved_download
                # 커밋한 독립 사본을 기존 PDF 생성기에 전달한다. 새 자료로 재조립하지 않는다.
                response = make_response(saved_download(deepcopy(saved)))
                response.headers.update({'X-TCI-Type-Context': context_token(report, saved),
                    'X-TCI-Request-Id': form.get('_request_id', ''),
                    'X-TCI-Saved-At': baseline(saved)})
                return response
            destination = (url_for('final_report.show', report_id=report_id) if action == 'report' else
                url_for('web.edit_report', report_id=report_id, return_to='candidates') if action == 'edit' else
                url_for('web.dashboard') if action == 'dashboard' else None)
        try:
            with get_engine().connect() as connection:
                data = model(connection, report, saved, found)
        except SQLAlchemyError:
            if request.accept_mimetypes.best != 'application/json':
                recovery = form.copy()
                recovery['type_context'] = context_token(report, saved)
                recovery['composition'] = json.dumps(report['composition'])
                return render_template('composition_recovery.html', recovery=recovery, save_state=save_state,
                    message=('저장은 완료되었습니다. ' if save_state == 'saved' else '') +
                    '자료 조회에 실패했습니다. 제출한 본문을 유지했습니다. 다시 시도해 주세요.'), 503
            return dict(errors={'query': '자료 조회에 실패했습니다. 현재 편집문을 유지했습니다. 다시 시도해 주세요.'},
                save_state=save_state, type_context=context_token(report, saved),
                saved_at=baseline(saved),
                request_id=form.get('_request_id')), 503
        if request.accept_mimetypes.best != 'application/json':
            if destination:
                flash('현재 해석·기준을 저장했습니다.', 'success')
                return redirect(destination)
            return render_template('type_workspace.html', **data)
        return dict(errors={}, composition=report['composition'], settings=settings,
            type_context=data['draft_context'], block_status=data['block_status'],
            body_html=render_template('type_body.html', **data),
            profile_html=render_template('workspace_profile.html', **data),
            save_state=save_state, saved_at=baseline(saved), destination=destination, request_id=form.get('_request_id'))
    except (BadSignature, ValueError, KeyError, TypeError) as error:
        message = str(error) if isinstance(error, ValueError) else '작성 연결을 확인할 수 없습니다. 현재 입력을 유지했습니다.'
        return failure({'composition': message}, 422)
    except SQLAlchemyError:
        return failure({'query': '저장 또는 조회 요청에 실패했습니다. 현재 입력을 유지했습니다. 다시 시도해 주세요.'}, 503,
                       'failed' if form.get('action') != 'compare' else 'not_saved')
