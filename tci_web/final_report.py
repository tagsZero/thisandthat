"""웹·PDF 공통 보고서 읽기 모델과 명시적인 출력 설정 저장."""
import json
from decimal import InvalidOperation

from flask import Blueprint, abort, flash, get_flashed_messages, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .auth import login_required
from . import composition as comp
from .db import get_engine, reports, utc_now
from .library import SECTIONS
from .selection import RELATIONS
from .scores import report_types, profile_rows
from .views import find_report

bp = Blueprint('final_report', __name__)

GUIDES = {
    'NS': '새로운 것에 호기심을 느끼며 시도해 보는 성향',
    'HA': '위험이 예상되는 상황을 경계하고 피하려는 성향',
    'RD': '감정에 민감하고 사람들과 교류하고 싶어하는 성향',
    'PS': '곧바로 보상이 주어지지 않아도 행동을 꾸준히 지속하는 성향',
    'SD': '주도적으로 목표를 세우고 자율적으로 행동하는 정도',
    'CO': '관계 속에서 다른 사람의 상황을 이해하고 조화를 이루는 정도',
    'ST': '정신적인 세계에 몰두하거나 우주만물과 일체감을 느끼는 정도',
}


def display_options(value, scores):
    if 'output' in value:
        return comp.validate_output(value['output'])
    result = {key: bool(value['sections'][key]['blocks'] or value['sections'][key]['opinion'])
              for key in comp.OUTPUT_SECTIONS}
    result['subscales'] |= any(row.get('raw') not in (None, '')
                               for row in scores.get('subscales', {}).values())
    return result


def read_model(report):
    value = comp.decode(json.dumps(comp.initial(report)), report)
    types = report_types(report['scores'], report['settings'])
    rows = [dict(row, guide=GUIDES[row['code']]) for row in profile_rows(report['scores'], types)]
    missing = [row['code'] for row in rows if row['grade'] is None]
    block_status = {block['id']: comp.snapshot_status(block, report, types)
                    for section in value['sections'].values() for block in section['blocks']}
    return dict(report=report, composition=value, types=types, profile_rows=rows,
                missing=missing, options=display_options(value, report['scores']),
                section_labels=SECTIONS, relations=RELATIONS, block_status=block_status)


def failure(message, save_state='not_saved', options=None, code=503):
    if request.method == 'GET' and any(m in ('현재 해석·기준을 저장했습니다.', '표시 설정을 저장했습니다.')
                                       for m in get_flashed_messages()):
        save_state = 'saved'
        message = '저장은 완료되었습니다. 이후 ' + message
    return render_template('final_report_error.html', active='tci', message=message,
                           save_state=save_state, options=options), code


@bp.route('/tci/reports/<int:report_id>/report', methods=['GET', 'POST'])
@login_required
def show(report_id):
    options = None
    if request.method == 'POST':
        options = {key: request.form.get('include_' + key) == '1' for key in comp.OUTPUT_SECTIONS}
        if request.form.get('action') not in ('preview', 'save_output'):
            return failure('지원하지 않는 표시 설정 동작입니다.', options=options, code=422)
    try:
        report = find_report(report_id)
        data = read_model(report)
    except SQLAlchemyError:
        return failure('저장된 보고서를 읽지 못했습니다. 다시 시도해 주세요.', options=options)
    except (ValueError, KeyError, TypeError, InvalidOperation):
        return failure('저장된 보고서 구조나 점수를 읽을 수 없습니다. 저장 내용을 확인해 주세요.',
                       options=options, code=422)
    if request.method == 'POST' and request.form['action'] == 'save_output':
        try:
            with get_engine().begin() as connection:
                # 출력 설정만 변경한다. 동시에 저장된 본문·점수·기준을 덮어쓰지 않는다.
                fresh = connection.execute(select(reports).where(reports.c.id == report_id)
                                           .with_for_update()).mappings().first()
                if fresh is None:
                    abort(404)
                value = comp.initial(dict(fresh))
                comp.decode(json.dumps(value), dict(fresh))
                value['output'] = options
                connection.execute(reports.update().where(reports.c.id == report_id).values(
                    composition=value, updated_at=utc_now()))
        except SQLAlchemyError:
            return failure('표시 설정을 저장하지 못했습니다. 선택한 설정을 유지했습니다.',
                           'failed', options)
        except (ValueError, KeyError, TypeError):
            return failure('저장된 본문을 확인할 수 없어 표시 설정을 저장하지 않았습니다.',
                           'not_saved', options, 422)
        if request.accept_mimetypes.best == 'application/json':
            return dict(save_state='saved', options=options)
        flash('표시 설정을 저장했습니다.', 'success')
        return redirect(url_for('final_report.show', report_id=report_id))
    data['saved_options'] = dict(data['options'])
    if options is not None:
        data['options'] = options
    data['preview'] = request.method == 'POST'
    data['status_known'] = True
    try:
        with get_engine().connect() as connection:
            data['block_status'] = comp.material_status(connection, data['composition'], report)
    except SQLAlchemyError:
        # 본문 사본은 표시하되 최신 상태 조회의 성공을 가장하지 않는다.
        data['status_known'] = False
    except (ValueError, KeyError, TypeError):
        return failure('저장된 출처 사본을 읽을 수 없습니다. 저장 내용을 확인해 주세요.', code=422)
    return render_template('final_report.html', active='tci', **data)
