# TCI · K-HTP 웹 솔루션

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
