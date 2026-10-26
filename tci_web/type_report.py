"""TYPE-02 읽기 전용 자동 초안. 화면 연결은 type_workspace가 담당한다.

new_draft는 미저장 보고서 또는 새 점수 INSERT 직후에 한 번만 사용한다. change_settings는 사용자가
기준을 직접 변경했을 때만 호출한다. 조회/재열기는 기존 composition.initial을 쓴다.
반환값과 입력은 독립된 사본이며 DB에는 SELECT만 수행한다.
"""
from copy import deepcopy

from . import composition as comp
from .candidates import collect_candidates
from .library import FAMILIES, SECTIONS
from .scores import report_types
from .selection import group_id


def lookup(connection, report):
    """현재 family/code의 통합 원고와 같은 묶음의 실제 차이만 조회한다."""
    types = report_types(report['scores'], report['settings'])

    def relevant(item):
        pair = item.get('related_type') or {}
        family, code = pair.get('family'), pair.get('code')
        link = item.get('selection') or {}
        return (family in FAMILIES and code is not None and code == types[family]
                and link.get('topic') == family + ':' + code
                and link.get('relation') in ('common', 'additional', 'alternative')
                and item['section'] in SECTIONS and bool(item['description'].strip()))

    defaults, additions, unavailable = {}, [], {}
    for family in FAMILIES:
        # 같은 문장이 두 family에 있어도 서로의 출처/유형을 합치지 않는다.
        sections = collect_candidates(connection, report['scores'], types, item_filter=lambda item:
            relevant(item) and item['related_type']['family'] == family, separate_common=True)
        related = [c for s in sections for c in s['match'] + s['reference']]
        commons = [c for c in related if c.get('selection')
                   and all(m['item']['selection']['relation'] == 'common' for m in c['members'])]
        applicable = [c for c in commons if all(m['category'] == 'match' for m in c['members'])]
        # 서로 다른 통합 원고를 임의로 우선 선정하거나 이어 붙이지 않는다.
        if len(applicable) == 1:
            defaults[family] = applicable[0]
        else:
            unavailable[family] = dict(code=types[family], reason=(
                '유형 미완성' if types[family] is None else
                '적용 가능한 통합 설명이 여러 개임' if applicable else
                '적용 조건 불충족' if commons else '통합 설명 미수록'),
                members=[deepcopy(m) for c in commons for m in c['members']])
        # 통합 기본이 있으면 그 묶음의 차이만 제시한다. 초기/구 전사 대안 전체를 섞지 않는다.
        common_groups = {group_id(c['selection']) for c in
                         ([defaults[family]] if family in defaults else commons)}
        common_texts = {' '.join(c['description'].split()) for c in commons}
        for card in related:
            if (not card.get('selection') or group_id(card['selection']) not in common_groups
                    or ' '.join(card['description'].split()) in common_texts
                    or not all(m['item']['selection']['relation'] in ('additional', 'alternative')
                               and m['item'].get('conflict', '').strip() for m in card['members'])):
                continue
            additions.append(dict(card=card, offer=comp.offer(card, dict(report, id=report.get('id'))), differences=[dict(
                text=m['item']['conflict'], source=deepcopy(m['source']),
                location=m['item']['location'], original=m['item']['original'],
                basis=m['item']['selection']['basis']) for m in card['members']]))
    return dict(types=types, defaults=defaults, additions=additions, unavailable=unavailable)


def _automatic(card, report, family):
    return comp.offer(card, dict(report, id=report.get('id')), automatic=dict(
        family=family, code=report_types(report['scores'], report['settings'])[family]))


def _result(report, found):
    report['types'] = deepcopy(found['types'])
    statuses = {}
    for section in report['composition']['sections'].values():
        for block in section['blocks']:
            previous = {m['item']['related_type']['family']: m['item']['related_type']['code']
                        for m in block['evidence']['members'] if m['item'].get('related_type')}
            statuses[block['id']] = dict(comp.snapshot_status(block, report, found['types']),
                type_differences={family: dict(previous=code, current=found['types'][family])
                                  for family, code in previous.items()
                                  if family in FAMILIES and code != found['types'][family]})
    return dict(report=report, **found, block_status=statuses)


def new_draft(connection, report, *, new_score_entry=False):
    """새 초안만 구성. new_score_entry는 새 점수 INSERT의 호출자가 명시한다.

    기존 id를 지우지 않는다. 기존 body/빈 composition은 이 경우에도 보존한다.
    """
    result = deepcopy(report)
    result.setdefault('id', None)
    found = lookup(connection, result)
    result['composition'] = comp.initial(result)
    if ((report.get('id') is None or new_score_entry) and report.get('composition') is None
            and not report.get('body')):
        # 미저장 초안에만 존재하는 슬롯. 조건 불충족과 사용자의 삭제를 구별한다.
        # DB composition v2에는 새 필드를 요구하지 않는다.
        result['_type_draft'] = {family: None for family in FAMILIES}
        for family, card in found['defaults'].items():
            block = _automatic(card, result, family)
            result['composition']['sections'][block['evidence']['section']]['blocks'].append(block)
            result['_type_draft'][family] = block['id']
    return _result(result, found)


def change_settings(connection, report, settings, *, new_score_entry=False):
    """명시적 기준 변경. 새 점수 초안의 자격은 호출자가 서명으로 확인한다.

    일반 저장본과 편집/이동/삭제문·추가문은 보존한다.
    """
    result = deepcopy(report)
    result['settings'] = deepcopy(settings)
    result['composition'] = comp.initial(report)
    found = lookup(connection, result)
    if (report.get('id') is None or new_score_entry) and report['settings'] != settings:
        moved = []
        for key, section in result['composition']['sections'].items():
            blocks = []
            for block in section['blocks']:
                evidence = block['evidence']
                automatic = evidence.get('automatic')
                # HTML form 제출은 줄바꿈을 CRLF로 전송한다. 줄끝 형식만 다른
                # 원고를 직접 편집으로 오인하지 않으며 실제 본문/근거는 보존한다.
                same_text = block['text'].replace('\r\n', '\n').replace('\r', '\n') == evidence['description'].replace('\r\n', '\n').replace('\r', '\n')
                if (not automatic or not same_text
                        or key != evidence['section']):
                    blocks.append(block)
                    continue
                family = automatic['family']
                # 유형/적용 조건이 그대로라면 자료 업데이트만으로 교체하지 않는다.
                if (automatic['code'] == found['types'][family]
                        and not comp.snapshot_status(block, result, found['types'])['mismatch']):
                    blocks.append(block)
                elif family in found['defaults']:
                    replacement = _automatic(found['defaults'][family], result, family)
                    if '_type_draft' in result:
                        result['_type_draft'][family] = replacement['id']
                    if replacement['evidence']['section'] == key:
                        blocks.append(replacement)
                    else:
                        # 사용자가 옮긴 블록과 혼동하지 않도록 새 위치는 아래에서 반영한다.
                        moved.append(replacement)
                elif '_type_draft' in result:
                    result['_type_draft'][family] = None
            section['blocks'] = blocks
        for block in moved:
            result['composition']['sections'][block['evidence']['section']]['blocks'].append(block)
        for family, block_id in result.get('_type_draft', {}).items():
            if block_id is None and family in found['defaults']:
                block = _automatic(found['defaults'][family], result, family)
                result['composition']['sections'][block['evidence']['section']]['blocks'].append(block)
                result['_type_draft'][family] = block['id']
        comp.prune_modes(result['composition'])
    return _result(result, found)
