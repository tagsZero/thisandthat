# 계정별 검사·일정·공유·댓글 SSOT

2026-10-29 추가 보완: K-HTP 작성 계정 전환 보호와 검사 댓글 SQL 실패의 제출값 복구는 [현행 계약](08-people-scheduler.md#account-draft-recovery)을 따른다. 복구 폼은 조회된 권한/저장 결과를 가정하지 않으며 재시도에서 기존 접근권·작성자·CSRF를 다시 검사한다. 실제 결과는 [PLAT-20261029-03](../changes/platform.md#plat-20261029-03)에 기록한다.

2026-10-29 최신 변경: 일정 공유·댓글은 검사 공유와 같은 소유/읽기/작성자 편집 원칙으로 확장하되 별도 appointment_shares/comments에 저장한다. 일정 공유는 연결 검사나 대상자 이력을 자동 공개하지 않는다. 계정 활성 상태·세션 개정과 기능 OFF를 서버에서 검사하며 관리자도 자료 접근권을 우회하지 않는다. 상세 계약은 [대상자·스케줄러 SSOT](08-people-scheduler.md)를 따른다. 아래 이와 다른 과거 일정 배치·비공개 전용 설명은 대체한다. 검증 진행은 [변경 대장](../changes/platform.md#plat-20261029-01)에 기록한다.

상태: 구현·최종 자체 검증·독립 재검수 통과 / 운영 적용·사용자 최종 판단 전 · 2026-10-28 사용자 검토 후 진행 지시 · 주관 PLAT-06

## 범위와 확정 동작

계정마다 TCI/K-HTP 검사와 일정을 분리한다. 소유자는 완료 후에도 원본을 수정한다. 특정 계정에 검사 단위 공유를 하면 수신자는 현재 저장본 열람·원본을 저장하지 않는 PDF 다운로드·자신의 댓글 작성/수정/삭제만 가능하다. 다시 공유·점수/본문/그림 수정·재분석은 불가다. 공유 회수 후 새 조회·댓글·그림·PDF 요청을 차단한다. 이미 내려받은 파일 회수는 제공하지 않는다.

댓글은 개인 메모(작성자만)와 공유 대화(소유자와 해당 수신자만)로 분리한다. 다른 수신자의 대화와 개인 메모는 공개하지 않는다. 댓글은 검사 본문·PDF·검사 수정시각/개정을 변경하지 않는다. 공유 회수 후 댓글은 보존하되 수신자의 접근을 막고 소유자에게는 공유 대화를 보존한다. 소유자도 수신자의 개인 메모는 읽지 못한다.

KHTP 기존 검사에서 다른 그림으로 시작하면 저장본 공유 링크를 숨기고 href를 제거한다. 업로드/저장본 로드의 adopt에서 현재 검사ID의 공유 링크만 표시한다. 이전 검사 링크가 새 검사 화면에 남지 않게 하며 기존 미저장 보호/요청/모델/PDF 동작은 유지한다. 댓글 생성 시 created_at/updated_at은 같은 시각으로 저장하고 실제 수정 요청에서만 updated_at을 갱신한다.

일정은 통합 대시보드로 이동하며 소유자만 조회/등록/수정/삭제한다. 일정 연결은 이번에 기존 TCI 연결을 유지하며 접근 가능한 TCI만 선택한다. 검사 공유로 일정은 공유되지 않는다. 통합 대시보드는 공유받은 두 종류 검사를 합쳐 보여준다. 프로그램별 목록도 소유/공유 상태를 구별한다.

예: sura의 TCI5/KHTP3은 sura만 보이며 test1은0건이다. TCI2/KHTP1 공유 후 sura 원본8건은 유지되고 test1의 공유받음은3건이다. 같은 이름/관리번호는 다른 계정의 검사를 연결하는 권한이 아니다.

## 소유권과 구현 경계

- 제품 코드/자료/의존성 구성 유지: Flask/Jinja/기본 JS/PostgreSQL/SQLAlchemy. 신규 UI 배치는 Flexbox, 신규 아이콘 없이 텍스트 조작 사용.
- TCI `reports`, `appointments`에 nullable owner_id FK를 추가한다. nullable은 기존 미귀속 자료 격리용이며 신규 생성은 서버가 로그인 계정으로 고정한다. 클라이언트 owner_id는 신뢰하지 않는다. KHTP 기존 owner_id는 보존한다.
- 미귀속 TCI/일정은 누구에게도 자동 노출/귀속하지 않는다. 사용자가 기존 TCI/일정 모두 sura 작성이라고 확인했다. 명시적 DB 준비와 sura 귀속 CLI를 제공하며 실제 사용자 DB에는 이번에 실행하지 않는다. 기존 본문/점수/자료/그림은 변경하지 않는다.
- 기본 해석자료·관찰 팩은 기존 공통 참고자료 구조를 유지한다. 이번 개인화의 대상은 검사 결과·일정·공유·댓글이며 개인 해석 라이브러리/조직 역할은 추가하지 않는다.
- 소유자 편집 전용 조회와 본인 또는 유효 공유의 읽기 조회를 분리한다. 목록/검색/건수/이력/직접URL/API/그림/PDF와 모든 저장 경로에 적용한다. 기존 서명 문맥은 권한을 대체하지 않는다.

## 모듈 계약 (동시 작업 파일 소유권)

1. core 익스큐트: `tci_web/db.py`, 신규 `tci_web/account_schema.py`, 신규 `tci_web/permissions.py`, `views.py`, `candidates.py`, `type_workspace.py`, `final_report.py`, `pdf_export.py`, `exam_history.py` 및 기존 TCI 테스트. 다른 에이전트는 이 파일을 수정하지 않는다.
2. collaboration 익스큐트: 신규 `tci_web/collaboration.py`, 신규 `tests/test_collaboration.py`만. UI·core·KHTP 파일 수정 금지.
3. KHTP Astra 익스큐트: `khtp_web/__init__.py`, `tests/test_khtp.py`만. 다른 파일 수정 금지.
4. root: 앱 등록 `app.py`, 문서, 새 통합 권한/브라우저 테스트와 통합 검증. KHTP 서버 실행 완료 후 Astra에게 모든 지정 템플릿/새 CSS 실행을 추가 분리했으며 root는 해당 UI 파일을 동시에 수정하지 않는다. 코드 실행 후 별도 리뷰어가 수정 없이 순차 검수한다.

### 공통 schema (account_schema.py)

`exam_shares`: id, report_id(nullable FK reports.id), job_id(nullable String36 FK khtp_jobs.id), recipient_id(FK users.id), created_at. 검사 FK는 정확히 하나. 각각 (report_id,recipient_id), (job_id,recipient_id) UNIQUE.

`exam_comments`: id, report_id/job_id(동일한 one-of FK), author_id(FK users.id), recipient_id(nullable FK users.id), body(Text), created_at, updated_at. recipient_id NULL은 작성자 개인 메모, 값이 있으면 해당 수신자와 소유자의 대화. 이 값은 검사 소유자가 아니며 클라이언트가 임의로 접근 범위를 늘리지 못한다.

### 권한 함수 (permissions.py)

- `readable_condition(table, kind, user_id=None)` : kind는 `tci`/`khtp`, 로그인 사용자 소유 OR 현재 공유. 미귀속은 제외.
- `owner_condition(table, user_id=None)` : owner_id와 로그인 사용자 일치.
- `get_exam(connection, kind, exam_id, *, write=False, lock=False)` : 존재/권한 없는 경우404, dict 반환. write=True는 소유자만, lock=True는 with_for_update.
- `csrf_token()` / `check_csrf()` : 새 공유/댓글/일정 폼 hidden `_csrf`와 session `account_csrf`, 실패403. 기존 검사 편집 폼의 검증과 구별.

### 화면/서버 연결

- 기존 TCI `find_report(report_id)`와 편집기/최종/PDF POST는 소유자 전용을 유지한다. 공유 수신자는 신규 공통 읽기 화면으로 이동한다. 단순히 find_report만 수정하지 않고 ID 직접 SQL 경로도 소유 조건으로 제한한다.
- `/dashboard` context: today, period, events, editing, choices(접근 가능한 TCI 선택), shared_records(TCI/KHTP 통합 요약), account_csrf. shared_records는 id,kind(`tci`/`khtp`),name,reference,exam_date,owner_username,updated_at.
- `/tci`와 `/khtp` 목록은 readable_condition을 적용하고 각 record에 is_owner, owner_username을 제공한다. 공유 행은 공통 읽기 화면 링크만, 소유 행은 기존 편집 링크와 공유/메모 링크를 제공한다.
- 공통 읽기 `GET /exams/<kind>/<exam_id>` endpoint `collaboration.detail`: `exam`, kind, is_owner, owner_username, account_csrf, shares(소유자만), comments(현재 사용자가 볼 수 있는 항목), thread_options(소유자의 현재 공유 수신자 목록), view(TCI final_report.read_model 결과 또는 KHTP의 public 응답이 아닌 저장 row).
- 공통 PDF `GET /exams/<kind>/<exam_id>/pdf` endpoint `collaboration.pdf`: 현재 읽기 권한과 저장 사본으로만 생성, 어떤 원본 저장/시각/개정 변경도 없음.
- 공유 `POST /exams/<kind>/<exam_id>/shares` endpoint `collaboration.share`: `_csrf`, username. owner만, 정확 일치 기존 계정·자기 자신 거부, 중복은 멱등.
- 회수 `POST /exams/<kind>/<exam_id>/shares/<int:share_id>/revoke` endpoint `collaboration.revoke` : owner만, 댓글 보존.
- 댓글 `POST /exams/<kind>/<exam_id>/comments` endpoint `collaboration.comment` : `_csrf`, body(1~5000자), audience(`private`/`shared`), recipient_id(소유자가 shared를 쓸 때만 수신자 선택; 수신자는 본인으로 강제).
- 댓글 수정/삭제 `POST /exams/<kind>/<exam_id>/comments/<int:comment_id>/edit|delete`, endpoint `collaboration.edit_comment` / `delete_comment`: 현재 읽기 권한 + 댓글 작성자만. 수정은 body만, 공개 범위 이동 금지.
- 신규 댓글/공유 뮤테이션은 검사/공유의 현재 권한을 트랜잭션 안에서 다시 확인한다. 수신자 쓰기는 grant row lock, 회수는 검사/관련 grant lock을 사용해 회수 완료 후 지연 요청을 차단한다.
- KHTP `find`는 write/owner 경로 기본 유지. image/data의 명시 읽기만 공유 허용. 기존 작업 화면은 owner 전용이며 공유 행은 공통 읽기 화면으로 연다. save/analyze/upload/PDF POST 등 원본 쓰기는 owner 전용.
- 통합 검사 이력은 선택 원본 및 결과 각각 readable_condition을 적용하고 비공유 형제 검사의 제목/번호/건수도 노출하지 않는다.

## DB 준비·검증·복구

`upgrade-privacy`는 기존 테이블에 owner 열·인덱스와 공유/댓글 테이블을 명시 준비한다. `assign-legacy-owner --username ... --report-id ... --appointment-id ...`는 기본 dry-run, `--apply`에서 지정한 미귀속 행만 트랜잭션으로 귀속한다. 사용자 소유 확인에 따른 `--username sura --all-unassigned`는 미귀속 TCI/일정을 일괄 선택하며 개별ID 옵션과 혼용하지 않는다. 이미 다른 소유자의 행은 선택하지 않는다. 없는 계정 자동 생성 금지, 기존 소유자 변경 거부, 반복 적용 멱등. 자동 시작 DDL/자동 첫 사용자 귀속 금지.

인증된 동적 화면/API 응답은 Cache-Control:no-store로 계정 전환 시 개인 결과의 캐시 재사용을 제한한다. 정적 자산은 해당 처리를 제외한다. 실제 실행 결과는 [패치 기록](../changes/PLAT-20261028-04-account-isolation.md)에 누적하며 구현과 운영 적용을 구별한다.

기존 테스트 fixture도 실제 작성자 소유권을 명시해 갱신하고 기존 점수/본문/편집/실패 보존 검증을 삭제하지 않는다. 전체 unittest, 새 권한 매트릭스와 실제 Chromium 두 계정·공유/회수·댓글·일정·원본 불변 PDF·320/390px를 확인한다. PostgreSQL 격리 검증 가능 여부를 별도로 기록한다. 실사용 DB/서버/배포/Git 명령은 이번에 실행하지 않는다.

소유권 분리 뒤 예전 무권한 공동 조회 코드로 되돌리면 자료 노출이 다시 발생할 수 있으므로 코드 rollback만으로 운영 복구하지 않는다. 새 컬럼/공유/댓글을 보존하고 접근을 차단한 상태에서 호환을 확인한다. 실제 사용자 기록 삭제/재배정은 이번 구현에 포함하지 않는다.
