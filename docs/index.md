# 실행·사용 매뉴얼

2026-10-29 해석 업그레이드: [대상자·스케줄러 계약](ssot/08-people-scheduler.md), [코드 반영 후 DB 준비·관리자 지정](../README.md), [검증·배포 상태](changes/platform.md#plat-20261029-01)를 먼저 확인한다. 통합 진입 화면 이름은 대시보드이고 TCI·K-HTP·스케줄러 세 영역을 사용한다.

[시작 안내](../README.md) · [폰트 출처·라이선스](../static/fonts/README.md)

기능 수정·CSS·아이콘·베타 패치는 **[작업 매뉴얼 인덱스](manual-index.md)**에서 시작한다. 이 문서는 설치·실행·일상 사용을 담당하며 기능별 계약과 변경 이력은 작업 인덱스로 연결한다.

## 설치와 환경 설정

Windows PowerShell, Python 3.12, PostgreSQL 18을 사용한다. 별도 프런트엔드 빌드 없이 Flask가 화면·정적 파일을 제공한다. 프로젝트 루트에서 실행한다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-khtp.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

| 의존성 파일 | 용도 |
|---|---|
| [requirements.txt](../requirements.txt) | Flask·DB·Playwright 기본 실행 |
| [requirements-khtp.txt](../requirements-khtp.txt) | K-HTP 이미지 처리 |
| [requirements-khtp-model.txt](../requirements-khtp-model.txt) | 로컬 CPU 모델로 자동 후보 생성 |
| [requirements-khtp-tools.txt](../requirements-khtp-tools.txt) | 선택 사항: PDF 자료 준비·검수 |

모델 requirements가 tools 파일을 constraints로 참조하므로 네 파일은 함께 유지한다. 앱 실행에 검수 도구 전체 설치가 필요한 것은 아니다. 자동 후보 생성이 필요한 환경에서만 추가 설치한다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-khtp-model.txt
.\.venv\Scripts\python.exe -m pip check
```

PostgreSQL에 프로젝트용 DB·접속 계정을 준비한다. 최초 설치에서만 아래 명령으로 환경 예시를 복사한다. 기존 `.env`는 유지한다.

```powershell
Copy-Item .env.example .env
```

`.env`를 실제 DB 접속 정보로 수정한다.

```dotenv
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=tci
DB_USER=tci_app
DB_PASSWORD="직접 설정한 DB 비밀번호"
```

`SECRET_KEY`는 최초 실행 시 생성해 `.env`에 추가한다. `.env`는 Git에서 제외한다. DB 비밀번호와 웹 로그인 비밀번호는 별개다.

## DB·계정·서버 실행

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app init-db
.\.venv\Scripts\python.exe -m flask --app app:create_app create-user
.\.venv\Scripts\python.exe -m flask --app app:create_app run --debug
```

`init-db`는 없는 테이블을 만들며 기존 데이터를 삭제하지 않는다. `create-user`는 아이디·비밀번호를 대화식으로 입력받고 기존 계정을 덮어쓰지 않는다. 기본 주소는 `http://127.0.0.1:5000`, 종료는 `Ctrl+C`다. 로그인 → 통합 대시보드 → TCI 또는 K-HTP로 이동한다. 이 명령은 로컬 개발용이다.

기존 DB에 계정 분리 버전을 적용할 때는 **앱 재시작 전에** 아래 [계정 분리 준비](#account-privacy)의 `upgrade-privacy`와 기존 자료 귀속을 수행한다. `init-db`만으로 기존 reports/appointments에 owner_id가 추가되지는 않는다. 운영 설치·설정·배포는 사용자가 직접 수행한다.

`create-user`는 초기 계정을 명령으로 만들 때 사용한다. 웹에서도 아래 회원가입을 사용할 수 있으며 같은 `users` 테이블에 저장한다.

기존 DB는 서버 재시작 전에 필요한 갱신을 실행한다. `init-db`만으로 기존 테이블의 누락 컬럼이 추가되지는 않는다.

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app upgrade-composition
.\.venv\Scripts\python.exe -m flask --app app:create_app upgrade-selection
```

각각 `reports.composition`, `interpretations.selection`의 nullable JSONB 컬럼을 추가한다. 기존 본문·점수·자료를 갱신하지 않으며 재실행 가능하다. 새 DB는 `init-db`에서 해당 컬럼까지 생성한다. 앱 시작 시 갱신을 자동 실행하지 않는다.

<a id="registration"></a>
## 회원가입

로그인 화면의 **회원가입**을 누르거나 `/register`를 연다. 아이디(앞뒤 공백 제거·내부 공백 없이1~80자), 비밀번호(8~128자·공백만 불가), 비밀번호 확인을 입력한다. 중복 아이디는 가입하지 않으며 비밀번호를 해시로 저장한다. 성공하면 로그인 화면에서 가입 완료를 안내한다. 가입 후 직접 로그인해 통합 대시보드를 연다.

2026-10-28 사용자가 **누구나 가입하는 공개 회원가입**을 선택했다. 기본값은 공개 가입이며 등록 관련 환경변수가 없어도 가입 버튼을 사용할 수 있고 초대 코드를 요구하지 않는다. 서버에 이전 `REGISTRATION_OPEN=0/false` 또는 빈값이 명시되어 있다면 `1` 또는 `true`로 바꾸고, `REGISTRATION_INVITE_CODE`가 있다면 제거/비운 뒤 앱을 재시작한다. 무설정과 달리 명시적인 빈값·`0`·`false`는 닫힘 설정으로 유지한다. 초대 코드가 설정되어 있으면 기존 제한 호환을 위해 코드 검증을 우선한다. 공개 운영에는 초대 코드를 설정하지 않는다. 운영 설정과 재시작은 사용자가 수행하며 앱이 기존 `.env`에 설정을 자동으로 쓰지 않는다.

현재 검사는 계정별로 분리된다. 새 계정은 본인이 만든 검사와 명시 공유받은 검사만 열람하며 원본과 일정은 소유자만 수정한다. 기본 해석자료·관찰 팩은 기존 공통 참고자료다. 가입 처리 자체는 기존 계정·보고서·자료를 변경하지 않고 신규 계정만 저장한다. 기존 DB의 계정 분리 준비는 아래 절을 따른다.

<a id="account-privacy"></a>
## 계정별 검사·일정과 기존 자료 준비

새 DB는 `init-db`로 준비한다. 기존 DB는 사용자가 DB/설정을 보존하고 앱을 중단한 상태에서 프로젝트 루트의 가상환경으로 실행한다. 이 문서의 예시 명령은 자동 실행 지시가 아니다.

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app upgrade-privacy
```

TCI reports·appointments의 owner_id와 공유/댓글 테이블·인덱스를 추가하며 재실행 가능하다. 기존 본문·점수·그림·일정 내용과 KHTP 소유권을 바꾸지 않는다. 미귀속 TCI/일정은 모든 계정에서 숨긴다. 앱 시작/Git 갱신으로 자동 이관하지 않는다.

2026-10-28 사용자가 기존 TCI와 일정은 **모두 sura 작성**이라고 확인했다. 실제 적용 DB에 sura 계정이 이미 있는지 확인한 뒤 다음 점검을 실행한다. 명령은 sura 계정을 자동 생성하지 않는다.

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app assign-legacy-owner --username sura --all-unassigned
```

기본은 dry-run이다. 대상/미귀속 건수를 확인하고, 실제 귀속할 때만 실행한다.

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app assign-legacy-owner --username sura --all-unassigned --apply
```

owner_id가 없는 TCI/일정만 sura에 귀속하며 이미 다른 계정 소유인 행은 유지한다. 반복 실행은 멱등이다. 잘못된 연결·없는 계정·오류 시 트랜잭션 전체를 취소한다. 일부 검사만 지정할 경우 `--report-id`/`--appointment-id`를 반복 사용하고 `--all-unassigned`와 혼용하지 않는다. 일정에 연결된 검사는 해당 계정이 소유/공유 접근할 수 있어야 한다.

원래 로컬 실행 명령으로 앱을 시작하고 sura의 기존 검사/일정, test1의 초기 빈 목록, 명시 공유한 검사만 보이는지 확인한다. 코드 복구만으로 과거 공동 조회 버전으로 돌아가면 분리가 풀리므로 새 소유권/공유/댓글을 보존하고 접근 차단 상태에서 호환을 확인한다.

### 공유·개인 메모·댓글 사용

검사 목록이나 원본 편집 화면의 **공유·메모**에서 저장본 화면을 연다. 소유자가 상대 아이디를 정확히 입력해 그 검사만 공유한다. 수신자의 통합 대시보드 **공유받은 검사**와 각 프로그램 목록에 표시된다. 상대는 원본을 수정/재분석/재공유하지 못한다. 저장본 PDF는 원본을 저장하지 않으며 댓글/개인 메모도 출력하지 않는다.

검사 소유자는 완료 후에도 원본을 편집할 수 있고 수신자는 최신 저장본을 본다. **개인 메모**는 작성자만, **공유 대화**는 소유자와 선택한 수신자만 본다. 작성자는 자기 메모/댓글만 수정·삭제한다. 공유 회수 뒤 새로운 읽기/댓글/그림/PDF 요청을 막고 기존 대화는 소유자에게 보존한다. 이미 내려받은 파일은 회수되지 않는다.

오늘·이번 주 일정은 **통합 대시보드**에서 계정별로 등록·수정·삭제한다. 검사 공유로 일정/일정 메모가 공유되지 않는다. 일정 연결은 현재 접근 가능한 TCI만 선택하며 공유 회수 후 검사 이름/링크를 새로 노출하지 않는다.

## TCI 자료 등록

테이블 준비 후 명시적으로 등록한다. 앱 기동·초기화만으로 자동 등록되지 않는다.

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app seed-library
.\.venv\Scripts\python.exe -m flask --app app:create_app link-initial-selection
.\.venv\Scripts\python.exe -m flask --app app:create_app seed-type-library
```

`seed-library`는 `data/interpretations.json`의 소스 4개·문단 8개를 등록한다. `link-initial-selection`은 초기 내용과 같고 연결이 비어 있는 문단만 보강한다. 사용자 편집·사용 중지·기존 연결은 유지한다.

`seed-type-library` 기본 동작은 읽기 전용 점검이다. 누락 목록·차이를 확인한 뒤 원고를 등록하려면 실행한다.

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app seed-type-library --apply
```

`data/type_interpretations.json`의 통합 54개·추가 원고 중 없는 안정 키만 등록한다. 기존 전사·편집·중지·연결·보고서는 덮어쓰지 않는다. 원문 전사·비출력 비교 자료와 보고서용 설명을 구별한다. 제공 자료 기반 설명이며 공식 성인용 검증 완료를 뜻하지 않는다.

추가 자료는 TCI **자료 관리**에서 등록·수정·사용 상태를 관리한다. 일반적인 자료 변경에 코드 수정·재배포는 필요 없다.

## TCI 사용

대시보드에서 새 점수 입력 또는 최근 검사·검색·빠른 리뷰·이어 작성으로 기록을 연다. 오늘·이번 주 일정도 관리한다.

새 보고서는 점수·T기준 입력 → 자동 보고서 확인 → 저장·PDF 순서다. 현재 기질·성격 두 유형의 통합 설명을 기본 구성하고 다른 해석은 필요할 때 추가한다. 직접 편집하거나 비운 본문과 저장 기록은 자료 갱신만으로 덮어쓰지 않는다.

- 원점수·T점수·백분위는 독립 입력이다. 빈칸을 0으로 바꾸거나 표준점수를 임의 환산하지 않는다.
- 기본 T56은 L: T ≤ 45, M: 45 < T < 56, H: T ≥ 56이다. T55·사용자 지정 경계도 제공한다.
- 반올림 기본값은 없음이며 선택 시 원본을 보존하고 Decimal·ROUND_HALF_UP을 적용한다.
- 기질 코드는 NS·HA·RD, 성격 코드는 SD·CO·ST 순서다. PS·SC는 세 글자 코드에서 제외한다.
- 그래프 위치는 입력 백분위이고 H/M/L은 선택한 T기준의 분류다.

T기준 변경 시 유형과 수정하지 않은 자동 본문을 갱신한다. 직접 편집·추가 내용은 유지하고 유형 차이를 표시한다. 다른 해석은 추가한 내용만 출력한다. 저장 후 검사 목록에서 다시 연다.

TCI·K-HTP 목록의 **검사 이력**에서 같은 관리번호의 기록을 함께 확인한다. 별도 대상자 선행 등록은 필요 없다.

## K-HTP 준비·사용

최초 준비 또는 이전 구조 갱신 시 실행한다.

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app khtp-upgrade-db
.\.venv\Scripts\python.exe -m flask --app app:create_app khtp-import-pack data/khtp/observations-v1.json
```

`khtp-upgrade-db`는 K-HTP 테이블·이름·관리번호·검사일을 준비하고 과거 JSON 대상 정보를 한 번 이관한다. 기존 독립 필드는 덮어쓰지 않는다. 유효하지 않거나 일부만 있는 과거 대상 필드는 자동 보정하지 않고 중단하므로 오류를 확인한다. TCI 자료는 변경하지 않는다.

관찰 팩은 자체 정의 24개·8그룹이다. 같은 버전은 중복 등록하지 않으며 같은 버전의 내용 변경은 거부한다. 갱신은 JSON 버전을 바꿔 등록한다. 기존 검사의 자료 사본은 유지한다.

K-HTP → **새 검사**에서 이름 또는 관리번호 하나와 검사일을 입력한다. 이름·관리번호는 각각 100자까지이며 검사일은 오늘이 기본값이고 비울 수 있다. JPEG/PNG 한 장을 올리고 관찰표를 확인·수정한 뒤 **PDF 받기**를 누른다. 제한은 20MB·2천만 픽셀이며 방향 보정·메타데이터 제거 후 저장한다.

그룹 제목을 눌러 상태·문장을 수정한다. **PDF 받기**는 현재 수정도 함께 저장한다. 실패하면 입력을 유지한 채 재시도한다. 목록에서 이름·관리번호·검사일로 검색해 다시 연다. 기록·그림은 DB에 영구 보관하며 24시간 자동 삭제는 없다. `khtp-cleanup`은 삭제하지 않는 호환 안내다.

### 자동 후보 생성용 별도 자산

모델 패키지 외에 다음 자산이 프로젝트 루트 기준으로 필요하다. Git에 포함하지 않으며 앱이 자동 다운로드하지 않는다.

```text
tmp/khtp-model/
  house-best.pt
  tree-best.pt
  personf-best.pt
  personm-best.pt
  upstream.zip
  upstream/yolov5-d3ea0df8b9f923685ce5f2555c303b8eddbf83fd/
```

준비된 로컬 자산을 별도로 배치한다. worker는 가중치·원본 ZIP 해시와 고정 소스 파일을 확인한다. 기준값은 [worker.py](../khtp_web/worker.py)에 있다. 외부 소스·모델의 이용 조건도 확인한다. 자산·패키지가 없거나 검증에 실패하면 자동 분석 실패를 표시하며 직접 작성·PDF는 사용할 수 있다. 새 PC에서 저장소만 내려받으면 자동 후보 자산까지 준비되는 것은 아니다.

자동 관찰은 확인할 후보이며 최종 심리 판단은 사용자가 한다. 실제 복합 K-HTP 판독 성능·임상적 타당성은 미검증이다. 사용자 그림을 외부 AI로 전송하지 않는다.

## PDF·문제 해결

PDF는 현재 편집·표시 설정을 저장한 동일 데이터로 생성한다. 실제 적용 기준과 참고 설명을 구별한다. `static/fonts/`의 Noto Sans CJK KR Regular·Bold와 `OFL.txt` 라이선스를 함께 유지한다.

| 증상 | 확인 |
|---|---|
| DB 접속 실패 | PostgreSQL 실행, DB·계정, `.env` 접속 정보 |
| 기존 DB 컬럼 누락 | DB 갱신 명령과 K-HTP 갱신 여부 |
| TCI 자동 설명 없음 | 자료 등록, 점수·유형·적용 조건, 자료 사용 상태 |
| K-HTP 이미지 처리 불가 | 이미지 패키지 설치와 이미지 제한 |
| 자동 관찰 실패 | 모델 패키지·별도 자산·고정 소스/해시. 직접 수정 후 PDF 가능 |
| PDF 생성 실패 | 실행 계정의 Chromium 설치·로컬 폰트 |

Chromium이 없으면 같은 실행 계정에서 실행한다.

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

저장 뒤 PDF 생성만 실패하면 화면의 PDF 재시도를 사용한다. Linux/AWS 실제 실행·출력은 별도 확인이 필요하다. AWS 서버 설치·설정은 사용자가 직접 진행한다.

<a id="git-scope"></a>
## Git 관리 범위

실행 코드·템플릿·정적 자산·지정 초기 데이터·의존성 4파일·환경 예시·실행 매뉴얼과 현행 유지보수 문서를 포함한다. 상세 허용 목록은 [.gitignore](../.gitignore)를 따른다.

2026-10-28부터 `AGENTS.md`, `SSOT.md`, `docs/manual-index.md`, `docs/manual/*.md`, `docs/ssot/*.md`, `docs/changes/*.md`를 명시 허용한다. 공통 기반·TCI·K-HTP의 현행 계약과 패치 이력을 새 체크아웃에서도 읽을 수 있게 한다. 허용 목록만으로 추적·commit·push 완료를 판단하지 않는다.

테스트·`scripts/` 검증 도구·보고서·중복 보존본·개발 계획·과거 task/설계/참고/인계 문서·원본 자료·비밀 설정·가상환경·임시 산출물은 로컬 보관 대상으로 제외한다. 과거 개발 문서의 링크는 추가 근거이며 설치 선행 조건이 아니다. 폰트 출처 안내·라이선스는 배포 자산에 포함한다.

기존 `.env`·DB·사용자 기록을 Git 업데이트로 교체하지 않는다. `.gitignore`는 커밋 이력을 지우지 않으므로 이후 포함 범위를 바꾸면 추적 목록도 확인한다.
