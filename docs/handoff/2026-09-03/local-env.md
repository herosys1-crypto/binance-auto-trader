## 로컬 개발환경 재구축

새 PC(Windows)에서 이 저장소로 개발을 시작하기까지 필요한 모든 것.
아래 내용은 **옛 PC 에서 실제로 명령을 돌려 확인한 것**만 적었다. 확인하지 못한 것은 「⚠️ 확인 못 함」으로 표시했다.

---

### 0. 한 눈에 — 새 PC 에서 필요한 것

| # | 항목 | git clone 으로 따라오나 | 어디서 얻나 |
|---|---|---|---|
| 1 | 저장소 코드 | ✅ 따라옴 | `git clone` |
| 2 | Git / Python / Node / Docker | ❌ | 각 공식 설치본 (§1) |
| 3 | GitHub 인증 | ❌ | 브라우저 로그인 (Git Credential Manager, §2). ⚠️ **저장소가 public 이라 clone 엔 불필요** — 첫 `push` 때만 필요 (§2-3) |
| 4 | Python 패키지 (23개 + 전이) | ❌ | 🚨 **`pip install -r requirements.txt` 를 그냥 쓰지 마라** — 23개 중 핀이 3개뿐이라 옛 PC 와 다른 버전이 깔린다(`redis` 7→8 등). **§4-3 ②번의 고정 설치 명령**을 쓴다 |
| 5 | `backend/.env` (SECRET_KEY / ENCRYPTION_KEY / DB 접속) | ❌ **gitignore** | 옛 PC 에서 손으로 옮김 (§5) — 🚨 **이것 없으면 로컬 앱 안 뜸** / 🚨 **통째로 복사하면 안 된다** (옛 값의 `DATABASE_URL` 이 운영 Neon 을 가리킴, §5-4) |
| 6 | Claude Code 메모리 83개 | ❌ (저장소 밖) | `docs/handoff/memory-backup-2026-09-03/` — RESTORE 문서 참조 |
| 7 | `.claude/agents/` (impl·locator·mech) | ✅ **따라옴** | 클론하면 그대로 있음 (§10) |
| 8 | `.claude/settings.local.json` (권한 허용 목록) | ❌ **전역 gitignore** | 옛 PC 에서 손으로 옮김 (§10). ⚠️ **옛 PC 에 4개가 있고 내용이 다 다르다** (164/345/731/71건) — §10-2 |
| 9 | git worktree 4개 | ❌ | 새 PC 에선 **없는 게 정상**. 새로 만들면 됨 (§9) |
| 10 | 프런트엔드 빌드 산출물 | — | **빌드 없음**. 정적 파일 그대로 (§6) |

---

### 1. 사전 설치물

옛 PC 에서 실제로 돌아가던 버전 (`python --version` / `git --version` / `node --version` / `docker --version` 출력):

| 도구 | 옛 PC 실측 버전 | 새 PC 에서 |
|---|---|---|
| Python | **3.14.2** | 3.12 를 권장 — 이유는 아래 🚨 |
| pip | 26.1.1 | Python 에 딸려옴 |
| git | 2.53.0.windows.2 | 최신으로 무방 |
| node | v24.14.1 | **이 저장소는 node 를 안 쓴다** (§6). 다른 용도로만 |
| npm | 11.11.0 | 위와 같음 |
| Docker Desktop | 29.3.1 (build c2be9cc) | 로컬 DB/Redis 를 띄우려면 필요 |

🚨 **Python 버전이 세 곳에서 서로 다르다 — 이게 사고의 씨앗이다.**

| 어디 | Python | 근거 |
|---|---|---|
| 옛 로컬 PC | 3.14.2 | `python --version` 실측 |
| Docker 이미지 (VPS 운영) | **3.12** | `backend/Dockerfile:1` — `FROM python:3.12-slim` |
| GitHub Actions CI | **3.12** | `.github/workflows/sajangnim_sasang_audit.yml:21` — `python-version: "3.12"` |

로컬만 3.14 였다. 로컬에서 통과한 것이 운영(3.12)에서 통과한다는 보장이 없다.
**새 PC 에서는 3.12 로 맞추는 것을 권한다** — 그러면 로컬·CI·운영이 한 버전이 된다.

Python 설치: https://www.python.org/downloads/windows/ 에서 3.12.x 를 받는다.
설치 시 「Add python.exe to PATH」를 반드시 체크.

---

### 2. 저장소 클론 + GitHub 인증 (gh CLI 없이)

사장님은 `gh` CLI 를 쓰지 않는다 (메모리 `user_profile.md` — 「GitHub 웹 UI 만 사용」).
`gh` 는 **설치할 필요가 없다.** 인증은 Git 이 브라우저를 띄워서 처리한다.

옛 PC 의 git 설정 (`git config --show-origin --get ...` 실측):

| 설정 | 값 | **실제** 출처 (2026-09-03 재실측) |
|---|---|---|
| `remote.origin.url` | `https://github.com/herosys1-crypto/binance-auto-trader.git` | 저장소 로컬 |
| `credential.helper` | **`manager`** (Git Credential Manager) | **system** — `C:/Program Files/Git/etc/gitconfig` (Git 설치 기본값) |
| `core.autocrlf` | **true** | **system** — 같은 파일 (설치 기본값) |
| `user.name` | 이규수 | **전역**(`--global`) |
| `user.email` | herosys1@gmail.com | **전역** |
| `init.defaultBranch` | **`main`** | **전역** ← 손으로 넣은 것. system 기본값은 `master` 다 |
| `core.longpaths` | true | ⚠️ **전역이 아니다.** 아래 참조 |

🚨 **`credential.helper` 와 `core.autocrlf` 는 「전역 설정」이 아니라 Git 설치 기본값(system)이다.**
→ 새 PC 에 **Git 을 정상 설치하기만 하면 자동으로 붙는다. 따로 할 것이 없다.**

🚨 **옛 PC 의 `--global` 설정은 딱 3줄뿐이다** (`git config --global --list` 실측):
`user.name` / `user.email` / `init.defaultbranch=main`. **그러므로 §2-1 과 §2-2 만 하면 재현 끝이다.**

#### 2-1. git 사용자 정보 + 기본 브랜치 (새 PC 최초 1회)

```bash
git config --global user.name "이규수"
```

```bash
git config --global user.email "herosys1@gmail.com"
```

```bash
git config --global init.defaultBranch main
```

세 줄이 다 들어갔는지 확인 — 정확히 이 3줄이 나오면 옛 PC 와 같은 상태다:

```bash
git config --global --list
```

#### 2-2. 긴 경로 허용

```bash
git config --global core.longpaths true
```

⚠️ **정정**: 옛 PC 에서 이 값은 **전역에도, 메인 저장소에도 설정돼 있지 않았다**
(`git config --global --get core.longpaths` → 빈 출력 / exit 1. 실측).
유일하게 값이 있던 곳은 worktree 하나의 `.git/worktrees/<이름>/config.worktree` 였고
그건 Claude Code 가 worktree 를 만들면서 넣은 것이다.

**즉 이것이 없어도 옛 PC 는 정상적으로 clone·작업했다. 「빠뜨리면 클론이 깨진다」는 과장이었다.**
그래도 켜 두기를 권한다 — 이 저장소는 `.claude/worktrees/<긴이름>/backend/app/...` 처럼 경로가 깊어지고,
Windows 기본 260자 제한에 실제로 가까워지기 때문이다. 부작용은 없다.

#### 2-3. 클론

경로를 옛 PC 와 **똑같이** 두는 것을 권한다 (이유는 §3 과 RESTORE 문서 §1).

🚨 **먼저 새 PC 의 Windows 사용자명이 `user` 인지 확인한다.** 아래 명령들은 전부 `/c/Users/user/...` 로
박혀 있어서, 사용자명이 다르면 **엉뚱한 자리에 폴더가 생기고** 이후 모든 명령이 어긋난다:

```bash
echo "$HOME"
```

`/c/Users/user` 가 나오면 그대로 진행한다. **다른 이름이 나오면** 이 문서의 모든
`/c/Users/user/바이낸스/...` 를 그 이름으로 바꿔 읽어야 한다 (그리고 §3-2 를 읽는다).

```bash
mkdir -p "$HOME/바이낸스"
```

```bash
cd "$HOME/바이낸스" && git clone https://github.com/herosys1-crypto/binance-auto-trader.git
```

(`$HOME` 을 쓰면 사용자명이 무엇이든 「내 홈 아래 `바이낸스`」로 정확히 간다.
이후 절들은 읽기 쉽도록 `/c/Users/user/...` 를 그대로 쓴다 — 사용자명이 `user` 가 아니면 그 부분만 바꿔라.)

저장소가 public 이라 **clone 자체는 로그인 없이 조용히 끝난다** (아래 정정 상자).

**로그인이 실제로 필요해지는 시점은 첫 `git push` 다.** 그때 **Git Credential Manager 창이 뜬다**
→ 「Sign in with your browser」 → GitHub 웹으로 로그인 → 끝.
`gh auth login` 도, 토큰을 손으로 만들 필요도 없다. 한 번 로그인하면 Windows 자격 증명 관리자에 저장돼 다음부터 안 묻는다.

> # 🚨 정정 — 이 저장소는 **Private 이 아니라 Public 이다** (2026-09-03 실측)
>
> `GIT_SYNC_GUIDE.md:36` 은 「**Private** 선택 (반드시!)」이라고 적고 있지만 **현재 상태는 그렇지 않다.**
> 인증을 전혀 쓰지 않은 요청으로 확인했다 (GitHub 은 private 저장소를 미인증 요청에 **404** 로 숨긴다):
>
> ```bash
> curl -s -o /dev/null -w "%{http_code}\n" https://api.github.com/repos/herosys1-crypto/binance-auto-trader
> ```
>
> 결과 **`200`**, 그리고 응답 본문이 `"private": false`, `"visibility": "public"` 이었다.
>
> **① 새 PC 절차에 미치는 영향 — 좋은 쪽이다.**
> **clone 에는 GitHub 로그인이 필요 없다.** 아래 「Credential Manager 창이 뜬다」는
> **`git push` 를 처음 할 때** 해당된다. clone 이 로그인 없이 되더라도 고장이 아니다.
>
> **② 그러나 이건 별도로 판단이 필요한 사안이다.**
> 실자금이 도는 매매 시스템의 **전체 소스·전략 로직·기획서가 인터넷에 공개**돼 있다는 뜻이다.
> ✅ 비밀 값이 새어 나가지는 않았다 — 확인했다:
> `git log --all -- backend/.env .env` → **커밋 0건**,
> 트리에 있는 `.env` 계열은 값이 없는 `.env.example` · `.env.production.template` 둘뿐,
> 히스토리 전체에 `*.pem` · `*.key` · `id_rsa` 로 추가된 파일 **0건**.
> **즉 지금 당장의 유출 사고는 없다.** 다만 매매 규칙이 공개된 상태이므로
> **비공개로 바꿀지는 사장님이 결정할 사항**이다 (이 문서는 판단하지 않는다).
> 바꾸려면 GitHub → 저장소 → Settings → 맨 아래 Danger Zone → Change visibility.
> ⚠️ 비공개로 바꾸면 **VPS 가 `git pull` 할 때 인증이 필요해진다** — VPS 배포가 멈출 수 있으니
> 바꾸기 전에 VPS 쪽 인증 방식을 먼저 확인해야 한다.

#### 2-4. 클론 확인

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git log --oneline -3
```

2026-09-03 기준 `origin/main` 의 최신 커밋은
`e51d9a8 chore(handoff): 저장소 밖 자산을 저장소 안으로 — 새 PC 이전 대비` 다.
갓 clone 한 저장소라면 맨 윗줄이 이것이어야 한다.

이어서 이 세 줄이 나오는지도 본다 (`e51d9a8` 다음이 `ded22f3` = Fix 327):

```
e51d9a8 chore(handoff): 저장소 밖 자산을 저장소 안으로 — 새 PC 이전 대비
ded22f3 feat(Fix 327): 차트분석 전문가 에이전트팀 — 지지선 7점 판정을 진입에 배선
1d04598 fix(Fix 326): 남긴 10 USDT 를 다음 사이클이 죽이고 있었다
```

한글이 `\353\260\224...` 처럼 깨져 보이면 §3 함정 ② 대로 `git config --global core.quotepath false` 를 하면 된다.
**깨져 보이는 것과 실제 파일이 깨진 것은 다르다** — 표시 문제일 뿐이다.

---

### 3. 경로에 한글(「바이낸스」)이 들어간 것 — 문제인가

**결론: 프로그램 동작에는 문제가 없다. 다만 세 가지 함정이 있다.**

옛 PC 에서 실제로 이 경로로 pytest 1,766건과 FastAPI 앱 구동이 정상 동작했다.
Python·pip·pytest·FastAPI 모두 한글 경로를 문제없이 다뤘다.

| 함정 | 증상 | 대처 |
|---|---|---|
| ① Bash 에서 따옴표 없이 쓰면 깨진다 | `cd C:/Users/user/바이낸스/...` 가 실패 | **항상 따옴표로 감싼다**: `cd "C:/Users/user/바이낸스/..."` |
| ② git 출력에서 escape 로 보인다 | `git worktree list` 가 `"C:/Users/user/\353\260\224..."` 로 표시 | 표시만 그런 것. `git config --global core.quotepath false` 로 한글 그대로 볼 수 있다 |
| ③ 🚨 Claude Code 메모리 폴더 이름이 경로에서 자동 생성된다 | 경로가 바뀌면 **옛 메모리 83개를 못 읽는다** | §3-1 |

#### 3-1. 🚨 경로를 바꾸면 메모리가 끊긴다

Claude Code 메모리는 저장소 밖 `C:/Users/user/.claude/projects/<프로젝트키>/memory` 에 있고,
`<프로젝트키>` 는 **프로젝트 절대경로를 변환해 자동 생성**된다.

옛 PC: `C:\Users\user\바이낸스\binance-auto-trader` → 키 `C--Users-user------binance-auto-trader`

셈이 맞는지 보면 규칙이 보인다 — **`:` 와 `\` 도, 한글 한 글자도 각각 하이픈 하나**로 바뀐다:

| 원본 조각 | `C` | `:` | `\` | `Users` | `\` | `user` | `\` | `바`·`이`·`낸`·`스` | `\` | `binance-auto-trader` |
|---|---|---|---|---|---|---|---|---|---|---|
| 변환 | `C` | `-` | `-` | `Users` | `-` | `user` | `-` | `----` | `-` | `binance-auto-trader` |

→ `user` 뒤의 하이픈이 **6개**인 이유 = 구분자 1 + **「바이낸스」 4글자** 4 + 구분자 1.
(「3글자」가 아니다 — 바·이·낸·스 **4글자**다.)

경로를 `C:\dev\binance-auto-trader` 같은 영문으로 바꾸면 키가 달라져 옛 메모리 폴더를 안 읽는다.

💡 새 PC 에서 **실제 키가 무엇인지 직접 보는 것이 가장 확실하다.** Claude Code 를 그 폴더에서 한 번 띄운 뒤:

```bash
ls "$HOME/.claude/projects/"
```

**권장: 새 PC 도 같은 경로 `C:\Users\user\바이낸스\binance-auto-trader` 를 쓴다.**
(사용자명이 `user` 가 아니면 키가 달라지므로 §3-2)

경로를 꼭 바꾸고 싶으면 — 바꿔도 **개발은 정상 동작한다.** 잃는 것은 메모리 연결뿐이고,
그건 `docs/handoff/RESTORE-2026-09-03.md` §1 「방법 B」대로 새 폴더 이름을 확인해 복사하면 된다.

#### 3-2. ⚠️ 새 PC 의 Windows 사용자명이 `user` 가 아니면

경로가 `C:\Users\<다른이름>\바이낸스\...` 가 되므로 프로젝트 키도 달라진다.
→ 메모리는 RESTORE 문서 「방법 B」로 복원한다. **코드 쪽에는 영향 없다.**

✅ **전수 검색을 실제로 했다** (2026-09-03). 저장소 전체에서 `C:\Users\user` / `C:/Users/user` 를 찾은 결과
**소스·스크립트에는 한 건도 없다.** 걸린 5개 파일은 전부 `docs/handoff/2026-09-03/` 안의 이 핸드오프 문서들뿐이다.

추적 중인 실행 스크립트 4개(`backend/backup-db-for-home.bat`, `backend/home-pc-sync-from-office.bat`,
`backend/restore-from-home-backup.bat`, 루트 `home-pc-sync-from-office.bat`)는 전부
**`cd /d "%~dp0"` (스크립트 자기 위치 기준 상대경로)** 를 쓴다 — 사용자명이 달라도 그대로 돈다.
유일한 예외는 `backend/restore-from-home-backup.bat:7` 인데 그것도 `REM` **주석 한 줄**이라 동작에 영향이 없다
(게다가 `C:\Users\user\binance\...` 라는 옛 폴더명이라 이미 낡은 주석이다).

→ **새 PC 의 Windows 사용자명이 무엇이든 코드는 그대로 돈다.** 바뀌는 것은 메모리 폴더 키뿐이다.

---

### 4. backend 의존성 설치

의존성 파일은 **`backend/requirements.txt` 하나뿐이다.** `pyproject.toml` 은 **없다** (`ls backend/pyproject.toml` → 없음).

#### 4-1. 🚨 왜 버전 핀이 목숨줄인가 — 실제로 났던 사고

`backend/requirements.txt:1-8` 이 주석으로 사고 원인을 직접 적어 두었다:

> fastapi 가 핀 없어 재빌드 시 신버전 드리프트 → `include_router` 가 `app.routes` 에
> `.path` 없는 `_IncludedRouter` (라우트 중첩) 추가 → `prometheus-fastapi-instrumentator`
> 7.1.0 (`<8` 핀) 이 `route.path` 접근 시 **전 요청 500** (대시보드 전체 다운).

즉 **핀이 없던 패키지 하나가 올라가서 mainnet 대시보드가 전부 500** 이 됐다.
그래서 지금 핀이 걸린 것은 딱 3개뿐이다:

| 핀 걸린 것 | 핀 | 이유 |
|---|---|---|
| `fastapi` | `==0.135.3` | requirements.txt:7 — `_IncludedRouter` 없는 검증된 버전 |
| `starlette` | `==0.52.1` | requirements.txt:8 — fastapi 0.135.3 의 검증 조합 |
| `prometheus-fastapi-instrumentator` | `>=7.0.0,<8` | requirements.txt:27 |

**나머지 20개는 전부 핀이 없다.** 그래서 새 PC 에서 그대로 설치하면 옛 PC 와 다른 버전이 깔린다.

#### 4-2. 🚨 실측 — 지금 설치하면 이만큼 달라진다

`pip install --dry-run --ignore-installed -r requirements.txt` 를 **실제로 돌려** 나온 결과와
옛 PC 의 `pip freeze` 를 비교했다:

| 패키지 | 옛 PC (동작 확인됨) | 오늘 새로 깔면 | 차이 |
|---|---|---|---|
| **redis** | **7.4.0** | **8.1.0** | 🚨 **메이저 1단계 점프** |
| **websockets** | **16.0** | **17.1** | 🚨 메이저 1단계 |
| **cryptography** | **46.0.7** | **50.0.1** | 🚨 메이저 4단계 — ENCRYPTION_KEY(Fernet) 를 다루는 패키지 |
| uvicorn | 0.44.0 | 0.52.4 | 마이너 8단계 |
| pydantic | 2.12.5 | 2.13.5 | 마이너 1단계 |
| pydantic-settings | 2.14.0 | 2.15.0 | 마이너 1단계 |
| SQLAlchemy | 2.0.49 | 2.0.52 | 패치 |
| alembic | 1.18.4 | 1.19.1 | 마이너 |
| APScheduler | 3.11.2 | 3.11.3 | 패치 |
| PyJWT | 2.12.1 | 2.13.0 | 마이너 |
| requests | 2.33.1 | 2.34.2 | 마이너 |
| sentry-sdk | 2.58.0 | 2.68.1 | 마이너 10단계 |
| prometheus_client | 0.25.0 | 0.26.0 | 마이너 |
| pytest | 9.0.3 | 9.1.1 | 마이너 |
| python-multipart | 0.0.26 | 0.0.32 | 패치 6단계 |
| websocket-client | 1.9.0 | 1.9.2 | 패치 |
| fastapi / starlette / instrumentator / psycopg2-binary / passlib / httpx / bcrypt / email-validator | 동일 | 동일 | ✅ 핀 or 우연히 일치 |

**`redis` 7 → 8 은 메이저 버전 변경이다.** 이 시스템은 Redis 에 락·kill-switch·mark price 캐시·
health heartbeat 를 전부 걸어 두고 있다(`backend/app/main.py:24-25`, `docker-compose.yml:69-80`).
아무 검증 없이 8.x 로 올린 채 실자금을 돌리는 것은 fastapi 사고와 같은 종류의 위험이다.

**🚨 `websockets` 는 §4-3 ②번 고정 설치 명령에도 핀이 없다 — 그래도 괜찮은 이유:**
바이낸스 스트림 워커 2종은 `websockets` 가 아니라 **`websocket-client`** 를 쓴다
(실측: `app/workers/binance_user_stream_consumer.py:3` 과 `app/workers/mark_price_stream_consumer.py:28`
둘 다 `import websocket`. 저장소 전체에서 `import websockets` 는 **0건**).
그리고 `websocket-client` 는 ②번 명령에 `==1.9.0` 으로 **핀이 걸려 있다.**
`websockets` 는 `uvicorn[standard]` 가 딸려 오는 전이 의존성일 뿐이라 **실거래 경로에 없다.**
→ 위 표의 「websockets 🚨 메이저」는 **우선순위가 낮다.** 진짜로 신경 쓸 것은 `redis` 와 `cryptography` 다.

#### 4-3. 권장 절차 — 옛 PC 버전 그대로 재현

**① 가상환경을 만든다** (옛 PC 는 venv 없이 전역에 깔려 있었고, 전역에 anthropic·openai·pandas 등
저장소와 무관한 패키지가 118개 섞여 있었다 — 새 PC 에선 분리하는 편이 낫다):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && python -m venv .venv
```

`.venv/` 는 `.gitignore:55` 에 이미 들어 있어 커밋될 걱정이 없다 (`grep -n '\.venv' .gitignore` 로 확인 가능).

```bash
source "/c/Users/user/바이낸스/binance-auto-trader/backend/.venv/Scripts/activate"
```

⚠️ Windows 라서 `bin/activate` 가 아니라 **`Scripts/activate`** 다. PowerShell 이면 대신 이것:

```powershell
& "C:\Users\user\바이낸스\binance-auto-trader\backend\.venv\Scripts\Activate.ps1"
```

(PowerShell 이 스크립트 실행을 막으면 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` 를 한 번 실행한다.)

🚨 **가상환경은 터미널마다 다시 켜야 한다.** 새 창을 열 때마다 위 `source` 를 다시 돌린다.
지금 venv 안에 있는지 확인 — `.venv` 경로가 나와야 한다:

```bash
python -c "import sys; print(sys.prefix)"
```

**② 옛 PC 와 같은 버전으로 고정 설치** (아래를 그대로 붙여넣는다):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && pip install fastapi==0.135.3 starlette==0.52.1 uvicorn[standard]==0.44.0 python-multipart==0.0.26 sqlalchemy==2.0.49 alembic==1.18.4 psycopg2-binary==2.9.12 pydantic==2.12.5 pydantic-settings==2.14.0 PyJWT==2.12.1 bcrypt==5.0.0 "passlib[bcrypt]==1.7.4" requests==2.33.1 email-validator==2.3.0 websocket-client==1.9.0 pytest==9.0.3 httpx==0.28.1 cryptography==46.0.7 APScheduler==3.11.2 redis==7.4.0 prometheus-fastapi-instrumentator==7.1.0 prometheus-client==0.25.0 "sentry-sdk[fastapi]==2.58.0"
```

✅ **이 23개 핀이 Python 3.12 에서도 되는지 실제로 확인했다** (2026-09-03).
`pip download --python-version 3.12 --only-binary=:all: --platform win_amd64` 로 위 목록 전부를 받아본 결과
**전이 의존성까지 합쳐 54개 wheel 이 모두 존재**하고 해석에 실패한 것이 하나도 없다
(`cryptography-46.0.7-cp311-abi3-win_amd64.whl`, `psycopg2_binary-2.9.12-cp312-cp312-win_amd64.whl`,
`pydantic_core-2.41.5-cp312-cp312-win_amd64.whl`, `redis-7.4.0-py3-none-any.whl` 등).
→ **3.12 로 새 PC 를 맞춰도 이 명령은 그대로 돈다.** 컴파일러(Visual C++ Build Tools) 도 필요 없다.

**③ (대안) 최신으로 그냥 깔고 싶다면** — 되긴 하지만 위 표의 차이를 감수한다는 뜻이다:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && pip install -r requirements.txt
```

**④ 설치 확인** — 핀 3종이 정확히 맞는지:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && pip freeze | grep -iE "^(fastapi|starlette|prometheus-fastapi-instrumentator|redis|cryptography)=="
```

②번(고정 설치)으로 깔았다면 정확히 이 5줄이 나온다 (옛 PC 에서 이 명령을 실제로 돌려 확인한 출력):

```
cryptography==46.0.7
fastapi==0.135.3
prometheus-fastapi-instrumentator==7.1.0
redis==7.4.0
starlette==0.52.1
```

③번(최신 설치)으로 깔았다면 `redis`·`cryptography` 두 줄이 다르게 나온다 — 그건 §4-2 표의 차이를 감수했다는 뜻이다.

> 💡 이 사고를 영구히 막으려면 `requirements.txt` 를 전부 `==` 로 고정하는 것이 정답이다.
> 다만 그건 **코드 변경**이라 이번 조사 범위 밖이다. 새 PC 에서 정상 동작을 확인한 뒤 사장님이 결정하시면 된다.

#### 4-4. requirements.txt 에 **없는데** 쓰이는 패키지

| 패키지 | 어디서 | 언제 필요 |
|---|---|---|
| `anthropic` | `tools/batch/run.py:59` (`import anthropic`, 없으면 `sys.exit`) | 배치 실행기(Fix 292)를 쓸 때만. 앱 구동·테스트에는 불필요 |

```bash
pip install anthropic
```

`tools/batch/run.py:74` 이 안내하듯 `console.anthropic.com → API Keys` 에서 키를 받아
`ANTHROPIC_API_KEY` 환경변수로 넣는다. (🚨 키 값은 이 문서에 적지 않는다.)

🚨 이 키도 **명령줄에 직접 적지 마라** (`ANTHROPIC_API_KEY=sk-... python ...` 형태). `.bash_history` 와
터미널 스크롤백에 그대로 남는다. Windows 사용자 환경변수(시스템 속성 → 환경 변수)에 등록하는 편이 안전하다.

---

### 5. `backend/.env` — 🚨 clone 으로 절대 안 따라온다

`git check-ignore -v backend/.env` 실측 → `.gitignore:7:backend/.env` 에 걸린다. **커밋된 적 없고 앞으로도 없다.**

옛 PC 에는 `C:/Users/user/바이낸스/binance-auto-trader/backend/.env` 가 **36줄**로 존재했다.
(주의: **worktree 안에는 `.env` 가 없다.** 메인 저장소 폴더에만 있다.)

#### 5-1. 옛 PC `.env` 에 들어 있던 키 이름 (값은 적지 않음)

`grep -oE "^[A-Za-z_0-9]+=" backend/.env` 실측 — 22개:

| 키 | 새 PC 에서 어떻게 얻나 | 🚨 |
|---|---|---|
| `ENCRYPTION_KEY` | **반드시 옛 PC 와 똑같은 값**을 옮긴다 | 🚨 **잃으면 DB 안의 거래소 API 키를 영영 복호화 못 한다** — 구체적으로 `exchange_accounts` 테이블의 `api_key_enc` / `api_secret_enc` 두 컬럼(`backend/app/models/exchange_account.py:13-14`)이 Fernet 으로 암호화돼 있어 **이 키 없이는 복구 수단이 전혀 없다**. 바이낸스에서 키를 새로 발급받아 재등록하는 것 말고는 방법이 없다 (`DEV-WORKFLOW.md:28`) |
| `SECRET_KEY` | 옛 PC 값을 옮긴다 | 다르면 기존 JWT 토큰이 전부 무효 → 재로그인 필요 |
| `DATABASE_URL` | 🚨 **옛 PC 값을 그대로 복사하지 마라.** 로컬 개발용으로 §5-3 표의 `localhost:5433` 값을 **새로 적는다** | 🚨 **실측 확인: 옛 PC 의 이 값은 운영 Neon DB 를 가리키고 있다.** 그대로 옮기면 새 PC 로컬 앱이 **실자금 DB 에 직접 붙는다** (§5-3) |
| `TEST_DATABASE_URL` | 위와 같음 (옛 PC 값은 docker 내부 호스트 `db:5432` 라 호스트에서는 안 통한다) | |
| `REDIS_URL` | 로컬이면 `redis://localhost:6380/0` (§5-3) | |
| `POSTGRES_PASSWORD` | docker-compose 의 db 비번. 로컬 개발은 `postgres` 로 충분 | `docker-compose.yml:10` |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 옛 PC 값 (텔레그램 BotFather) | 비워두면 알림만 안 감 |
| `SENTRY_DSN` / `SENTRY_TRACES_SAMPLE_RATE` / `SENTRY_PROFILES_SAMPLE_RATE` | Sentry 프로젝트 설정 화면 | 비워도 동작 |
| `APP_NAME` / `APP_ENV` / `JWT_ALGORITHM` / `ACCESS_TOKEN_EXPIRE_MINUTES` | `.env.example` 값 그대로 | |
| `BINANCE_FUTURES_BASE_URL` / `BINANCE_FUTURES_TESTNET_BASE_URL` | `.env.example` 값 그대로 | |
| `ENABLE_METRICS` | `true` | |
| `ALLOWED_SYMBOLS_CSV` / `MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT` / `MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE` / `ALLOW_DUPLICATE_SYMBOL_STRATEGIES` | 운영 정책값 | 없으면 `config.py` 기본값 |

값이 없는 뼈대는 저장소 안에 있다 — **이 두 파일은 커밋돼 있어서 clone 으로 따라온다**:

- `backend/.env.example` (29줄, 값 없음 — `.gitignore:9` 의 `!backend/.env.example` 로 예외 허용)
- `backend/.env.production.template` (119줄, `.gitignore:10` 로 예외 허용) — 운영용 키 **26개**
  (`grep -cE "^[A-Za-z_0-9]+=" backend/.env.production.template` → **26**. 로컬 개발에는 안 쓴다 — 참고용)

#### 5-2. `.env` 만들기

> 🚨 **맨손 `cp .env.example .env` 는 위험하다 — 이미 있는 `.env` 를 아무 말 없이 덮어쓴다.**
> USB 로 옮겨 온 `ENCRYPTION_KEY` 를 이미 `.env` 에 넣어 둔 상태에서 이걸 치면
> **그 키가 그 자리에서 사라진다.** `.env` 는 gitignore 라 git 으로 되살릴 수도 없다.
> 아래처럼 **`-n`(덮어쓰지 않음)** 을 붙여 쓴다.

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && cp -n .env.example .env && echo "새로 만들었다" || echo "이미 .env 가 있다 — 덮어쓰지 않았다 (정상)"
```

그다음 `.env` 를 편집기로 열어 옛 PC 값(특히 `ENCRYPTION_KEY`, `SECRET_KEY`)을 채운다.

⚠️ **`.env.example` 은 18개 키뿐이다. 옛 PC `.env` 는 22개다** (양쪽 다 `grep -cE "^[A-Za-z_0-9]+=" ...` 로 실측).
`cp` 만 하면 아래 **4개가 비어 있는 상태**가 된다 — `.env.example` 에 아예 없는 키들이다:

| 빠지는 키 | `app/core/config.py` 기본값 | 비워둬도 되나 |
|---|---|---|
| `MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT` | `10` (`config.py:38`) | ✅ 된다 |
| `MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE` | `None` = 제한 없음 (`config.py:41`) | ✅ 된다 |
| `ALLOWED_SYMBOLS_CSV` | `None` = 모든 심볼 허용 (`config.py:44`) | ✅ 된다 |
| `ALLOW_DUPLICATE_SYMBOL_STRATEGIES` | `False` (`config.py:62`) | ✅ 된다 |

**넷 다 `config.py` 에 기본값이 있어서 없어도 앱은 정상 기동한다.** 다만 §11 체크리스트의
「`.env` 22개 키」는 **옛 PC `.env` 를 그대로 참고해 채웠을 때의 숫자**다.
`cp .env.example .env` 로 시작했다면 **18 이 나오는 것이 정상**이니 놀라지 마라.
운영과 똑같은 정책값을 쓰고 싶으면 옛 PC `.env` 에서 이 4줄만 보고 옮겨 적으면 된다 (비밀 값 아님).

🚨 **`.env` 파일을 통째로 복사하지 마라.** 옛 PC 의 `.env` 는 `DATABASE_URL` 이 **운영 Neon DB** 를 가리키고 있다(실측). 통째로 덮으면 새 PC 로컬 앱이 실자금 DB 에 붙는다. **옮길 값과 옮기면 안 되는 값을 나눠서** 손으로 채운다 — §5-4 표.

🚨 **`ENCRYPTION_KEY` 를 새로 만들면 안 된다.** 새로 만들면 DB 에 암호화 저장된 바이낸스 API 키를 못 읽는다.
옮기는 방법은 §5-4 를 따른다. **채팅·이메일·카톡 전송 금지**(`DEV-WORKFLOW.md:29`).

새 키가 정말 필요한 상황(= 처음부터 다시 세팅)일 때만:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

이 명령은 `backend/app/core/crypto.py:22` 가 오류 메시지로 직접 안내하는 것과 같다.
`app/main.py` 는 기동 시 `validate_encryption_key()` 를 호출해 **잘못된 키면 즉시 죽는다**
(`crypto.py:12-30` — 「첫 거래 시점에 crash 방지」).

#### 5-3. 🚨 로컬 개발용 DATABASE_URL — 값에 따라 실자금 DB 를 건드린다

`.env.example:13` 의 기본값은 `postgresql+psycopg2://postgres:postgres@db:5432/binance_auto_trader` 로,
호스트명이 `db` = **docker 컨테이너 안에서만** 통한다.

| 어디서 앱을 돌리나 | DATABASE_URL 호스트 | REDIS_URL |
|---|---|---|
| docker compose 안 (api 컨테이너) | `db:5432` | `redis://redis:6379/0` |
| Windows 호스트에서 직접 (`uvicorn`) | `localhost:5433` ← 🚨 **5432 아님** | `redis://localhost:6380/0` ← 🚨 **6379 아님** |

포트가 다른 이유: `docker-compose.yml:14` 가 `127.0.0.1:5433:5432`,
`docker-compose.yml:24` 가 `6380:6379` 로 매핑한다 (호스트 포트 충돌 방지).

🚨 **운영 DB(Neon) 주소를 로컬 `.env` 에 넣지 마라.** 로컬에서 워커를 실수로 띄우면
실자금 포지션에 명령이 나갈 수 있다. `DEV-WORKFLOW.md:23` 도 「mainnet 운영 시: 한 시점에 한 PC 에서만 `docker compose up`」을 못 박고 있다.

#### 5-4. 🚨 비밀 값을 새 PC 로 안전하게 옮기는 법

**이 문서에는 비밀 값이 한 개도 적혀 있지 않다. 앞으로도 적지 마라.**
아래는 「어느 값을 / 어떻게」 옮기는지만 정리한 것이다.

**① 무엇을 옮기고 무엇을 옮기지 않나** (옛 PC `.env` 22개 키를 실제로 분류했다 — 값은 보지 않고 호스트/길이만 확인):

| 분류 | 키 | 새 PC 에서 |
|---|---|---|
| 🔴 **반드시 그대로 옮긴다** | `ENCRYPTION_KEY` | 잃으면 복구 불가 (§5-1). 옛 PC 값 그대로 |
| 🟡 옮기면 편하다 | `SECRET_KEY` / `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 안 옮겨도 앱은 뜬다. SECRET_KEY 가 다르면 재로그인, 텔레그램은 알림만 안 감 |
| 🔵 **옮기지 말고 새로 적는다** | `DATABASE_URL` / `TEST_DATABASE_URL` / `REDIS_URL` | 🚨 옛 값은 **운영 Neon / docker 내부 호스트**다. §5-3 표의 `localhost:5433` · `localhost:6380` 으로 **손으로 적는다** |
| ⚪ 그냥 `.env.example` 값 | 나머지 (`APP_*` / `JWT_*` / `BINANCE_*` / `ENABLE_METRICS` / `POSTGRES_PASSWORD` 등) | 복사할 필요 없음 |
| ⚫ 비어 있음 | `SENTRY_DSN` | 옛 PC 에서도 비어 있었다. 그대로 비워둔다 |

**② 옮기는 경로 — 해도 되는 것 / 절대 안 되는 것**

| ✅ 써도 되는 방법 | ❌ 절대 금지 |
|---|---|
| 비밀번호 관리자 (1Password 등) — `DEV-WORKFLOW.md:27` 이 권하는 방식 | 채팅·이메일·카톡·메신저 (`DEV-WORKFLOW.md:29`) |
| USB 로 직접 들고 가서 손으로 입력 | **Claude/ChatGPT 대화창에 붙여넣기** — 대화 기록에 영구히 남는다 |
| 옛 PC 화면을 보고 새 PC 에 타이핑 | OneDrive·Dropbox·Google Drive 등 **클라우드 동기화 폴더**에 `.env` 복사 |
| | GitHub 저장소·Gist·이슈·PR 본문 |
| | `ENCRYPTION_KEY=... 명령` 처럼 **명령줄에 직접 적기** — `.bash_history` 와 터미널 스크롤백에 남는다 |

> 🚨 `C:\Users\user\` 아래가 OneDrive 로 동기화돼 있는 PC 가 흔하다. USB 를 쓸 거면 옮긴 **직후 USB 에서 지우고 휴지통까지 비운다.**

**③ 🚨 옛 PC 를 정리하기 전에 `ENCRYPTION_KEY` 를 백업해라**

지금 이 키는 **옛 PC 의 `backend/.env` 단 한 곳에만** 있다. VPS 에도 있지만 옛 PC 를 밀거나
디스크가 죽으면 사실상 단일 장애점이다. `DEV-WORKFLOW.md:28` 이 「Mainnet 운영자는 백업 필수」라고 못 박고 있다.
**새 PC 세팅을 시작하기 전에** 비밀번호 관리자에 먼저 넣어라.

**④ 값을 보지 않고 옮겨졌는지 확인하는 법**

지문(해시 앞 12자)만 비교하면 값을 화면에 띄우지 않고도 두 PC 가 같은지 알 수 있다.
**옛 PC 와 새 PC 에서 각각 돌려 출력이 같으면 성공이다:**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && grep '^ENCRYPTION_KEY=' .env | cut -d= -f2- | tr -d '\r\n' | sha256sum | cut -c1-12
```

길이만 빠르게 보고 싶으면 (정상값은 **44**):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && grep '^ENCRYPTION_KEY=' .env | cut -d= -f2- | tr -d '\r\n' | wc -c
```

**⑤ 새 `.env` 가 운영 DB 를 안 가리키는지 마지막 확인** — 앱을 띄우기 전에 반드시:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && grep -c "neon.tech" .env
```

**`0` 이 나와야 한다.** `0` 이 아니면 멈추고 `DATABASE_URL` 을 §5-3 표대로 고친다.

> ⚠️ 위 명령은 **「운영 호스트가 없다」를 확인하는 부정형**이라 약하다. 운영 DB 호스트가 `neon.tech` 가
> 아닌 다른 이름으로 바뀌면 `0` 이 나와도 안전하지 않다.
> **「로컬을 가리킨다」를 확인하는 긍정형**을 같이 돌려라 (§8-3 ①번과 같은 명령):
>
> ```bash
> cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && grep -qE '^DATABASE_URL=postgresql\+psycopg2://[^@]*@(db|localhost|127\.0\.0\.1):' .env && echo "OK - 로컬 DB 다." || echo "!!! 중단 !!! 로컬 DB 가 아니다."
> ```
>
> **두 명령이 모두 통과해야 앱을 켠다.**

---

### 6. 프런트엔드 — 빌드가 없다

**결론: 빌드 단계가 없다. node/npm 이 필요 없다.**

근거:

- 저장소 어디에도 `package.json` 이 없다 (`find . -name package.json -not -path "*/node_modules/*"` → **0건**)
- 화면은 `backend/app/static/` 아래 **정적 HTML + 순수 JS** 다
  - `index.html` 218,684 bytes (대시보드 본체) 외 **8개** 페이지 — `analysis.html` / `bb-breakdown-ranking.html` /
    `bb-middle-ranking.html` / `bb-reversal-ranking.html` / `learning-insights.html` /
    `multi-timeframe-ranking.html` / `pump-ranking.html` / `realtime-monitor.html`
    (`git ls-tree --name-only origin/main backend/app/static/ | grep '\.html$'` → **9개**, index 포함)

    ⚠️ 옛 PC 의 worktree 에서 `ls` 를 하면 `perp-terminal.html` 이 하나 더 보인다. 그건 **아직 커밋 안 된
    작업 중인 파일**이라 새 PC 의 clone 에는 **따라오지 않는다**. 「파일이 하나 없다」고 놀라지 마라.
  - `backend/app/static/js/` 아래 **43개 `.js` 파일** (`strategies-list.js` 94KB, `strategy-suggestions.js` 95KB 등)
- FastAPI 가 직접 서빙한다. 경로 3개가 이렇게 나뉜다 (`main.py` 실측):

  | 위치 | 하는 일 |
  |---|---|
  | `main.py:164` | `app.mount("/static", _NoCacheStaticFiles(...))` — `js`·`css` 등 정적 자산 |
  | `main.py:166` `/admin-ui` | `index.html` 을 읽어 `?v=` 자산 버전을 **내용 해시로 갈아 끼운 뒤** `HTMLResponse` 로 돌려준다 (`:179`) |
  | `main.py:187` `/` | `RedirectResponse(url="/admin-ui")` — **307 리다이렉트**. HTML 을 직접 돌려주지 않는다 (§8-1) |

  ⚠️ `main.py:186` 의 `FileResponse` 는 **정상 경로가 아니라** 버전 재작성이 실패했을 때의
  fail-open 폴백이다 (`except Exception` 안에 있다). 평소에는 실행되지 않는다.

즉 **JS 를 고치면 저장하는 즉시 반영**된다. 트랜스파일·번들링·`npm install` 어느 것도 없다.

관련 함정: `main.py:93` 의 `_NoCacheStaticFiles` 가 캐시 금지 헤더를 붙인다(Fix 199).
과거 `?v=` 쿼리 18개가 낡아 옛 JS 가 뜨던 사고가 있었고, 지금은 **내용 해시 자동화**로 바뀌었다
(`main.py:2` 의 `hashlib` 임포트 + `:159` `_rewrite_asset_versions()` 가 그 구현이다).

⚠️ `--reload` 는 **`.py` 변경만** 감시한다. `index.html`·`js` 를 고쳤을 때는 서버 재시작이 필요 없고
**브라우저 새로고침만** 하면 된다 (위 no-cache 헤더 + 해시 재작성 덕분에 강력 새로고침도 대개 불필요).

---

### 7. 테스트 실행 — 실제로 돌려본 결과

#### 7-1. 어떻게 돌리나

pytest 설정은 `backend/pytest.ini` 에 있고 `pythonpath = .` 이므로 **반드시 `backend/` 에서 돌려야 한다.**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && PYTHONIOENCODING=utf-8 python -m pytest tests/ -q
```

🚨 **`PYTHONIOENCODING=utf-8` 을 빼면 한글이 깨진다.** 테스트 이름에 한글이 들어 있다
(예: `test_pump_dump_live_analyzer.py::test_5m은_신호를_내지_않음`).

PowerShell 에서 돌린다면 (⚠️ PowerShell 은 `VAR=값 명령` 형태를 못 쓴다. 아래처럼 `$env:` 로 따로 세팅한다):

```powershell
cd "C:\Users\user\바이낸스\binance-auto-trader\backend"
$env:PYTHONIOENCODING = "utf-8"
python -m pytest tests/ -q
```

💡 `PYTHONIOENCODING` 은 pytest 만의 문제가 아니다. 이 PC 의 콘솔 기본 인코딩이 **cp949** 라
`pip install --report -` 처럼 유니코드를 뱉는 명령도 `UnicodeEncodeError: 'cp949' codec can't encode ...` 로 죽는다
(실제로 겪었다). **한글이 섞인 출력을 내는 명령 앞에는 습관적으로 붙이는 편이 안전하다.**

#### 7-2. 🚨 실측 결과 — 2026-09-03, 옛 PC, Python 3.14.2

```
52 failed, 1714 passed in 618.63s (0:10:18)
```

| 항목 | 값 |
|---|---|
| 통과 | **1,714건** |
| 실패 | **52건** |
| 합계 | 1,766건 |
| 소요 | **618.63초 (10분 18초)** — 새 PC 에서도 10분 안팎으로 보면 된다 (재실행 시 669초가 나오기도 했다. PC 부하에 따라 ±1분은 흔들린다) |
| 테스트 파일 수 | 156개 (`find backend/tests -name "test_*.py" \| wc -l`) |

✅ **독립 재현 확인 (2026-09-03).** 같은 명령을 다시 돌려 **`52 failed, 1714 passed in 669.51s`** 로
숫자가 정확히 일치하는 것을 확인했다. 이 기준선은 신뢰해도 된다.

**DB 도 Redis 도 필요 없다.** `backend/tests/conftest.py:6` 이
`TEST_DATABASE_URL = "sqlite+pysqlite:///:memory:"` 로 인메모리 SQLite 를 쓴다.
`integration/` 폴더 테스트도 마찬가지다.

#### 7-2b. 🚨 그런데 「52」는 **`.env` 가 없을 때**의 숫자다

위 52 는 **`ENCRYPTION_KEY` 가 없는 상태**에서 나온 값이다 (측정을 worktree 에서 했는데
`.env` 는 메인 저장소 폴더에만 있다 — §5 참조).

`.env` 를 §5 대로 제대로 넣고 전체를 다시 돌려봤다. **실패가 52 → 44 로 줄었다** (전체 실행 실측):

```
44 failed, 1722 passed, 2 warnings in 695.49s (0:11:35)
```

두 실행의 실패 목록을 `comm` 으로 대조한 결과, **정확히 아래 8건**이 통과로 바뀌었고
**새로 실패한 것은 0건**이었다:

| 통과로 바뀐 테스트 | `.env` 없을 때의 실패 이유 |
|---|---|
| `unit/test_admin_module_split.py::test_router_registered_in_main_app` | `from app.main import app` → `main.py:46` → **`CryptoError: ENCRYPTION_KEY 가 기본값('change_me')`** |
| `unit/test_strategies_module_split.py::test_router_registered_in_main_app` | 위와 같음 |
| `unit/test_codebase_guards.py::test_static_routes_registered_before_param_routes` | 위와 같음 |
| `integration/test_exchange_credentials_update.py` **5건** (`test_valid_keys_rotate_and_encrypt` / `test_flip_testnet_to_mainnet_no_active_strategies` / `test_key_rotation_with_active_strategy_allowed` / `test_audit_notification_sent_on_success` / `test_passphrase_explicit_empty_clears`) | 거래소 API 키를 **Fernet 으로 암호화**하는 경로라 유효한 키가 없으면 못 돈다 |

**→ 그러므로 §11 체크리스트 순서(`.env` 를 먼저 넣고 테스트)를 따르면 기대 숫자는 52 가 아니다.**

| 상태 | 기대 결과 | 근거 |
|---|---|---|
| `.env` 없음 / `ENCRYPTION_KEY` 미설정 | **52 failed, 1714 passed** | 전체 실행 2회 재현 |
| `.env` 정상 (유효한 `ENCRYPTION_KEY`) | **44 failed, 1722 passed** | 전체 실행 실측 |

🚨 **판정 기준: 위 두 숫자 중 하나가 나오면 정상. 그보다 실패가 많으면 환경 문제다.**
반대로 `.env` 를 넣었는데도 **52** 가 나오면 **`ENCRYPTION_KEY` 가 앱에 안 읽히고 있다는 뜻**이다
(오타·따옴표·BOM·`.env` 가 `backend/` 가 아닌 곳에 있음 등). 그때는 §5-2 부터 다시 본다 —
이건 「원래 실패하던 8건」이 아니라 **설정이 안 먹었다는 신호**다.

💡 이 8건은 **환경 검증에 아주 쓸모 있는 신호**다. `.env` 를 넣었는데 `test_exchange_credentials_update` 5건이
여전히 빨간불이면, 앱이 `ENCRYPTION_KEY` 를 못 읽고 있다는 것을 **앱을 띄우기 전에** 알 수 있다.

#### 7-2c. ✅ 「새 PC 의 clone」을 그대로 재현해서 확인했다

위 숫자들은 옛 PC 의 **작업 트리**에서 잰 것이고, 그 트리에는 미커밋 변경이 있었다
(`M router.py` / `M exchange_accounts.py` / `M market.py` = **+166 / −6줄**, 미추적 `terminal.py`·`perp-terminal.html`).
「새 PC 가 clone 하면 받게 될 코드」와는 다르다.

그래서 **`git archive origin/main` 으로 순정 트리를 따로 뽑아**(= clone 과 동일한 내용) 저장소 밖에서 돌렸다:

```
44 failed, 1722 passed, 2 warnings in 662.95s (0:11:02)
```

실패 **목록까지 한 줄도 다르지 않았다** (`comm` 으로 대조 → 양쪽 차집합 **0건**).
순정 트리 자체도 확인했다 — HTML **9개**, 테스트 파일 **156개**, alembic **32개**, `backend/.env` **없음**.

**→ 새 PC 에서 clone 하고 `.env` 를 넣고 돌리면 `44 failed, 1722 passed` 가 나온다. 이것이 최종 기준선이다.**

#### 7-3. 🚨 52건 실패는 「새 PC 라서」가 아니다 — 옛 PC 에서도 이미 실패하던 것

실패 원인을 하나씩 확인했다. **환경 문제가 아니라 코드와 테스트가 어긋난 것**이다:

```
tests/unit/test_strategy_status_constants.py::test_exactly_seven_statuses
  AssertionError: assert 8 == 7
  frozenset({'CLOSED','CLOSED_BY_SL','CLOSED_BY_TP','COMPLETED',
             'KILL_SWITCH_TRIGGERED','REENTRY_READY', ...})
  Extra items in the left set: 'STOPPED_CAPITAL_EXHAUSTED'
```

= 코드에 `STOPPED_CAPITAL_EXHAUSTED` 상태가 추가됐는데 테스트가 「정확히 7개」라고 못 박고 있다.

```
tests/integration/test_sl_pct_per_template.py::test_default_50_pct
  AssertionError: assert evaluate_stop_loss(1) is True
```

= 손절 판정 로직이 바뀌었는데 옛 기대값이 그대로다.

**따라서 새 PC 에서도 같은 건수가 실패하는 것이 「정상」이다.**
기준선은 §7-2b 표 — `.env` 없으면 **52**, `.env` 정상이면 **44**. 그보다 **커지면** 그때가 진짜 환경 문제다.
(아래 52건 목록 중 `test_admin_module_split` · `test_strategies_module_split` · `test_codebase_guards` ·
`test_exchange_credentials_update` 5건 = **총 8건**은 `.env` 만 있으면 사라지므로
「코드/테스트 어긋남」에 해당하지 않는다.)

> 🚨 **「정상」은 「환경 이전 판정 기준」이라는 뜻이지, 「방치해도 된다」는 뜻이 아니다.**
> 실패 목록에 `test_exit_full_close_mismatch_guard`(청산 수량 불일치 가드) ·
> `test_sl_pct_per_template`(손절 비율) · `test_codebase_guards` · `test_static_assets_integrity` 처럼
> **손절·청산·자동 가드**를 지키는 테스트가 섞여 있다.
> 이 프로젝트는 「가드가 조용히 죽어 있던 것」으로 여러 번 손실을 봤다 (Fix 320/321/322 계열).
> 새 PC 이전이 끝나면 **52건을 그대로 두지 말고 따로 처리 대상으로 올려라.**
> 여기서 「52면 통과」로 쓰는 것은 **오직 환경 검증 한 번뿐**이다.
>
> ⚠️ 그리고 이 52 라는 숫자는 **Python 3.14.2 + 옛 PC 전역 패키지** 기준이다.
> §1 권고대로 **3.12 + venv** 로 맞추면 숫자가 달라질 수 있다 (⚠️ 확인 못 함 — 3.12 로는 돌려보지 않았다).
> 52 와 다르다고 곧바로 「환경 고장」으로 단정하지 말고, **실패한 테스트 이름이 위 목록과 같은지**를 먼저 비교하라.

**실패 파일 전체 목록 — 합이 정확히 52 다** (2026-09-03 재실행 결과에서 파일별로 센 것.
옛 표는 「그 밖」에 11개 파일을 뭉뚱그려 합이 37 밖에 안 됐다. 아래가 완전한 목록이다):

| 파일 | 실패 | 비고 |
|---|---|---|
| `tests/unit/test_martingale_stage_entry.py` | **7** | 🚨 **CI 가 돌리는 파일이다** (§7-4) |
| `tests/integration/test_exchange_credentials_update.py` | **5** | ⬅️ `.env` 만 있으면 **5건 전부 통과** (§7-2b) |
| `tests/unit/test_stream_service_partial_close.py` | 4 | |
| `tests/unit/test_v7_short_exit_partial_stage.py` | 4 | |
| `tests/integration/test_sl_pct_per_template.py` | 4 | 🚨 손절 비율 |
| `tests/integration/test_crisis_adhoc_safety_net.py` | 3 | |
| `tests/integration/test_crisis_threshold_per_template.py` | 3 | |
| `tests/integration/test_verify_tp_sl_entry.py` | 3 | |
| `tests/integration/test_admin_stats_breakdown.py` | 2 | |
| `tests/integration/test_strategy_full_capital_reservation.py` | 2 | |
| `tests/unit/test_risk_constants_centralization.py` | 2 | |
| `tests/unit/test_strategy_status_constants.py` | 2 | |
| `tests/integration/test_crisis_trailing_policy_v2.py` | 1 | |
| `tests/integration/test_ensure_isolated_margin.py` | 1 | |
| `tests/integration/test_exit_full_close_mismatch_guard.py` | 1 | 🚨 청산 수량 가드 |
| `tests/integration/test_reconcile_zombie_cleanup.py` | 1 | |
| `tests/integration/test_stopping_stuck_alert.py` | 1 | |
| `tests/integration/test_trigger_next_stage_and_inplace_stages.py` | 1 | |
| `tests/unit/test_pump_dump_live_analyzer.py` | 1 | |
| `tests/unit/test_static_assets_integrity.py` | 1 | |
| `tests/unit/test_admin_module_split.py` | 1 | ⬅️ `.env` 만 있으면 **통과** (§7-2b) |
| `tests/unit/test_strategies_module_split.py` | 1 | ⬅️ `.env` 만 있으면 **통과** |
| `tests/unit/test_codebase_guards.py` | 1 | ⬅️ `.env` 만 있으면 **통과** |
| **합계** | **52** | `.env` 정상이면 **44** (위 ⬅️ 표시 8건이 빠진다) |

#### 7-4. 🚨 CI 도 지금 빨간불일 가능성이 높다

`.github/workflows/sajangnim_sasang_audit.yml:29` 가 돌리는 3개 파일 중
**`tests/unit/test_martingale_stage_entry.py` 가 로컬에서 7건 실패**한다.
CI 는 Python 3.12 + `pip install pytest pydantic sqlalchemy fastapi` (4개만) 로 돌리므로
로컬과 조건이 다르긴 하다.

### ✅ 확인했다 — 「가능성」이 아니라 **사실이다. CI 는 빨간불이다** (2026-09-03)

저장소가 public 이라 GitHub Actions API 를 **인증 없이** 조회할 수 있었다:

```bash
curl -s "https://api.github.com/repos/herosys1-crypto/binance-auto-trader/actions/runs?per_page=5"
```

- 총 실행 **659건**. `main` 최근 5건(`#655`~`#659`, 2026-09-03) **전부 `conclusion: failure`**
- 더 거슬러 올라가 **최근 100건을 조회했는데 `success` 가 0건**이다.
  조회 범위의 가장 오래된 것이 `#557` (2026-08-29) — 즉 **최소 닷새, 100회 연속 실패** 중이다.

최신 실행(`#659`)의 job 별 결과:

| job | 결과 |
|---|---|
| 사장님 사상 단위 테스트 | ❌ **failure** — 실패 스텝 = `사장님 단위 테스트` (§7-4 표의 `:29`) |
| 사장님 E2E 시나리오 테스트 | ✅ success |
| 코드 ↔ spec 동기 검증 | ✅ success |

**→ 로컬에서 7건 실패하는 `test_martingale_stage_entry.py` 가 CI 에서도 그대로 터지고 있다.**
로컬 실패와 CI 실패가 **같은 원인**이라는 뜻이다.

🚨 **새 PC 세팅과의 관계**: 새 PC 에서 push 를 하면 **당연히 빨간불이 뜬다. 새 PC 탓이 아니다.**
「내가 환경을 잘못 만들었나?」 하고 되돌리지 마라. 이미 100회째 그런 상태다.
다만 이건 **원래 있던 문제**이므로, 이전이 끝난 뒤 §7-3 의 처리 대상 목록과 함께 다루어야 한다.

워크플로 파일은 `.github/workflows/sajangnim_sasang_audit.yml` **하나뿐**이고 job 이 3개다 (실측):

| job | 하는 일 |
|---|---|
| `sajangnim_unit_tests` | `test_sajangnim_stage_calculation.py` / `test_current_price_action.py` / `test_martingale_stage_entry.py` (`:29`) |
| `sajangnim_e2e_tests` | `tests/e2e/test_sajangnim_scenarios.py` (`:47`) |
| `sajangnim_spec_audit` | 금지 패턴 `grep` 2종 (`:62`, `:68`) — 파이썬을 안 쓴다 |

트리거는 `main`·`feat/**` 로의 PR 과 **`main` 에 push** 다(`:6-10`).
즉 새 PC 에서 `main` 에 push 하면 **자동으로 돈다** — 로컬 테스트를 건너뛰고 push 하지 마라.

💡 참고: CI 의 `pip install ... fastapi` 는 **핀이 없다**(`:25`, `:43`). §4-1 사고가 났던 그 형태다.
CI 가 갑자기 빨개지면 코드가 아니라 **CI 가 그날 받은 fastapi 버전**이 원인일 수 있다.
(고치는 것은 코드 변경이라 이번 이전 범위 밖 — 사장님 판단 사항으로 남긴다.)

#### 7-5. 빠르게 일부만 돌리기

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && PYTHONIOENCODING=utf-8 python -m pytest tests/unit -q
```

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && PYTHONIOENCODING=utf-8 python -m pytest tests/unit/test_strategy_status_constants.py -q --no-header
```

---

### 8. 로컬에서 앱을 띄울 수 있나

**결론: 띄울 수 있다. 다만 「어디까지 되는가」가 단계별로 다르다.**

#### 8-1. 실측 — DB/Redis 없이도 앱은 import 되고 화면은 나온다

✅ **`uvicorn` 을 실제 포트(127.0.0.1)에 띄우고 `curl` 로 확인했다** (2026-09-03 재검증).
DB 도 Redis 도 **안 띄운 상태**에서 나온 결과다:

| 경로 | 응답 |
|---|---|
| `/` | **307 Temporary Redirect** → `location: /admin-ui` (본문 0 bytes) |
| `/admin-ui` | **200**, 215,268 bytes ← **여기가 진짜 대시보드다** |
| `/static/js/api.js` | **200**, 6,404 bytes |
| `/metrics` | **200**, 9,912 bytes |
| `/health` | **200**, `{"status":"ok"}` (`main.py:201`) |
| `/healthz` | **404** — 이 이름의 경로는 **없다** |

🚨 **`/` 는 200 이 아니라 307 이다.** `main.py:187-189` 의 `root_redirect()` 가 `/admin-ui` 로 넘긴다.
브라우저는 리다이렉트를 자동으로 따라가므로 **`http://localhost:8000` 을 주소창에 치면 정상적으로 화면이 뜬다.**
다만 `curl http://localhost:8000` 처럼 명령줄로 확인하면 **빈 응답 + 307** 만 보여서
「앱이 고장났나?」 하고 오해하기 쉽다. `curl -L` 을 쓰거나 `/admin-ui` 를 직접 치면 된다:

```bash
curl -s -L -o /dev/null -w "%{url_effective} %{http_code} %{size_download}\n" http://127.0.0.1:8000/
```

기대 출력: `http://127.0.0.1:8000/admin-ui 200 215268`

💡 디스크의 `index.html` 은 218,684 bytes 인데 응답은 215,268 bytes 다. 줄어든 3,416 bytes = **줄 수**다.
`core.autocrlf=true` 라 디스크에는 CRLF 로 체크아웃되고, `main.py:179` 의 `read_text()` 가 LF 로 읽어
내보내기 때문이다. **불일치가 아니라 정상**이다.

앱 import 자체도 성공했다 (`routes: 146`).
`app/core/database.py:6` 의 `create_engine(...)` 은 **연결을 지연**하므로 DB 없이도 import 된다.
Redis 도 마찬가지다 — `main.py:28-41` 의 heartbeat 폴링이 `except Exception` 으로 감싸여 있어
Redis 가 없어도 5초마다 debug 로그만 남고 앱은 멀쩡히 돈다 (위 실측에서 확인).

단, `ENCRYPTION_KEY` 가 없거나 `change_me` / `.env.example` 의 `change_me_to_fernet_key` 면
**`app.main` 을 import 하는 순간 죽는다** — `main.py:46` 의 `validate_encryption_key()` 가
`app = FastAPI(...)` **보다 먼저** 실행되기 때문이다 (§5-2).

#### 8-2. 단계 A — DB/Redis 없이 화면만 보기 (제일 안전)

> 🚨 **「제일 안전」은 `.env` 의 `DATABASE_URL` 이 로컬일 때만 참이다.**
> 옛 PC 의 `.env` 를 그대로 옮겼다면 이 `uvicorn` 은 **운영 Neon DB 에 붙는다.**
> 그러면 「DB 가 없어 실패한다」가 아니라 **운영 데이터가 그대로 뜨고**, 대시보드가 주기적으로 폴링하는
> 잔고·포지션 API 가 **DB 에 저장된 운영 API 키로 Binance 를 호출**한다
> (`app/api/v1/analysis.py`, `app/api/v1/strategies/control.py` 가 binance client 를 쓴다 — 실측).
> = VPS 와 **같은 계정 weight 를 나눠 쓰게 되고**, §8-4 의 IP ban(418) 위험이 여기서도 발생한다.
> 게다가 이 화면에는 **주문·청산 버튼이 있다.** 「보기만 하겠다」가 한 번의 오클릭으로 실주문이 된다.
>
> **→ 이 명령 전에 §8-3 ①번 확인 명령을 먼저 돌려라.** 로컬 DB 가 아니면 켜지 마라.

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

⚠️ `uvicorn` 이 「명령을 찾을 수 없다」고 하면 venv 를 안 켠 것이다(§4-3 ①). 확실하게 가려면 `python -m` 을 붙인다:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

브라우저에서 `http://localhost:8000` → 307 리다이렉트를 따라 `http://localhost:8000/admin-ui` 로 가고 대시보드가 뜬다.
데이터를 부르는 API 는 DB 가 없어 실패한다. **JS/HTML 만 손볼 때 이걸로 충분하다.**

✅ **확인 완료 (2026-09-03).** 실제로 포트에 바인딩해 `curl` 로 위 §8-1 표의 6개 경로를 전부 찍어봤다.
DB(5433)·Redis 를 **띄우지 않은 상태**에서 `Application startup complete.` 까지 정상 도달했고,
Redis 연결 실패로 인한 크래시도 없었다.

기동 성공 시 터미널에 이 4줄이 나온다:

```
INFO:     Started server process [nnnnn]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

🚨 **이 4줄 대신 `CryptoError: ENCRYPTION_KEY ...` 가 나오면** `.env` 의 `ENCRYPTION_KEY` 문제다(§5-2).
앱이 아니라 **설정** 문제이니 코드를 뒤지지 마라.

#### 8-3. 단계 B — 로컬 DB/Redis 를 띄워 API 까지 쓰기

> ## 🚨🚨 이 절을 시작하기 전에 — 이 문서에서 가장 위험한 곳이다
>
> `alembic upgrade head` 는 **`DATABASE_URL` 이 가리키는 DB 의 스키마를 실제로 바꾼다.**
> 근거(실측): `backend/alembic/env.py:28-30` 이 `os.getenv("DATABASE_URL")` 로
> `alembic.ini:4` 의 기본 URL 을 **덮어쓴다.**
>
> §5 를 그대로 따라 옛 PC 의 `.env` 를 통째로 옮겼다면 `DATABASE_URL` 은 **운영 Neon DB** 다.
> 그 상태에서 컨테이너 안(`docker compose exec api alembic ...`)이나 `.env` 를 읽는 경로로 이 명령을 치면
> **실자금이 도는 운영 DB 에 마이그레이션이 나간다.** VPS 가 같은 DB 를 쓰고 있으므로
> 최악의 경우 **운영 중단 + 포지션 관리 불능**이다.
>
> **되돌리기가 사실상 없다.** `alembic downgrade` 는 추가했던 컬럼을 **DROP** 한다 —
> 그 사이 운영이 써 넣은 값은 같이 사라진다. 「실행 전에 막는 것」이 유일한 방어다.

**① 먼저 로컬 DB 를 가리키는지 확인한다** (값은 화면에 찍히지 않는다 — OK/중단만 나온다):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && grep -qE '^DATABASE_URL=postgresql\+psycopg2://[^@]*@(db|localhost|127\.0\.0\.1):' .env && echo "OK - 로컬 DB 다. 진행해도 된다." || echo "!!! 중단 !!! 로컬 DB 가 아니다. 5-3 표대로 먼저 바꿔라."
```

**② 로컬 DB/Redis 를 띄운다:**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && docker compose up -d db redis
```

컨테이너가 실제로 떴는지 먼저 본다 (db 는 `healthy` 가 될 때까지 10~20초 걸린다):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && docker compose ps
```

**③ 마이그레이션.** 🚨 **`docker compose exec api ...` 를 쓰면 안 된다** — 방금 `db redis` 만 띄웠으므로
`api` 컨테이너는 존재하지 않고 `service "api" is not running` 으로 실패한다.
venv 를 켠 **Windows 호스트에서** 직접 돌린다 (`backend/Makefile` 의 `upgrade` 타깃과 같은 명령):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && alembic upgrade head
```

🚨 **그런데 위 명령만으로는 십중팔구 접속 오류가 난다.** `alembic/env.py:28` 은 `DATABASE_URL` **환경변수**만
읽고 **`.env` 파일은 읽지 않는다**(env.py 실측 — `load_dotenv` 호출이 없다). 환경변수가 없으면
`alembic.ini:4` 의 `...@localhost:**5432**/...` 로 떨어지는데, docker-compose 는 호스트에 **5433** 으로
매핑한다(§5-3). 그래서 그 자리에서 직접 넘겨준다:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5433/binance_auto_trader" alembic upgrade head
```

(컨테이너 안에서 돌리고 싶다면 `api` 를 함께 띄운 뒤 `docker compose exec api alembic upgrade head` 를 쓴다.
🚨 **단 이 경로는 `.env` 를 그대로 읽는다** — `docker-compose.yml:30-31` 의 `env_file: .env`.
즉 `.env` 의 `DATABASE_URL` 이 아직 운영 Neon 이면 **운영 DB 가 마이그레이션된다.**
위 ①번 확인을 통과하지 않았다면 이 경로를 쓰지 마라. 호스트에서 URL 을 손으로 넘기는 위 방식이 더 안전하다 —
**어느 DB 를 건드리는지가 명령 줄에 눈으로 보이기 때문**이다.)

**되돌리기 — 로컬 DB 를 처음부터 다시 만들고 싶을 때만:**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && docker compose down -v
```

> 🚨 **`-v` 는 `postgres_data` 볼륨을 삭제한다** (`docker-compose.yml:136`). 로컬 DB 의 **모든 데이터가 사라진다.**
> 로컬 개발용 DB 일 때만 안전하다. **`.env` 가 운영 Neon 을 가리켜도 이 명령은 Neon 을 지우지 않는다**
> (Neon 은 compose 볼륨이 아니다) — 그래도 습관이 무서우니 「`-v` 는 로컬 전용」으로 외워 둘 것.
> 되돌린 뒤에는 ②→③ 을 다시 하면 된다.

`backend/alembic/versions/` 에 **32개** 마이그레이션 파일이 있고 최신은 `0034_surge_ladder_state.py` 다
(`ls backend/alembic/versions/*.py | wc -l` → **32**. 번호는 0001~0034 인데 **0025·0026 이 결번**이라 파일 수와 번호가 안 맞는다. 정상이다).

`.env` 의 `DATABASE_URL` / `REDIS_URL` 을 §5-3 표대로 맞춰야 한다.

#### 8-4. 단계 C — 전체 스택 (compose)

⚠️ **`backend/README.md:13-20` 의 「빠른 시작」은 `docker compose up -d` 가 아니다.** 실제 본문은
`docker compose up -d db redis` → `make upgrade` → `make seed-templates` → `make run` → `make scheduler`
→ 별도 터미널에서 `make user-stream` 이다. 즉 README 도 **DB/Redis 만 compose 로 띄우고 앱은 따로 켜는** 방식이다
(그리고 `make` 는 Windows 에 없다 — §8-5).

`docker-compose.yml` 이 띄우는 서비스는 **9개**다: `db`(postgres:16) / `redis`(redis:7) / `api` /
`scheduler` / `user-stream` / `mark-price-stream` / `prometheus`(9090) / `grafana`(127.0.0.1:3000) / `db-backup`.

> # ⛔ 여기서부터가 위험 구간이다 — 아래 명령을 읽기 전에 이 상자를 먼저 읽어라
>
> **`docker compose up -d` 를 인자 없이 치면 9개가 전부 뜬다.**
> 그중 `scheduler`·`user-stream`·`mark-price-stream` 은 **실제로 주문을 낼 수 있는 워커**다.
>
> `.env` 에 운영 DB 와 운영 API 키가 들어 있으면 **새 PC 에서 켜는 순간 VPS 와 동시에 같은 계정에 신호를 보낸다.**
> `DEV-WORKFLOW.md:22-23` 이 정확히 이 상황을 경고한다.
> 최악의 경우 **같은 심볼에 이중 진입 / 이중 손절 / 서로의 포지션을 청산**한다.
>
> 🚨 **추가 위험 ① — Binance IP ban (418).**
> 워커 3종은 각자 Binance REST/WebSocket 을 계속 두드린다. VPS 와 새 PC 가 **동시에** 같은 계정 키로
> 붙으면 **계정 단위 요청 weight 가 합산**돼 `429` → `418`(IP ban) 로 간다.
> 이 프로젝트는 **과거에 418 로 ban 이 스스로 연장되는 사고**를 겪었다
> (메모리 `project_2026-08-26_ip_ban_spiral.md`). ban 이 걸리면 **VPS 쪽 실거래도 같이 멈춘다** —
> 새 PC 의 실수가 운영을 세운다. 되돌리는 방법은 「기다리는 것」뿐이다.
>
> 🚨 **추가 위험 ② — `restart: unless-stopped`.**
> 9개 서비스 전부에 이 옵션이 붙어 있다(`docker-compose.yml`). 한 번 켜면 **PC 를 재부팅해도 자동으로 다시 뜬다.**
> 「잠깐 켜 봤다」가 며칠 동안 돌아가는 상태가 된다. 반드시 아래 「끄는 법」으로 명시적으로 내려라.
>
> **→ 새 PC 에서 이 명령(`docker compose up -d`, 인자 없음)은 「VPS 를 내렸다」는 확신이 없으면 치지 마라.**

**VPS 가 지금 돌고 있는지 확인하는 법 (읽기 전용 — 아무것도 바꾸지 않는다):**

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ps'
```

`scheduler` / `user-stream` / `mark-price-stream` 이 `Up` 으로 보이면 **VPS 가 실거래 중이다.**
그 상태에서 새 PC 워커를 켜면 §8-4 의 이중 주문 · IP ban 이 그대로 일어난다.

> 🚨 **VPS 를 내리는 것은 이 문서의 범위가 아니다.** 실자금이 도는 운영기다 —
> 내릴지 말지는 **사장님이 포지션 상태를 보고 직접 판단**하실 일이고,
> 이 핸드오프 작업 때문에 내릴 이유는 없다.
> **새 PC 는 「워커를 안 켜는 것」으로 충분히 안전하다** (§8-4 의 `db redis api` 만 켜기).

**안전 규칙 — 새 PC 에서 처음 띄울 때는 `api` 만 켠다:**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && docker compose up -d db redis api
```

**무엇이 떴는지 눈으로 확인한다 — `scheduler`/`user-stream`/`mark-price-stream` 이 목록에 있으면 즉시 내린다:**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && docker compose ps --services --filter status=running
```

**끄는 법 (되돌리기) — 실수로 워커를 켰다면 이것부터 친다:**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && docker compose stop scheduler user-stream mark-price-stream
```

전부 내리려면 (볼륨은 **안** 지운다 — `-v` 를 붙이지 마라):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && docker compose down
```

> ⚠️ 워커를 잠깐이라도 켰다면 **바이낸스 거래 내역과 텔레그램 알림을 반드시 눈으로 확인**해라.
> 주문이 나갔는지는 컨테이너를 끈다고 없어지지 않는다. 이미 나간 주문은 **되돌릴 수 없다** —
> 포지션 정리는 사장님이 화면에서 직접 판단하실 일이다.

#### 8-5. Makefile 로 워커를 개별 실행

`backend/Makefile` 에 타깃이 정리돼 있다 (`make run` / `make test` / `make upgrade` /
`make scheduler` / `make user-stream` / `make mark-price-stream` 등).

⚠️ **Windows 기본 환경에는 `make` 가 없다. Git Bash 에도 없다** (2026-09-03 실측 — `which make` → `no make in ...`,
`where.exe make` → 찾지 못함). **설치할 필요 없다.** Makefile 은 그냥 「명령 모음집」이라 아래 표대로 직접 치면 된다.

`backend/Makefile` 전체 대응표 (venv 켜고 `backend/` 에서 실행):

| `make ...` | 실제 명령 | 위험 |
|---|---|---|
| `make install` | `pip install -r requirements.txt` | — (🚨 핀 드리프트는 §4-2) |
| `make run` | `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` | ⚠️ `0.0.0.0` = **LAN 에 노출**. 혼자 쓸 땐 `--host 127.0.0.1` 로 바꿔라 |
| `make test` | `PYTHONIOENCODING=utf-8 python -m pytest -q` | 안전 |
| `make lint` | `python -m compileall app` | 안전 |
| `make upgrade` | `alembic upgrade head` | 🚨 §8-3 상자 |
| `make downgrade` | `alembic downgrade -1` | 🚨 **컬럼 DROP** |
| `make migrate` | `alembic revision --autogenerate -m "auto migration"` | 파일만 생성 |
| `make seed-templates` | `psql $DATABASE_URL -f seed_strategy_templates.sql` | ⚠️ Windows 에 `psql` 도 없다 — `docker compose exec -T db psql ...` 를 쓰거나 건너뛴다 |
| `make scheduler` | `python -m app.workers.scheduler_runner` | ⛔ 아래 상자 |
| `make user-stream` | `python -m app.workers.run_user_stream` | ⛔ 아래 상자 |
| `make mark-price-stream` | `python -m app.workers.mark_price_stream_consumer` | ⛔ 아래 상자 |
| `make worker-keepalive` / `-reconcile` / `-tpsl` / `-symbol-sync` | `python -m app.workers.run_workers --worker <keepalive\|reconcile\|tp-sl\|symbol-sync>` | ⛔ 아래 상자 |

(`make telegram-test` / `make pg-test` 도 있지만 각각 토큰·DB 가 필요해 새 PC 첫 세팅에서는 쓸 일이 없다.)

> 🚨 **`make scheduler` / `make user-stream` / `make mark-price-stream` 은 §8-4 의 워커와 똑같이 위험하다.**
> compose 를 거치지 않을 뿐 **같은 프로세스**다 (`Makefile:39-46` — `python -m app.workers.scheduler_runner`,
> `python -m app.workers.run_user_stream`). 「compose 를 안 썼으니 안전하다」가 아니다.
> §8-4 의 ⛔ 상자(이중 주문 · IP ban)가 그대로 적용된다.
>
> 또 `make seed-templates` 는 `psql $DATABASE_URL -f seed_strategy_templates.sql` 로 **DB 에 직접 쓴다**
> (`Makefile:24-25`). 로컬 DB 를 가리키는지 §8-3 ①번으로 확인한 뒤에만 쓸 것.

---

### 9. git worktree 구조 — 새 PC 에서 어떻게 되나

#### 9-1. 옛 PC 의 실제 상태 (`git worktree list` 실측)

| 경로 | 브랜치 | 커밋 |
|---|---|---|
| `C:/Users/user/바이낸스/binance-auto-trader` (**메인**) | `main` | 2586555 ← 🚨 아래 주의 |
| `.claude/worktrees/infallible-euler-6dc297` | `claude/infallible-euler-6dc297` | e51d9a8 (= `origin/main`) |
| `.claude/worktrees/charming-albattani-3f588f` | `feat/external-positions` | f346fee |
| `.claude/worktrees/loving-rhodes-52788c` | `feat/c-full-archive-filter-restore` | a3e5a02 |
| `C:/Users/user/AppData/Local/Temp/claude/.../scratchpad/baseline` | (detached) | 2a17a26 |

🚨 **옛 PC 의 로컬 `main` 브랜치(2586555)는 `origin/main`(e51d9a8) 보다 30커밋 뒤처져 있다**
(`git rev-list --count 2586555..e51d9a8` → **30**. Fix 318~327 이 전부 그 안에 있다).
최신 코드는 worktree 쪽(`claude/infallible-euler-6dc297`)에 있고 그게 이미 `origin/main` 에 push 돼 있다.
→ **새 PC 는 그냥 clone 하면 최신(e51d9a8)을 받으므로 이 뒤처짐은 새 PC 와 무관하다.**
헷갈리지 않도록 적어 둔다. 옛 PC 에서 `git log` 를 보고 「2586555 가 최신인가?」 하고 판단하지 마라.

#### 9-2. 🚨 새 PC 에서 worktree 는 **하나도 따라오지 않는다** — 그리고 그게 정상이다

세 가지가 겹친다:

1. **`.claude/worktrees/` 는 gitignore 다.**
   `git check-ignore -v .claude/worktrees` → `.gitignore:106:.claude/worktrees/` (메인 저장소에서 실측).
   → GitHub 에 올라간 적이 없다.

2. **worktree 메타데이터는 `.git/worktrees/` 안에 있고, `.git` 내부는 push 되지 않는다.**
   옛 PC 의 `C:/Users/user/바이낸스/binance-auto-trader/.git/worktrees/` 에
   `baseline` / `charming-albattani-3f588f` / `infallible-euler-6dc297` / `loving-rhodes-52788c` 4개 폴더가 있다.
   `git clone` 은 이걸 안 가져온다.

3. **worktree 는 절대경로로 서로를 가리킨다 — 새 PC 경로가 다르면 깨진다.**
   worktree 안의 `.git` 은 파일이고 내용이 이것뿐이다 (실측):

   ```
   gitdir: C:/Users/user/바이낸스/binance-auto-trader/.git/worktrees/infallible-euler-6dc297
   ```

   경로가 통째로 박혀 있다. 폴더를 새 PC 로 복사해 붙여넣으면 **이 경로가 안 맞아 git 이 동작하지 않는다.**

**→ 결론: worktree 폴더를 복사해 옮기려 하지 마라. 새 PC 에서는 브랜치만 받고 필요하면 새로 만든다.**

#### 9-3. 새 PC 에서 확인

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git worktree list
```

메인 하나만 나오면 정상이다.

#### 9-4. 브랜치가 필요하면 — worktree 를 새로 만든다

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git fetch origin
```

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git branch -r
```

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git worktree add ".claude/worktrees/external-positions" feat/external-positions
```

갓 clone 한 저장소에는 로컬 브랜치가 `main` 하나뿐이지만 이 명령은 **된다** — git 이 `origin/feat/external-positions`
하나만 찾으면 자동으로 추적 브랜치를 만들어 준다. `Preparing worktree (new branch 'feat/external-positions')` 가 나오면 성공이다.

🚨 **단, 옛 PC 의 worktree 3개 중 하나는 이 방법으로 못 만든다.**
`git ls-remote --heads origin <브랜치>` 로 실측한 결과:

| §9-1 의 브랜치 | origin 에 있나 | 새 PC 에서 `worktree add` |
|---|---|---|
| `claude/infallible-euler-6dc297` | ✅ 있음 | 된다 |
| `feat/external-positions` | ✅ 있음 (커밋 `f346fee` 까지 push 완료) | 된다 |
| `feat/c-full-archive-filter-restore` | ❌ **없음 — 옛 PC 로컬 전용** | **`fatal: invalid reference` 로 실패한다** |

✅ **그래도 잃는 것은 없다.** 확인했다:
- 그 브랜치의 커밋 `a3e5a02` 는 **`origin/main` 의 조상**이다 (`git merge-base --is-ancestor a3e5a02 origin/main` → 참).
  즉 **그 브랜치만 가진 커밋은 0개**다 (`git rev-list --count a3e5a02 --not --remotes` → **0**).
  브랜치 포인터가 옛 main 커밋을 가리키고 있었을 뿐이다.
- 유일한 고유 내용인 **미커밋 변경(2,971 bytes)** 은 §9-5 백업의
  `wip-backup-2026-09-03/loving-rhodes_feat-c-full-archive-filter-restore/uncommitted.patch` 에 들어 있다.

→ 그 작업을 이어서 하려면 **브랜치를 새로 파고 패치를 적용**한다.

🚨 **base 를 `origin/main` 으로 잡으면 패치가 안 붙는다.** 실제로 돌려봤다:

```
error: backend/app/api/v1/strategies.py: No such file or directory
error: patch failed: backend/app/workers/scheduler_runner.py:9
error: backend/app/workers/scheduler_runner.py: patch does not apply
```

이유는 그 사이 **`backend/app/api/v1/strategies.py` 가 `strategies/` 디렉터리로 쪼개졌기 때문**이다
(`git cat-file -e a3e5a02:backend/app/api/v1/strategies.py` → 있음 / `origin/main:...` → **없음**).
패치가 뜬 시점(`a3e5a02`)과 지금 main 의 파일 구조가 다르다.

**그래서 base 는 `a3e5a02` 로 잡는다:**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git worktree add -b feat/c-full-archive-filter-restore ".claude/worktrees/archive-filter" a3e5a02
```

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/archive-filter" && git apply --check "docs/handoff/wip-backup-2026-09-03/loving-rhodes_feat-c-full-archive-filter-restore/uncommitted.patch"
```

⚠️ 패치 경로는 **worktree 안의 상대경로**다. worktree 도 저장소 전체를 체크아웃하므로
`docs/handoff/...` 가 그 안에 그대로 있다. `../../../docs/...` 같은 상위 경로를 쓰면 안 된다 —
그건 **메인 체크아웃의 `docs/`** 를 가리키고, 그 시점 파일 구조가 다르면 엉뚱한 결과가 난다.

`--check` 는 **적용하지 않고 되는지만** 본다. 아무 출력이 없으면 성공 — 그때 `--check` 를 빼고 다시 친다.
붙인 뒤 최신 main 으로 옮기는 것은 그다음 문제다 (`git rebase origin/main` — `strategies.py` 분할 때문에
충돌이 나는 것이 정상이고 손으로 풀어야 한다).

#### 9-4-a. 🚨 worktree 를 쓸 때 절대 맨손으로 치면 안 되는 git 명령

worktree 들은 **하나의 `.git` 을 공유**한다. 한 폴더에서 친 명령이 다른 폴더의 작업을 지운다.
아래는 이 저장소에서 실제로 위험한 것들이다 — **이 문서 어디에도 이 명령들은 없다. 스스로 치지 마라.**

| 명령 | 무슨 일이 나나 | 대신 이렇게 |
|---|---|---|
| `git stash` / `git stash pop` | 🚨 stash 저장소는 **저장소 전체에 하나뿐**이다. worktree A 에서 `stash` 하고 worktree B 에서 `pop` 하면 **엉뚱한 폴더에 풀리고 충돌 나면 그 자리에서 유실**된다. 옛 PC 의 미커밋 작업을 §9-5 백업으로 뽑아 둔 이유가 이것이다 | 커밋하거나 (`git commit -m wip`) 브랜치를 파라. 꼭 필요하면 `git stash list` 로 **번호를 눈으로 확인**하고 `git stash apply stash@{N}` (pop 말고 apply — 실패해도 원본이 남는다) |
| `git reset --hard` | 그 worktree 의 **미커밋 변경 전부 소멸**. 되돌릴 수 없다 | `git stash` 도 답이 아니다. `git diff > backup.patch` 로 먼저 뽑아 둔다 |
| `git checkout -- .` / `git restore .` | 위와 같음 (조용히 지운다) | 같음 |
| `git clean -fd` | untracked 파일 삭제 — **`.env` 는 gitignore 라 `-x` 를 붙이면 같이 날아간다** | 쓰지 마라. 굳이 쓸 거면 `git clean -nd` 로 **먼저 목록만** 본다 |
| `git push --force` / `-f` | 원격 히스토리를 덮어쓴다. VPS 가 `git pull` 로 받는 코드다 | 절대 금지. 되돌리려면 `git revert` 로 **새 커밋**을 쌓는다 |
| `git worktree remove <경로>` | 그 폴더의 미커밋 작업까지 삭제 | 먼저 `cd` 해서 `git status` 로 비었는지 확인. `--force` 는 쓰지 마라 |
| `rm -rf .claude/worktrees/...` | git 이 모르는 채로 지워져 `.git/worktrees/` 에 **유령 항목**이 남는다 | `git worktree remove` 를 쓰고, 이미 지웠으면 `git worktree prune` |

> 💡 **`git worktree add` 는 이미 다른 worktree 가 체크아웃한 브랜치로는 실패한다**
> (`fatal: '<브랜치>' is already checked out at ...`). 이건 **고장이 아니라 보호 장치**다.
> `--force` 로 뚫지 마라 — 같은 브랜치를 두 폴더에서 고치면 서로를 덮어쓴다.

#### 9-5. 미커밋 작업은 별도 백업에 있다

옛 PC 의 worktree 에 있던 **커밋 안 된 작업**은 이미 저장소 안으로 옮겨져 있다.
구조는 **worktree 별 하위 폴더 3개**다 (`ls docs/handoff/wip-backup-2026-09-03/` 실측):

```
docs/handoff/wip-backup-2026-09-03/
├── main/
├── charming-albattani_feat-external-positions/
└── loving-rhodes_feat-c-full-archive-filter-restore/
```

각 폴더 안에 똑같이 6개가 들어 있다:
`uncommitted.patch` / `staged.patch` / `untracked/` / `untracked-list.txt` / `unpushed/` / `unpushed-commits.txt`.
복원 절차는 `docs/handoff/RESTORE-2026-09-03.md` §2 참조.

**백업 6종을 전부 열어 origin/main 과 대조했다** (2026-09-03). 실제로 손댈 것은 많지 않다:

| 폴더 / 항목 | 실측 | 새 PC 에서 할 일 |
|---|---|---|
| `main/` 의 `staged.patch`·`uncommitted.patch` | **0 bytes** (빈 파일) | 없음 |
| `main/untracked/docs/` 문서 2건 | 이미 `origin/main` 에 커밋됨 | **없음** — clone 으로 따라온다 (§9-6) |
| `charming.../unpushed/0001-feat-positions.patch` (`f346fee`) | **이미 `origin/feat/external-positions` 에 있음** (`git ls-remote --heads` 로 확인) | **없음** — worktree 만 새로 만들면 된다 |
| `charming.../untracked/HANDOFF-2026-05-21-SAFETY-NETS.md` | `origin/main` 에 **없음** (백업에만 있는 문서) | 필요하면 그냥 복사. 코드 아님 |
| `loving-rhodes.../uncommitted.patch` **2,971 bytes** | ⬅️ **유일하게 코드 복원이 필요한 것** | §9-4 절차대로 `a3e5a02` 기반 worktree 에 `git apply` |
| `loving-rhodes.../untracked/` 워커 2개 | 🚨 **아래 경고** | **복사하지 마라** |

> ## 🚨 `loving-rhodes` 의 「새 워커 2개」를 복사하면 **최신 코드를 옛 코드로 덮는다**
>
> `RESTORE-2026-09-03.md` §2-1 은 이 두 파일을 「**원격 어디에도 없는 작업**」이라고 적고 있다.
> **사실이 아니다.** 둘 다 이미 `origin/main` 에 있고, **main 쪽이 훨씬 크고 최신**이다 (`git cat-file -s` 실측):
>
> | 파일 | 백업본 | `origin/main` | 차이 |
> |---|---|---|---|
> | `backend/app/workers/auto_long_at_bottom_worker.py` | 12,019 bytes | **93,893 bytes** | diff **2,066줄** |
> | `backend/app/workers/long_bottom_detector_worker.py` | 27,244 bytes | **42,437 bytes** | diff **415줄** |
>
> 백업본은 그 워커들의 **초기 스냅샷**이다. 그대로 `cp` 하면 **8만 줄 가까운 개발분이 사라진다.**
> RESTORE 문서 §2-1 의 「바로 복사하지 마라 / diff 를 먼저 보라」 경고는 옳지만,
> **「원격에 없다」는 전제 자체가 틀렸으므로** 그 절은 그냥 건너뛰어도 된다.
>
> → **결론: 이 두 파일은 아무것도 하지 마라.** clone 한 `origin/main` 것이 정답이다.

→ **정리: 위 백업에서 새 PC 로 손수 복원할 것은 `loving-rhodes` 의 `uncommitted.patch` 하나뿐이다.**

#### 9-5-a. 🚨🚨 백업에 **빠져 있는** 것 — 옛 PC 를 밀기 전에 반드시 처리할 것

`wip-backup-2026-09-03/` 에는 폴더가 **3개**뿐이다: `main` / `charming-albattani` / `loving-rhodes`.
**지금 이 작업을 하고 있는 worktree(`infallible-euler-6dc297`) 폴더가 없다.**
백업이 만들어진 뒤에도 이 worktree 에서 작업이 계속됐기 때문이다.

그런데 그 worktree 에는 **커밋도 push 도 안 된 작업이 215KB 넘게** 있다 (`git status --short` 실측):

| 상태 | 파일 | 크기 |
|---|---|---|
| ?? 미추적 | `backend/app/static/perp-terminal.html` | **144,146 bytes** |
| ?? 미추적 | `backend/app/api/v1/terminal.py` | **71,608 bytes** |
| M 수정 | `backend/app/api/v1/exchange_accounts.py` | +101줄 |
| M 수정 | `backend/app/api/v1/market.py` | +69줄 |
| M 수정 | `backend/app/api/router.py` | +2줄 |

이건 **「perp 터미널」 기능**으로 보이며 **origin 어디에도 없다** (`git ls-tree origin/main` 에 없음).

🚨 **옛 PC 를 밀거나 디스크가 죽으면 이 작업은 그대로 사라진다.**
`git clone` 으로도, `wip-backup` 으로도 **복구할 방법이 없다.**

**→ 새 PC 로 넘어가기 전에 셋 중 하나를 반드시 해라:**

**① 커밋해서 push 한다 (가장 안전, 권장)**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" && git add -A && git commit -m "wip(perp-terminal): 새 PC 이전 전 임시 저장" && git push origin HEAD
```

**② 커밋하기 싫으면 패치로 떠서 저장소에 넣는다** (위 백업들과 같은 방식)

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" && mkdir -p docs/handoff/wip-backup-2026-09-03/infallible-euler_perp-terminal/untracked && git diff > docs/handoff/wip-backup-2026-09-03/infallible-euler_perp-terminal/uncommitted.patch && git ls-files --others --exclude-standard > docs/handoff/wip-backup-2026-09-03/infallible-euler_perp-terminal/untracked-list.txt
```

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" && git ls-files --others --exclude-standard | while read -r f; do mkdir -p "docs/handoff/wip-backup-2026-09-03/infallible-euler_perp-terminal/untracked/$(dirname "$f")"; cp "$f" "docs/handoff/wip-backup-2026-09-03/infallible-euler_perp-terminal/untracked/$f"; done
```

(그다음 이 백업 폴더를 커밋해서 push 해야 새 PC 로 따라온다. 안 하면 ①과 똑같이 사라진다.)

**③ 이 작업을 버릴 생각이면 아무것도 안 해도 된다** — 다만 **버린다는 결정을 의식적으로** 하라.
모르고 잃는 것과 알고 버리는 것은 다르다.

#### 9-6. 옛 PC 에 남아 있던 정리 안 된 것

메인 worktree 의 `git status --short` 실측:

```
?? docs/CURRENT_STATE_2026-08-24_END_OF_DAY.md
?? docs/ROLLBACK_GUIDE_2026-08-24.md
```

untracked 문서 2건. ✅ **담겨 있는 것을 실제로 확인했다** (2026-09-03) — 다음 자리에 그대로 있다:

```
docs/handoff/wip-backup-2026-09-03/main/untracked/docs/CURRENT_STATE_2026-08-24_END_OF_DAY.md
docs/handoff/wip-backup-2026-09-03/main/untracked/docs/ROLLBACK_GUIDE_2026-08-24.md
```

즉 clone 만 하면 새 PC 에 따라온다. 옛 PC 에서 따로 챙길 것이 없다.

---

### 10. `.claude/` — 무엇이 따라오고 무엇이 안 따라오나

`git check-ignore -v` 로 하나씩 확인했다.

| 경로 | gitignore? | 근거 | 새 PC 에서 |
|---|---|---|---|
| `.claude/agents/impl.md` | ❌ **아님** | `git ls-files .claude` → 3건 tracked | ✅ **clone 하면 그대로 있다** |
| `.claude/agents/locator.md` | ❌ 아님 | 위와 같음 | ✅ 따라옴 |
| `.claude/agents/mech.md` | ❌ 아님 | 위와 같음 | ✅ 따라옴 |
| `.claude/settings.local.json` | ✅ **ignore** | `"C:\Users\user/.config/git/ignore":3:**/.claude/settings.local.json` | ❌ **안 따라옴** — 손으로 옮겨야 함 |
| `.claude/worktrees/` | ✅ ignore | `.gitignore:106` | ❌ 안 따라옴 (§9) |
| `.claude/settings.json` | (파일 자체가 없음) | `ls` → 없음 | — |
| 저장소 루트 `CLAUDE.md` | (파일 자체가 없음) | `ls CLAUDE.md` → 없음 | — |

#### 10-1. 🚨 `settings.local.json` 을 막는 것은 저장소 `.gitignore` 가 **아니다**

전역 ignore 파일 `C:\Users\user\.config\git\ignore` 의 **3번째 줄**이 막고 있다.
저장소의 `.gitignore` 에는 이 규칙이 **없다.**

→ **새 PC 에 그 전역 ignore 파일이 없으면, `settings.local.json` 이 커밋 대상으로 잡힌다.**
민감 정보는 없지만(아래 참조) 42KB 짜리 로컬 설정이 저장소에 섞이는 것은 바람직하지 않다.

옛 PC 의 그 파일은 **3줄뿐**이고 내용은 전부 확인했다 (시크릿 없음, 그냥 ignore 규칙):

```
**/.claude\settings.local.json
(빈 줄)
**/.claude/settings.local.json
```

(역슬래시판·슬래시판을 둘 다 넣어 둔 것이다. 실제로 매칭되는 건 슬래시판 = 3번째 줄.)

`core.excludesFile` 은 **설정돼 있지 않다** (`git config --show-origin --get core.excludesFile` → 빈 출력).
git 이 `~/.config/git/ignore` 를 기본으로 읽기 때문에 별도 설정이 필요 없다.

새 PC 에서 같은 보호를 켜려면 파일 하나만 만들면 된다:

```bash
mkdir -p "$HOME/.config/git" && printf '%s\n' '**/.claude/settings.local.json' >> "$HOME/.config/git/ignore"
```

(`$HOME` 을 쓴다. Git Bash 에서 `$HOME` 은 `/c/Users/<윈도우사용자명>` 이라 사용자명이 `user` 가 아니어도 맞는다.
`echo $HOME` 으로 먼저 확인해도 좋다. `>>` 이므로 이미 있는 파일에 줄만 덧붙는다 — 두 번 돌리면 같은 줄이 두 번 생기지만 무해하다.)

확인:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git check-ignore -v .claude/settings.local.json
```

이런 한 줄이 나오면 성공이다 (옛 PC 실측 출력):

```
"C:\\Users\\user/.config/git/ignore":3:**/.claude/settings.local.json	.claude/settings.local.json
```

🚨 **아무 것도 안 나오고 조용히 끝나면 = 막히지 않은 것이다** (`git check-ignore` 는 매칭이 없으면 출력 없이 exit 1).
「에러가 안 났으니 됐다」고 착각하지 마라. 출력 줄이 보여야 성공이다.

#### 10-2. `settings.local.json` 안에 무엇이 있나

구조만 확인했다 (값 나열 안 함). 최상위 키는 **`permissions` 하나뿐**이고 그 안은 `allow` 배열 하나다.
API 키·토큰 같은 것은 **없다.**

🚨 **그런데 이 파일은 하나가 아니다. 옛 PC 에 네 개가 있고 내용이 전부 다르다** (2026-09-03 실측):

| 위치 | 크기 | `permissions.allow` 건수 |
|---|---|---|
| **메인 저장소** `binance-auto-trader/.claude/settings.local.json` | 20,766 bytes | **164** |
| worktree `loving-rhodes-52788c/.claude/settings.local.json` | **107,338 bytes** | **731** ← 가장 많다 |
| worktree `infallible-euler-6dc297/.claude/settings.local.json` | 42,065 bytes | 345 |
| worktree `charming-albattani-3f588f/.claude/settings.local.json` | 9,106 bytes | 71 |

**「345건 / 42KB」는 worktree 하나의 숫자였다.** 새 PC 가 clone 후 갖게 될 자리(메인 저장소)에
대응하는 것은 **164건 / 20,766 bytes** 쪽이다.

→ **권장: 가장 많은 `loving-rhodes-52788c` 것(731건)을 새 PC 메인 저장소 자리에 넣어라.**
허용 목록은 많을수록 덜 묻는다. 자동 병합되지 않으므로, 여러 개를 합치고 싶으면 손으로 합쳐야 한다.
(옛 PC 를 아직 안 밀었다면 나중에 다시 가져와도 된다 — 잃어도 「다시 묻는다」일 뿐 복구 불가한 값이 아니다.)

이걸 안 옮기면 새 PC 에서 Claude Code 가 명령마다 허용을 다시 묻는다. 동작은 하지만 매우 번거롭다.

**「같은 자리」란 정확히 어디인가** — **저장소 루트 바로 아래**다. 홈 디렉터리가 아니다:

```
C:\Users\user\바이낸스\binance-auto-trader\.claude\settings.local.json
```

USB 로 옮긴 뒤 그 자리에 놓고 확인한다:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && ls -l .claude/settings.local.json && python -c "import json,io; d=json.load(io.open('.claude/settings.local.json',encoding='utf-8')); print('keys:', list(d)); print('allow:', len(d['permissions']['allow']))"
```

기대 출력: `keys: ['permissions']` 와, 어느 파일을 가져왔는지에 따라 `allow:` **164 / 345 / 731 / 71** 중 하나
(아래 표 참조). `keys` 가 `['permissions']` 가 아니면 잘못된 파일을 가져온 것이다.

⚠️ **worktree 를 새로 만들면 그 폴더에도 별도의 `.claude/` 가 생긴다.** worktree 안에서 Claude Code 를
쓸 거라면 그쪽에도 같은 파일을 넣어야 같은 허용 목록이 적용된다 (옛 PC 도 그렇게 돼 있었다).

#### 10-3. `.claude/agents/` 3종 — 클론하면 바로 쓸 수 있다

| 에이전트 | 모델 | 용도 (파일 front matter 에서 발췌) |
|---|---|---|
| `impl` | sonnet | 「매매 로직이 아닌 일반 구현 — UI/화면, API 엔드포인트, 문서, 스크립트, 테스트」. 🚨 「손절·자본·진입 판정 코드는 이 에이전트에 맡기지 마라」 |
| `locator` | haiku | 코드 위치 찾기 전용. 「코드를 고치지 않는다」 |
| `mech` | haiku | 기계적 점검 — 문법/임포트/포맷, 테스트 실행·분류. 「매매 로직 판단에는 쓰지 마라」 |

---

### 11. 새 PC 체크리스트 (순서대로)

| # | 할 일 | 확인 방법 |
|---|---|---|
| **0** | 🚨 **옛 PC 를 밀기 전에** `ENCRYPTION_KEY` 를 비밀번호 관리자에 백업 (§5-4 ③) | 지문 12자 메모 (§5-4 ④) |
| **0-b** | 🚨 **옛 PC 를 밀기 전에** `infallible-euler-6dc297` worktree 의 미커밋 작업(**215KB**, perp 터미널)을 push 하거나 패치로 뜬다 (§9-5-a) | 그 worktree 에서 `git status --short` 가 **비어 있어야** 안전 |
| 1 | Python 3.12 설치 (PATH 체크) | `python --version` |
| 2 | Git 설치 + `user.name`/`user.email`/`init.defaultBranch`/`core.longpaths` 설정 (§2-1, §2-2) | `git config --global --list` 에 3줄 (`credential.helper`·`core.autocrlf` 는 설치만 하면 자동) |
| 3 | Docker Desktop 설치 | `docker --version` |
| 3-b | 새 PC 사용자명 확인 (§2-3) | `echo $HOME` 이 `/c/Users/user` 인가? 아니면 이 문서의 경로를 전부 바꿔 읽어야 한다 |
| 4 | `$HOME/바이낸스/` 폴더 만들고 clone (**로그인 안 뜬다 — public 이다**, §2-3) | `git log --oneline -3` 첫 줄이 `e51d9a8` |
| 5 | 메모리 83개 복원 | RESTORE 문서 §1 — `ls .../memory \| wc -l` 이 83 |
| 6 | `.claude/settings.local.json` 복사 (§10-2) — 옛 PC 4개 중 **731건짜리** 권장 | §10-2 의 `python -c ...` 가 `keys: ['permissions']` 를 출력 |
| 7 | 전역 git ignore 설정 (§10-1) | `git check-ignore -v .claude/settings.local.json` 이 걸림 |
| 8 | venv 만들고 §4-3 ②번 명령으로 고정 설치 | `pip freeze \| grep -i "^fastapi=="` → `fastapi==0.135.3` |
| 9 | 🚨 옛 PC `.env` 의 비밀 값을 **§5-4 ①②** 대로 옮김 (통째 복사 ❌, ENCRYPTION_KEY 필수). 옮긴 뒤 USB 는 지운다 | 아래 9-확인 명령 + §5-4 ④ 지문 일치 |
| 9-b | 🚨 **옮긴 `.env` 의 `DATABASE_URL`·`TEST_DATABASE_URL`·`REDIS_URL` 을 로컬용으로 바꾼다 (§5-3)** | 아래 9b-확인 명령 |
| 10 | 테스트 (10~12분 소요) | 9·9-b 를 마쳤으면 **`44 failed, 1722 passed`** 가 정상. `.env` 없이 돌렸다면 `52 failed, 1714 passed` (§7-2b) |
| 11 | 앱 기동 (api 만) | `http://localhost:8000` 에서 대시보드 HTML |
| 12 | ⛔ 워커(`scheduler`/`user-stream`/`mark-price-stream`)는 **VPS 를 내렸다는 확신이 없으면 켜지 않는다.** 이중 주문 + Binance IP ban(418) 로 **VPS 실거래까지 멈춘다** | §8-4 ⛔ 상자. 켜졌는지 확인 = `docker compose ps --services --filter status=running` |
| 13 | 🚨 **`docker compose up -d` 를 인자 없이 치지 않았는지** 되짚는다 (인자 없으면 워커 3종 포함 9개가 전부 뜨고, `restart: unless-stopped` 라 재부팅해도 되살아난다) | 위 12번과 같은 명령. 워커가 보이면 즉시 `docker compose stop scheduler user-stream mark-price-stream` |

**9-확인** — 키가 22개 다 왔는지 센다. **값은 안 찍고 개수만** 나온다:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && grep -cE "^[A-Za-z_0-9]+=" .env
```

**9b-확인** — 🚨 이게 이번 이전에서 **가장 위험한 한 줄**이다. `.env` 의 DB/Redis 주소가 어디를 가리키는지
**호스트 이름만** 뽑아 본다 (비번·토큰은 안 찍힌다):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && grep -E "^(DATABASE_URL|TEST_DATABASE_URL|REDIS_URL)=" .env | sed -E 's#://[^@]*@#://***:***@#'
```

출력에 `neon.tech` 같은 **운영 DB 호스트**가 보이면 **거기서 멈추고** §5-3 대로 `localhost:5433` /
`redis://localhost:6380/0` 으로 바꾼 다음에 10번으로 간다. 운영 주소를 그대로 둔 채 앱을 켜면
**로컬에서 실자금 DB 를 건드린다.**

📌 **9-확인 숫자 읽는 법**: 옛 PC `.env` 를 참고해 채웠으면 **22**, `cp .env.example .env` 로 시작했으면 **18** 이
정상이다(§5-2). 그보다 **적게 나오면** `ENCRYPTION_KEY` 를 포함해 뭔가 빠진 것이니 §5-1 표와 대조한다.

---

### 12. ⚠️ 확인 못 한 것

| 항목 | 왜 |
|---|---|
| ~~GitHub 저장소가 실제로 Private 인지~~ | ✅ **확인 완료 (2026-09-03) — Private 이 아니라 `public` 이었다.** 미인증 `curl` 로 GitHub API 가 **200** + `"private": false` 를 반환. `GIT_SYNC_GUIDE.md:36` 의 「Private 선택」은 옛 설정 안내일 뿐 현재 상태가 아니다. clone 에 로그인이 필요 없다. §2-3 의 정정 상자 참조 |
| ~~GitHub Actions 최근 실행이 초록불인지 빨간불인지~~ | ✅ **확인 완료 (2026-09-03) — 빨간불이다.** 저장소가 public 이라 Actions API 를 미인증 조회했다. `main` **최근 100건 전부 실패**(`success` 0건, 최소 2026-08-29 `#557` 이후 연속). 실패 job 은 `사장님 사상 단위 테스트` 하나이고 나머지 2개는 통과. 로컬 7건 실패와 **같은 원인**이다. §7-4 참조 |
| ~~`pip install` 이 Python **3.12** 에서도 문제없이 되는지~~ | ✅ **확인 완료 (2026-09-03)** — `pip download --python-version 3.12 --only-binary=:all: --platform win_amd64` 로 §4-3 ②번 23개 핀을 전부 받아봤고 전이 의존성 포함 **54개 wheel 이 모두 존재**, 해석 실패 0건. §4-3 참조 |
| ~~`uvicorn` 을 포트에 실제 바인딩해 열어본 결과~~ | ✅ **확인 완료 (2026-09-03)** — `127.0.0.1:8765` 에 바인딩해 `curl` 로 6개 경로 확인. **`/` 는 200 이 아니라 307 → `/admin-ui`** 였다(옛 기록의 200 은 TestClient 가 리다이렉트를 자동으로 따라간 결과). §8-1 참조. 단 **브라우저 GUI 로 눈으로 본 것은 아니다** |
| ~~저장소 소스에 `C:\Users\user` 절대경로 하드코딩이 있는지 전수 조사~~ | ✅ **확인 완료 (2026-09-03)** — 저장소 전체 검색 결과 소스·스크립트에 **0건**. `.bat` 4개는 전부 `%~dp0` 상대경로. §3-2 참조 |
| ~~`make` 를 새 PC 에 어떻게 넣을지~~ | ✅ **해결 (2026-09-03)** — 넣을 필요가 없다. `backend/Makefile` 14개 타깃 전부를 실제 명령으로 풀어 §8-5 에 표로 옮겨 적었다. `make` 미설치를 `which make` / `where.exe make` 로 실측 확인 |
| ~~52건 실패가 origin/main 에서도 동일한지~~ | ✅ **확인 완료 (2026-09-03)** — 옛 설명(`git diff --stat origin/main HEAD` 빈 출력)은 **커밋끼리만** 비교한 것이라 근거가 약했다. 실제 작업 트리엔 미커밋 변경이 있었다(`M router.py`/`M exchange_accounts.py`/`M market.py` = +166/−6줄, 미추적 `terminal.py`·`perp-terminal.html`). 그래서 `git archive origin/main` 으로 **순정 트리를 따로 뽑아 저장소 밖에서 전체 실행** → `44 failed, 1722 passed`, **실패 목록까지 완전히 동일**. §7-2c |
| 52건 실패가 **Python 3.12 + venv** 에서도 똑같이 52건인지 | 실측은 3.14.2 + 전역 패키지에서만 했다. §1 권고대로 3.12 로 맞추면 숫자가 달라질 수 있다 — **숫자보다 실패 테스트 이름을 비교**할 것 (§7-3) |
| §8-3 의 `alembic upgrade head` 를 실제 로컬 DB 에 돌려본 결과 | **일부러 안 돌렸다.** 옛 PC `.env` 가 운영 Neon 을 가리키고 있어, 조사 중 실수로 운영 DB 를 마이그레이션할 위험이 있었다. 명령의 동작은 `alembic/env.py:28-30` 과 `alembic.ini:4` 를 **읽어서** 추론한 것이다 |
| 워커(`scheduler`/`user-stream`/`mark-price-stream`)를 로컬에서 켰을 때 실제로 어떤 주문이 나가는지 | **실자금이라 시험하지 않았다.** §8-4 의 위험 설명은 `docker-compose.yml` 의 command 와 `DEV-WORKFLOW.md:22-23`, 그리고 과거 사고 기록에 근거한 것이다 |
| Binance weight 가 어느 지점에서 `429`/`418` 로 넘어가는지 | 재보지 않았다(재보는 행위 자체가 ban 을 부른다). 과거 418 사고 기록(`project_2026-08-26_ip_ban_spiral.md`)에 근거해 **「동시 접속을 만들지 마라」**로만 적었다 |
| `docker compose down -v` 가 운영 Neon 에 영향이 없다는 것 | compose 볼륨(`postgres_data`)만 지운다는 정의상 그렇다. **실행해서 확인하지는 않았다** — 어차피 이 명령은 로컬에서만 쓸 것 |
