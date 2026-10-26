"""Small observation contracts; detector output is evidence, never a diagnosis."""
from copy import deepcopy
import hashlib
from io import BytesIO
import math
import warnings

IDS = tuple(f'O{g}.{i}' for g, n in enumerate((2, 4, 5, 4, 4, 2, 2, 1), 1) for i in range(1, n + 1))
STATES = ('observed', 'absent', 'unobserved', 'uncertain')
STATE_LABELS = dict(zip(STATES, ('관찰됨', '없음 확인', '아직 관찰하지 않음', '판단불가')))
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 20_000_000


def normalize_image(raw):
    from PIL import Image, ImageOps, UnidentifiedImageError
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError('20MB 이하의 JPEG 또는 PNG 한 장을 선택해 주세요.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as source:
                if source.format not in ('JPEG', 'PNG') or getattr(source, 'n_frames', 1) != 1:
                    raise ValueError('움직이지 않는 JPEG 또는 PNG 한 장이 필요합니다.')
                w, h = source.size
                if w < 32 or h < 32 or w * h > MAX_PIXELS:
                    raise ValueError('이미지는 가로·세로32픽셀 이상, 전체2천만픽셀 이하여야 합니다.')
                orientation = source.getexif().get(274, 1)
                if orientation not in range(1, 9):
                    raise ValueError('이미지 방향 정보를 확인할 수 없습니다.')
                source.load()
                fixed = ImageOps.exif_transpose(source).convert('RGBA')
                image = Image.new('RGBA', fixed.size, 'white')
                image.alpha_composite(fixed)
                image = image.convert('RGB')
                # A new canvas deliberately strips source EXIF/ICC/text metadata.
                clean = Image.new('RGB', image.size)
                clean.paste(image)
                output = BytesIO()
                clean.save(output, format='PNG')
        return output.getvalue(), dict(width=clean.width, height=clean.height,
            original_width=w, original_height=h, exif_orientation=orientation,
            transform='EXIF transpose; inverse is defined by original dimensions and orientation',
            source_sha256=hashlib.sha256(raw).hexdigest())
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as error:
        raise ValueError('읽을 수 있는 JPEG 또는 PNG 이미지인지 확인해 주세요.') from error


def validate_pack(pack):
    if not isinstance(pack, dict) or not isinstance(pack.get('version'), str) or not 1 <= len(pack['version']) <= 100:
        raise ValueError('자료 버전이 필요합니다.')
    if [row.get('id') for row in pack.get('items', [])] != list(IDS):
        raise ValueError('기존24개 ID와 순서를 유지해야 합니다.')
    if [row.get('id') for row in pack.get('groups', [])] != [f'O{i}' for i in range(1, 9)]:
        raise ValueError('기존8개 그룹이 필요합니다.')
    if [sum(r.get('kind') == k for r in pack['items']) for k in 'ABC'] != [2, 15, 7]:
        raise ValueError('조건부 계산2·후보15·직접관찰7을 유지해야 합니다.')
    candidates={'O2.1','O2.2','O2.3','O3.1','O3.2','O3.3','O3.4','O4.1','O4.2','O4.3','O4.4','O5.1','O5.2','O5.3','O5.4'}
    for row in pack['items']:
        expected='A' if row['id'] in ('O2.4','O8.1') else 'B' if row['id'] in candidates else 'C'
        if row['kind']!=expected or expected=='B' and row.get('model') not in ('house','tree','person'):
            raise ValueError('항목별 자동 관찰 범위를 유지해야 합니다.')
        for field in ('title', 'definition', 'exclusions', 'unit', 'uncertainty', 'model'):
            if not isinstance(row.get(field), str) or len(row[field]) > 3000:
                raise ValueError('관찰 정의의 문자열을 확인해 주세요.')
        if not isinstance(row.get('labels'), list) or any(not isinstance(v, str) for v in row['labels']):
            raise ValueError('모델 라벨 목록을 확인해 주세요.')
    if not isinstance(pack.get('sources'), list) or not pack['sources'] or len(pack.get('photo_limits', [])) != 3:
        raise ValueError('출처와 사진 한계3개가 필요합니다.')
    if any(not isinstance(pack.get(k),str) for k in ('title','notice')) or any(not isinstance(g.get('title'),str) for g in pack['groups']):
        raise ValueError('양식 제목과 적용 한계를 확인해 주세요.')
    if any(not isinstance(item.get(k),str) for item in pack['photo_limits'] for k in ('title','reason')):
        raise ValueError('사진 한계의 항목·이유를 확인해 주세요.')
    for source in pack['sources']:
        if any(not isinstance(source.get(k), str) for k in ('id','title','url','location','note')):
            raise ValueError('출처의 서지·위치·한계를 확인해 주세요.')
        if source['url'] and not source['url'].startswith('https://'):
            raise ValueError('출처 링크는 HTTPS 주소만 허용합니다.')
    return deepcopy(pack)


def blank_observations(pack):
    return {row['id']: dict(state='unobserved', text='', reason='직접 관찰 필요' if row['kind'] == 'C' else '아직 실행하지 않음',
        author='auto', regions=[], candidates=[], refs=[]) for row in pack['items']}


def valid_box(box, width, height):
    return (isinstance(box, list) and len(box) == 4
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in box)
        and 0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height)


def overlap(a, b):
    area = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    return area / min((a[2]-a[0])*(a[3]-a[1]), (b[2]-b[0])*(b[3]-b[1]))


def merge_analysis(current, pack, result, dimensions):
    value = deepcopy(current)
    models = result.get('models', {})
    all_candidates = []
    for model, execution in models.items():
        if execution.get('status') != 'ok':
            continue
        for candidate in execution.get('detections', []):
            box = candidate.get('xyxy')
            if not valid_box(box, dimensions['width'], dimensions['height']):
                continue
            key = f"{model}:{candidate['label']}:" + ','.join(str(round(x, 2)) for x in box)
            all_candidates.append(dict(id='r'+hashlib.sha256(key.encode()).hexdigest()[:16],
                box=box, label=candidate['label'], model=model, parent=None, confirmed=False,
                confidence=candidate['confidence']))
    for definition in pack['items']:
        if definition['kind'] != 'B':
            continue
        id = definition['id']
        selected = ('personf', 'personm') if definition['model'] == 'person' else (definition['model'],)
        candidates = [deepcopy(c) for c in all_candidates if c['model'] in selected and c['label'] in definition['labels']]
        old = value[id]
        old['candidates'] = candidates
        if old['author'] == 'user':
            continue
        complete = all(models.get(m, {}).get('status') == 'ok' for m in selected)
        successful = any(models.get(m, {}).get('status') == 'ok' for m in selected)
        state, text = 'unobserved', ''
        reason = '자동 분석을 실행하지 못했습니다. 다시 시도할 수 있습니다.'
        if candidates:
            state, text = 'observed', definition['title'] + '로 보이는 영역 후보 — 자동 초안'
            reason = '존재·개수·전체 경계와 부모 귀속은 확인 필요합니다.'
            competing_pairs = ({'문','창문'}, {'지붕','산'}, {'나무전체','꽃'}, {'나뭇잎','열매'}, {'나뭇잎','꽃'})
            competing = any(overlap(c['box'], d['box']) > .65 and {c['label'],d['label']} in competing_pairs
                for c in candidates for d in all_candidates if c['model'] == d['model'])
            if competing or id in ('O4.2', 'O5.2'):
                state = 'uncertain'
                reason = '종류 또는 범위·단위를 확정할 수 없습니다. 후보 영역을 확인해 주세요.'
            if not complete:
                state = 'uncertain'
                reason += ' 일부 모델 실행에 실패했습니다.'
        elif complete:
            state, reason = 'uncertain', '자동으로 찾지 못함. 없다는 뜻이 아닙니다.'
        elif successful:
            reason = '일부 모델 실행에 실패했습니다. 관찰을 완료하지 않았습니다.'
        value[id].update(state=state, text=text, reason=reason, regions=candidates)
    # Replacing automatic candidates can remove a parent used by a user row.
    # Preserve the observation and its region; only invalidate the lost link.
    parents = {r['id'] for id in ('O2.1','O2.2','O2.3','O3.3') for r in value[id]['regions']}
    for row in value.values():
        for region in row['regions']:
            if region.get('parent') and region['parent'] not in parents:
                region['parent'] = None
    return recalculate(value, dimensions), [c for c in all_candidates if c['model'] == 'tree' and c['label'] in ('나뭇잎','열매')]


def recalculate(value, dimensions):
    target = value['O2.4']
    if target['author'] != 'user':
        texts = []
        for id in ('O2.1','O2.2','O2.3'):
            for index,region in enumerate(value[id]['regions'],1):
                if value[id]['state'] == 'observed' and region.get('confirmed'):
                    x1,y1,x2,y2 = region['box']
                    if valid_box(region['box'], dimensions['width'], dimensions['height']):
                        title={'O2.1':'집','O2.2':'나무','O2.3':'사람'}[id]
                        texts.append(f"{title} 영역{index}: 중심({(x1+x2)/2:.1f}, {(y1+y2)/2:.1f})px, 폭{x2-x1:.1f}px / 높이{y2-y1:.1f}px, 이미지 폭 대비{100*(x2-x1)/dimensions['width']:.1f}% / 높이 대비{100*(y2-y1)/dimensions['height']:.1f}%")
        target.update(state='observed' if texts else 'unobserved', text='\n'.join(texts),
            reason='사용자가 확인한 전체 경계의 이미지 기준 값입니다. 종이·선 면적 비율이 아닙니다.' if texts else '전체 경계를 확인한 객체가 없어 계산하지 않았습니다.')
    refs = []
    for id in IDS[:-1]:
        row = value[id]
        if row['state'] in ('unobserved','uncertain') or row['author'] == 'auto' and row['regions']:
            refs.append(dict(item=id, region=None, reason=row['reason'] or STATE_LABELS[row['state']]))
        for region in row['regions']:
            if row['state'] != 'absent' and id.startswith(('O3.', 'O4.', 'O5.')) and not region.get('parent'):
                refs.append(dict(item=id, region=region['id'], reason='부모 귀속 미정'))
    value['O8.1'].update(state='uncertain' if refs else 'observed',
        text=f'확인할 참조 {len(refs)}개' if refs else '남은 미확인 참조 없음',
        reason='미실행·판단불가·후보 또는 귀속 확인입니다. 오류 수나 심리 점수가 아닙니다.',
        author='auto', refs=refs, regions=[])
    return value


def apply_edits(current, edits, dimensions):
    if not isinstance(edits, dict) or any(id not in IDS[:-1] for id in edits):
        raise ValueError('수정할 관찰 항목을 확인해 주세요.')
    value = deepcopy(current)
    for id, edit in edits.items():
        if not isinstance(edit, dict) or edit.get('state') not in STATES:
            raise ValueError('관찰 상태를 확인해 주세요.')
        for field in ('text', 'reason'):
            if not isinstance(edit.get(field), str) or len(edit[field]) > 12000:
                raise ValueError('관찰 내용·이유는 각각12,000자 이내로 입력해 주세요.')
        regions = edit.get('regions')
        if not isinstance(regions, list) or len(regions) > 100:
            raise ValueError('근거 영역 목록을 확인해 주세요.')
        clean = []
        for region in regions:
            if (not isinstance(region, dict) or not isinstance(region.get('id'), str)
                    or not 1 <= len(region['id']) <= 64 or not valid_box(region.get('box'), dimensions['width'], dimensions['height'])
                    or not isinstance(region.get('confirmed', False), bool)
                    or region.get('parent') is not None and not isinstance(region['parent'], str)):
                raise ValueError('영역은 그림 안의 유효한 x,y,폭,높이로 입력해 주세요.')
            clean.append(dict(id=region['id'], box=region['box'], parent=region.get('parent'),
                confirmed=region.get('confirmed', False) if id in ('O2.1','O2.2','O2.3') else False,
                label=value[id]['text'][:100], model='user'))
        value[id].update(state=edit['state'],text=edit['text'],reason=edit['reason'],regions=clean,author='user')
    region_ids = [r['id'] for row in value.values() for r in row['regions']]
    if len(region_ids) != len(set(region_ids)):
        raise ValueError('근거 영역 ID가 중복되었습니다.')
    parents = {r['id'] for id in ('O2.1','O2.2','O2.3','O3.3') for r in value[id]['regions']}
    for row in value.values():
        for region in row['regions']:
            if region.get('parent') and (region['parent'] not in parents or region['parent'] == region['id']):
                raise ValueError('부모 영역 ID는 현재 그림의 객체 또는 창문 영역이어야 합니다.')
    return recalculate(value, dimensions)
