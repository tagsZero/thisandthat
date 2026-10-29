# TCI 기능·유지보수 SSOT

2026-10-29 추가 보완 R7/R8: 검사 댓글 신규/수정의 SQL 실패 입력 복구와 대상자 검색 Enter의 폼 제출 방지는 [추가 보완 계약](08-people-scheduler.md#account-draft-recovery)을 따른다. 점수·본문·계산은 유지한다. 최신 검증/운영 상태는 [PLAT-20261029-03](../changes/tci.md#plat-20261029-03)에 기록한다.

2026-10-29 최신 변경: 점수 폼 안에서 기존 대상자를 검색 선택하거나 첫 저장 때 코드를 발급한다. person_id와 검사 스냅샷을 구분한다. 저장에는 CSRF와 저장 기준시각 검증을 적용하여 오래된 탭의 덮어쓰기를 차단한다. 저장본 열람에서 일정 잡기·대상자 이력으로 연결한다. 계산·본문 자동 구성·PDF 출력 규칙은 보존한다. 상세 계약은 [대상자·스케줄러 SSOT](08-people-scheduler.md)를 따른다. 아래 이와 다른 과거 일정 배치·비공개 전용 설명은 대체한다. 검증 진행은 [변경 대장](../changes/platform.md#plat-20261029-01)에 기록한다.

2026-10-29 후속 보완: 검사 대상자 변경의 일정 연결 정리는 [보완 계약](08-people-scheduler.md#recovery-fixes)을 따른다. 구현 위치와 전체 311건/독립 29건 검증·운영 상태는 [최신 패치 기록](../changes/tci.md#plat-20261029-02)에 연결한다.

상태: active · 계약 관리: TCI 익스큐트 / 오케스트라 · 갱신·소스 대조: 2026-10-29

[작업 인덱스](../manual-index.md) · [통합 SSOT](../../SSOT.md) · [공통 UI](../manual/ui-rules.md) · [TCI 변경 대장](../changes/tci.md)

아래 ID는 유지보수 기능 ID다. 과거 TCI-01~08·TYPE/UI 작업 번호와 별개이며 과거 완료 판정을 바꾸지 않는다. 상세 횡단 요구는 [기능](01-features.md), [화면](02-screens.md), [기술](03-technology.md) SSOT에 연결한다. 이 문서는 TCI 작업의 소유 위치와 현재 핵심 계약을 담당한다.

2026-10-28 최신 계정 분리/공유는 [계정·공유 SSOT](07-account-sharing.md)가 소유한다. 원본 편집 경로는 소유자만, 공유 수신자는 `/exams/tci/<id>`에서 저장본·무저장 PDF·자신의 메모/수신자별 대화를 이용한다. 목록·건수·검색·관리번호 이력과 ID 직접 SQL도 권한을 적용한다. 일정은 통합 대시보드로 이동했다.

<a id="scores"></a>
## TCI-M01 점수·분류

- 진입·소스: `/tci/reports/new`, `/tci/reports/<int:report_id>/edit`, `POST /tci/classification-preview`; `tci_web/views.py:edit_report/classification_preview`, `scores.py`, `templates/score_input.html`, `workspace_profile.html`, `static/app.js`, `score_save.js`, `static/app.css`.
- 계약 원본: `scores.py`의 점수·설정 파싱/분류 및 [통합 분류 규칙](../../SSOT.md). 원점수·T점수·백분위는 독립 저장하고 빈칸을 0으로 바꾸거나 표준점수를 환산하지 않는다. 기본 T56은 L: T≤45, M: 45<T<56, H: T≥56이며 T55·사용자 지정·척도별 예외를 제공한다. 반올림 기본 없음, 선택 시 Decimal·ROUND_HALF_UP이며 원입력을 보존한다.
- 유형/화면: 기질 NS·HA·RD, 성격 SD·CO·ST 순서로 만들고 PS·SC는 세 글자 코드에서 제외한다. 그래프 위치는 백분위이고 H/M/L은 선택 T분류다.
- 저장·공용 영향: `reports.scores/settings`로 연결한다. 유형 변경은 자동 본문·후보·출력에 영향을 주므로 M02/M05와 함께 확인한다. 폼 저장과 preview 조회를 구별한다. 생성 파일은 점수 기능 자체에는 없다.
- 검증·복구: 경계45/55/56·소수·반올림·누락·유형 순서·저장/재열기를 확인한다. 기존 점수/설정을 재계산해 일괄 덮어쓰지 않는다. 형식 변경 시 구버전 reader 호환을 먼저 정하고 소스/문서를 함께 복구한다. 이번 실행 없음.

<a id="composition"></a>
## TCI-M02 자동 본문·다른 해석·편집

- 진입·소스: `GET/POST /tci/reports/<int:report_id>/candidates`; `tci_web/candidates.py`, `type_report.py`, `type_workspace.py`, `composition.py`, `selection.py`, `templates/type_workspace.html`, `type_body.html`, `candidate_card.html`, `static/type_workspace.js`, `candidates.js`.
- 계약 원본: 자동 구성 `type_report.py`, 현재 입력/저장 처리 `type_workspace.py`, 사본·편집 계약 `composition.py`, 조건 평가 `candidates.py`. 제공 자료의 현재 기질/성격 통합54 설명 중 두 본문을 자동 포함하고 다른 해석은 추가/취소로만 넣는다. 기본 반영 버튼·문장별 필수 선택·단일/다중 모드를 요구하지 않는다.
- 자동 사용: unknown/reference·검사판 근거 미확인만으로 승인된 통합 본문을 막지 않는다. 공식 성인용 검증 완료로 표시하지 않으며 출처는 보존한다. 실제 점수 조건·명시 제한·비활성·비출력 비교를 구별한다.
- 상태/저장: 폼의 composition·기준과 서명된 작성 문맥을 서버에서 검증한다. `compare` 조회와 명시 저장을 구별한다. 기준을 직접 바꾸면 수정하지 않은 자동 본문만 갱신하고 직접 편집·추가·비운 본문은 보존한다. 출처 업데이트·빠른 리뷰·재열기로 기존 본문을 덮어쓰지 않으며 추가/취소 반복은 무중복이어야 한다. `reports.composition`과의 세부 형식은 M06을 따른다.
- 경계/생성물: 로그인 및 서명·기준·기존 저장 시각 검증을 유지한다. API 응답에는 동작에 따라 `errors`, `composition`, `settings`, 본문/그래프 HTML, `save_state`, 저장시각/이동 목적지 등이 있다. 전체 응답 schema 변경은 실제 분기와 JS를 함께 대조한다. 본문 자체는 PDF 파일을 생성하지 않으며 PDF 동작은 M05로 이어진다.
- 검증·복구: 두 유형 자동 구성·조건·편집/빈값·이전 기준 표시·반복 추가/취소·저장/재열기·자료 갱신 후 보존·지연/중복 저장을 확인한다. 구형 body/v1/v2 사본의 읽기 호환을 유지한다. 코드 되돌림이 이미 저장한 본문을 원복하지는 않는다. 이번 실행 없음.

<a id="library"></a>
## TCI-M03 자료 관리·명시 등록

- 진입·소스: `/tci/library`, `/sources/new`, `/sources/<int:record_id>/edit`, `/items/new`, `/items/<int:record_id>/edit`(하위 경로는 `/tci/library` 기준). `tci_web/library.py`, `type_library.py`, `templates/library*.html`, `static/library.js`가 담당한다.
- 계약·저장: `interpretation_sources`, `interpretations`에 원문/보고서용 설명·출처/위치·유형/척도·조건·선택 연결·사용 상태를 구분해 저장한다. schema는 `tci_web/db.py`, 입력 계약은 `library.py/selection.py`가 원본이다. 원본 `.footga/tci/`는 수정하지 않는다. 없는 해석을 생성하지 않는다.
- 초기 자료: `data/interpretations.json`, `data/type_interpretations.json`은 등록 팩이다. 앱 시작이나 Git 갱신만으로 DB에 적용하지 않는다. `seed-type-library` 기본은 점검, `--apply`에서 없는 안정 키만 등록한다. 기존 사용자 편집·중지·연결·보고서는 덮어쓰지 않는다. 일반 자료 변경은 관리 화면에서 하며 재배포가 필요 없다.
- 경계·공용 영향: 로그인 보호를 유지한다. 새 자료/사용 중지는 새 후보 판정에 반영하되 기존 저장 본문을 자동 수정하지 않는다. CLI는 요청된 등록 범위와 DB 대상을 먼저 구별한다. 사용자 기록·원문·생성 PDF는 Git 자산이 아니다.
- 검증·복구: 조건 파싱·출처/유형 연결·중복 등록·기존 편집/중지/선택 보존을 확인한다. JSON 파일 되돌림과 DB 등록 취소는 별개다. 실사용 자료 수정/제거는 대상과 보존 근거가 필요하다. 이번 등록·실행 없음.

<a id="dashboard"></a>
## TCI-M04 목록·빠른 리뷰

- 진입·소스: `GET /tci`, `POST /tci/appointments`, `POST /tci/appointments/<int:event_id>`, `POST /tci/appointments/<int:event_id>/delete`; `tci_web/views.py`, `templates/tci_dashboard.html`, `static/app.css`.
- 처리/저장: 이름·관리번호·검사일 검색, 최근 수정 순 목록·빠른 리뷰·이어 작성. 목록10건 페이지는 소유 또는 유효 공유 검사만 세고 조회한다. 소유자는 편집, 수신자는 공통 저장본 열람으로 이동한다. 일정은 공통 플랫폼의 통합 대시보드에서 owner별로 처리하며 기존 `/tci/appointments` 주소는 호환용으로 유지한다.
- 공용·생성물: 관리번호 이력은 [PLAT-03](04-platform.md#history) 소유다. 빠른 리뷰는 저장 본문을 조회하며 소스 갱신으로 본문을 갱신하지 않는다. 파일 생성은 해당 없음.
- 검증·복구: 검색/페이지/리뷰·이어 작성·일정 등록/수정/삭제·보고서 연결을 확인한다. 화면/route 복구와 이미 수정한 일정 데이터 복구를 구별한다. 이번 실행 없음.

<a id="pdf"></a>
## TCI-M05 최종 보고서·PDF

- 진입·소스: `GET/POST /tci/reports/<int:report_id>/report`, `POST /tci/reports/<int:report_id>/pdf`, `GET` 같은 PDF 경로의 저장본 재시도; 편집 화면의 PDF 동작도 연결된다. `tci_web/final_report.py`, `pdf_export.py`, `templates/final_report.html`, `report_body.html`, `report_pdf.html`, `static/report_options.js`, `pdf_download.js`, `report_print.css`.
- 계약·저장: 현재 편집 저장 후 같은 사본을 출력한다. 최종 보고서/PDF route는 표시 옵션을 저장하고 편집기 경유 PDF는 본문도 저장한다. `reports.composition`의 출력 옵션과 현재 본문·설정을 사용하며 저장 실패와 저장 후 PDF 생성 실패를 구별한다. 생성만 실패하면 저장본 재시도가 가능해야 한다.
- 생성 주체/경계: `pdf_export.py:render_pdf`의 Playwright/Chromium이 A4 PDF를 만들어 다운로드 응답으로 제공한다. 자동 PDF 이력 테이블·Git 보관 기능은 없다. 한글 폰트·실제 적용 T기준·참고 설명·긴 문장 페이지 나눔을 유지한다. 웹 미리보기와 마지막 저장된 PDF 표시 옵션의 차이를 안내하고 생성 중 최신 편집을 강제 덮어쓰지 않는다.
- 공용 영향·검증·복구: 공유 렌더러는 K-HTP에도 영향이 있다. 저장/재열기와 PDF 내용 일치, 그래프·한글·긴 문장·저장 및 생성 실패/재시도를 확인한다. 렌더러/템플릿/CSS를 호환되는 묶음으로 복구하며 이미 저장된 표시 옵션은 별도 데이터다. 이번 PDF 생성/열람 없음.

<a id="storage"></a>
## TCI-M06 공통 저장·권한·변경 기록

테이블 원본은 `tci_web/db.py`다. `reports`는 이름·관리번호·검사일·`scores`·`settings`·기존 `body`·nullable `composition`·생성/수정시각을 저장한다. PostgreSQL JSONB(코드의 공용 json_type)를 사용하며 세부 구조/버전 검증은 `scores.py`, `composition.py`를 실제 저장 분기와 함께 확인한다. 일정은 `appointments`, 자료는 M03의 두 테이블이다. 새 전용 저장 API나 schema registry를 임의로 추가하지 않는다.

`reports.owner_id`, `appointments.owner_id`는 사용자 FK다. nullable은 기존 미귀속 격리용이며 신규 생성은 서버가 현재 계정으로 지정한다. 소유자만 원본 편집하고 유효 공유는 별도 읽기 화면/댓글을 허용한다. 미귀속 자료는 숨기며 사용자가 기존 TCI/일정을 sura 소유로 확인했다. `upgrade-privacy`와 명시 귀속 명령은 [매뉴얼](../index.md#account-privacy)을 따른다. 앱 시작 시 DDL이나 자동 귀속을 실행하지 않는다.

수정은 [변경 절차](../manual/change-workflow.md#patch)를 따르고 [TCI 대장](../changes/tci.md)에 재현·변경·실제 검증·Git/운영 상태·복구를 기록한다. 과거 자료 등록/검증 수치를 이번 베타 통과로 재사용하지 않는다. 운영 DB/schema·전체 payload 분기·실사용 베타 결과는 이번 대조에서 미확인이다.
