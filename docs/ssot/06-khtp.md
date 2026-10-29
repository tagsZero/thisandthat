# K-HTP 기능·유지보수 SSOT

2026-10-29 추가 보완 R6~R8: 작성 계정의 서명 컨텍스트·동일 계정 재인증·다른 계정 저장 차단, 검사 댓글 실패 복구, 검색 Enter 처리는 [추가 보완 계약](08-people-scheduler.md#account-draft-recovery)을 따른다. 기존 API/옛 화면 호환 제한과 실제 검증/운영 상태는 [PLAT-20261029-03](../changes/khtp.md#plat-20261029-03)에 기록한다.

2026-10-29 최신 변경: 그림 업로드/저장에 대상자 선택·자동 코드 발급을 연결한다. 기존 revision과 저장/분석/PDF 계약을 유지한다. 공유 수신자에게 원 소유자의 person_id·전체 이력을 노출하지 않는다. 저장한 기록에서 일정 잡기를 제공한다. 상세 계약은 [대상자·스케줄러 SSOT](08-people-scheduler.md)를 따른다. 아래 이와 다른 과거 일정 배치·비공개 전용 설명은 대체한다. 검증 진행은 [변경 대장](../changes/platform.md#plat-20261029-01)에 기록한다.

2026-10-29 후속 보완: 검사 대상자 변경의 일정 연결 정리, 저장 응답 사본과 실패 복구는 [보완 계약](08-people-scheduler.md#recovery-fixes)을 따른다. 구현 위치와 전체 311건/독립 29건 검증·운영 상태는 [최신 패치 기록](../changes/khtp.md#plat-20261029-02)에 연결한다.

상태: active · 계약 관리: K-HTP 익스큐트(Astra) / 오케스트라 · 갱신·소스 대조: 2026-10-29

[작업 인덱스](../manual-index.md) · [통합 SSOT](../../SSOT.md) · [공통 UI](../manual/ui-rules.md) · [K-HTP 변경 대장](../changes/khtp.md)

아래 ID는 유지보수 기능 ID다. 문서·설계·검토 후 구현하며 그림→관찰표 확인/필요 수정→PDF의 단순 흐름을 유지한다. 최신 영구 기록 계약을 따른다. 옛 문서의 24시간 임시 보관은 현재 기능 계약이 아니다. 과거 모델 실행 근거는 실제 복합 K-HTP 정확도 승인과 별개다. 로컬 심화 설계 `docs/tasks/KHTP-program-design.md`는 과거 근거를 포함하며 새 체크아웃의 필수 설치 파일로 요구하지 않는다.

2026-10-28 최신 공유/메모는 [계정·공유 SSOT](07-account-sharing.md)를 따른다. 기존 owner_id와 원본 편집/저장/분석/PDF POST는 소유자 전용으로 유지한다. 목록·image/data의 읽기만 본인 또는 유효 공유로 확장하고 `/exams/khtp/<id>`에서 수신자가 저장본·무저장 PDF·개인 메모/수신자별 댓글을 이용한다. 공유 회수 뒤 그림/데이터/댓글/PDF의 새 접근을 막고 기존 원본/개정은 보존한다.

<a id="workspace"></a>
## KHTP-M01 대상 정보·그림·관찰 편집

- 진입/소스: `GET /khtp/new`, `GET /khtp/<uuid:id>`, `POST /khtp/upload`; `khtp_web/__init__.py`, `domain.py`, `templates/khtp/workspace.html`, `static/khtp.js`, `static/khtp.css`.
- 입력·검증 원본: `validate_subject`, `domain.py:normalize_image/apply_edits`가 담당한다. 이름·관리번호 중 하나는 입력하고 각100자 이내, 검사일은 한국 오늘 기본·빈값 허용이다. 업로드는 multipart `image/name/reference/exam_date`, JPEG/PNG 한 장·20MB·2천만 픽셀 제한이다. 방향 보정·메타데이터 제거 후 그림을 저장한다.
- 관찰 계약: 자료 팩은 `data/khtp/observations-v1.json`의 자체24개/8그룹이다. 관찰됨·사용자 없음 확인·아직 관찰하지 않음·판단불가를 구별한다. 그룹에서 수정하고 직접 비운 문장·좌표·상태를 재분석으로 덮어쓰지 않는다. 필수 행별 승인·모델/양식 선택 단계를 추가하지 않는다.
- 저장/응답: 업로드 시 `khtp_jobs`에 그림·크기·팩 사본·대상 정보·관찰·분석 상태·개정을 생성한다. `public()`의 `job`은 id/dimensions/pack/observations/analysis/extras/revision과 subject/url/image_url을 제공한다. subject 응답은 독립 저장 열에서 구성한다. 영구 저장은 M03을 따른다.
- 인증·공용 영향·생성물: 로그인·K-HTP API 검증을 유지하고 그림은 소유자 조회 route로 제공한다. 공통 헤더와 TCI 소스/자료는 변경 범위가 아니다. 정규화 그림은 DB에 저장하며 별도 공개 정적 파일로 생성하지 않는다.
- 검증·복구: 대상 오류·그림 제한·새 검사/기존 검사·수정/빈값/새로고침·미저장 보호를 확인한다. UI와 domain 계약을 호환되게 복구한다. 소스 복구만으로 저장 관찰·그림을 되돌리지 않는다. 이번 실행 없음.

<a id="analysis"></a>
## KHTP-M02 로컬 자동 후보·자료 팩

- 진입·소스: `POST /khtp/<uuid:id>/analyze`, `khtp_web/__init__.py:analyze/run_inference`, `domain.py:merge_analysis/recalculate`, `worker.py`.
- 처리·상태: 현재 편집/대상과 개정을 먼저 저장한 뒤 로컬 worker를 실행한다. house/tree/personf/personm의 결과에 따라 ok/partial/failed를 구별한다. 실행 실패·미탐지를 ‘없음 확인’으로 바꾸지 않는다. 박스·비율 계산과 의미상 후보·사용자 직접 판단은 다르며 객체 수·부모 귀속을 좌표 유효성만으로 확정하지 않는다.
- 보존/저장: `analysis`, `observations`, `extras`, `revision`을 갱신한다. 늦은 응답·개정 충돌에서 최신 수정을 보존한다. 재분석으로 부모가 사라지면 연결 미정을 허용하고 사용자 문장·빈값·좌표를 유지한다. 관찰이 미확정이어도 저장/PDF를 막지 않는다.
- 자산·의존성: 가중치·upstream ZIP/고정 소스는 [매뉴얼](../index.md)의 별도 로컬 자산이며 Git에 넣거나 앱이 자동 다운로드하지 않는다. 해시/클래스 검증 원본은 `worker.py`. 기본 TCI requirements와 K-HTP 앱/모델/tools 파일을 구별하고 설치를 기능 완료로 표시하지 않는다. 외부 AI 전송은 현재 범위에 없다.
- 자료 팩: `khtp_packs`에 버전·digest·content를 명시 import한다. 같은 버전의 다른 내용을 덮어쓰지 않고 새 버전으로 등록하며 기존 검사 팩 사본은 유지한다. schema/검증 원본은 `validate_pack`·`import_pack`이다.
- 검증·복구: 실제 후보 실행과 통제 실패 주입을 구별하고 수정 보존·부분/실패·충돌·자료 버전 호환을 확인한다. 모델/팩 변경은 실행 근거·이용 조건·이전 자산 복구 가능성을 먼저 기록한다. 공개 개별 HTP 수치를 복합 그림 성능으로 확장하지 않는다. 이번 추론·설치·자료 등록 없음.

<a id="records"></a>
## KHTP-M03 기록·목록·저장·권한

- 진입·소스: `GET /khtp` 목록, `GET /khtp/<uuid:id>/data`, `POST /khtp/<uuid:id>/save`; `khtp_web/__init__.py:index/find/public/commit_edit`, `templates/khtp/records.html`, `static/khtp.js`.
- 목록: 소유자별 이름·관리번호·검사일 통합 검색, 최근 사용시각/ID 정렬·20건 페이지, UUID별 다시 열기를 제공한다. 관리번호 통합 이력은 [PLAT-03](04-platform.md#history) 담당이다. 기록·그림은 영구 보관하며 24시간 자동 삭제는 없다. `khtp-cleanup`은 삭제하지 않는 안내다.
- 저장 원본: 테이블은 `khtp_web/__init__.py`의 `khtp_jobs`. id/owner_id, image(bytea), dimensions/pack/observations/analysis/extras(JSONB), name/reference(nullable VARCHAR100), exam_date(nullable DATE), revision/last_used 및 legacy subject/expires_at을 보유한다. 독립 대상 열이 현재 원본이며 legacy subject/expires_at은 현재 대상/보관 기간의 기준이 아니다.
- payload·검증: 저장 JSON은 정수 `revision`, `edits`, 선택 `subject`를 받는다. `commit_edit`가 수정/대상을 같은 트랜잭션에서 검증하고 개정을 증가시킨다. 응답은 `job`과 안내이며 개정 불일치는409다. 상세 edits 구조는 `domain.py:apply_edits`와 `static/khtp.js`를 함께 대조한다.
- 인증: 로그인과 `owner_id`, 쓰기 API의 `X-KHTP-CSRF`를 검증한다. UUID가 있다는 이유만으로 타 사용자 접근을 허용하지 않는다. 세션 current와 명시 UUID 조회를 구별하며 다른 탭 기록을 섞지 않는다. 이 권한을 TCI 전체에 구현된 것으로 확대하지 않는다.
- 이관·생성물·복구: `khtp-upgrade-db`의 과거 대상 JSON 이관은 명시 실행하며 반복으로 최신 값/빈값을 덮어쓰지 않는다. 상세 설치는 매뉴얼 소유다. 목록/저장은 별도 파일을 생성하지 않는다. 되돌릴 코드가 신규 열·저장 형식을 읽는지 확인하며 DB 열 삭제나 저장 기록 초기화를 코드 rollback에 포함하지 않는다.
- 검증: 저장/재열기·오래된 기록·검색/페이지·타 소유자·복수탭·재로그인·개정 충돌·이관 반복/실패 보존을 변경에 맞춰 확인한다. 이번 DB·브라우저 검증 없음.

<a id="pdf"></a>
## KHTP-M04 같은 개정 PDF

- 진입·소스: `POST /khtp/<uuid:id>/pdf`, `khtp_web/__init__.py:pdf/pdf_bytes`, `templates/khtp/pdf.html`, `static/khtp.js`.
- 계약·저장: M03의 revision/edits/subject 저장을 먼저 완료하고 그 사본으로 PDF를 생성한다. 상·하단 버튼은 같은 동작이며 별도 선행 저장을 요구하지 않는다. PDF 실패여도 저장 성공은 `save_state='saved'`와 해당 job으로 구별한다.
- 생성 주체: 공통 `tci_web/pdf_export.py:render_pdf`가 Playwright/Chromium으로 생성하고 `application/pdf` 다운로드로 응답한다. 그림·폰트는 렌더링에 포함하며 `X-KHTP-Revision`, `X-KHTP-Save-State`를 사용한다. PDF 파일의 자동 이력 저장은 없다.
- 경계·영향: 로그인/소유권/CSRF/개정 검증 후 출력한다. 미확정 관찰의 PDF를 막지 않으며 실제 판독 검증 완료로 표시하지 않는다. 공유 렌더러·폰트 수정은 TCI PDF에도 영향을 준다.
- 검증·복구: 현재 대상/문장과 PDF 개정 일치·한글·그림·긴 문장 페이지 나눔·실패/재시도·중복 잠금을 확인한다. 렌더러/템플릿/JS를 호환되게 복구하고 이미 저장된 관찰을 되돌리는 동작과 구별한다. 이번 PDF 생성/열람 없음.

<a id="maintenance"></a>
## 변경과 확인의 경계

[변경 절차](../manual/change-workflow.md#patch)와 [K-HTP 대장](../changes/khtp.md)을 사용한다. 문서·정적 소스 확인과 실제 모델·브라우저·DB·PDF 검증을 구별한다. 이번 문서 정비에서는 운영 schema·도메인·모델 자산·전체 payload 분기·실제 복합 그림 품질을 확인하지 않았다. 새 모델·관찰 정의·라이브러리 변경은 별도 완료 조건과 실제 용도 검증을 갖춘 작업으로 분할한다.
