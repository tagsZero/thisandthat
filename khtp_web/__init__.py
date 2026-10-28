"""Persistent K-HTP records with a single observation editor."""
from copy import deepcopy
from datetime import date, datetime
from functools import wraps
import base64
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import sys
import uuid
from zoneinfo import ZoneInfo

import click
from flask import Blueprint, abort, current_app, g, make_response, render_template, request, session, url_for
from sqlalchemy import Column, Date, DateTime, ForeignKey, Index, Integer, LargeBinary, MetaData, String, Table, cast, inspect, or_, select
from sqlalchemy.exc import SQLAlchemyError

from tci_web.auth import login_required
from tci_web.db import get_engine, json_type, metadata, users, utc_now
from tci_web.exam_history import load_history, reference_key
from tci_web.pdf_export import render_pdf
from tci_web.permissions import get_exam, readable_condition
from .domain import (MAX_BYTES, STATE_LABELS, apply_edits, blank_observations,
    merge_analysis, normalize_image, recalculate, validate_pack)

bp = Blueprint('khtp', __name__, url_prefix='/khtp')


@bp.after_request
def private_response(response):
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response


@bp.errorhandler(413)
def too_large(exc):
    return dict(message='20MB 이하의 JPEG 또는 PNG 한 장을 선택해 주세요.'),413


packs = Table('khtp_packs', metadata,
    Column('id',Integer,primary_key=True), Column('version',String(100),unique=True,nullable=False),
    Column('digest',String(64),nullable=False), Column('content',json_type,nullable=False),
    Column('created_at',DateTime(timezone=True),nullable=False,default=utc_now))
jobs = Table('khtp_jobs', metadata,
    Column('id',String(36),primary_key=True),Column('owner_id',ForeignKey('users.id'),nullable=False),
    Column('image',LargeBinary,nullable=False),Column('dimensions',json_type,nullable=False),
    Column('pack',json_type,nullable=False),Column('observations',json_type,nullable=False),
    Column('analysis',json_type,nullable=False),Column('extras',json_type,nullable=False),
    Column('subject',json_type,nullable=True),
    Column('name',String(100),nullable=True),Column('reference',String(100),nullable=True),
    Column('exam_date',Date,nullable=True),
    Column('revision',Integer,nullable=False),Column('last_used',DateTime(timezone=True),nullable=False),
    Column('expires_at',DateTime(timezone=True),nullable=False))
Index('ix_khtp_jobs_owner_last_used_id',jobs.c.owner_id,jobs.c.last_used.desc(),jobs.c.id.desc())


def error(message, status=422, **extra):
    return dict(message=message,**extra),status


def api(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        if not g.user:
            return error('로그인이 만료되었습니다. 다른 탭에서 로그인한 뒤 다시 시도하세요. 현재 입력은 유지됩니다.',401)
        if request.method != 'GET' and not secrets.compare_digest(request.headers.get('X-KHTP-CSRF',''),session.get('khtp_csrf','-')):
            return error('로그인 세션이 바뀌었습니다. 현재 입력을 보관한 뒤 새로고침해 주세요.',403)
        try:
            return view(*args,**kwargs)
        except (ValueError,KeyError,TypeError) as exc:
            return error(str(exc))
        except SQLAlchemyError as exc:
            current_app.logger.error('KHTP database operation failed: %s',type(exc).__name__)
            return error('저장소에 연결하지 못했습니다. 현재 입력은 유지됩니다. 준비 상태를 확인한 뒤 다시 시도하세요.',503,save_state='failed')
    return wrapped


def find(connection,id):
    row = connection.execute(select(jobs).where(jobs.c.id==id,jobs.c.owner_id==g.user['id'])).mappings().first()
    if row is None:
        abort(404)
    row = deepcopy(dict(row))
    row['subject']=subject_view(row)
    return row


def subject_view(row):
    """The independent columns are the only runtime source of subject data."""
    return dict(name=row.get('name') or '',reference=row.get('reference') or '',
        exam_date=row['exam_date'].isoformat() if row.get('exam_date') else '')


def subject_columns(value):
    return dict(name=value['name'],reference=value['reference'],
        exam_date=date.fromisoformat(value['exam_date']) if value['exam_date'] else None)


def public(row):
    return {key:deepcopy(row[key]) for key in ('id','dimensions','pack','observations','analysis','extras','revision')} | {
        'subject':subject_view(row), 'url':url_for('khtp.workspace',id=row['id']),
        'image_url':url_for('khtp.image',id=row['id'])}


def validate_subject(value):
    if not isinstance(value,dict) or any(not isinstance(value.get(key,''),str) for key in ('name','reference','exam_date')):
        raise ValueError('대상 정보를 확인해 주세요.')
    subject={key:value.get(key,'').strip() for key in ('name','reference','exam_date')}
    if not subject['name'] and not subject['reference']:
        raise ValueError('이름 또는 관리번호 중 하나를 입력해 주세요.')
    if len(subject['name'])>100 or len(subject['reference'])>100:
        raise ValueError('이름과 관리번호는 각각 100자 이내로 입력해 주세요.')
    if subject['exam_date']:
        try:
            subject['exam_date']=date.fromisoformat(subject['exam_date']).isoformat()
        except ValueError as exc:
            raise ValueError('검사일을 확인해 주세요.') from exc
    return subject


def commit_edit(connection,row,payload,**extra):
    if type(payload.get('revision')) is not int or payload['revision']!=row['revision']:
        raise Conflict()
    value = apply_edits(row['observations'],payload.get('edits',{}),row['dimensions'])
    if 'subject' in payload:
        extra.update(subject_columns(validate_subject(payload['subject'])))
    now = utc_now()
    changes = dict(observations=value,revision=row['revision']+1,last_used=now,**extra)
    changed = connection.execute(jobs.update().where(jobs.c.id==row['id'],jobs.c.owner_id==g.user['id'],
        jobs.c.revision==row['revision']).values(**changes))
    if changed.rowcount!=1:
        raise Conflict()
    row.update(changes)
    row['subject']=subject_view(row)
    return row


class Conflict(Exception):
    pass


def conflict():
    return error('다른 요청에서 작업이 변경되었습니다. 현재 입력을 보관한 뒤 새로고침해 최신 작업을 확인하세요.',409)


@bp.get('')
@login_required
def index():
    query=request.args.get('q','').strip()
    page=max(1,request.args.get('page',1,type=int) or 1)
    page=min(page,1000000)
    statement=select(jobs.c.id,jobs.c.name,jobs.c.reference,jobs.c.exam_date,jobs.c.last_used,
        jobs.c.owner_id,users.c.username.label('owner_username')).join(users,jobs.c.owner_id==users.c.id).where(
            readable_condition(jobs,'khtp'))
    if query:
        statement=statement.where(or_(jobs.c.name.icontains(query,autoescape=True),
            jobs.c.reference.icontains(query,autoescape=True),cast(jobs.c.exam_date,String).contains(query,autoescape=True)))
    try:
        with get_engine().connect() as connection:
            rows=connection.execute(statement.order_by(jobs.c.last_used.desc(),jobs.c.id.desc()).offset((page-1)*20).limit(21)).mappings().all()
    except SQLAlchemyError:
        return render_template('khtp/records.html',active='khtp',records=[],query=query,page=1,has_next=False,
            storage_error='검사 목록을 불러오지 못했습니다. 저장소 준비 상태를 확인한 뒤 다시 시도하세요.'),503
    records=[dict(row,is_owner=row['owner_id']==g.user['id'],
        has_history_reference=bool(reference_key(row['reference']))) for row in rows[:20]]
    history=load_history('K-HTP','khtp.index',dict(q=query,page=page))
    return render_template('khtp/records.html',active='khtp',records=records,query=query,page=page,has_next=len(rows)>20,history=history)


@bp.get('/new')
@login_required
def new():
    return editor()


@bp.get('/<uuid:id>')
@login_required
def workspace(id):
    with get_engine().connect() as connection:
        if not connection.execute(select(jobs.c.id).where(jobs.c.id==str(id),jobs.c.owner_id==g.user['id'])).first():
            abort(404)
    return editor(str(id))


def editor(id=''):
    session.setdefault('khtp_csrf',secrets.token_urlsafe(24))
    return render_template('khtp/workspace.html',active='khtp',csrf=session['khtp_csrf'],job_id=id,
        today=datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat())


@bp.get('/current')
@api
def current():
    """Compatibility token endpoint; never select a record via shared session state."""
    csrf=session.setdefault('khtp_csrf',secrets.token_urlsafe(24))
    return dict(job=None,csrf=csrf)


@bp.get('/<uuid:id>/data')
@api
def data(id):
    with get_engine().connect() as connection:
        return dict(job=public(get_exam(connection,'khtp',str(id))))


@bp.post('/upload')
@api
def upload():
    request.max_content_length = MAX_BYTES + 1024*1024
    subject=validate_subject({key:request.form.get(key,'') for key in ('name','reference','exam_date')})
    uploaded = request.files.get('image')
    if uploaded is None:
        return error('그림 한 장을 선택해 주세요.')
    try:
        image,dimensions = normalize_image(uploaded.stream.read(MAX_BYTES+1))
    except ImportError:
        return error('그림 처리 환경이 준비되지 않았습니다. 관리자에게 초기 설정을 확인해 주세요.',503)
    with get_engine().begin() as connection:
        pack = connection.execute(select(packs.c.content).order_by(packs.c.id.desc())).scalar()
        if pack is None:
            return error('기본 자료가 준비되지 않았습니다. 관리자에게 초기 설정을 확인해 주세요.',503)
        now = utc_now()
        row = dict(id=str(uuid.uuid4()),owner_id=g.user['id'],image=image,dimensions=dimensions,pack=pack,
            **subject_columns(subject),
            observations=recalculate(blank_observations(pack),dimensions),analysis=dict(status='not_run'),extras=[],
            revision=1,last_used=now,expires_at=now)  # Legacy NOT NULL column; never used for retention.
        connection.execute(jobs.insert().values(**row))
    return dict(job=public(row)),201


@bp.get('/<uuid:id>/image')
@api
def image(id):
    with get_engine().connect() as connection:
        row = get_exam(connection,'khtp',str(id))
    response = make_response(row['image'])
    response.headers.update({'Content-Type':'image/png','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
    return response


def run_inference(image):
    result = subprocess.run([sys.executable,str(Path(__file__).with_name('worker.py'))],input=image,
        capture_output=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
    if result.returncode:
        raise RuntimeError('local inference worker failed')
    value = json.loads(result.stdout)
    if not isinstance(value.get('models'),dict):
        raise ValueError('invalid inference result')
    return value


@bp.post('/<uuid:id>/analyze')
@api
def analyze(id):
    id=str(id)
    try:
        with get_engine().begin() as connection:
            row = commit_edit(connection,find(connection,id),request.get_json(),analysis=dict(status='running'))
    except Conflict:
        return conflict()
    try:
        result = run_inference(row['image'])
        state = 'ok' if all(result['models'].get(m,{}).get('status')=='ok' for m in ('house','tree','personf','personm')) else 'partial'
    except Exception:
        current_app.logger.exception('KHTP local inference failed')
        result,state = dict(models={}), 'failed'
    observations,extras = merge_analysis(row['observations'],row['pack'],result,row['dimensions'])
    changes = dict(observations=observations,analysis=dict(status=state,result=result),extras=extras,revision=row['revision']+1)
    with get_engine().begin() as connection:
        changed = connection.execute(jobs.update().where(jobs.c.id==id,jobs.c.owner_id==g.user['id'],
            jobs.c.revision==row['revision']).values(**changes))
        if changed.rowcount != 1:
            return conflict()
    row.update(changes)
    message = '자동 후보를 준비했습니다. 필요한 부분만 수정하세요.' if state=='ok' else '분석의 일부 또는 전체를 실행하지 못했습니다. 수정 내용은 유지됩니다. 다시 분석하거나 현재 표를 PDF로 받을 수 있습니다.'
    return dict(job=public(row),message=message)


@bp.post('/<uuid:id>/save')
@api
def save(id):
    try:
        with get_engine().begin() as connection:
            row=commit_edit(connection,find(connection,str(id)),request.get_json())
    except Conflict:
        return conflict()
    return dict(job=public(row),message='현재 내용을 저장했습니다.')


def pdf_bytes(row):
    assets=Path(current_app.static_folder)
    fonts={weight:base64.b64encode((assets/'fonts'/('NotoSansCJKkr-'+name+'.otf')).read_bytes()).decode('ascii')
        for weight,name in (('normal','Regular'),('bold','Bold'))}
    html=render_template('khtp/pdf.html',job=row,states=STATE_LABELS,fonts=fonts,
        image_data=base64.b64encode(row['image']).decode('ascii'))
    return render_pdf(html)


@bp.post('/<uuid:id>/pdf')
@api
def pdf(id):
    try:
        with get_engine().begin() as connection:
            row=commit_edit(connection,find(connection,str(id)),request.get_json())
    except Conflict:
        return conflict()
    snapshot=deepcopy(row)
    try:
        data=pdf_bytes(snapshot)
    except Exception:
        current_app.logger.exception('KHTP PDF failed after save')
        return error('현재 내용은 저장됐지만 PDF 생성에 실패했습니다. PDF 받기를 다시 눌러 주세요.',503,
            save_state='saved',job=public(snapshot))
    response=make_response(data)
    response.headers.update({'Content-Type':'application/pdf','Cache-Control':'no-store',
        'Content-Disposition':'attachment; filename="KHTP-observation.pdf"',
        'X-KHTP-Revision':str(snapshot['revision']),'X-KHTP-Save-State':'saved'})
    return response


def import_pack(connection,value):
    pack=validate_pack(value)
    digest=hashlib.sha256(json.dumps(pack,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    existing=connection.execute(select(packs).where(packs.c.version==pack['version'])).mappings().first()
    if existing:
        if existing['digest']!=digest:
            raise ValueError('같은 버전의 내용은 변경할 수 없습니다. 새 버전을 지정해 주세요.')
        return False
    connection.execute(packs.insert().values(version=pack['version'],digest=digest,content=pack))
    return True


def upgrade_records(connection):
    """Atomic, one-time extraction. Existing columns (including blanks) always win."""
    if connection.dialect.name=='postgresql':
        # Serialize concurrent setup before checking/creating tables.
        connection.exec_driver_sql('SELECT pg_advisory_xact_lock(1800241024)')
    packs.create(connection,checkfirst=True)
    jobs.create(connection,checkfirst=True)
    if connection.dialect.name=='postgresql':
        connection.exec_driver_sql('LOCK TABLE khtp_jobs IN ACCESS EXCLUSIVE MODE')
    columns={column['name'] for column in inspect(connection).get_columns('khtp_jobs')}
    target={'name','reference','exam_date'}
    if columns & target and not target <= columns:
        raise ValueError('대상 정보 열이 일부만 존재합니다. 원자료를 보존했으며 스키마 확인이 필요합니다.')
    migrated=0
    if not columns & target:
        old=Table('khtp_jobs',MetaData(),autoload_with=connection)
        values=[]
        if 'subject' in columns:
            for row in connection.execute(select(old.c.id,old.c.subject)).mappings():
                subject=row['subject']
                if subject is None:
                    value=dict(name=None,reference=None,exam_date=None)
                else:
                    try:
                        if not isinstance(subject,dict):raise ValueError()
                        value={key:subject.get(key) for key in ('name','reference','exam_date')}
                        for key in ('name','reference'):
                            if value[key] is not None and (not isinstance(value[key],str) or len(value[key])>100):raise ValueError()
                        raw=value['exam_date']
                        if raw in (None,''):value['exam_date']=None
                        elif isinstance(raw,str):
                            value['exam_date']=date.fromisoformat(raw)
                            if value['exam_date'].isoformat()!=raw:raise ValueError()
                        else:raise ValueError()
                    except (ValueError,TypeError) as exc:
                        raise ValueError('기존 대상 정보 형식·길이·날짜를 확인해야 합니다. 기록 ID: '+row['id']+' (원자료 변경 없음)') from exc
                values.append((row['id'],value))
        for column,datatype in (('name','VARCHAR(100)'),('reference','VARCHAR(100)'),('exam_date','DATE')):
            connection.exec_driver_sql('ALTER TABLE khtp_jobs ADD COLUMN '+column+' '+datatype)
        for id,value in values:
            connection.execute(jobs.update().where(jobs.c.id==id).values(**value))
        migrated=len(values)
    if 'subject' not in columns:
        datatype='JSONB' if connection.dialect.name=='postgresql' else 'JSON'
        connection.exec_driver_sql('ALTER TABLE khtp_jobs ADD COLUMN subject '+datatype)
    for index in jobs.indexes:index.create(connection,checkfirst=True)
    return migrated


def init_app(app):
    app.register_blueprint(bp)

    @app.cli.command('khtp-upgrade-db')
    def upgrade():
        """검사 기록용 대상 열을 한 번 이관한다. 기존 기록과 반복 적용 시 최신값을 보존한다."""
        try:
            with get_engine().begin() as connection:
                migrated=upgrade_records(connection)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        except SQLAlchemyError as exc:
            raise click.ClickException('저장 구조 준비에 실패했습니다. 변경은 롤백됩니다. 오류 종류: '+type(exc).__name__) from exc
        click.echo(f'K-HTP 검사 기록 준비 완료. 대상 정보 이관 {migrated}개. 기존 독립 열이 있으면 변경 없음. 기록 삭제 없음.')

    @app.cli.command('khtp-import-pack')
    @click.argument('path',type=click.Path(exists=True,path_type=Path))
    def register(path):
        """검토한 자체 관찰 JSON 팩을 등록한다. 기존 작업에는 소급 적용하지 않는다."""
        try:
            with get_engine().begin() as connection:
                changed=import_pack(connection,json.loads(path.read_text(encoding='utf-8-sig')))
        except (ValueError,SQLAlchemyError) as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo('새 자료 버전 등록 완료' if changed else '같은 자료 버전이 이미 있습니다. 변경 없음')

    @app.cli.command('khtp-cleanup')
    def cleanup():
        """호환 명령: 검사 기록은 계속 보관하며 어떤 데이터도 삭제하지 않는다."""
        click.echo('K-HTP 검사 기록은 계속 보관합니다. 자동 삭제가 중단되었으며 삭제한 기록은 0개입니다.')
