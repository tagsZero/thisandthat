# 해석 작업 매뉴얼 인덱스

2026-10-29 진입점 추가: [대상자 코드·검색·병합](ssot/08-people-scheduler.md#identity), [스케줄러·공유·댓글](ssot/08-people-scheduler.md#schedule), [구현 소유권](ssot/08-people-scheduler.md#ownership). 제품명은 해석, 통합 진입 화면은 대시보드다. 이번 후속 구현/격리 검증은 사용자가 승인했으며 아래 문서 최초 작성 때의 실행 제한과 구분한다.

상태: active · 문서 관리: 오케스트라(범위·색인), 각 기능 익스큐트(계약·소스 대조)
최종 갱신일·정적 구현 대조일: 2026-10-29 · 운영 도메인·배포 상태: 사용자 연결 보고, 직접 확인하지 않음

<a id="entry"></a>
## 1. 목적과 접근 순서

`AGENTS.md → 이 인덱스 → 작업 유형별 규칙·기능 SSOT → 해당 소스·계약` 순서로 읽는다. 설치·실행·일상 사용은 [실행·사용 매뉴얼](index.md)이 담당한다. 이 문서는 코드 수정과 베타 패치의 진입점이다.

- 적용: thisandthat의 공통 기반, TCI, K-HTP 및 앞으로 추가할 프로그램.
- 조사·수정: 현재 사용자 요청에 필요한 문서와 소스부터 확인한다. 링크는 탐색 안내이며 별도 수정·배포 권한이 아니다.
- 이번 작성 범위: 문서 및 `.gitignore`의 문서 허용 목록. 제품 코드·DB·의존성·운영 설정은 변경하지 않는다.
- 이번 실행 제한: Git 명령·build·dev server·test를 실행하지 않는다. 이 제한은 이번 문서 정비에 적용하며 이후 승인된 패치의 검증을 금지하지 않는다.

최신 사용자 지시를 우선한다. [통합 SSOT](../SSOT.md)는 제품 전체 범위, 기능별 SSOT는 해당 기능 계약, [공통 UI 규칙](manual/ui-rules.md)은 스타일·아이콘 소유권, [변경 규칙](manual/change-workflow.md)은 수정·검증·패치 기록을 소유한다. 같은 계약의 원문을 여러 문서에 복제하지 않고 소유 문서의 고정 앵커를 연결한다. 과거 날짜의 실행 기록·snapshot은 현재 계약이나 실행 허가가 아니다.

<a id="routing"></a>
## 2. 작업 선택표

| 작업 | 먼저 읽을 문서·앵커 | 소스 확인 시작점 | 추가 확인 조건 |
|---|---|---|---|
| 대시보드·새 프로그램 진입 | [공통 기반#portal](ssot/04-platform.md#portal) | `tci_web/views.py:portal`, `templates/portal.html` | 헤더·인증·새 데이터 연결 시 공통 계약 확인 |
| 공통 헤더·탐색·로그인 | [공통 기반#auth-navigation](ssot/04-platform.md#auth-navigation) | `templates/base.html`, `tci_web/auth.py`, `static/navigation.js` | 두 프로그램 이동·미저장 보호 영향 |
| 회원가입·가입 제한 설정 | [공통 기반#registration](ssot/04-platform.md#registration) | `tci_web/auth.py:register`, `templates/register.html`, `static/register.css` | 계정 신규 저장·CSRF·중복·기존 열람 범위·초대 설정 |
| 계정별 검사·일정·기존 자료 귀속 | [계정·공유 SSOT](ssot/07-account-sharing.md) | `tci_web/permissions.py`, `db.py`, `views.py`, `khtp_web/__init__.py` | 미귀속 격리·직접 URL/SQL·이력·그림·PDF·명시 이관 |
| 검사 공유·회수·개인 메모·수신자별 댓글 | [계정·공유 SSOT](ssot/07-account-sharing.md) | `tci_web/collaboration.py`, `account_schema.py`, `templates/exam_detail.html` | 소유/읽기 분리·회수 대기 요청·댓글 공개범위·원본 불변 |
| CSS·마크업·반응형·아이콘 | [UI#layout](manual/ui-rules.md#layout), [UI#ownership](manual/ui-rules.md#ownership), [UI#icons](manual/ui-rules.md#icons) | 대상 템플릿 및 그 CSS·JS | 공용 selector·상속·PDF까지 연결 시 영향 확장 |
| TCI 점수·기준·유형 | [TCI#scores](ssot/05-tci.md#scores) | `tci_web/scores.py`, `views.py`, `static/app.js` | 자동 본문·그래프·저장·재열기 영향 |
| TCI 자동 본문·추가·편집·자료 | [TCI#composition](ssot/05-tci.md#composition), [TCI#library](ssot/05-tci.md#library) | `type_report.py`, `type_workspace.py`, `composition.py`, `candidates.py` (`tci_web/`) | 서명·출처·직접 비운 본문·기존 자료 보존 |
| TCI 목록·빠른 리뷰 | [TCI#dashboard](ssot/05-tci.md#dashboard) | `tci_web/views.py`, `templates/tci_dashboard.html` | 소유/공유 필터·검사 이력 영향 |
| 스케줄러·일정 공유·댓글 | [스케줄러 계약](ssot/08-people-scheduler.md#schedule) | `tci_web/scheduler.py`, `scheduler_schema.py`, `templates/scheduler/` | 소유권·연결 검사 별도 권한·소요 시간·개정 충돌·실패 복구 |
| 검사 대상자 재선택·비노출 연결·저장 실패 복구 | [후속 보완 계약](ssot/08-people-scheduler.md#recovery-fixes) | `tci_web/schedule_links.py`, `scheduler.py`, `views.py`, `khtp_web/__init__.py` | 같은 저장 트랜잭션·입력/개정 보존·응답 사본·[패치 결과](changes/platform.md#plat-20261029-02) |
| 작성 계정 전환·검사 댓글 복구·검색 키보드 | [추가 보완 계약](ssot/08-people-scheduler.md#account-draft-recovery) | `khtp_web/__init__.py`, `static/khtp.js`, `tci_web/collaboration.py`, `static/people.js` | 초안/파일·CSRF 갱신·재시도 권한·키보드 제출·[패치 결과](changes/platform.md#plat-20261029-03) |
| 대상자 코드·검색·병합 | [대상자 계약](ssot/08-people-scheduler.md#identity) | `tci_web/people.py`, `db.py`, `templates/people/` | 같은 소유자·순번·병합 확인·원문 보존·양쪽 검사/일정 개정 |
| 회원 관리·기능 스위치 | [관리 계약](ssot/08-people-scheduler.md#management) | `tci_web/admin.py`, `auth.py`, `templates/admin.html` | 관리자·세션 무효화·모든 기능 진입 차단·개인 권한 우회 금지 |
| TCI PDF | [TCI#pdf](ssot/05-tci.md#pdf) | `tci_web/pdf_export.py`, `final_report.py`, `templates/report_pdf.html` | 저장 사본·출력 옵션·공유 렌더러 영향 |
| K-HTP 그림·관찰·모델 | [K-HTP#workspace](ssot/06-khtp.md#workspace), [K-HTP#analysis](ssot/06-khtp.md#analysis) | `khtp_web/__init__.py`, `domain.py`, `worker.py` | 후보 정의·모델 자산·수정 보존 영향 |
| K-HTP 기록·저장·PDF | [K-HTP#records](ssot/06-khtp.md#records), [K-HTP#pdf](ssot/06-khtp.md#pdf) | `khtp_web/__init__.py`, `static/khtp.js`, `templates/khtp/` | 개정 충돌·소유권·이관·공유 렌더러 영향 |
| 통합 검사 이력 | [공통 기반#history](ssot/04-platform.md#history) | `tci_web/exam_history.py`, `templates/exam_history.html` | 양쪽 목록·관리번호·K-HTP 소유권 |
| DB·payload·인증 계약 | 해당 기능의 저장 절 + [공통 기반#storage](ssot/04-platform.md#storage) | `tci_web/db.py`, `khtp_web/__init__.py`, `app.py` | 이관·하위 호환·실사용 기록 영향 |
| 베타 오류·수정·Git 패치 | [변경 규칙#patch](manual/change-workflow.md#patch), 해당 기능의 변경 대장 | 해당 기능의 SSOT부터 선택 | 코드·DB·배포·자료 패치를 구별 |
| 문서 수정·기능 추가 | [변경 규칙#documents](manual/change-workflow.md#documents), [이 문서#extension](#extension) | 계약 소유 문서 | 색인·상위 SSOT·변경 대장의 연결 갱신 |

<a id="ownership"></a>
## 3. 소유권과 역할

| 구분 | 계약 소유 문서 | 수정·패치 기록 | 경계 |
|---|---|---|---|
| 공통 기반 PLAT | [공통 기반 SSOT](ssot/04-platform.md), [대상자·스케줄러 SSOT](ssot/08-people-scheduler.md) | [공통 변경 대장](changes/platform.md) | 대시보드·인증·공용 UI·대상자·일정·통합 이력·관리 |
| TCI | [TCI SSOT](ssot/05-tci.md) | [TCI 변경 대장](changes/tci.md) | TCI 점수·자료·본문·일정 연결·출력 |
| KHTP | [K-HTP SSOT](ssot/06-khtp.md) | [K-HTP 변경 대장](changes/khtp.md) | K-HTP 그림·관찰·기록·출력 |

문서/모듈 소유권은 계약의 담당 위치를 뜻하며 개인별 쓰기 권한이나 계정 권한을 뜻하지 않는다. `tci_web/` 내부에도 공통 인증·공유 PDF 렌더러·통합 이력이 있으므로 폴더 이름만 보고 TCI 전용으로 판단하지 않는다.

오케스트라는 범위·완료 조건·상태, 익스큐트는 지정 구현·실행 근거, 리뷰어는 구현을 바꾸지 않는 독립 검토를 담당한다. 큰 구현은 실행 후 순차 리뷰한다. 작은 문서·링크 수정은 직접 처리할 수 있다. 사용자 최종 완료 판단과 자체 점검 완료를 구별한다.

<a id="extension"></a>
## 4. 새 기능과 문서 추가

새 프로그램이나 통합 대시보드 기능을 추가할 때 구현 전에 기능 ID, 소유 기능군, 진입 route, 소스, 입력·응답·저장 계약, 공용 의존, 검증·복구 계획을 작성한다. 각 기능 문서는 [필수 항목](manual/change-workflow.md#contract)을 채운다. 미확인은 그대로 표시한다. 새 프로그램은 자체 SSOT·변경 대장을 만들고 이 표에 연결한다. 기존 프로그램의 작은 기능은 그 프로그램 SSOT에 고정 앵커를 추가한다.

기능 요구는 기능별 SSOT, 화면 세부는 [화면 SSOT](ssot/02-screens.md), 기술 공통 계약은 [기술 SSOT](ssot/03-technology.md)가 소유한다. 기존 [기능 SSOT](ssot/01-features.md)는 횡단 요구를 보존한다. 요구가 바뀌면 해당 원본과 [통합본](../SSOT.md)을 함께 갱신한다. 완료 보고서는 현재 계약을 대체하지 않는다.

<a id="limits"></a>
## 5. 확인 범위와 알려진 차이

2026-10-28 로컬 문서·route·테이블 선언·템플릿·스타일을 정적으로 대조했다. 운영 도메인 주소·서버 코드 revision·실제 DB schema·브라우저·PDF·현재 Git 추적 목록은 미확인이다. 사용자 도메인 연결 보고를 AWS/배포 검증 완료로 바꾸지 않는다.

기존 `static/app.css`와 `static/report_print.css`에 Grid 관련 규칙이 남아 있다. 기존 `templates/icons.html`의 직접 작성 SVG는 Tabler 원본 출처가 확인되지 않았다. 이번 문서 작업에서 전환하지 않았다. 향후 해당 레이아웃·아이콘을 변경할 때 새 규칙을 적용하고 예외·미전환 범위를 기록한다. K-HTP 옛 문서의 24시간 임시 보관 설명은 최신 영구 기록 계약으로 대체됐으며 옛 실행 기록은 보존한다.

Git 배포본에 필요한 현행 문서만 명시적으로 허용한다. 로컬 `docs/tasks/`, `docs/reports/`, `docs/references/`, `docs/handoffs/`는 심화 이력이며 새 체크아웃의 필수 진입 문서로 요구하지 않는다. [Git 포함 기준](index.md#git-scope)을 따른다.
