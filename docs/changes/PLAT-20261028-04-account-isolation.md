# PLAT-20261028-04 계정 분리·공유·댓글 패치 기록

날짜:2026-10-28 · 기능:PLAT-06/TCI/KHTP · 상태:구현·최종 자체 검증·독립 재검수 통과/운영 적용 전

요청과 계약은 [계정·공유 SSOT](../ssot/07-account-sharing.md)를 따른다. 사용자 예시 sura TCI5/KHTP3·test1 초기0·특정2+1공유후3, 소유자만 원본 수정, 개인 메모/수신자별 댓글, 개인 일정의 통합 대시보드 이동을 구현했다. 기존 TCI/일정 모두 sura 소유라는 후속 확인을 받았으며 명시 귀속 CLI를 준비했다.

## 변경과 영향

- 공통 서버: `account_schema.py`, `permissions.py`, `collaboration.py`, `db.py`, `views.py`, `exam_history.py`, 앱 등록/인증 응답 no-store(`app.py`).
- TCI 원본 경로: `candidates.py`, `type_workspace.py`, `final_report.py`, `pdf_export.py`의 소유 조건. 분류·본문·출처 사본 형식은 유지.
- KHTP: `khtp_web/__init__.py`의 목록/image/data 공유 읽기만 확장. owner 전용 workspace/save/analyze/PDF POST·모델/팩은 유지.
- UI: portal/TCI·KHTP 목록/공통 검사이력/최종보고서·KHTP 편집 링크, 신규 exam_detail/schedule_panel/account.css. R1로 static/khtp.js에서 새 검사/업로드의 현재 공유 링크만 동기화. 새 배치는 Flexbox, 추가 아이콘/프런트엔드/라이브러리 없음.
- DB/payload 변경 있음: reports/appointments nullable owner FK(미귀속격리), 공유/댓글2테이블·검증 FK/UNIQUE/one-of. 신규작성 owner는 서버 고정. 공유/댓글/일정 POST는 계정CSRF. 본문/점수/그림/수정시각/개정은 댓글/무저장 PDF로 변경하지 않음.
- 공용 영향 있음: 두 프로그램 조회/공유/이력·통합 대시보드·댓글 공개범위. 기본 참고 라이브러리는 이번 개인화 대상에서 제외.
- 생성 파일: 제품은 요청한 PDF만 다운로드, 메모/댓글 미포함. QA 산출물은 로컬 tmp에만 보관.

## 실행 근거

초기 전체unittest233건, --all-unassigned 추가 후235건 통과. no-store 보완 뒤 새 통합6건 통과. 실제 Chromium10검증군·JS오류0·320/390px, 실제 한글PDF10쪽 렌더/직접 확인, PostgreSQL18.6의 FK/중복/one-of7건·이관/rollback·실제잠금회수경쟁 검증을 수행했다. PG클러스터와 QA웹서버는 종료했다. 최종 전체/독립 리뷰는 후속 기록한다. 각 실행자 결과와 root 통합 결과는 로컬 실행보고서에서 구별하고 최초 실패도 보존한다.

독립 최초검수: SQLite 권한반례8건 통과·읽기경로SQL DML0, R1(P2)1건(KHTP A→새검사에서 공유링크A잔존). 별도Astra UI보완 후 **최종 전체236건·70.627초·OK**, 실제Chromium R1추가3검증군 통과·JS오류0·QA종료. 기존10검증군과 합쳐13개 그룹이되 서로다른검증으로구별한다. 댓글생성시각 O1은101건에서미재현된잠재권고였으며 같은시각저장으로예방보완했다. 최초실패/보완/재검수판정은 로컬 `docs/reports/PLAT-account-review.md`에 보존한다.

독립 재검수 **필수 범위 통과·추가 필수 수정0건**. 리뷰어 Chromium4검증군·JS0에서 미저장 전환취소/A보존·확정전환링크제거·B업로드/올바른B공유·신규C즉시링크를 확인했다. 별도 시계 제어 unittest2건으로 양 프로그램의 댓글생성시각동일·실제편집시갱신·검사원본불변을 확인했다. 최초 권한8반례, root236/브라우저13/PDF10쪽/PG와 독립 결과는 구별한다. 리뷰 하네스303전달timeout 후 브라우저이동/FlaskPOST를 분리해 통과한 한계도 리뷰 원문에 보존했다.

## 운영·복구·남은 일

운영 DB/기존 서비스·실사용 계정/기록·모델·Git·배포는 변경하지 않았다. 실제 적용은 [매뉴얼](../index.md#account-privacy)의 구조 준비/명시 sura 귀속 후 사용자 재시작·검증 단계다. 원본 이관은 소유자 열만 변경하며 실제 계정 없으면 거부한다. 미귀속은 숨김 유지.

코드/문서는 복원할 수 있으나 과거 공동 조회 버전으로 운영 rollback하지 않는다. 새 owner/공유/댓글 보존과 접근 차단·호환 확인이 필요하다. 독립 검수는 통과했으며 사용자 최종 판단·실제 운영 이관/배포는 별도다.
