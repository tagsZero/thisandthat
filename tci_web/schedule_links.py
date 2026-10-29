"""Keep owned appointment identities stable when an exam is reassigned.

Call inside the examination save transaction, after locking its owner user and
successfully updating the examination. Never move an appointment to another person.
"""
from sqlalchemy import select

from .db import appointments, utc_now


def detach_mismatched_links(connection, kind, exam_id, owner_id, person_id):
    if kind not in ('tci', 'khtp'):
        raise ValueError('Invalid examination kind')
    if person_id is None:
        return 0
    key = appointments.c.report_id if kind == 'tci' else appointments.c.job_id
    condition = (appointments.c.owner_id == owner_id, key == exam_id,
                 appointments.c.person_id.is_not(None), appointments.c.person_id != person_id)
    identifiers = list(connection.scalars(select(appointments.c.id).where(*condition)
        .order_by(appointments.c.id).with_for_update()))
    if not identifiers:
        return 0
    changed = connection.execute(appointments.update().where(*condition,
        appointments.c.id.in_(identifiers)).values({key.name: None,
            'revision': appointments.c.revision + 1, 'updated_at': utc_now()})
        .returning(appointments.c.id)).all()
    return len(changed)


def reassignment_notice(count):
    if not count:
        return ''
    return (f'대상자가 달라진 일정 {count}건의 검사 연결을 해제했습니다. '
            '일정의 대상자와 시간은 유지됩니다.')
