# 공통 UI·CSS·아이콘 규칙

상태: active · 관리: 공통 UI 담당 익스큐트 / 오케스트라 · 갱신·정적 대조: 2026-10-28

<a id="layout"></a>
## 1. 레이아웃

신규·변경 레이아웃은 Flexbox로 구현한다. 가로/세로 전환, 카드, 버튼 줄, 입력 묶음에는 `flex-direction`, `flex-wrap`, `gap`, `flex-basis`, `min-width`를 사용한다. Grid를 편의상 기본값으로 선택하지 않는다. Flexbox로 구현하기 어려운 경우에만 Grid를 예외 사용하고 해당 selector·어려운 이유·Flexbox 검토 결과·영향 화면·검증 결과를 변경 기록에 남긴다. 이차원이라는 이유만으로 자동 예외를 적용하지 않는다.

데이터 표는 의미에 맞는 HTML `table`을 사용한다. 보고서 그래프·그림·아이콘의 SVG 좌표는 CSS 레이아웃 Grid와 다른 개념이다. 기존 TCI 화면 전체를 일괄 재작성하지 않는다. 단순 문구 수정만으로 주변 배치를 변환하지 않되, 실제 배치를 바꾸는 부분은 새 기준을 적용한다. 기존 Grid를 유지해야 하는 변경은 범위와 이유를 기록한다.

<a id="ownership"></a>
## 2. 스타일과 마크업 소유권

| 소유 영역 | 실제 수정 시작점 | 확인할 공용 영향 |
|---|---|---|
| 색상·폰트·공통 버튼·헤더·페이지 | `static/app.css`, `templates/base.html` | 로그인·통합 대시보드·TCI·K-HTP의 공통 상속 |
| 통합 대시보드 카드 | `templates/portal.html`, `static/app.css`의 `.program-*`, `.portal-*` | TCI/K-HTP 이동 경로, 공용 카드 selector |
| 회원가입 | `templates/register.html`, `static/register.css`의 `.register-page` 범위 | 기존 `app.css` 상속·로그인 진입 링크·PC/모바일 폼 |
| 개인 일정·공유·메모 | `templates/portal.html`, `schedule_panel.html`, `exam_detail.html`, `static/account.css` | owner/공유 표시·읽기 전용 결과·수신자별 대화·개인 메모 |
| TCI 입력·대시보드·해석·웹 보고서 | 해당 `templates/*.html`, `static/app.css` | `.settings-fields`, `.record-actions`, `.profile-*` 등의 다른 사용처 |
| TCI 인쇄 | `templates/report_pdf.html`, `templates/report_body.html`, `static/report_print.css` | `app.css` 상속 및 웹/PDF 데이터 일치 |
| K-HTP 작업·목록 | `templates/khtp/workspace.html`, `records.html`, `static/khtp.css` | `base.html`·`app.css` 공통 상속 |
| K-HTP 인쇄 | `templates/khtp/pdf.html`의 인쇄 스타일 | 그림·표·한글 폰트·긴 문장 페이지 나눔 |
| 공통 아이콘 | `templates/icons.html` | 호출하는 모든 Jinja 템플릿 |
| 미저장 이동 보호 | `static/navigation.js`, 기능별 JS | 헤더·링크·기존 편집문 유지 |

공통 selector 변경 전 실제 사용처를 검색한다. 특정 기능의 배치 변경은 그 영역으로 범위를 제한하고 전역 규칙 중복·말단 덮어쓰기를 누적하지 않는다. 새 CSS 파일이 필요하면 owner와 로딩 위치를 기록한다. 별도 UI 프레임워크는 추가하지 않는다.

<a id="icons"></a>
## 3. Tabler 아이콘

UI 아이콘은 [Tabler Icons 공식 목록](https://tabler.io/icons)에 제공되는 것만 사용한다. 현재 Flask·Jinja2에서는 공식 SVG 마크업을 기존 `templates/icons.html` 매크로로 모아 재사용한다. 공식 사이트도 HTML 삽입·SVG sprite 사용을 안내한다. 아이콘 사용만을 위해 React·Vue·Vite·별도 프런트엔드 서버를 추가하지 않는다.

아이콘을 추가·교체할 때 공식 이름, 원본 URL, 가져온 버전 또는 commit, 라이선스 위치를 매크로 근처 또는 별도 출처 문서에 기록한다. 공식 SVG를 사용하고 크기·색·stroke는 공통 속성으로 맞춘다. 임의 path를 만들어 Tabler라고 표시하지 않는다. 패키지를 사용하는 구조 변경이 실제로 필요하면 기술 SSOT와 의존성 계약부터 갱신한다.

장식 아이콘은 `aria-hidden="true"`, 아이콘만 있는 조작은 버튼/링크에 접근 가능한 이름을 둔다. 점수 그래프나 사용자 그림은 아이콘이 아니므로 Tabler 아이콘으로 대체하지 않는다.

현재 매크로의 원본 출처·버전은 미확인이다. 이번 작업에서 공식 원본 대조·교체·라이선스 파일 추가를 실행하지 않았다. 해당 아이콘을 수정하는 패치에서 대조·출처 기록과 라이선스 보존을 수행한다.

<a id="verification"></a>
## 4. 변경 시 확인

실제 변경 화면과 공용 사용처의 데스크톱·좁은 모바일, 긴 한글·빈 상태·오류·키보드 초점을 확인한다. 로그인→통합 대시보드→해당 프로그램 이동과 미저장 보호를 확인한다. 인쇄에 닿는 변경은 한글·그래프·긴 문장 페이지 나눔을 PDF에서 확인한다. CSS 클래스 이름에 `grid`가 남았다는 사실과 실제 Grid 선언 사용을 구별한다. 실행하지 않은 확인은 미실행으로 기록한다.
