# 해석 · 검사 결과와 일정

## 해석 대상자·스케줄러 업그레이드 (2026-10-29)

최신 [추가 보완 R6~R8](docs/changes/platform.md#plat-20261029-03)은 계정 전환 시 K-HTP 초안 보호, 검사 댓글 복구, 검색 Enter 처리를 포함하며 추가 DB 이관은 없다. K-HTP API·템플릿·JS를 함께 반영한다. 배포 전에 열어 둔 옛 K-HTP 화면은 세션 변경 후 자동 복구가 차단되므로 입력을 보관한 뒤 새 화면을 열어야 한다. 새 화면은 동일 계정 재로그인 후 이어 저장할 수 있다.

후속 오류 보완 R2~R5의 내용·검증·운영 상태는 [최신 패치 대장](docs/changes/platform.md#plat-20261029-02)에서 확인한다. 이 보완 자체는 추가 DB 이관이 없으며, 아래 명령은 대상자·스케줄러 최초 업그레이드에 필요하다.

이번 버전은 DB 준비 후 실행한다. 운영 반영은 사용자가 수행한다. 앱 중지·DB 백업을 완료한 상태에서 저장소의 Python 가상환경으로 실행한다(Windows는 `.\.venv\Scripts\python.exe`, Linux는 `.venv/bin/python`).

```bash
.venv/bin/python -m flask --app app:create_app upgrade-haeseok
.venv/bin/python -m flask --app app:create_app set-admin --username sura
```

`upgrade-haeseok`은 기존 소유권·보고서·그림·댓글을 보존하고 대상자/일정/관리 스키마만 준비한다. 기존 대상자를 이름으로 자동 생성·병합하지 않는다. 기존 소요 시간은 미설정으로 남는다. 첫 관리자는 위처럼 운영자가 지정한 기존 활성 계정이며 공개 가입 순서와 무관하다. `sura`는 이 프로젝트 운영자가 명시한 계정 예시다. 새 설치는 `init-db`와 계정 생성 후 관리자를 지정할 수도 있다. 세 기능은 기본 ON이다. 코드만 업데이트하고 이관을 생략하면 새 컬럼 조회가 실패한다.

사용 흐름: 검사 폼에서 기존 대상자 검색 또는 새 이름/관리번호 입력 → 저장 시 자동 코드 → 저장본의 일정 잡기 → 시간 확인·저장. 대상자 상세에서 중복 코드를 확인 후 병합한다. 일정 공유와 검사 공유는 별도이고, 수신자는 원본을 수정하지 못한다. [저장·권한·복구 계약](docs/ssot/08-people-scheduler.md)을 따른다. 운영 이관·관리자 지정·재시작은 이번 개발 작업에서 대신 실행하지 않았다.

TCI 점수 입력·유형별 보고서 작성과 K-HTP 그림 관찰·PDF 출력을 제공하는 Flask 웹 애플리케이션이다. 계정·검사 기록·자료·일정은 PostgreSQL에 저장한다.

설치·DB 갱신·자료 등록·사용 방법은 **[실행·사용 매뉴얼](docs/index.md)**에서 확인한다.

로그인 화면의 **회원가입** 또는 `/register`에서 아이디·비밀번호·확인으로 누구나 가입한다. 검사는 계정별로 저장하며 지정 계정에만 읽기 전용으로 공유한다. 개인 일정은 통합 대시보드, 공유·개인 메모·수신자별 댓글은 검사 저장본 화면에서 관리한다. [계정 분리·기존 자료 준비](docs/index.md#account-privacy)를 확인한다.

기능 수정·베타 패치는 **[작업 매뉴얼 인덱스](docs/manual-index.md)**에서 시작한다. [에이전트 지침](AGENTS.md) → 인덱스 → 공통 규칙·기능별 SSOT → 소스 순서로 확인한다. 통합 대시보드·TCI·K-HTP의 계약과 수정 대장을 구분하고, 신규·변경 배치는 Flexbox를 기본으로 하며 UI 아이콘은 Tabler만 사용한다.

## 빠른 실행

Windows PowerShell, Python 3.12, PostgreSQL 18과 프로젝트용 DB·접속 계정을 준비한다. 최초 설치에서 실행한다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-khtp.txt
.\.venv\Scripts\python.exe -m playwright install chromium
Copy-Item .env.example .env
```

`.env`를 실제 DB 접속 정보로 수정한다. 기존 `.env`가 있으면 복사하지 않고 유지한다.

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app init-db
.\.venv\Scripts\python.exe -m flask --app app:create_app create-user
.\.venv\Scripts\python.exe -m flask --app app:create_app run --debug
```

기본 주소는 `http://127.0.0.1:5000`, 종료는 `Ctrl+C`다. 자료 등록·K-HTP 준비는 매뉴얼을 따른다. 위 명령은 로컬 개발용이며 AWS 설치·배포는 별도다.

## GitHub 포함 범위

| 포함 | 용도 |
|---|---|
| `app.py`, `tci_web/`, `khtp_web/` | Flask 실행·서버 기능 |
| `templates/`, `static/` | 화면·스크립트·스타일·PDF 한글 폰트와 라이선스 |
| `data/`의 지정 JSON 3개 | TCI 초기·유형 해석, K-HTP 관찰 양식 |
| `requirements*.txt` 4개 | 고정 의존성·모델 설치 시 필요한 constraints |
| `.gitignore`, `.env.example` | Git 포함 기준·비밀값 없는 환경 예시 |
| `README.md`, `docs/index.md`, `static/fonts/README.md` | 시작 안내·실행/사용 매뉴얼·폰트 출처 |
| `AGENTS.md`, `SSOT.md`, `docs/manual-index.md` | 에이전트 지침·제품 통합 기준·수정 작업 진입점 |
| `docs/manual/*.md`, `docs/ssot/*.md`, `docs/changes/*.md` | 공통 수정/UI 규칙·기능별 계약·패치 기록 |

테스트·검증 스크립트·보고서·보존본·과거 task/조사/인계·개발 계획 등 위 허용 목록 밖 문서·원본 자료·비밀 설정·가상환경·임시 결과물·모델 자산은 로컬에 보관하고 Git에서 제외한다. 2026-10-28부터 현행 유지보수 규칙·SSOT·패치 대장은 Git 포함 대상으로 확장했다. 허용 목록 변경은 실제 추적·commit·push 완료를 뜻하지 않는다. 새 루트 파일은 기본 제외되므로 실행 파일을 추가하면 `.gitignore`의 허용 목록도 갱신한다.

K-HTP 자동 후보 생성용 외부 모델 가중치·고정 소스는 별도 준비가 필요하다. 경로와 사용 한계는 매뉴얼을 따른다.
