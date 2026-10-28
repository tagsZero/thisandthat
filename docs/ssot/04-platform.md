# 공통 기반·통합 대시보드 SSOT

상태: active · 계약 관리: 오케스트라 / 공통 기반 익스큐트 · 갱신·정적 소스 대조: 2026-10-28

[작업 인덱스](../manual-index.md) · [공통 UI](../manual/ui-rules.md) · [변경 규칙](../manual/change-workflow.md) · [공통 변경 대장](../changes/platform.md)

아래 ID는 유지보수 기능 ID이며 과거 실행 task 번호와 별개다. 이번 대조는 정적 확인이며 운영·기능 재검증이 아니다.

<a id="auth-navigation"></a>
## PLAT-01 로그인·공통 탐색

- 목적·진입: `/`에서 로그인 상태에 따라 `/login` 또는 `/dashboard`로 이동한다. `GET/POST /login`, `POST /logout`과 공통 헤더가 로그인→통합 대시보드→프로그램 흐름을 담당한다.
- 소스/소유: `tci_web/auth.py`, `app.py:create_app`, `templates/login.html`, `templates/base.html`, `static/navigation.js`, `static/app.js`, `static/app.css`. 물리 폴더는 TCI지만 공통 모듈이다.
- 계약 원본·저장: 인증 검증은 `auth.py`, 테이블 선언은 `tci_web/db.py:users`. 로그인 폼 `username/password`를 검증하고 비밀번호 해시를 비교한다. 세션은 `user_id`를 사용한다. 로그인 요청은 계정을 새로 만들지 않는다. 쿠키 설정은 `app.py`가 소유한다.
- 경계·공용 영향: `login_required`와 `g.user`를 두 프로그램이 사용한다. 검사 소유/공유 읽기는 [PLAT-06](#account-privacy) 계약으로 추가 검증한다. K-HTP API 인증·CSRF는 기존 계약을 유지하고 새 공유/댓글/일정 폼은 별도 계정 CSRF를 사용한다. 헤더 이동은 기능별 미저장 보호와 연결된다.
- 생성 파일: 로그인 자체는 해당 없음. 앱 최초 시작 시 `SECRET_KEY`가 없으면 `.env`에 생성하는 기존 동작이 있으므로 단순 조사 목적으로 앱을 기동하지 않는다.
- 변경·검증·복구: 공통 변경으로 분류하고 양쪽 로그인/만료/로그아웃/탐색/미저장 보호를 확인한다. 소스·템플릿·문서를 함께 되돌리되 운영 비밀키를 코드 패치로 교체하지 않는다. 이번 실행 검증 없음.

계정 신규 생성은 아래 [PLAT-05](#registration) 계약을 따른다. 2026-10-28 회원가입 추가 후의 실제 로그인 검증은 해당 변경 대장에 기록하며 위 최초 정적 대조와 구별한다.

<a id="portal"></a>
## PLAT-02 통합 대시보드·프로그램 진입

- 목적·진입: 로그인 후 `GET /dashboard`에서 TCI와 K-HTP 진입 카드를 제공한다. TCI `/tci`, K-HTP `/khtp`로 연결한다.
- 소스/소유: `tci_web/views.py:portal`, `templates/portal.html`, `templates/base.html`, `static/app.css`의 portal/program 관련 규칙.
- 계약·서버 처리: `portal()`은 로그인 보호 후 `portal.html`을 렌더링한다. 현재 카드별 설정 schema·registry·전용 API는 없다. 기존 템플릿을 원본으로 확인한다.
- 저장 payload·위치: 개인 일정은 `appointments.owner_id` 기준으로 조회·등록·수정·삭제한다. 공유받은 검사 요약은 `exam_shares`와 양쪽 검사에서 접근 가능한 항목만 조회한다. 별도 대시보드 설정 테이블/생성 파일은 없다. 화면/처리 상세는 [PLAT-06](#account-privacy)을 따른다.
- 공용 영향·변경 절차: 카드 문구·배치 변경과 새 서비스/저장 기능 추가를 구별한다. 새 프로그램 추가 시 자체 기능 SSOT·변경 대장을 먼저 연결한다. 공유 카드 스타일·헤더를 바꾸면 양쪽 진입 화면 영향도 확인한다. 카드만 추가한다는 이유로 TCI/K-HTP 계약을 바꾸지 않는다.
- 검증·복구: 로그인 진입·기존 두 링크·새 링크(해당 시)·모바일 줄바꿈·접근성을 확인한다. 템플릿/CSS/연결 문서를 복원한다. 신규 저장이 있다면 별도 데이터 호환 계획을 먼저 정한다. 이번 정적 대조만 수행.

<a id="history"></a>
## PLAT-03 관리번호 통합 검사 이력

- 목적·진입: TCI와 K-HTP의 기존 목록에서 `history`(선택한 저장 기록 ID), `history_page` query로 같은 관리번호의 요약 이력을 조회한다. 별도 대상자 등록 화면이나 독립 API route를 만들지 않는다.
- 소스/소유: `tci_web/exam_history.py:load_history/history_query`, `templates/exam_history.html`, `tci_web/views.py:dashboard`, `khtp_web/__init__.py:index`.
- 계약 원본: `reference_key`는 앞뒤 일반 공백만 제거한다. 이름·유사 번호로 매칭하지 않는다. `reports`와 `khtp_jobs`에서 종류/ID/이름/관리번호/검사일/저장시각 요약을 UNION ALL 조회한다. 검사일·저장시각·종류·ID 순서, 20건 페이지를 유지한다.
- 인증·저장: 선택한 원본과 결과 각 행에 현재 사용자 소유 또는 유효 공유를 적용한다. 같은 관리번호라는 이유로 비공유 형제 검사나 다른 계정 검사를 노출하지 않는다. 읽기 전용 기능이며 행 병합·관리번호 변경·본문 갱신·생성 파일은 없다. 별도 조회 연결 오류가 기존 목록을 대체하지 않도록 한다.
- 공용 영향·검증: 양쪽 목록, 공백/빈 번호/정확 매칭, 페이지/안정 정렬, K-HTP 타 소유자 제외, 오류 시 목록·검색 상태 보존을 확인한다. 이번 정적 대조 외 실행 없음.
- 복구: 공유 조회 함수·양쪽 호출부·템플릿을 호환되는 묶음으로 복구한다. 데이터 변경이 없으므로 이 기능만의 DB 되돌림은 해당 없음.

<a id="storage"></a>
## PLAT-04 앱 구성·공유 DB·PDF 렌더러

공통 기반은 `app.py:create_app`의 Flask 앱/Blueprint 등록·DB engine과 `tci_web/db.py`의 metadata/json_type을 사용한다. TCI 테이블은 `db.py`, K-HTP 테이블은 `khtp_web/__init__.py`가 선언한다. 저장 payload의 세부 소유권은 [TCI](05-tci.md#storage), [K-HTP](06-khtp.md#records)에 있다. PostgreSQL이 운영 저장 원본이고 Git JSON은 명시적으로 등록할 초기 자료이며 기존 사용자 데이터의 대체본이 아니다.

PDF 렌더러 `tci_web/pdf_export.py:render_pdf`는 두 프로그램이 공유한다. TCI는 `templates/report_pdf.html`·`static/report_print.css`, K-HTP는 `templates/khtp/pdf.html`을 사용한다. `static/fonts/`의 한글 폰트·라이선스도 공용이다. 각 생성 route가 저장한 사본을 렌더링하며 다운로드 결과를 Git에 넣지 않는다. PDF 엔진 변경은 양쪽 한글·긴 문장·그래프/그림 확인이 필요하다.

설치·CLI·환경 예시 원본 안내는 [실행·사용 매뉴얼](../index.md), 기술 계약은 [기술 SSOT](03-technology.md)다. DB 이관은 앱 기동이나 Git 업데이트만으로 자동 실행하지 않는다. 원본·`.env`·모델 자산은 코드와 분리한다. 운영 schema·실제 설치 버전·현재 저장 파일은 이번에 확인하지 않았다.

변경은 공통 대장에 기록하고 기능군의 데이터 호환을 확인한다. DB 변경이면 단순 코드 복구와 별도의 이관/복구 계획이 필요하다. 이 문서 작성으로 새 DB/권한/백업 기능을 추가하지 않는다.

<a id="registration"></a>
## PLAT-05 회원가입

- 요청·진입: 2026-10-28 회원가입 폼 제작 요청. 로그인 화면의 회원가입 링크 → `GET /register` → `POST /register` → 성공 시303으로 `/login` → 기존 로그인 → 통합 대시보드다. 로그인 중에는 GET/POST 가입 모두 통합 대시보드로 보낸다.
- 소스·소유권: 공통 인증 `tci_web/auth.py:register/registration_errors`, 기존 `users` 선언(`tci_web/db.py`), `templates/register.html`, `templates/login.html`, 전용 `static/register.css`. 비밀번호 표시 버튼은 기존 `static/app.js`를 재사용한다. 신규 배치는 Flexbox이며 아이콘은 추가하지 않았다.
- 입력·검증: form `username`, `password`, `password_confirm`, `csrf_token`, 설정된 경우 `invite_code`. 아이디는 앞뒤 공백 제거 후1~80자이며 내부 공백/제어문자는 거부하고 기존 대소문자 구별을 유지한다. 비밀번호는8~128자·공백만 사용 불가·확인 일치이며 자동 trim하지 않는다. 비밀번호·확인·초대 코드는 오류 HTML에 재출력하지 않는다. 요청 본문 상한은16KiB다.
- 가입 방식·설정: 2026-10-28 사용자 후속 답변 “누구나 가입하는 공개 회원가입”으로 **무설정 기본값을 공개 가입**으로 확정했다. `app.py`는 `REGISTRATION_OPEN`이 없으면1로 읽으며1/true(앞뒤 공백 제거·대소문자 무관)는 공개 허용, 명시 빈값/0/false/기타 값은 공개 차단이다. `REGISTRATION_INVITE_CODE`가 명시되어 있으면 기존 제한 설정 호환을 위해 코드 검증을 우선한다. 공개 운영에는 초대 코드를 설정하지 않는다. 명시적으로 공개 가입이 차단되고 초대 코드도 없으면 폼/닫힘 안내·버튼 비활성·POST503을 유지한다. 이전 미응답 때의 R1/닫힘 검수는 당시 근거로 보존하며 최신 정책은 [PLAT-20261028-03](../changes/platform.md#plat-20261028-03)을 따른다. 운영 설정과 앱 재시작은 사용자가 수행한다.
- 저장·인증: 세션의 `registration_csrf`와 constant-time 비교 후 트랜잭션으로 `users.username/password_hash`만 추가한다. Werkzeug 해시를 사용하고 기존 행을 덮어쓰지 않는다. 중복 사전 조회와 DB UNIQUE 제약으로 동시 중복을 처리한다. 성공 시 가입 CSRF 토큰을 제거하고 로그인 안내 flash를 남기며 자동 로그인하지 않는다. schema 변경·기존 데이터 이관은 없다.
- 오류·보존: 입력 오류422, CSRF403, 중복409, DB 실패/가입 닫힘503. 아이디는 유지하고 비밀번호 입력은 비운다. 오류 응답에 SQL/접속정보를 내보내지 않는다. 폼 응답은 `Cache-Control: no-store`다.
- 공용 영향·생성물: 두 프로그램이 같은 계정을 쓴다. 이후 계정 분리 지시에 따라 신규 계정은 본인 또는 명시 공유 검사만 읽고, 원본과 일정은 소유자만 수정한다. 기본 해석자료는 공통 참고 구조를 유지한다. 조직별 권한·이메일·비밀번호 찾기·약관 관리 기능은 추가하지 않았다. 제품 생성 파일은 없다.
- 검증·복구: 입력/CSRF/중복/저장 실패/해시/기존 계정 보존과 가입→로그인→양쪽 프로그램 이동을 격리 DB에서 확인한다. 최신 공개 기본 검증은 [PLAT-20261028-03](../changes/platform.md#plat-20261028-03), 최초 구현·독립 검수는 [이전 기록](../changes/platform.md#plat-20261028-02)에 구별한다. 가입 route·템플릿·스타일·설정 로딩·로그인 링크를 복구할 수 있다. 이미 만들어진 계정 삭제는 별도 데이터 변경이며 코드 rollback에 포함하지 않는다. 운영 PostgreSQL/도메인 검증·배포는 이번에 하지 않는다.

<a id="account-privacy"></a>
## PLAT-06 계정별 검사·개인 일정·공유·댓글

[계정·공유 SSOT](07-account-sharing.md)가 소유권·읽기/수정 권한·검사별 공유·개인 메모·수신자별 댓글·원본 불변 PDF·이관/복구 계약을 담당한다. 공통 구현은 `permissions.py`, `account_schema.py`, `collaboration.py`, `views.py`의 통합 대시보드/일정과 `templates/exam_detail.html`, `schedule_panel.html`, `static/account.css`다. TCI/KHTP의 기존 계산·본문·관찰·모델 계약은 유지한다. 기능별 검증과 운영 상태는 [PLAT-20261028-04](../changes/platform.md#plat-20261028-04)에 기록한다.
