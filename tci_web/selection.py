"""사람이 확인한 해석 연결. 관련성은 개인 조건 일치와 별도로 사용한다."""
import re
from itertools import product

from .scores import SCALES, SUBSCALES

TOPICS = {f'scale:{code}': f'{code} {label}' for code, label, _ in SCALES}
TOPICS.update({f'scale:{code}': f'{code} {label}' for rows in SUBSCALES.values() for code, label in rows})
TOPICS['scale:SC'] = 'SC 제공된 수치'
for family, label in [('temperament', '기질'), ('character', '성격')]:
    TOPICS.update({f'{family}:{code}': f'{label}유형 {code}' for code in map(''.join, product('HML', repeat=3))})
TOPICS.update({'combined:SC': 'SC와 기질 반응 조절', 'combined:general': '기질·성격 연계'})
RELATIONS = {'common': '공통 설명', 'additional': '추가 관점', 'alternative': '대안 설명'}


def validate_selection(value):
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {'topic', 'group', 'relation', 'basis'}
            or value['topic'] not in TOPICS or value['relation'] not in RELATIONS
            or not isinstance(value['group'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', value['group'])
            or not isinstance(value['basis'], str) or not value['basis'].strip()):
        raise ValueError('해석 주제·선택 묶음·관계·원문 대조 근거를 확인해 주세요.')
    return dict(value)


def group_id(selection):
    return selection['topic'] + '/' + selection['group'] if selection else None


def item_topic(item):
    link = item.get('selection')
    if link:
        return link['topic']
    related = item.get('related_type')
    if related:
        return related['family'] + ':' + related['code']
    scales = item.get('related_scales') or []
    return 'scale:' + scales[0] if scales else 'combined:general'
