"""현재 저장 사본의 PDF. 생성 중 DB 트랜잭션·자체 HTTP 요청을 사용하지 않는다."""
import base64
import asyncio
from copy import deepcopy
from decimal import InvalidOperation
from pathlib import Path

from flask import Blueprint, abort, current_app, make_response, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from . import composition as comp
from .auth import login_required
from .db import get_engine, reports, utc_now
from .final_report import read_model
from .scores import SCALES, SUBSCALES, parse_scores, parse_settings
from .views import find_report
from .permissions import owner_condition

bp = Blueprint('pdf_export', __name__)
INVALID = (ValueError, KeyError, TypeError, InvalidOperation)


class PdfError(RuntimeError):
    pass


def validate_report(report):
    """기존 분류기를 사용하기 전에 저장 기준·수치·본문 구조를 검증한다."""
    settings = report['settings']
    if (not isinstance(settings, dict) or not isinstance(report['scores'], dict)
            or any(not isinstance(settings.get(k), str) for k in ('low', 'high', 'rounding'))
            or not isinstance(settings.get('overrides', {}), dict)
            or any(not isinstance(row, dict) for row in report['scores'].values())):
        raise ValueError('저장된 점수·기준 구조를 확인해 주세요.')
    if any(not isinstance(row, dict) for row in report['scores'].get('subscales', {}).values()):
        raise ValueError('저장된 하위척도 구조를 확인해 주세요.')
    form = {key: settings[key] for key in ('low', 'high', 'rounding')}
    for code, bounds in settings.get('overrides', {}).items():
        if (code not in {row[0] for row in SCALES} or not isinstance(bounds, dict)
                or any(not isinstance(bounds.get(k), str) for k in ('low', 'high'))):
            raise ValueError('척도별 기준을 확인해 주세요.')
        form.update({code + '_override': '1', code + '_low': bounds['low'], code + '_high': bounds['high']})
    _, errors = parse_settings(form)
    # parse_scores는 미제출 값을 보존한다. 저장 수치도 동일한 입력 검증을 거친다.
    fields = {code + '_' + key: str(value) for code, row in report['scores'].items()
              if code != 'subscales' for key, value in row.items() if value is not None}
    fields.update({code + '_raw': str(row['raw']) for code, row in report['scores'].get('subscales', {}).items()
                   if row.get('raw') is not None})
    _, score_errors = parse_scores(fields, report['scores'])
    if errors or score_errors:
        raise ValueError('저장된 점수 또는 분류 기준을 확인해 주세요.')
    data = read_model(report)
    if data['missing']:
        raise ValueError('PDF에는 7개 주척도 T점수가 필요합니다. 미입력: ' + ', '.join(data['missing']))
    return data


def render_pdf(html):
    """각 단계와 전체 생성 예산을 제한하고 모든 브라우저 자원을 닫는다."""
    from playwright.async_api import async_playwright

    async def generate():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(timeout=30000)
            try:
                context = await browser.new_context(java_script_enabled=False)
                try:
                    # 사용자 본문은 이스케이프하며 외부 요청도 허용하지 않는다.
                    await context.route('**/*', lambda route: route.abort())
                    page = await context.new_page()
                    await page.set_content(html, wait_until='load', timeout=30000)
                    await page.emulate_media(media='print')
                    await page.wait_for_function("""() => document.fonts.status === 'loaded'
                        && [...document.fonts].length === 2
                        && [...document.fonts].every(f => f.status === 'loaded')""", timeout=15000)
                    if not await page.evaluate("""() => document.fonts.check('14px TCIPdf', '한글 기준 ≤ ≥ HML')
                        && document.fonts.check('bold 14px TCIPdf', '한글 기준 ≤ ≥ HML')"""):
                        raise PdfError('한글 폰트를 불러오지 못했습니다.')
                    session = await context.new_cdp_session(page)
                    await session.send('DOM.enable')
                    await session.send('CSS.enable')
                    root = (await session.send('DOM.getDocument'))['root']['nodeId']
                    node = (await session.send('DOM.querySelector', dict(nodeId=root, selector='.report-paper')))['nodeId']
                    # 실제 텍스트 노드가 있는 제목으로 사용 폰트까지 확인한다.
                    node = (await session.send('DOM.querySelector', dict(nodeId=node, selector='h1')))['nodeId']
                    fonts = (await session.send('CSS.getPlatformFontsForNode', dict(nodeId=node)))['fonts']
                    if not fonts or any(not f['isCustomFont'] for f in fonts):
                        raise PdfError('로컬 한글 폰트의 실제 사용을 확인하지 못했습니다.')
                    pdf = await page.pdf(format='A4', print_background=True, prefer_css_page_size=True,
                                   margin=dict(top='16mm', right='16mm', bottom='18mm', left='16mm'),
                                   display_header_footer=False)
                    if not pdf.startswith(b'%PDF-') or b'%%EOF' not in pdf[-1024:]:
                        raise PdfError('올바른 PDF 응답이 아닙니다.')
                    return pdf
                finally:
                    await asyncio.wait_for(context.close(), timeout=5)
            finally:
                await asyncio.wait_for(browser.close(), timeout=5)

    async def bounded():
        return await asyncio.wait_for(generate(), timeout=45)

    try:
        return asyncio.run(bounded())
    except TimeoutError as error:
        raise PdfError('PDF 생성 제한시간을 초과했습니다.') from error
    except PdfError:
        raise
    except Exception as error:
        raise PdfError('PDF 브라우저·폰트 또는 출력에 실패했습니다.') from error


def download(report):
    # report는 커밋된 입력의 독립 사본이다. 후속 보고서 조회와 섞지 않는다.
    data = validate_report(report)
    data.update(status_known=True, pdf_mode=True, subscales=SUBSCALES)
    try:
        with get_engine().connect() as connection:
            data['block_status'] = comp.material_status(connection, data['composition'], report)
    except SQLAlchemyError:
        data['status_known'] = False
    assets = Path(current_app.static_folder)
    try:
        fonts = {weight: base64.b64encode((assets / 'fonts' / ('NotoSansCJKkr-' + name + '.otf')).read_bytes()).decode('ascii')
                 for weight, name in (('normal', 'Regular'), ('bold', 'Bold'))}
        css = (assets / 'app.css').read_text(encoding='utf-8') + '\n' + (assets / 'report_print.css').read_text(encoding='utf-8')
        html = render_template('report_pdf.html', css=css, fonts=fonts, **data)
        pdf = render_pdf(html)
    except OSError as error:
        raise PdfError('PDF용 로컬 CSS·한글 폰트를 읽지 못했습니다.') from error
    response = make_response(pdf)
    response.headers.update({'Content-Type': 'application/pdf',
        'Content-Disposition': f'attachment; filename="TCI-report-{report["id"]}.pdf"',
        'Cache-Control': 'no-store', 'X-TCI-Save-State': 'saved'})
    return response


def failure(message, state='not_saved', code=503, recovery=None):
    retry = url_for('pdf_export.retry', report_id=request.view_args['report_id'])
    if request.accept_mimetypes.best == 'application/json':
        return dict(errors={'pdf': message}, message=message, save_state=state,
                    retry_url=retry if state == 'saved' else None), code, {'X-TCI-Save-State': state}
    return render_template('pdf_error.html', message=message, save_state=state,
                           recovery=recovery, retry_url=retry), code


def saved_download(report):
    try:
        return download(deepcopy(report))
    except Exception:
        current_app.logger.exception('저장 후 PDF 생성 실패')
        return failure('저장은 완료되었습니다. PDF 생성에 실패했습니다. 저장된 보고서로 PDF만 다시 시도하세요.', 'saved')


def save_editor(report_id):
    """편집 폼 전용: 최신 행에서 입력을 검증하고 커밋한 사본만 전달한다."""
    try:
        with get_engine().begin() as connection:
            fresh = connection.execute(select(reports).where(reports.c.id == report_id, owner_condition(reports)).with_for_update()).mappings().first()
            if fresh is None:
                abort(404)
            original = deepcopy(dict(fresh))
            report = deepcopy(original)
            settings, errors = parse_settings(request.form, report['settings'])
            if errors:
                raise ValueError(' '.join(errors.values()))
            report['settings'] = settings
            value = comp.read_form(request.form, report)
            report['composition'] = value
            validate_report(report)
            comp.material_status(connection, value, {**original, 'settings': settings}, validate_new=True)
            report['updated_at'] = utc_now()
            connection.execute(reports.update().where(reports.c.id == report_id, owner_condition(reports)).values(
                settings=settings, composition=value, updated_at=report['updated_at']))
    except INVALID as error:
        return editor_failure(str(error), 'not_saved', 422)
    except SQLAlchemyError:
        return editor_failure('저장하지 못했습니다. 입력은 유지됩니다. PDF는 생성하지 않았습니다.', 'failed', 503)
    return saved_download(report)


def editor_failure(message, state, code):
    if request.accept_mimetypes.best == 'application/json':
        return failure(message, state, code)
    return render_template('composition_recovery.html', recovery=request.form, message=message,
                           save_state=state, pdf_retry=True), code


@bp.post('/tci/reports/<int:report_id>/pdf')
@login_required
def save_output(report_id):
    try:
        with get_engine().begin() as connection:
            fresh = connection.execute(select(reports).where(reports.c.id == report_id, owner_condition(reports)).with_for_update()).mappings().first()
            if fresh is None:
                abort(404)
            report = deepcopy(dict(fresh))
            value = comp.initial(report)
            value['output'] = {key: request.form.get('include_' + key) == '1' for key in comp.OUTPUT_SECTIONS}
            report['composition'] = value
            validate_report(report)
            report['updated_at'] = utc_now()
            connection.execute(reports.update().where(reports.c.id == report_id, owner_condition(reports)).values(
                composition=value, updated_at=report['updated_at']))
    except INVALID as error:
        return failure(str(error), code=422, recovery=request.form)
    except SQLAlchemyError:
        return failure('표시 설정을 저장하지 못했습니다. 입력을 유지했습니다. PDF는 생성하지 않았습니다.', 'failed', recovery=request.form)
    return saved_download(report)


@bp.get('/tci/reports/<int:report_id>/pdf')
@login_required
def retry(report_id):
    try:
        report = find_report(report_id)
        validate_report(report)
    except SQLAlchemyError:
        return failure('저장된 보고서를 읽지 못했습니다. PDF만 다시 시도하세요.', 'saved')
    except INVALID as error:
        return failure(str(error), code=422)
    return saved_download(report)
