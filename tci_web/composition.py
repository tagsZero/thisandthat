"""현재 보고서 v2. v1은 읽기 어댑터로 열고 명시적 저장 때만 전환한다."""
import json
from hashlib import sha256
import re
from copy import deepcopy
from uuid import uuid4

from flask import current_app
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import select

from .db import interpretations, sources
from .library import SECTIONS
from .selection import validate_selection, group_id

OUTPUT_SECTIONS = ('subscales', 'combined', 'summary')


def validate_output(value):
    if (not isinstance(value, dict) or set(value) != set(OUTPUT_SECTIONS)
            or any(type(v) is not bool for v in value.values())):
        raise ValueError('추가 영역 표시 설정을 확인해 주세요.')
    return deepcopy(value)


def serializer():
    return URLSafeSerializer(current_app.secret_key, salt='tci-composition-v1')


def initial(report):
    if report.get('composition') is not None:
        value = deepcopy(report['composition'])
        if value.get('version') == 1:
            value['version'] = 2
            value['group_modes'] = {}
            for section in value['sections'].values():
                for block in section['blocks']:
                    # 현재 자료로 과거 선택의 묶음을 추측하지 않는다.
                    block['selection'] = None
        return value
    return dict(version=2, group_modes={}, sections={key: dict(mode='multiple', blocks=[],
                opinion=report.get('body', '') if key == 'summary' else '') for key in SECTIONS})


def offer(card, report, automatic=None):
    section = card['members'][0]['item']['section']
    evidence = dict(report_id=report['id'], section=section, description=card['description'],
                    members=deepcopy(card['members']), scores=deepcopy(report['scores']),
                    settings=deepcopy(report['settings']), selection=deepcopy(card.get('selection')))
    if automatic is not None:
        evidence['automatic'] = deepcopy(automatic)
    return dict(id='b-' + sha256(serializer().dumps(evidence).encode()).hexdigest()[:32], item_ids=[m['item']['id'] for m in card['members']],
                text=card['description'], selection=evidence['selection'], evidence=evidence, token=serializer().dumps(evidence))


def _automatic_family(block):
    """서버 근거가 동일 family/code의 공통 원고로 구성된 자동 블록인지 확인한다."""
    evidence = block['evidence']
    automatic = evidence.get('automatic')
    if not isinstance(automatic, dict):
        return None
    family, code = automatic.get('family'), automatic.get('code')
    if family not in ('temperament', 'character') or not isinstance(code, str) or not re.fullmatch('[HML]{3}', code):
        return None
    members = evidence['members']
    if (not members or not block.get('selection')
            or block['selection']['topic'] != family + ':' + code
            or any(m['item'].get('related_type') != dict(family=family, code=code)
                   or (m['item'].get('selection') or {}).get('relation') != 'common' for m in members)):
        return None
    return family


def description_overlap(left, right):
    """동일 문장 중복. 서로 다른 두 family의 자동 공통 원고만 별도로 유지한다."""
    if ' '.join(left['evidence']['description'].split()) != ' '.join(right['evidence']['description'].split()):
        return False
    left_family, right_family = _automatic_family(left), _automatic_family(right)
    return not (left_family and right_family and left_family != right_family)


def decode(raw, report):
    """출처는 저장 사본 또는 서버 서명에서 복원하고 사용자 편집문만 받는다."""
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError('작성 내용의 형식을 확인해 주세요.') from None
    if (not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] not in (1, 2)
            or not {'version', 'sections'} <= set(value) <= {'version', 'sections', 'output', 'group_modes'} or not isinstance(value['sections'], dict)
            or set(value['sections']) != set(SECTIONS)):
        raise ValueError('지원하지 않는 작성 구조 또는 보고서 항목입니다.')
    if value['version'] == 2 and not isinstance(value.get('group_modes'), dict):
        raise ValueError('선택 묶음별 모드를 확인해 주세요.')
    saved = {b['id']: (key, b) for key, section in initial(report)['sections'].items() for b in section['blocks']}
    seen_ids, seen_items, seen_descriptions = set(), set(), {}
    result = dict(version=2, group_modes={}, sections={})
    # 구형 v1 클라이언트가 새 출력 설정을 보내지 않아도 저장된 설정을 보존한다.
    output = value.get('output', initial(report).get('output'))
    if output is not None:
        result['output'] = validate_output(output)
    elif 'output' in value:
        raise ValueError('추가 영역 표시 설정을 확인해 주세요.')
    for key in SECTIONS:
        section = value['sections'][key]
        if (not isinstance(section, dict) or set(section) != {'mode', 'blocks', 'opinion'}
                or section['mode'] not in ('single', 'multiple') or not isinstance(section['blocks'], list)
                or not isinstance(section['opinion'], str)):
            raise ValueError('선택 모드·문장·직접 의견 형식을 확인해 주세요.')
        target = dict(mode=section['mode'], opinion=section['opinion'], blocks=[])
        result['sections'][key] = target
        for block in section['blocks']:
            if (not isinstance(block, dict) or not isinstance(block.get('id'), str)
                    or not re.fullmatch(r'b-[a-f0-9]{32}', block['id']) or block['id'] in seen_ids
                    or not isinstance(block.get('text'), str)
                    or not isinstance(block.get('item_ids'), list) or not block['item_ids']
                    or any(type(i) is not int or i <= 0 for i in block['item_ids'])
                    or len(set(block['item_ids'])) != len(block['item_ids'])):
                raise ValueError('블록 식별자·원본 항목·중복 순서를 확인해 주세요.')
            seen_ids.add(block['id'])
            if block['id'] in saved:
                old_key, old = saved[block['id']]
                if old['item_ids'] != block['item_ids']:
                    raise ValueError('저장된 선택문의 연결 항목을 변경할 수 없습니다.')
                canonical = deepcopy(old)
            else:
                try:
                    evidence = serializer().loads(block.get('token', ''))
                except (BadSignature, TypeError):
                    raise ValueError('새 선택의 근거를 확인할 수 없습니다. 후보를 다시 선택해 주세요.') from None
                if (not isinstance(evidence, dict) or evidence.get('report_id') != report['id'] or evidence.get('section') not in SECTIONS
                        or [m['item']['id'] for m in evidence['members']] != block['item_ids']):
                    raise ValueError('선택문과 원본 항목이 다릅니다.')
                canonical = dict(id=block['id'], item_ids=block['item_ids'], evidence=evidence, token=block['token'],
                                 selection=validate_selection(evidence.get('selection')))
            if 'selection' in block and block['selection'] != canonical.get('selection'):
                raise ValueError('선택 당시 주제·묶음을 변경할 수 없습니다.')
            for item_id in canonical['item_ids']:
                if item_id in seen_items:
                    raise ValueError('같은 자료를 중복 선택할 수 없습니다.')
                seen_items.add(item_id)
            description_key = ' '.join(canonical['evidence']['description'].split())
            previous_blocks = seen_descriptions.setdefault(description_key, [])
            for previous in previous_blocks:
                if description_overlap(canonical, previous) and not (block['id'] in saved and previous['id'] in saved
                        and not canonical.get('selection') and not previous.get('selection')):
                    raise ValueError('동일 설명을 중복 선택할 수 없습니다.')
            previous_blocks.append(canonical)
            canonical['text'] = block['text']
            target['blocks'].append(canonical)
    allowed = {group_id(b.get('selection')) for s in result['sections'].values() for b in s['blocks']} - {None}
    allowed |= set(initial(report).get('group_modes', {}))
    modes = value.get('group_modes', {}) if value['version'] == 2 else {}
    if any(key not in allowed or mode not in ('single', 'multiple') for key, mode in modes.items()):
        raise ValueError('선택 묶음·모드를 확인해 주세요.')
    result['group_modes'] = deepcopy(modes)
    return result


def read_form(form, report):
    value = decode(form.get('composition', ''), report)
    known_groups = group_keys(value) | set(value['group_modes'])
    known_blocks = {b['id'] for s in value['sections'].values() for b in s['blocks']}
    if any((key.startswith('group_mode_') and key[11:] not in known_groups)
           or (key.startswith('position_') and key[9:] not in known_blocks) for key in form):
        raise ValueError('알 수 없는 선택 묶음 또는 위치 변경입니다.')
    if form.get('output_present') == '1':
        value['output'] = {key: form.get('include_' + key) == '1' for key in OUTPUT_SECTIONS}
    for key, section in value['sections'].items():
        section['opinion'] = form.get('opinion_' + key, section['opinion'])
        mode = form.get('mode_' + key, section['mode'])
        if mode not in ('single', 'multiple'):
            raise ValueError('선택 모드를 확인해 주세요.')
        section['mode'] = mode
        for block in section['blocks']:
            block['text'] = form.get('text_' + block['id'], block['text'])
    for group in group_keys(value):
        mode = form.get('group_mode_' + group, value['group_modes'].get(group, 'multiple'))
        if mode not in ('single', 'multiple'):
            raise ValueError('선택 묶음 모드를 확인해 주세요.')
        if 'group_mode_' + group in form or group in value['group_modes']:
            value['group_modes'][group] = mode
    # 위치 입력은 원본 목록을 순회한 뒤 한 번씩 적용한다.
    moves = [(b['id'], form.get('position_' + b['id'], key))
             for key, s in value['sections'].items() for b in s['blocks']]
    for block_id, destination in moves:
        move(value, block_id, destination)
    return value


def group_keys(value):
    return {group_id(b.get('selection')) for s in value['sections'].values() for b in s['blocks']} - {None}


def move(value, block_id, destination):
    if destination not in SECTIONS:
        raise ValueError('보고서 반영 위치를 확인해 주세요.')
    for key, section in value['sections'].items():
        for block in section['blocks']:
            if block['id'] == block_id:
                if key != destination:
                    section['blocks'].remove(block)
                    value['sections'][destination]['blocks'].append(block)
                return
    raise ValueError('선택문을 찾을 수 없습니다.')


def apply_action(value, action, report):
    if action.startswith('select:'):
        try:
            evidence = serializer().loads(action[7:])
        except BadSignature:
            raise ValueError('후보를 새로 조회하고 다시 선택해 주세요.') from None
        block = dict(id='b-' + uuid4().hex, item_ids=[m['item']['id'] for m in evidence['members']],
                     evidence=evidence, token=action[7:], text=evidence['description'],
                     selection=validate_selection(evidence.get('selection')))
        # decode validates report/section provenance for no-JS actions too.
        section = value['sections'].get(evidence['section'])
        if section is None:
            raise ValueError('보고서 항목을 확인해 주세요.')
        overlap = [b for s in value['sections'].values() for b in s['blocks'] if set(b['item_ids']) & set(block['item_ids'])
                   or description_overlap(b, block)]
        if overlap:
            for s in value['sections'].values():
                s['blocks'] = [b for b in s['blocks'] if b not in overlap]
        else:
            group = group_id(block['selection'])
            if group and value['group_modes'].get(group) == 'single':
                for s in value['sections'].values():
                    s['blocks'] = [b for b in s['blocks'] if group_id(b.get('selection')) != group]
            section['blocks'].append(block)
        prune_modes(value)
        return decode(json.dumps(value), report)
    if action.startswith('move:'):
        _, block_id, destination = action.split(':', 2)
        move(value, block_id, destination)
        return value
    if action.startswith(('remove:', 'up:', 'down:')):
        operation, block_id = action.split(':', 1)
        for section in value['sections'].values():
            blocks = section['blocks']
            for index, block in enumerate(blocks):
                if block['id'] == block_id:
                    if operation == 'remove':
                        blocks.pop(index)
                        prune_modes(value)
                    else:
                        other = index + (-1 if operation == 'up' else 1)
                        if 0 <= other < len(blocks):
                            blocks[index], blocks[other] = blocks[other], blocks[index]
                    return value
        raise ValueError('선택문을 찾을 수 없습니다.')
    if action not in ('compare', 'save', 'edit', 'dashboard', 'report'):
        raise ValueError('지원하지 않는 동작입니다.')
    return value


def prune_modes(value):
    value['group_modes'] = {key: mode for key, mode in value['group_modes'].items() if key in group_keys(value)}


def snapshot_status(block, report, types=None):
    """최신 자료 조회와 분리하여 저장 사본과 현재 점수·기준을 비교한다."""
    from .candidates import evaluate_item
    from .scores import report_types
    evidence = block['evidence']
    types = types or report_types(report['scores'], report['settings'])
    def normalized(settings):
        return {**settings, 'overrides': settings.get('overrides', {})}
    return dict(
        provided_draft=bool(evidence.get('automatic')) and all(
            m.get('provided_draft', False) for m in evidence['members']),
        type_differences={family: dict(previous=member['item']['related_type']['code'], current=types[family])
            for member in evidence['members']
            for family in [((member['item'].get('related_type') or {}).get('family'))]
            if family in ('temperament', 'character') and member['item']['related_type']['code'] != types[family]},
        previous=normalized(evidence['settings']) != normalized(report['settings']) or evidence['scores'] != report['scores'],
        reference=any(m['category'] == 'reference' for m in evidence['members']),
        mismatch=any(evaluate_item(m['item'], m['source'], report['scores'], types)['category'] == 'reference'
                     for m in evidence['members']))


def material_status(connection, value, report, validate_new=False):
    from .scores import report_types
    items = {r['id']: dict(r) for r in connection.execute(select(interpretations)).mappings()}
    source_map = {r['id']: dict(r) for r in connection.execute(select(sources)).mappings()}
    saved_ids = {b['id'] for s in initial(report)['sections'].values() for b in s['blocks']}
    types = report_types(report['scores'], report['settings'])
    statuses = {}
    for section in value['sections'].values():
        for block in section['blocks']:
            evidence = block['evidence']
            changed = False
            for member in evidence['members']:
                item, source = member['item'], member['source']
                # v1에는 새 nullable 연결 필드가 없다. 빈 필드 추가만으로 자료 변경이라고 하지 않는다.
                changed |= items.get(item['id']) != dict(item, selection=item.get('selection')) or source_map.get(source['id']) != source
            if validate_new and block['id'] not in saved_ids and changed:
                raise ValueError('새로 선택한 자료가 변경되었거나 중지되었습니다. 작성문은 유지됩니다. 해당 선택을 제외한 뒤 최신 후보에서 다시 선택해 주세요.')
            statuses[block['id']] = dict(**snapshot_status(block, report, types), changed=changed)
    return statuses
