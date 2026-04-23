# 집 ↔ 사무실 Git 동기화 가이드

## 개요

- 코드는 GitHub 비공개 저장소에 올리고 양쪽에서 `git pull / push` 로 동기화한다.
- **민감 정보**(.env, API 키, DB 데이터)는 git 에 올리지 않는다. 각 PC 에서 별도로 생성/보관한다.
- DB 상태(마이그레이션 후의 테이블 내용, 관리자 계정)는 git 으로 옮기지 않는다. 각 PC 에서 한 번씩 setup 한다.

## 한 번만 하는 작업 (집에서 — 저장소 만들기)

### 1) Git 설치 확인
```powershell
git --version
```
안 깔려 있으면 https://git-scm.com/download/win 에서 설치.
설치 후 최초 1회:
```powershell
git config --global user.name "이규수"
git config --global user.email "herosys1@gmail.com"
git config --global init.defaultBranch main
```

### 2) 로컬 저장소 초기화
```powershell
cd C:\Users\user\바이낸스\binance_auto_trader_project

git init
git add .
git status   # .env 가 목록에 없어야 함!!! 있다면 .gitignore 확인
git commit -m "initial: Binance futures auto trader baseline"
```

### 3) GitHub 에서 비공개 저장소 만들기
1. https://github.com/new 접속
2. Repository name: `binance-auto-trader` (원하는 이름)
3. **Private** 선택 (반드시!)
4. "Add a README", ".gitignore", "license" 은 **체크 해제** (이미 로컬에 있으므로 충돌 방지)
5. **Create repository** 클릭
6. 다음 화면에 나오는 "…or push an existing repository from the command line" 섹션의 URL을 복사
   - 보통 이런 모양: `https://github.com/<본인계정>/binance-auto-trader.git`

### 4) 로컬 저장소 → GitHub 연결 & 업로드
```powershell
# <URL> 자리에 위에서 복사한 주소 붙여넣기
git remote add origin https://github.com/<본인계정>/binance-auto-trader.git
git branch -M main
git push -u origin main
```

첫 push 시 GitHub 로그인 창이 뜸. 브라우저로 인증하면 통과.

### 5) 완료 확인
GitHub 저장소 페이지 새로고침 → backend/ 폴더와 파일들이 보이면 성공.
**`.env` 파일이 보이면 즉시 알려주세요 — 시크릿 유출 방지 조치 필요합니다.**

---

## 사무실 PC 에서 처음 세팅 (최초 1회)

### 1) Git 설치 (위 1번과 동일)

### 2) 저장소 clone
원하는 작업 폴더에서:
```powershell
cd C:\Users\<사무실유저>\
git clone https://github.com/<본인계정>/binance-auto-trader.git 바이낸스
cd 바이낸스
```

### 3) Docker Desktop 설치 (집과 동일)
https://www.docker.com/products/docker-desktop/

### 4) .env 복원

두 가지 선택지:

**A. 집에서 .env 를 안전하게 가져와 그대로 복사 (데이터 공유하고 싶을 때)**
- 집 PC 의 `.env` 파일 내용을 USB/암호화 메신저/1Password 등으로 옮겨와서
- `backend/.env` 로 붙여넣기
- 같은 `ENCRYPTION_KEY` 를 쓰면 집에서 만든 exchange_accounts 를 DB 덤프로 가져와 그대로 쓸 수 있음

**B. 사무실에서는 독립된 환경으로 새로 생성 (권장)**
PowerShell 에서:
```powershell
cd C:\Users\<사무실유저>\바이낸스\binance_auto_trader_project\backend

# Fernet 키 & SECRET_KEY 새로 생성
$fernet = python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
$secret = python -c "import secrets; print(secrets.token_urlsafe(48))"

# .env.example 복사해서 수정 (직접 편집기로 열어서 값 붙여넣어도 됨)
Copy-Item .env.example .env
```
그 다음 `.env` 를 메모장/VS Code 로 열어서:
- `SECRET_KEY=` 뒤에 위 `$secret` 값
- `ENCRYPTION_KEY=` 뒤에 위 `$fernet` 값
저장.

### 5) DB/Redis 기동 + 마이그레이션 + seed + admin
집 PC 에서 했던 것과 동일:
```powershell
docker compose up -d db redis
docker compose run --rm api alembic upgrade head
Get-Content seed_strategy_templates.sql | docker compose exec -T db psql -U postgres -d binance_auto_trader
docker compose run --rm api python scripts/create_admin.py --email herosys1@gmail.com
```

이제 집과 동일한 상태가 됨.

---

## 평소 작업 흐름

### 집 → 사무실 이동 시
집 PC 에서 퇴근 전:
```powershell
cd C:\Users\user\바이낸스\binance_auto_trader_project
git add -A
git commit -m "작업 요약 한 줄"
git push
```

사무실 PC 출근 후:
```powershell
cd C:\Users\...\바이낸스\binance_auto_trader_project
git pull
```

### 충돌 방지
- 양쪽 PC 에서 **동시에** 같은 파일을 고치지 않도록 주의.
- 작업 시작 전엔 항상 `git pull` 먼저.
- 작업 끝내면 반드시 `git push`.

### 실수로 `.env` 를 커밋한 경우
```powershell
git rm --cached backend/.env
git commit -m "remove accidentally committed .env"
git push
```
그리고 **즉시** 새로운 `SECRET_KEY`, `ENCRYPTION_KEY`, 유출된 API 키는 모두 **로테이션(재발급)**.

---

## 자주 쓰는 명령 요약

| 목적 | 명령 |
| --- | --- |
| 변경사항 확인 | `git status` |
| 스테이지에 올리기 | `git add <파일>` 또는 `git add -A` |
| 커밋 | `git commit -m "메시지"` |
| 원격 push | `git push` |
| 원격 pull | `git pull` |
| 최근 커밋 기록 | `git log --oneline -10` |
| 변경 diff | `git diff` |
| 특정 파일 되돌리기 | `git checkout -- <파일>` |

## 커밋 메시지 팁

짧아도 좋으니 **무엇을 왜 바꿨는지** 한 줄. 영문/한글 자유.
- `feat: add admin CLI password rotation`
- `fix: alembic 0003 revision id shortened`
- `docs: runbook updated for hedge mode`
