"""TCI-TYPE-01 자료 팩의 명시적 등록. 기존 행·보고서를 갱신하지 않는다."""
import json
from itertools import product
from pathlib import Path

import click
from sqlalchemy import select, text
from werkzeug.datastructures import MultiDict

from .db import get_engine, interpretations, sources
from .library import item_form, parse_item, SECTIONS

TYPE_PATH = Path(__file__).resolve().parents[1] / 'data/type_interpretations.json'


def load_type_data():
    data = json.loads(TYPE_PATH.read_text(encoding='utf8'))
    expected = {(family, ''.join(code)) for family in ('temperament', 'character')
                for code in product('HML', repeat=3)}
    source_keys = {row['seed_key'] for row in data['sources']}
    transcriptions = data['transcriptions']
    if len(source_keys) != 4 or len(transcriptions) != 162:
        raise ValueError('TYPE-01 소스/전사 수가 다릅니다.')
    keys = set()
    for row in transcriptions + data['interpretations']:
        if row['seed_key'] in keys or row['source_key'] not in source_keys:
            raise ValueError('자료 키 중복 또는 출처 누락')
        keys.add(row['seed_key'])
        # 원문 확인 전 검사판/조건 원값의 승격을 방지한다. 통합54개 사용 판정과 별개다.
        if row['edition'] != 'unknown' or row['conditions']['status'] != 'reference':
            raise ValueError('검사판 미확인 자료 팩의 적용 범위를 확인해 주세요.')
        fields, scales, numeric = item_form(dict(row, source_id=1))
        form = MultiDict(fields)
        form.setlist('related_scales', scales)
        for condition in numeric:
            for key,value in condition.items():
                form.add('numeric_' + key, value)
        _, errors = parse_item(form, {1})
        if errors:
            raise ValueError(f"{row['seed_key']}: {errors}")
    for row in transcriptions:
        proof = data['provenance'][row['seed_key']]['unit']
        if (row['original'] != proof['original']
                or row['description'] != '\n\n'.join(proof['paragraphs'])
                or len(row['description']) < 100 or len(proof['paragraphs']) < 3):
            raise ValueError('상세 본문/원문 연결 누락: ' + row['seed_key'])
    for source_key in ('jtci-ppt', 'tci-types-pdf', 'tci-hwpx'):
        actual = {(r['related_type']['family'], r['related_type']['code'])
                  for r in transcriptions if r['source_key'] == source_key}
        if actual != expected:
            raise ValueError('소스별 기질27/성격27 누락: ' + source_key)
    validate_integration(data, expected)
    return data


def validate_integration(data, expected):
    """고정 편집 원고와 원문 연결을 검사한다. 보고서 자동 구성은 하지 않는다."""
    archive = {r['seed_key']: r for r in data['transcriptions']}
    items = {r['seed_key']: r for r in data['interpretations']}
    notes = {r['excluded_seed_key']: r for r in data['comparison_notes']}
    if (len(notes) != len(data['comparison_notes']) or set(notes) & set(items)
            or any(r['report_eligible'] is not False for r in notes.values())):
        raise ValueError('비교 기록을 보고서용 원고로 등록할 수 없습니다.')
    used_notes = set()
    actual, used = set(), set()
    for entry in data['integration']:
        pair = (entry['family'], entry['code'])
        if pair in actual or pair not in expected:
            raise ValueError('통합 유형 중복/오류')
        actual.add(pair)
        common = items[entry['common_key']]
        units = entry['units']
        ids = {u['id'] for u in units}
        if len(ids) != len(units) or not units:
            raise ValueError('통합 문장 중복/누락')
        paragraph_ids = sorted({u['paragraph'] for u in units})
        description = '\n\n'.join(' '.join(u['text'] for u in units if u['paragraph'] == p)
                                  for p in paragraph_ids)
        if (paragraph_ids != list(range(1, len(paragraph_ids) + 1))
                or common['description'] != description):
            raise ValueError('통합 본문/문단 연결 불일치')
        def check_ref(ref):
            row = archive[ref['transcription_key']]
            if tuple(row['related_type'][k] for k in ('family', 'code')) != pair:
                raise ValueError('다른 유형 원문 연결')
            count = len(data['provenance'][row['seed_key']]['unit']['paragraphs'])
            if not ref['paragraphs'] or any(not 1 <= p <= count for p in ref['paragraphs']):
                raise ValueError('원문 문단 위치 오류')
        for unit in units:
            if len({r['transcription_key'] for r in unit['refs']}) < 2:
                raise ValueError('공통 문장 대조 근거 누락')
            for ref in unit['refs'] + unit.get('shared_tail_refs', []):
                check_ref(ref)
        seen = set()
        for disposition in entry['source_dispositions']:
            ref = dict(transcription_key=disposition['transcription_key'],
                       paragraphs=[disposition['paragraph']])
            check_ref(ref)
            key = (ref['transcription_key'], ref['paragraphs'][0])
            if key in seen or any(u not in ids for u in disposition['units']):
                raise ValueError('원문 대조 중복/연결 오류')
            seen.add(key)
        required = {(key, p) for key, row in archive.items()
                    if tuple(row['related_type'][k] for k in ('family', 'code')) == pair
                    for p in range(1, len(data['provenance'][key]['unit']['paragraphs']) + 1)}
        if seen != required:
            raise ValueError('원문 문단 대조 누락')
        for key in entry.get('comparison_note_keys', []):
            note = notes.get(key)
            difference = entry.get('difference', {})
            if (note is None or key in used_notes
                    or note['related_type'] != dict(family=pair[0], code=pair[1])
                    or difference.get('report_eligible') is not False):
                raise ValueError('비출력 비교 기록 연결 오류')
            proof = data['provenance'][difference['transcription_key']]['unit']
            if note['original'] != proof['paragraphs'][difference['paragraph'] - 1]:
                raise ValueError('비교 기록 원문 연결 오류')
            used_notes.add(key)
        for key, relation in [(entry['common_key'], 'common')] + [
                (k, 'additional') for k in entry['additional_keys']]:
            row = items[key]
            if (key in used or row['related_type'] != dict(family=pair[0], code=pair[1])
                    or row['selection']['relation'] != relation
                    or row['selection']['group'] != 'type01-integrated'
                    or row['selection']['topic'] != ':'.join(pair)
                    or row['conditions']['clauses'] != [dict(kind='type', family=pair[0], code=pair[1])]):
                raise ValueError('통합/추가 자료 연결 오류')
            used.add(key)
            if relation == 'additional' and (not row['conflict'] or not row['selection']['basis']):
                raise ValueError('추가 해석 차이 설명 누락')
    if actual != expected or used != set(items) or used_notes != set(notes):
        raise ValueError('기질27/성격27 통합 또는 추가 자료 누락')


def inspect_type_library(connection, data=None):
    """값을 쓰지 않고 추가 예정·그대로 유지·충돌을 보고한다."""
    data = data or load_type_data()
    source_rows = {r['seed_key']: dict(r) for r in connection.execute(select(sources)).mappings()}
    item_rows = {r['seed_key']: dict(r) for r in connection.execute(select(interpretations)).mappings()}
    common = [r for r in data['interpretations'] if r['selection']['relation'] == 'common']
    default_types = {(r['related_type']['family'], r['related_type']['code']) for r in common
                     if r['edition'] in ('adult', 'common') and r['conditions']['status'] == 'match'}
    result = dict(packaged_items=len(data['interpretations']), packaged_types=len(data['integration']),
                  packaged_transcriptions=len(data['transcriptions']), packaged_integrated_types=len(common),
                  packaged_additional_items=len(data['interpretations'])-len(common),
                  packaged_comparison_notes=len(data['comparison_notes']),
                  packaged_default_types=len(default_types),
                  packaged_reference_types=len(common)-len(default_types), missing_sources=[], missing_items=[],
                  unchanged_items=0, conflicts=[], database_types=0, database_items=0)
    result['legacy_transcription_items'] = sum(r['seed_key'] in item_rows for r in data['transcriptions'])
    # 이전57개 팩을 넣은 DB도 사용자 행을 자동 중지/변경하지 않고 별도로 알린다.
    result['existing_comparison_items'] = [dict(key=n['excluded_seed_key'],
        active=item_rows[n['excluded_seed_key']]['active']) for n in data['comparison_notes']
        if n['excluded_seed_key'] in item_rows]
    required_source_keys = {r['source_key'] for r in data['interpretations']}
    for expected in data['sources']:
        current = source_rows.get(expected['seed_key'])
        if current is None:
            if expected['seed_key'] in required_source_keys:
                result['missing_sources'].append(expected['seed_key'])
        else:
            fields = [k for k,v in expected.items() if current[k] != v]
            if fields:
                result['conflicts'].append(dict(kind='source',key=expected['seed_key'],fields=fields))
    types = set()
    for row in data['interpretations']:
        current = item_rows.get(row['seed_key'])
        if current is None:
            result['missing_items'].append(row['seed_key'])
            continue
        result['database_items'] += 1
        if current['related_type']:
            types.add((current['related_type'].get('family'), current['related_type'].get('code')))
        fields = [k for k,v in row.items() if k != 'source_key' and current[k] != v]
        source = source_rows.get(row['source_key'])
        if source is None or current['source_id'] != source['id']:
            fields.append('source_id')
        if fields:
            result['conflicts'].append(dict(kind='item',key=row['seed_key'],fields=fields))
        else:
            result['unchanged_items'] += 1
    result['database_types'] = len(types)
    # 제품의 자료 기반 사용 가능 수와 검사판 확인 수를 분리한다.
    from .candidates import evaluate_item, provided_integrated
    from .scores import DEFAULT_SETTINGS, report_types
    def usable(row, source):
        if (not provided_integrated(row) or row.get('section') not in SECTIONS
                or not isinstance(row.get('description'), str) or not row['description'].strip()):
            return False
        family, code = row['related_type']['family'], row['related_type']['code']
        scales = ('NS', 'HA', 'RD') if family == 'temperament' else ('SD', 'CO', 'ST')
        scores = {scale: dict(t=dict(H='60', M='50', L='40')[grade]) for scale, grade in zip(scales, code)}
        return (row.get('active', True) and source.get('active', True)
                and evaluate_item(row, source, scores, report_types(scores, DEFAULT_SETTINGS))['category'] == 'match')
    packaged_sources = {r['seed_key']: r for r in data['sources']}
    result['packaged_provided_draft_types'] = sum(usable(r, packaged_sources[r['source_key']]) for r in common)
    result['packaged_edition_confirmed_types'] = len(default_types)
    result['database_provided_draft_types'] = sum(
        usable(item_rows[r['seed_key']], source_rows[r['source_key']]) for r in common
        if r['seed_key'] in item_rows and r['source_key'] in source_rows
        and item_rows[r['seed_key']]['source_id'] == source_rows[r['source_key']]['id'])
    return result


def seed_type_library(connection):
    data = load_type_data()
    # initial seed-library와 같은 잠금으로 안정 키 경쟁을 직렬화한다.
    if connection.dialect.name == 'postgresql':
        connection.execute(text('SELECT pg_advisory_xact_lock(7403103)'))
    # 누락 원고에 필요한 소스만 추가한다. 기존 소스/원고의 편집·중지는 갱신하지 않는다.
    current_keys = set(connection.execute(select(interpretations.c.seed_key)).scalars())
    missing = [r for r in data['interpretations'] if r['seed_key'] not in current_keys]
    source_ids = {r.seed_key: r.id for r in connection.execute(select(sources.c.seed_key, sources.c.id))}
    needed = {r['source_key'] for r in missing}
    added_sources = added_items = 0
    for row in data['sources']:
        if row['seed_key'] in needed and row['seed_key'] not in source_ids:
            source_ids[row['seed_key']] = connection.execute(sources.insert().values(**row)).inserted_primary_key[0]
            added_sources += 1
    for raw in missing:
        row = dict(raw)
        row['source_id'] = source_ids[row.pop('source_key')]
        connection.execute(interpretations.insert().values(**row))
        added_items += 1
    return dict(added_sources=added_sources, added_items=added_items,
                **inspect_type_library(connection, data))


def init_app(app):
    @app.cli.command('seed-type-library')
    @click.option('--apply', 'apply_changes', is_flag=True,
                  help='없는 통합·추가 원고만 등록. 기존 전사·편집·중지·연결은 유지.')
    def command(apply_changes):
        """기본은 읽기 전용 점검. 적용판 미확인 54유형 통합·추가 원고 팩."""
        try:
            if apply_changes:
                with get_engine().begin() as connection:
                    result = seed_type_library(connection)
            else:
                with get_engine().connect() as connection:
                    if connection.dialect.name == 'postgresql':
                        connection.execute(text('SET TRANSACTION READ ONLY'))
                    result = inspect_type_library(connection)
            click.echo(json.dumps(dict(mode='apply' if apply_changes else 'read-only', **result),
                                  ensure_ascii=False, indent=2))
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
