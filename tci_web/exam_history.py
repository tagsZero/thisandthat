"""Read-only summaries shared by the two existing examination lists."""
from uuid import UUID

from flask import current_app, g, request, url_for
from sqlalchemy import String, cast, func, literal, select, union_all
from sqlalchemy.exc import SQLAlchemyError

from .db import get_engine, reports

PAGE_SIZE = 20


def reference_key(value):
    """Only ordinary edge spaces are ignored; never change stored values."""
    return (value or '').strip(' ')


def history_query(reference, owner_id):
    from khtp_web import jobs

    def summary(table, kind, timestamp):
        return select(literal(kind).label('kind'), cast(table.c.id, String).label('id'),
                      table.c.name, table.c.reference, table.c.exam_date,
                      timestamp.label('saved_at')).where(func.trim(table.c.reference, ' ') == reference)

    combined = union_all(summary(reports, 'TCI', reports.c.updated_at),
                         summary(jobs, 'K-HTP', jobs.c.last_used).where(jobs.c.owner_id == owner_id)).subquery()
    return select(combined).order_by(combined.c.exam_date.desc().nulls_last(),
                                    combined.c.saved_at.desc(), combined.c.kind, combined.c.id)


def load_history(kind, endpoint, list_state):
    """Use an authorized saved source, a separate connection and summary columns only."""
    source = request.args.get('history')
    if source is None:
        return None
    result = dict(rows=[], error='', page=1, has_next=False,
                  close_url=url_for(endpoint, **list_state))
    try:
        if kind == 'TCI':
            if not source.isascii() or not source.isdecimal() or len(source) > 10:
                raise ValueError
            source_id = int(source)
            if not 0 < source_id <= 2147483647:
                raise ValueError
            source_query = select(reports.c.reference).where(reports.c.id == source_id)
        else:
            from khtp_web import jobs
            source_id = str(UUID(source))
            source_query = select(jobs.c.reference).where(jobs.c.id == source_id, jobs.c.owner_id == g.user['id'])
        page = min(1000000, max(1, request.args.get('history_page', 1, type=int) or 1))
        with get_engine().connect() as connection:
            row = connection.execute(source_query).first()
            if row is None:
                raise ValueError
            reference = reference_key(row.reference)
            if not reference:
                result['error'] = '관리번호가 없는 기록은 검사 이력으로 연결하지 않습니다.'
                return result
            rows = connection.execute(history_query(reference, g.user['id'])
                                      .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE + 1)).mappings().all()
        result.update(rows=rows[:PAGE_SIZE], reference=reference, page=page, has_next=len(rows) > PAGE_SIZE)
        result['previous_url'] = url_for(endpoint, **list_state, history=source, history_page=page-1, _anchor='exam-history') if page > 1 else None
        result['next_url'] = url_for(endpoint, **list_state, history=source, history_page=page+1, _anchor='exam-history') if result['has_next'] else None
    except (ValueError, TypeError, AttributeError):
        result['error'] = '검사 이력을 조회할 수 없는 기록입니다. 목록에서 다시 선택해 주세요.'
    except SQLAlchemyError as exc:
        current_app.logger.warning('Examination history query failed: %s', type(exc).__name__)
        result['error'] = '검사 이력을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'
    return result
