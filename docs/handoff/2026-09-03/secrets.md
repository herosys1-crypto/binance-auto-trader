## 비밀·설정 인벤토리 (값 없이 이름만)

> # 🚨🚨 이 문서를 깃에 커밋하기 전에 반드시 읽을 것 — **이 저장소는 공개(public)다**
>
> 2026-09-03 실측:
> ```
> $ curl -s https://api.github.com/repos/herosys1-crypto/binance-auto-trader | grep visibility
>   "visibility": "public",     # "private": false
> ```
> 그리고 `docs/handoff/` 는 **이미 깃에 추적되는 디렉터리**다 (커밋된 파일 102개 — `git ls-files docs/handoff/`).
> 즉 **이 파일을 커밋해서 push 하면 아래 내용이 전 세계에 공개된다.**
>
> - 운영 VPS 공인 IP + **root 로 SSH 접속한다**는 사실
> - **`ufw` 가 꺼져 있고 redis `6380` 이 비밀번호 없이 열려 있다**는 사실 (§9-5) — 이건 그대로 침입 안내문이다
> - 안전장치가 전부 해제돼 있다는 사실 (일일 손실 한도 0 / 레버리지 125 / 청산거리 검사 0)
> - 운영 비밀들의 지문
>
> 값 자체는 없으니 「즉시 계정이 털린다」는 뜻은 아니지만, **공격자에게 어디를 어떻게 두드릴지 알려주는 문서**다.
>
> **권장 (순서대로):**
> 1. **커밋하지 않는다.** 이 파일은 `docs/handoff/2026-09-03/` 에 있고 지금은 `??`(미추적) 상태다 — 그대로 두고 USB·비밀번호 관리자로만 옮긴다.
> 2. 굳이 저장소에 두려면 **저장소를 private 으로 바꾼 뒤**에 한다 (GitHub → Settings → Danger Zone → Change visibility).
> 3. 그래도 커밋하겠다면 **§9-5(redis/ufw)와 §0 의 VPS IP 를 먼저 지운다.**
>
> ⚠️ 이미 커밋·push 한 뒤라면 파일을 지우는 것만으로는 부족하다 — **깃 히스토리에 남는다.** 그때는 (a) 저장소를 private 으로 전환하고 (b) redis 를 `127.0.0.1` 로 묶고 `ufw` 를 켜는 것이 실질적인 대응이다.
>
> (참고: 2026-09-03 기준 **이미 커밋된 102개 handoff 문서에서는 비밀 값이 발견되지 않았다** — Grafana 비번·Neon 엔드포인트·봇 토큰·개인키 패턴 전부 0건.)
>
> 🚨 **다만 handoff 문서가 아닌 곳에 이미 새어 있는 것이 하나 있다.**
> `backend/docker-compose.yml:98-99` 의 **Grafana admin 비밀번호는 평문으로 이미 이 공개 저장소에 커밋돼 있다.**
> 「앞으로 조심하자」가 아니라 **지금 이미 공개된 상태**다. 이전 작업과 별개로 처리하실 것:
> ① Grafana 비밀번호를 바꾸고 ② compose 에서 값을 빼 `.env` 참조(`${GF_SECURITY_ADMIN_PASSWORD}`)로 돌린다.
> (다행히 Grafana 는 `127.0.0.1:3000` 바인딩이라 인터넷에서 직접 로그인창에 닿지는 않는다. 하지만
> `ufw` 가 꺼져 있고 같은 비밀번호를 다른 데 쓰셨다면 위험이 번진다.)
> 🚨 **이 조치는 저장소를 private 으로 바꿔도 끝나지 않는다** — 이미 공개돼 있던 값이므로 **비밀번호 자체를 교체**해야 한다.

> 조사 일시: 2026-09-03 / 대상: 로컬 사무실 PC + 운영 VPS `159.65.137.250`
> **이 문서에는 어떤 비밀 값도 적혀 있지 않다.** 키 이름 · 「어디서 얻는가」 · 지문(SHA-256 앞 12자리, 역산 불가) 만 기록했다.
> (초안에는 Grafana admin 비밀번호가 평문으로 한 군데 들어가 있었다 — 비밀 검토에서 발견해 **삭제**했다. §9-5b. 이 문서를 고칠 때 값을 다시 넣지 마시라.)
> VPS 는 조회만 했고 아무것도 바꾸지 않았다.

---

### 0. 먼저 읽을 것 — 이번 이전에서 가장 위험한 5가지

| # | 위험 | 왜 위험한가 | 근거 |
|---|---|---|---|
| 🚨 1 | **`ENCRYPTION_KEY` 를 잃으면 DB 의 바이낸스 API 키를 영원히 복호화할 수 없다** | Fernet 대칭키. 키가 없으면 `exchange_accounts.api_key_enc` 는 복구 불가능한 쓰레기 문자열이 된다. 바이낸스에서 키를 **새로 발급**받는 것 말고는 방법이 없다 | `backend/app/core/crypto.py:33-56`, `deploy/generate-secrets.sh:107` |
| 🚨 2 | **사무실 PC 의 `backend/.env` 가 운영 Neon DB 를 가리킨다** — DATABASE_URL 만 최신값으로 채우는 순간 **VPS 와 똑같은 실계좌로 매매하는 엔진이 하나 더 뜬다** | 로컬 `.env` 의 DATABASE_URL 은 호스트·DB·사용자·쿼리까지 VPS 와 **전부 동일**하고 **비밀번호만 다르다**. 그 비밀번호는 이미 만료돼 지금 그대로는 **인증 실패**한다(실측). 하지만 `ENCRYPTION_KEY` 지문이 VPS 와 **완전히 같으므로**, DB 만 붙으면 mainnet 키가 그대로 복호화된다 | 아래 §4 지문 비교 (2026-09-03 실측: 로컬 DSN 연결 시 `AUTH_FAIL`) |
| 🚨 3 | **VPS SSH 접속 키가 새 PC 에 없으면 VPS 를 아예 못 만진다 — 비밀번호로 들어가는 우회로가 없다** | `~/.ssh/authorized_keys` 에 등록된 공개키가 **딱 1개**(`ssh-ed25519 … binance-trader-vps`) 이고, 그 짝인 개인키는 사무실 PC 의 `~/.ssh/id_ed25519` 하나뿐이다. 게다가 서버는 **비밀번호 로그인이 꺼져 있다**(`passwordauthentication no`) → 키를 잃으면 SSH 로는 **어떤 방법으로도** 못 들어간다. 그때 남는 유일한 길은 **DigitalOcean 웹 콘솔(Recovery Console)** 로 붙어 새 공개키를 직접 넣는 것이다 (사장님의 DigitalOcean 로그인 필요) | VPS `wc -l authorized_keys` = 1 / `sshd -T` → `permitrootlogin yes`, `passwordauthentication no`, `pubkeyauthentication yes` (2026-09-03 읽기 전용 실측) / 로컬 `id_ed25519.pub` 주석이 `binance-trader-vps` 로 일치 |
| 🚨 4 | **새 PC 에서 `alembic upgrade head` 를 그냥 치면 운영 Neon DB 에 마이그레이션이 걸린다** | alembic 은 `.env` 의 `DATABASE_URL` 을 그대로 따라간다. 로컬 `.env` 가 운영 Neon 을 가리키므로(위험 2), 「로컬 스키마 만들려고」 친 명령이 **실운영 DB 를 변경**한다. DDL 은 롤백 스크립트가 없다. ⚠️ 지금 이 순간은 그 비밀번호가 만료돼 있어 인증 단계에서 먼저 막히지만(§4-1), **최신 DATABASE_URL 을 채운 직후부터는 진짜로 걸린다** | §7-2 의 안전 절차를 **반드시** 먼저 볼 것 |
| 🚨 5 | **새 PC 에서 바이낸스를 직접 호출하면 IP ban(418) 위험** | 새 PC 공인 IP 는 바이낸스 화이트리스트에 없다 → 서명 요청이 전부 거부되고, 재시도가 반복되면 **IP 밴이 스스로 연장**된다(2026-08-26 실사고). 밴은 그 IP 전체에 걸리므로 조사 중 VPS 까지 영향받을 수 있다 | §7-2b (초안의 `§7-5` 는 존재하지 않는 절 — 링크 수정함) |

> **⚠️ 위험 4·5 는 「읽기만 하려던 명령」에서 났다.** 이 문서의 명령 중 `alembic`, `check_binance_key.py`, `rotate_encryption_key.py` 셋은 **읽기 명령이 아니다.** 치기 전에 해당 절을 끝까지 읽을 것.

---

### 1. `.env` 키 인벤토리

#### 1-1. `backend/.env.example` 의 18개 키 (신규 환경의 최소 집합)

`backend/.env.example` 전체 (값은 전부 더미이므로 그대로 읽어도 안전).

| # | 키 | 무엇인가 | 누가 만드나 | 새 PC/새 배포에서 얻는 법 |
|---|---|---|---|---|
| 1 | `APP_NAME` | 앱 표시 이름 | 코드 기본값 | 그대로 두면 됨 (`config.py:5`) |
| 2 | `APP_ENV` | `local` / `production` | 사장님 | 직접 입력. **미설정 시 `local`** (`config.py:6`) |
| 3 | `SECRET_KEY` | JWT 서명키 (로그인 토큰) | **명령으로 생성** | `python -c "import secrets; print(secrets.token_urlsafe(48))"` — 바꾸면 전 사용자 재로그인 필요 |
| 4 | `JWT_ALGORITHM` | 고정 `HS256` | 코드 기본값 | 건드리지 말 것 |
| 5 | `ACCESS_TOKEN_EXPIRE_MINUTES` | 토큰 유효시간(분) | 사장님 | 운영값 `10080`(7일) |
| 6 | `POSTGRES_PASSWORD` | 로컬 `db` 컨테이너 비번 | **명령으로 생성** | Neon 을 쓰면 **실질적으로 안 쓰임** (§6 참고). `docker-compose.yml:10` 이 참조 |
| 7 | `DATABASE_URL` | 실제 DB 접속 문자열 | **Neon 콘솔에서 복사** | https://console.neon.tech → 프로젝트 → Connection details 복사. 🚨 현재 운영 DB 를 가리킴 |
| 8 | `TEST_DATABASE_URL` | 테스트용 DB | 사장님 | 로컬 `db` 컨테이너 그대로 두면 됨 |
| 9 | `REDIS_URL` | Redis 주소 | 코드 기본값 | 컨테이너 내부는 `redis://redis:6379/0` 고정 |
| 10 | `BINANCE_FUTURES_BASE_URL` | 메인넷 엔드포인트 | 코드 기본값 | `https://fapi.binance.com` 고정 |
| 11 | `BINANCE_FUTURES_TESTNET_BASE_URL` | 테스트넷 엔드포인트 | 코드 기본값 | `https://testnet.binancefuture.com` 고정 |
| 12 | 🚨 `ENCRYPTION_KEY` | **DB 의 API 키 암복호화 Fernet 키** | **명령으로 생성 — 단 기존 DB 를 쓸 거면 절대 새로 만들면 안 됨** | §3 전체를 읽을 것 |
| 13 | `ENABLE_METRICS` | Prometheus 지표 노출 | 사장님 | VPS 현재 `false` |
| 14 | `TELEGRAM_BOT_TOKEN` | 알림 봇 토큰 | **사장님이 BotFather 에서** | 텔레그램 `@BotFather` → `/mybots` → 기존 봇 토큰 재사용 또는 `/newbot` |
| 15 | `TELEGRAM_CHAT_ID` | 알림 받을 채팅 ID | **사장님** | 봇과 1:1 대화 후 `https://api.telegram.org/bot<TOKEN>/getUpdates` |
| 16 | `SENTRY_DSN` | 오류 수집 DSN | **사장님이 sentry.io 에서** | https://sentry.io → 프로젝트 → Client Keys(DSN). 비워도 동작함 |
| 17 | `SENTRY_TRACES_SAMPLE_RATE` | 트레이스 표본율 | 코드 기본값 | `0.1` |
| 18 | `SENTRY_PROFILES_SAMPLE_RATE` | 프로파일 표본율 | 코드 기본값 | `0.0` |

> ⚠️ 위 표의 `python -c "…"` 명령은 **Windows 새 PC 에서 `python3` 이 아니라 `python`** 이다 (사무실 PC 실측: `python3` 은 없다). 실행 전 §2 의 주의사항을 먼저 읽을 것.
> ⚠️ 이 18개는 **「완전히 새 환경을 처음부터 만들 때」의 최소 집합**이다. 이번 이전은 그게 아니라 **기존 `.env` 를 그대로 옮기는 것**이므로, 실제로 새로 만들 값은 **`DATABASE_URL` 하나뿐**이다 (§4-1). 나머지를 새로 만들면 오히려 사고가 난다.

#### 1-2. 운영 VPS `.env` 에 실제로 들어있는 키 = **26개** (example 보다 8개 많음)

VPS 에서 키 이름만 뽑은 결과. **APP_NAME / APP_ENV 두 개가 빠져 있다.**

| 키 | example 대비 | 현재 운영값 | 해설 |
|---|---|---|---|
| `SECRET_KEY` | 동일 | (비밀) | 길이 64 |
| `JWT_ALGORITHM` | 동일 | `HS256` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 동일 | `10080` | 7일 |
| `POSTGRES_PASSWORD` | 동일 | (비밀) | 로컬 db 컨테이너용 — Neon 쓰므로 사실상 미사용 |
| `DATABASE_URL` | 동일 | Neon `ep-…(엔드포인트 ID 마스킹).ap-southeast-1.aws.neon.tech/neondb` | 🚨 운영 DB. 정확한 엔드포인트는 https://console.neon.tech → Connection details 에서 확인 |
| `TEST_DATABASE_URL` | 동일 | (비밀) | |
| `REDIS_URL` | 동일 | `redis://redis:6379/0` | 비밀번호 없음 |
| `BINANCE_FUTURES_BASE_URL` | 동일 | `https://fapi.binance.com` | |
| `BINANCE_FUTURES_TESTNET_BASE_URL` | 동일 | `https://testnet.binancefuture.com` | |
| 🚨 `ENCRYPTION_KEY` | 동일 | (비밀, 길이 44 = 정상 Fernet) | §3 |
| `ENABLE_METRICS` | 동일 | `false` | Prometheus 스크레이프 비활성 |
| `TELEGRAM_BOT_TOKEN` | 동일 | (비밀) | |
| `TELEGRAM_CHAT_ID` | 동일 | (비밀) | |
| `SENTRY_DSN` | 동일 | (비밀) | 설정돼 있음 |
| `SENTRY_ENV` | **➕ 추가** | `mainnet` | ⚠️ **코드에서 이 키를 읽는 곳이 하나도 없다** — `grep -rn "SENTRY_ENV\|sentry_env" backend/app/` 결과 0건. 죽은 키 |
| `SENTRY_TRACES_SAMPLE_RATE` | 동일 | `0.1` | |
| `SENTRY_PROFILES_SAMPLE_RATE` | 동일 | `0.0` | |
| `ALLOWED_SYMBOLS_CSV` | **➕ 추가** | (빈 값) | 비어 있음 = **모든 심볼 허용** (`config.py:74-77`) |
| `MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT` | **➕ 추가** | `100` | 계정당 동시 전략 상한. 템플릿 권장 3~5 인데 운영은 100 |
| `MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE` | **➕ 추가** | `100` | 단일 전략이 잔액의 100%까지 = **사실상 무제한** |
| `ALLOW_DUPLICATE_SYMBOL_STRATEGIES` | **➕ 추가** | `false` | 같은 심볼+방향 중복 전략 차단 (`config.py:62`) |
| `DAILY_LOSS_LIMIT_USDT` | **➕ 추가** | `0` | **0 = 일일 손실 한도 비활성** (`config.py:33`) |
| `MAX_LEVERAGE` | **➕ 추가** | `125` | 바이낸스 최대치 = 상한 없음과 동일 |
| `MIN_LIQUIDATION_DISTANCE_PCT` | **➕ 추가** | `0` | **0 = 청산가 거리 검사 비활성** |
| `HEARTBEAT_INTERVAL_HOURS` | **➕ 추가** | `6` | 하루 4번 텔레그램 생존 알림 |
| `WALLET_LIMIT_PCT` | **➕ 추가** | `130` | 지갑 대비 투입 상한 %. ⚠️ pydantic 이 아니라 `os.environ` 으로 직접 읽는다 (`app/services/capital_calculator.py:38`) → `config.py` 에 정의가 **없다** |
| `APP_NAME` | **➖ 없음** | — | 코드 기본값 사용 |
| `APP_ENV` | **➖ 없음** | — | ⚠️ 미설정 → `config.py:6` 기본값 **`local`** 로 운영 중. 운영 서버인데 `local` 로 뜬다 |

#### 1-3. 사무실 PC `backend/.env` = **22개** (VPS 와 다름)

경로: `C:\Users\user\바이낸스\binance-auto-trader\backend\.env` (2026-05-10 수정, 1380 bytes)

- VPS 에 있고 로컬에 **없는** 키: `SENTRY_ENV`, `DAILY_LOSS_LIMIT_USDT`, `MAX_LEVERAGE`, `MIN_LIQUIDATION_DISTANCE_PCT`, `HEARTBEAT_INTERVAL_HOURS`, `WALLET_LIMIT_PCT`
- 로컬에 있고 VPS 에 **없는** 키: `APP_NAME`, `APP_ENV`(=`local`)
- `SENTRY_DSN` 은 로컬만 **빈 값**
- ⚠️ **키 이름은 같은데 값이 다른 것 2개** (2026-09-03 실측):
  - `ALLOWED_SYMBOLS_CSV` — VPS 는 **빈 값**(모든 심볼 허용)인데 로컬은 **심볼 2개가 들어 있다**. 로컬 엔진을 띄우면 그 2개만 거래된다. 사본을 새 PC 로 옮길 때 「VPS 와 같은 설정」이 아님을 알고 있을 것
  - `DATABASE_URL` — **비밀번호만 다르고 이미 만료됐다.** §4-1 참고
- 🚨 `DATABASE_URL` 호스트 = **VPS 와 동일한 운영 Neon** (`ep-…(마스킹)/neondb`)

> ⚠️ 워크트리(`.claude/worktrees/infallible-euler-6dc297/backend/`) 에는 `.env` 가 없다. 있는 건 본 저장소 쪽뿐이다.

---

### 2. 사장님이 직접 해야 하는 것 vs 코드/명령이 만드는 것

> **이 세션의 규칙: Claude 는 API 키를 발급하지도, 입력하지도 않는다. 아래 「사장님」 항목은 전부 사장님이 직접 하신다.**

| 구분 | 항목 | 방법 |
|---|---|---|
| 🙋 **사장님이 직접** | 바이낸스 API Key / Secret | https://www.binance.com/en/my/settings/api-management 에서 발급. Futures ✅ / 출금 ❌ / 신뢰 IP 제한 ✅ |
| 🙋 **사장님이 직접** | 바이낸스 IP 화이트리스트에 새 IP 추가 | 새 PC 나 새 서버에서 바이낸스를 직접 호출할 거면 그 공인 IP 를 등록해야 함 |
| 🙋 **사장님이 직접** | Neon DB 접속 문자열 | https://console.neon.tech → Connection details |
| 🙋 **사장님이 직접** | 텔레그램 봇 토큰 / Chat ID | @BotFather |
| 🙋 **사장님이 직접** | Sentry DSN | https://sentry.io |
| 🙋 **사장님이 직접** | GitHub 로그인 | 원격이 HTTPS 이고 credential helper = `manager` → 새 PC 첫 push 때 브라우저 로그인 창이 뜬다 |
| 🙋 **사장님이 직접** | SSH 개인키 이전 | §7 참고 |
| ⚙️ **명령이 생성** | `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| ⚙️ **명령이 생성** | `ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` — 🚨 **기존 DB 를 계속 쓸 거면 새로 만들면 안 된다** |
| ⚙️ **명령이 생성** | `POSTGRES_PASSWORD` / `REDIS_PASSWORD` | `deploy/generate-secrets.sh` 가 한번에 만들어 줌 — 🚨 **바로 아래 경고를 먼저 읽을 것** (그 스크립트는 `ENCRYPTION_KEY` 도 새로 만든다). ⚠️ `REDIS_PASSWORD` 는 **넣어도 아무 일이 안 일어난다**: 코드에도 compose 에도 이 키를 읽는 곳이 **0곳**이고(`grep -rn REDIS_PASSWORD` → 생성 스크립트와 템플릿 주석뿐), redis 는 `--requirepass` 없이 뜬다. 실제로 잠그려면 ① compose 의 redis `command` 에 `--requirepass` 추가 ② `REDIS_URL` 을 `redis://:<비번>@redis:6379/0` 으로 변경, 두 가지를 같이 해야 한다 (§9-5) |
| 🤖 **코드가 자동 생성** | `api_key_enc` / `api_secret_enc` | 사장님이 평문 키를 넣으면 `encrypt_text()` 가 암호화해 저장 (`app/api/v1/exchange_accounts.py:103-104`) |
| 🤖 **코드가 자동 생성** | `password_hash` | `hash_password()` (`scripts/create_admin.py:59`) |
| 🤖 **코드가 자동 생성** | `system_settings` 63행 | 워커/UI 가 씀 — §5 |

자동 생성 가능한 것들을 한 번에 뽑는 명령:

```bash
bash deploy/generate-secrets.sh > /tmp/new-secrets.env
```

> 🚨 **이번 이전에서는 이 스크립트를 쓰지 마시라.** 두 가지 이유다.
>
> 1. **이 스크립트는 새 `ENCRYPTION_KEY` 도 같이 만든다** (`generate-secrets.sh:39,47`). 출력을 통째로 `.env` 에 붙여 넣으면 **DB 의 바이낸스 키가 즉시 복호화 불가**가 된다 (§3-2). 이건 「완전히 새 DB 로 처음부터 시작할 때」 쓰는 스크립트다.
> 2. **Windows 새 PC 에서는 아예 안 돈다.** 스크립트가 `python3` 을 요구하는데(`:23-26`) Windows 파이썬은 `python` 이라는 이름만 설치된다. 2026-09-03 사무실 PC 에서 실행해 확인:
>    ```
>    $ bash deploy/generate-secrets.sh > /tmp/new-secrets.env
>    ERROR: python3 가 필요합니다 (sudo apt install python3)
>    exit=1
>    ```
>    쓰려면 VPS 같은 Linux 에서 돌리거나, Git Bash 라면 `python3` 별칭을 먼저 만들어야 한다:
>    ```bash
>    alias python3=python && bash deploy/generate-secrets.sh > /tmp/new-secrets.env
>    ```
> 3. **경로 주의**: `generate-secrets.sh` 는 **저장소 루트**의 `deploy/` 에 있다 (`backend/deploy/` 아님 — 실측). 이 문서의 다른 명령은 대부분 `backend/` 에서 도는데 이것만 루트다. `cd "…/binance-auto-trader"` 에서 실행할 것.
> 4. 🚨 **`/tmp/new-secrets.env` 는 평문 비밀 파일이다.** 만들었으면 반드시 쓰고 나서 지운다. 그냥 두면 재부팅 전까지 디스크에 남는다.
>    ```bash
>    shred -u /tmp/new-secrets.env 2>/dev/null || rm -f /tmp/new-secrets.env
>    ```
>    (Git Bash 의 `/tmp` 는 실제로는 Windows 사용자 임시폴더다. `shred` 가 없으면 `rm` 이라도 반드시 칠 것.)

**이번 이전에서 필요한 건 아래 두 줄이 전부다** (기존 DB·기존 키를 그대로 쓰므로).

`SECRET_KEY` 만 새로 만들 때 (만들면 전 사용자 재로그인 필요 — 안 만들어도 된다):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`ENCRYPTION_KEY` 를 **정말로** 새로 만들 때 (§3-3 (B) 회전 절차와 반드시 같이):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> ⚠️ 두 명령 모두 **Windows 에서는 `python3` 이 아니라 `python`** 이다 (`python3` 은 없다 — 실측).
> ⚠️ 두 번째 명령은 `cryptography` 패키지가 있어야 돈다. 새 PC 의 맨 파이썬에는 없다. `ModuleNotFoundError: No module named 'cryptography'` 가 나면:
> ```bash
> pip install cryptography
> ```
> (또는 `python -m pip install cryptography`. 정상이면 44자짜리 키가 한 줄 출력된다.)

---

### 3. 🚨 `ENCRYPTION_KEY` — 이전에서 가장 위험한 지점

#### 3-1. API 키가 DB 에 저장되는 구조

1. 사장님이 **평문** API key/secret 을 입력한다 — 경로는 두 가지뿐이다.
   - REST: `POST /api/v1/exchange-accounts` (`app/api/v1/exchange_accounts.py:95-117`) / 교체는 `PATCH /{id}/credentials` (`:148`)
   - CLI: `backend/scripts/create_admin.py --binance-api-key ... --binance-api-secret ...` (`:79-80`)
2. `encrypt_text()` 가 **Fernet** 으로 암호화한다 (`app/core/crypto.py:40-45`).
3. 결과 문자열이 `exchange_accounts.api_key_enc` / `api_secret_enc` 컬럼에 들어간다 (`app/models/exchange_account.py:13-14`).
4. 워커가 주문을 낼 때마다 `decrypt_text()` 로 되돌린다 (`app/core/crypto.py:48-56`). 호출처는 워커·에이전트·API 전반에 수십 곳.
5. Fernet 키는 **`settings.encryption_key` 하나뿐** — 즉 `.env` 의 `ENCRYPTION_KEY` (`crypto.py:35`).

#### 3-2. 키를 잃으면 어떻게 되는가

> **Fernet 은 대칭키다. 토큰 안에 키 힌트가 들어있지 않다.**
> `ENCRYPTION_KEY` 를 잃으면 `api_key_enc` 는 **수학적으로 복구 불가능**하다. 백도어도, 복구 절차도, 「관리자 재설정」도 없다.

- 앱은 부팅 시 `validate_encryption_key()` 로 키 형식을 검사하고, 형식이 틀리면 **즉시 죽는다** (`app/main.py:46` → `crypto.py:12-30`).
- 형식은 맞는데 **값이 다른** 키면 부팅은 되고, 첫 주문 시점에 `CryptoError("Failed to decrypt: invalid token")` 가 난다 (`crypto.py:54-55`). 이게 더 나쁘다 — 조용히 매매가 멈춘다.
- 복구 방법은 **바이낸스에서 API 키를 새로 발급받아 다시 등록**하는 것뿐이다. 그러면 IP 화이트리스트도 다시 설정해야 한다.

#### 3-3. 그래서 이전 절차는 둘 중 하나다

**(A) 기존 DB 를 계속 쓴다 (권장, 지금 상황)**
→ `ENCRYPTION_KEY` 를 **글자 하나도 바꾸지 말고 그대로 옮긴다.** 새로 생성하면 안 된다.
→ 옮기는 방법: 1Password / Bitwarden 같은 비밀번호 관리자, 또는 USB. **채팅·이메일·텔레그램·깃·스크린샷·클라우드 드라이브 금지.**
→ 🚨 **Claude(나) 에게 값을 붙여넣지 마시라.** 이 문서를 만드는 동안에도 나는 `.env` 의 값을 한 번도 읽지 않았다. 옮기는 일은 사장님만 하신다.
→ USB 를 썼으면 **옮긴 뒤 그 파일을 지우고 휴지통도 비운다.** USB 는 잃어버리기 쉽다.
→ 제대로 옮겨졌는지는 **값을 열어보지 말고 §4 의 지문(fingerprint)으로 대조**한다. 눈으로 44자를 비교하지 말 것 — 한 글자 차이를 못 잡는다.

**(B) 키를 새로 만든다 (회전)**
→ 반드시 전용 도구를 쓴다. `.env` 만 바꾸면 DB 가 통째로 잠긴다.

> 🚨 **어디서 돌리는가가 중요하다.** 이 스크립트는 `.env` 의 **옛** `ENCRYPTION_KEY` 로 복호화하면서 동시에 **운영 DB 에 접속**한다. 즉 아래 세 조건이 동시에 맞는 곳에서만 돈다.
> - `DATABASE_URL` 이 **실제로 붙는** 값일 것 → **새 PC 의 `.env` 는 지금 인증 실패한다** (§4-1). 그래서 **새 PC 에서는 돌아가지 않는다.**
> - 앱 의존성(`sqlalchemy`, `cryptography`, `psycopg2`)이 깔려 있을 것
> - 옛 `ENCRYPTION_KEY` 가 그 `.env` 에 그대로 있을 것
>
> 현실적으로 **VPS 의 api 컨테이너 안**이 유일한 실행 장소다. 다만 이건 **운영 DB 에 쓰는 작업**이라 이번 세션 범위(읽기 전용) 밖이고, **사장님이 직접** 하셔야 한다:
> ```bash
> # dry-run (DB 변경 없음)
> ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app -e NEW_ENCRYPTION_KEY="<새-Fernet-키>" api python scripts/rotate_encryption_key.py --dry-run'
> ```
> 로컬(Windows)에서 굳이 돌린다면 `backend/` 안에서 아래 형태이지만, 위 세 조건 때문에 **현 상태로는 실패한다**:
> ```bash
> NEW_ENCRYPTION_KEY="<새-Fernet-키>" python scripts/rotate_encryption_key.py --dry-run
> ```
>
> 🚨 **위 두 명령은 새 Fernet 키를 「명령줄」에 적는다.** 그러면 그 키가 세 군데에 흔적을 남긴다.
> - Git Bash `~/.bash_history` / VPS `~/.bash_history` — 파일로 영구히 남는다
> - ssh 로 보낸 경우 **VPS 의 `~/.bash_history` 에도** 남는다
> - 실행 중에는 `ps aux` 로 같은 서버의 누구나 볼 수 있다
>
> 그래서 회전을 실제로 할 때는 **키를 명령줄에 쓰지 말고 파일로 넘기는 편이 안전하다.** 예: VPS 에서
> ```bash
> # ① 키를 600 권한 파일에 넣는다 (편집기로 직접 붙여넣기 — 명령줄에 쓰지 않는다)
> umask 077 && vi /root/.rotate_key.env      # NEW_ENCRYPTION_KEY=... 한 줄
> # ② 파일에서 읽어 실행
> cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app \
>   --env-file /root/.rotate_key.env api python scripts/rotate_encryption_key.py --dry-run
> # ③ 끝나면 지운다
> shred -u /root/.rotate_key.env 2>/dev/null || rm -f /root/.rotate_key.env
> ```
> ⚠️ `docker compose exec` 의 `--env-file` 지원 여부는 compose 버전을 탄다 — **이 절차는 실제로 돌려보지 않았다.** 안 되면 ①의 파일을 `source` 한 뒤 `-e NEW_ENCRYPTION_KEY` (값 없이 이름만) 로 넘기면 된다. 어느 쪽이든 **끝난 뒤 `history -c` 로 히스토리를 정리**할 것.

dry-run 이 `failed=0` 이면 `--dry-run` 만 떼고 같은 명령을 다시 실행한다 (컨테이너 안이면 위 ssh 줄에서 `--dry-run` 만 제거).

- 이 스크립트는 옛 키로 복호화 → 새 키로 재암호화 → **즉시 round-trip 검증**까지 한다 (`scripts/rotate_encryption_key.py:140-159`).
- 한 행이라도 실패하면 **전체를 롤백**하고 DB 를 건드리지 않는다 (`:263-271`).
- 백업 JSON(`key-rotation-backup-*.json`)이 자동 생성된다. 🚨 **이 파일에는 옛 암호문이 그대로 들어있다** — 안전한 곳으로 옮기고 검증 후 폐기 (`:181-189`). ⚠️ **`--dry-run` 에서도 이 파일이 만들어진다** (`:274`, 주석 「dry-run 도 백업 만듦」) — 「연습만 했으니 남는 게 없다」고 생각하면 안 된다.
- 되돌리기: `python scripts/rotate_encryption_key.py --restore-from <backup.json>` (`:234-243`)
- 🚨 **이 스크립트는 옛/새 `ENCRYPTION_KEY` 의 앞 8자를 화면에 출력한다** (`:257-258`, `old_key head=… / new_key head=…`). 출력을 채팅·스크린샷에 붙이지 말 것.

##### 🚨🚨 회전의 진짜 위험 — 「DB 만 바뀌고 엔진은 옛 키를 들고 있는 구간」

**스크립트가 성공한 순간, 실매매는 즉시 고장 난다.** 이건 스크립트 버그가 아니라 구조다.

- `settings.encryption_key` 는 프로세스 **기동 시점에 한 번** 읽혀 메모리에 남는다 (`config.py` 의 `settings = Settings()` 모듈 전역).
- 그래서 DB 를 새 키로 재암호화해도, **이미 떠 있는 api / scheduler / user-stream / mark-price-stream 은 옛 키를 계속 쓴다.**
- 그 순간부터 주문·청산·손절 경로가 전부 `CryptoError("Failed to decrypt: invalid token")` 로 실패한다.
  **부팅은 멀쩡하고 헬스체크도 초록이다.** §3-2 가 말한 「조용히 매매가 멈춘다」가 바로 이 상태다.
- 🚨 **손절이 안 나가는 구간**이라는 뜻이다. 포지션이 열려 있으면 이건 금전 손실로 직결된다.

**그래서 회전은 「포지션이 없을 때」 정비 작업으로만 한다.** 순서를 지킨다:

1. **활성 포지션·전략을 먼저 정리하거나, 최소한 신규 진입을 멈춘다** (Kill-Switch / 토글 OFF).
   포지션을 연 채로 회전하지 말 것.
2. `--dry-run` → `failed=0` 확인.
3. 백업 JSON 을 **먼저 안전한 곳으로 복사**해 둔다. 이게 유일한 되돌리기 수단이다.
4. 실행 (`--dry-run` 제거).
5. **VPS `.env` 의 `ENCRYPTION_KEY` 를 새 값으로 교체.** ← 이걸 빼면 4번의 고장이 계속된다.
6. **컨테이너 재시작** — `docker compose up -d --force-recreate api scheduler user-stream mark-price-stream`.
   (재시작은 사장님 판단·사장님 손으로. 이번 세션은 읽기 전용이었다.)
7. `validate_encryption_key()` + §3-4 의 복호화 확인이 통과하는지 본다.
8. 통과한 뒤에야 매매를 다시 켠다. 백업 JSON 은 검증 완료 후 폐기.

**되돌리기 (4~6 사이에서 문제가 생겼을 때)**

- DB 는 이미 새 키다. `.env` 만 옛 값으로 되돌리면 **복호화가 안 된다** — 반쪽 롤백은 상황을 더 나쁘게 만든다.
- 제대로 된 롤백은 **둘을 같이** 되돌리는 것이다:
  `--restore-from <backup.json>` 으로 DB 를 옛 암호문으로 복원 **하고**, `.env` 도 옛 `ENCRYPTION_KEY` 로 되돌린 **뒤 재시작**.
- 따라서 **백업 JSON 과 옛 키 둘 다 없으면 롤백이 불가능하다.** 3번 단계를 절대 건너뛰지 말 것.
- 어느 쪽으로도 복구가 안 되면 남는 길은 하나뿐이다 — **바이낸스에서 키 재발급 후 재등록**(§3-2).

> 정리: **지금 상황(§3-3 (A), 기존 DB 유지)에서는 회전할 이유가 없다.**
> 회전은 「키가 유출됐을 때」의 사고 대응 절차이지, PC 이전 절차가 아니다.
> 이전만 하실 거라면 (B) 를 통째로 건너뛰는 것이 가장 안전하다.

#### 3-4. 현재 상태 — 정상 확인됨

VPS 에서 실제로 복호화가 되는지 확인했다 (평문은 출력하지 않고 길이만).

```
ENCRYPTION_KEY_VALID_FERNET = True
account id=1 testnet=False active=True {'api_key_enc': 'DECRYPT_OK(plain_len=64)', 'api_secret_enc': 'DECRYPT_OK(plain_len=64)'}
account id=2 testnet=True  active=False {'api_key_enc': 'DECRYPT_OK(plain_len=3)',  'api_secret_enc': 'DECRYPT_OK(plain_len=3)'}
```

- id=1 = 실계좌. 평문 64자 = 바이낸스 표준 길이 → **정상**
- id=2 = 테스트넷, 비활성. 평문 3자 = 더미 자리채움

새 PC 에서 같은 검증을 하려면:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "from app.core.crypto import validate_encryption_key; validate_encryption_key(); print(\"OK\")"'
```

> 🚨 `backend/scripts/check_binance_key.py` 도 진단에 쓸 수 있지만, 이 스크립트는 **API key 앞 10자와 API _secret_ 앞 10자를 둘 다 화면에 출력한다** (`:38-39` — `[key] head=… / [sec] head=…`). 특히 **secret 이 찍히는 게 위험하다.** 출력을 채팅·스크린샷·이슈에 붙이지 말 것. 되도록 이 스크립트 대신 위의 `validate_encryption_key()` 한 줄을 쓸 것.

---

### 4. 사무실 PC ↔ VPS 값 일치 여부 (지문 비교, 값 노출 없음)

SHA-256 앞 12자리. 역산 불가능하며, 같은지 다른지만 알려준다.

> ℹ️ **왜 지문을 문서에 적어도 되는가.** 여기 나오는 값들은 전부 **난수로 생성된 고엔트로피 비밀**이다(Fernet 키 32바이트, `token_urlsafe(48)`, 봇 토큰, Neon 발급 비번). 해시를 역산하거나 후보를 전수 대입하는 게 계산적으로 불가능하다.
> 🚨 **사람이 정한 비밀번호에는 이 방법을 쓰지 마시라.** 짧고 흔한 비번은 해시만 있으면 사전 대입으로 몇 초 만에 뚫린다. 그런 값은 지문도 적지 말고 **「일치 / 불일치」만** 적을 것.

| 키 | 사무실 PC | VPS | 판정 |
|---|---|---|---|
| `ENCRYPTION_KEY` | `1728f1f33e3b` | `1728f1f33e3b` | ✅ **완전히 같음** |
| `SECRET_KEY` | `6b4d0d3e9d6f` | `6b4d0d3e9d6f` | ✅ 같음 |
| `TELEGRAM_BOT_TOKEN` | `a9eed4f168b3` | `a9eed4f168b3` | ✅ 같음 |
| `DATABASE_URL` | `4396df2704d2` | `a41b3c08b8a7` | ⚠️ **비밀번호만 다르다** — 아래 §4-1 참고 |

#### 4-1. `DATABASE_URL` 이 정확히 어디가 다른가 (2026-09-03 실측, 값 노출 없음)

URL 을 조각내 조각별로 지문을 떠서 비교했다.

| 조각 | 사무실 PC | VPS | 판정 |
|---|---|---|---|
| scheme (`postgresql+psycopg2`) | `a9dc07587109` | `a9dc07587109` | ✅ 같음 |
| user (`neondb_owner`) | `6f1981911003` | `6f1981911003` | ✅ 같음 |
| **password** | `23deba5d81e3` | `3980cf61167a` | 🚨 **다름** (둘 다 Neon 이 발급한 같은 형식·같은 길이) |
| host (Neon 엔드포인트) | `8f0c4435395b` | `8f0c4435395b` | ✅ 같음 |
| DB 이름 (`/neondb`) | `779b9128cc47` | `779b9128cc47` | ✅ 같음 |
| query (`?sslmode=…`) | `0c864f1972b8` | `0c864f1972b8` | ✅ 같음 |

**그리고 사무실 PC 의 그 비밀번호는 이미 만료됐다.** 실제로 붙여 봤다 (읽기 전용 `select 1`):

```
LOCAL DATABASE_URL: CONNECT_FAIL kind= AUTH_FAIL
```

→ 즉 **사무실 `.env` 를 그대로 복사하면 DB 에 붙지 않는다.** Neon 비밀번호가 언젠가 리셋됐고 VPS 만 갱신된 것이다.

**결론: 사무실 PC 의 `backend/.env` 는 `DATABASE_URL` 한 줄만 낡은 「운영 비밀 사본」이다.**
→ 이전 방법: **이 파일을 그대로 새 PC 로 손으로 옮기되, `DATABASE_URL` 한 줄만 최신값으로 교체한다.**
→ 최신 `DATABASE_URL` 얻는 법 (둘 중 하나. 값이 화면에 찍히므로 스크린샷·채팅 금지):
> - **(권장)** Neon 콘솔 https://console.neon.tech → 프로젝트 → **Connection details** 에서 새로 복사. 드라이버 접두어를 `postgresql+psycopg2://` 로 바꾸고 `?sslmode=require` 를 유지할 것 (VPS 값과 같은 형식).
> - VPS 것을 그대로 가져온다: `ssh root@159.65.137.250 'grep "^DATABASE_URL=" ~/binance-auto-trader/backend/.env'`
>
> 🚨 교체 전에 **§7-2 를 먼저 읽을 것.** 최신 DATABASE_URL 을 넣는 순간 새 PC 는 운영 DB 에 붙고, `ENCRYPTION_KEY` 가 같으므로 실계좌 키까지 복호화된다. 「DB 가 안 붙는다」가 지금은 우연한 안전장치 역할을 하고 있다.

새 PC 에서 옮긴 뒤 지문으로 검산 (값을 보지 않고 확인).

**Git Bash 에서** (`sha256sum` 은 Git Bash 에만 있다. PowerShell·cmd 에서는 없는 명령이다):

```bash
cd /c/Users/<Windows사용자명>/바이낸스/binance-auto-trader/backend && for K in ENCRYPTION_KEY SECRET_KEY; do V=$(grep "^$K=" .env | head -1 | cut -d= -f2-); printf "%s fp=%s\n" "$K" "$(printf '%s' "$V" | sha256sum | cut -c1-12)"; done
```

**PowerShell 밖에 없다면** (같은 결과가 나오는 것을 2026-09-03 실측 확인):

```powershell
Set-Location "C:\Users\<Windows사용자명>\바이낸스\binance-auto-trader\backend"
$v = ((Get-Content .env) | Where-Object { $_ -like 'ENCRYPTION_KEY=*' } | Select-Object -First 1) -replace '^ENCRYPTION_KEY=',''
$s = [System.IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($v))
"ENCRYPTION_KEY fp=" + (Get-FileHash -InputStream $s -Algorithm SHA256).Hash.ToLower().Substring(0,12)
```

`ENCRYPTION_KEY fp=1728f1f33e3b` 가 나오면 성공이다.

> ⚠️ **지문이 안 맞으면 90%는 줄바꿈 문자 때문이다.** 현재 `.env` 는 **LF** 다 (`file .env` → `UTF-8 text`, CR 0개 — 실측). Windows 메모장으로 편집·저장하면 CRLF 가 되고, 그러면 값 끝에 보이지 않는 `\r` 이 붙어 ① 지문이 달라지고 ② `ENCRYPTION_KEY` 가 **44자가 아니게 되어 Fernet 검증에서 앱이 부팅부터 죽는다** (§3-2). `.env` 는 VS Code / Notepad++ 처럼 **줄바꿈을 LF 로 유지**하는 편집기로만 열 것. Git Bash 로 확인:
> ```bash
> file .env && grep -c $'\r' .env   # "UTF-8 text" 이고 0 이면 정상
> ```
> ⚠️ 경로의 `<Windows사용자명>` 은 새 PC 의 실제 로그인 계정명이다 (Git Bash 에서 `echo $USERNAME` 으로 확인). 폴더 이름 `바이낸스` 는 한글이지만 공백이 없어 따옴표 없이도 동작한다.

---

### 5. `system_settings` — 운영 토글 (VPS 실조회, 총 63행)

값 읽는 규칙 (`app/services/system_settings_service.py:38-46`):
**`true` / `1` / `yes` / `on` (대소문자 무관) → 켜짐. 그 외 전부 꺼짐. 행 자체가 없으면 코드 기본값.**

#### 5-1. 요청받은 14개 키의 현재 상태

| 키 | DB 값 | 해석 | 근거 |
|---|---|---|---|
| `stage_trim_before_next_enabled` | `1` | ✅ **켜짐** — 다음 단계 진입 전 부분 정리 | `app/services/stage_trim.py:66` |
| `stage_keep_notional_usdt` | **행 없음** | 코드 기본값 **10 USDT** 사용 (남길 증거금) | `stage_trim.py` `KEEP_NOTIONAL_DEFAULT = Decimal("10")` |
| `entry_chg24_gate_enabled` | `1` | ✅ **켜짐** — 24h 변동률 진입 게이트 | `app/services/chg24_entry_gate.py:56` |
| `entry_rank_top_n` | **행 없음** | 코드 기본값 **50** (상승 50 + 하락 50 = 100종목) | `chg24_entry_gate.py` `TOP_N_DEFAULT: int = 50` |
| `entry_chg24_gate_mode` | **행 없음** | 코드 기본값 **`rank`** (순위 방식). 다른 값은 `abs`(절대값) | `chg24_entry_gate.py` `MODE_DEFAULT: str = "rank"` |
| `support_score_gate_enabled` | **행 없음** | ❌ **꺼짐** (기본 OFF, 헌법 161) | `app/services/support_score.py:99` + `gate_enabled()` |
| `support_score_min_long` | **행 없음** | 코드 기본값 **6** (이 점수 이상이면 LONG 허용, 승률 70.6% n=80) | `support_score.py` `MIN_LONG_DEFAULT = 6` |
| `support_score_max_short` | **행 없음** | 코드 기본값 **1** (이 점수 이하면 SHORT 허용, 승률 63.9% n=67) | `support_score.py` `MAX_SHORT_DEFAULT = 1` |
| `trend_4h_gate_enabled` | `1` | ✅ **켜짐** — 4H 추세 게이트 | `app/services/trend_4h_gate.py:62` |
| `auto_obv_enabled` | `1` | ✅ **켜짐** — OBV 자동 진입 | `app/api/v1/strategy_suggestions.py:878` |
| `adaptive_tp_enabled` | `1` | ✅ **켜짐** — 변동성 연동 TP1 | `app/services/adaptive_tp.py:77` |
| `sajangnim_ladder_stages_enabled` | `1` | ✅ **켜짐** — 사장님 3단 사다리 | `app/services/sajangnim_capital.py:353` |
| `sajangnim_pyramid_trigger_roi` | `2` | ROI **+2%** 에서 피라미딩 추가 진입 | `app/workers/success_pyramiding_worker.py:47` |
| `stage_wait_for_turn_enabled` | `1` | ✅ **켜짐** — 단계 진입 시 「꺾임」 대기 | `app/services/stage_entry_timing.py:68` |

> 🚨 **「행이 없다」와 「꺼져 있다」는 다르다.** 위 6개는 DB 에 행이 아예 없어서 코드 기본값으로 도는 중이다. 새 환경으로 DB 를 그대로 가져가면 동일하게 유지되지만, **DB 를 새로 만들면 이 기본값들이 그대로 적용된다**는 뜻이기도 하다.

#### 5-2. 전체 목록 — 진입/매매 토글

| 키 | 값 | 해설 |
|---|---|---|
| `confluence_gate_enabled` | `true` | ✅ 합의 게이트 (`app/services/confluence_gate.py:47`) |
| `entry_window_short_enabled` | `true` | ✅ SHORT 진입 시간창 |
| `long_surge_gate_enabled` | `1` | ✅ LONG 급등 게이트 (`app/services/long_surge_gate.py:62`) |
| `support_breakdown_short_enabled` | `0` | ❌ 지지 붕괴 SHORT 꺼짐 |
| `scheduled_entry_enabled` | `1` | ✅ 예약 진입 (`"1" 이어야 동작`, `app/workers/scheduled_entry_worker.py:64`) |
| `unified_entry_enabled` | `0` | ❌ 통합 진입 꺼짐 |
| `unified_15m_1h_pct` | `2` | 통합 진입 1h 기준 %(꺼져 있어 미적용) |
| `unified_15m_3h_pct` | `7` | 〃 3h 기준 % |
| `unified_v223_min_score` | `1` | 〃 최소 점수 |
| `auto_bb_breakdown_enabled` | `0` | ❌ 볼밴 하향 돌파 꺼짐 |
| `auto_bb_break_daily_limit` | `0` | 일일 한도 0 = 사실상 차단 |
| `auto_bb_break_reset_at` | `2026-08-23T07:34:…` | 워커가 쓰는 타임스탬프 (수동 편집 대상 아님) |
| `pending_hc_fast_enabled` | `0` | ❌ |
| `success_pyramiding_enabled` | `0` | ❌ 피라미딩 워커 꺼짐 — ⚠️ `sajangnim_pyramid_trigger_roi=2` 는 설정돼 있지만 워커 자체가 OFF |
| `whitelist_enabled` | `false` | ❌ 심볼 화이트리스트 미적용 (`ALLOWED_SYMBOLS_CSV` 도 비어 있음) |

#### 5-3. 3단 모드 키 (`off` / `shadow` / `on`) — 🚨 값 해석 주의

이 두 개는 bool 이 아니다. **`shadow` 는 「판정은 하되 실제 주문은 내지 않음」** 이다.

| 키 | 값 | 해설 | 근거 |
|---|---|---|---|
| `bb_mid_line_mode` | `on` | ✅ **실주문 나감** | `app/workers/bb_mid_line_worker.py:42` (`off \| shadow \| on`) |
| `surge_ladder_mode` | `shadow` | ⚠️ **로그만, 실주문 없음** | `app/workers/surge_peak_ladder_worker.py:70` |

#### 5-4. 볼밴 분할 / 사장님 사다리 / 재진입

| 키 | 값 | 해설 |
|---|---|---|
| `pump_split_enabled` | `1` | ✅ 볼밴 분할 켜짐 |
| `pump_split_capitals` | `100,200,500` | 1/2/3차 자본 (USDT) |
| `pump_split_steps` | `3,5,7` | 단계별 트리거 %p |
| `pump_split_sl_roi` | `10` | 손절 ROI % |
| `pump_split_max_concurrent` | `10` | 동시 보유 상한 |
| `split_peak_stall_enabled` | `1` | ✅ 정점-주춤 판정 (`app/workers/stage_trigger_worker.py:905`) |
| `sajangnim_capital_ladder` | `10,300,600` | 사장님 3단 사다리 |
| `sajangnim_default_capital` | `50.0` | 기본 자본 |
| `sajangnim_max_stage` | `3` | 최대 단계 |
| `sajangnim_pyramid_capital` | `300` | 피라미딩 1회 추가액 |
| `sajangnim_reentry_daily_limit` | `10` | 재진입 일일 한도 |
| `sajangnim_reentry_concurrent_slots` | `10` | 재진입 전용 동시 슬롯 |
| `sajangnim_top_short_daily_limit` | `50` | 정점 SHORT 일일 한도 |

#### 5-5. OBV 자동 진입

| 키 | 값 | 키 | 값 |
|---|---|---|---|
| `auto_obv_enabled` | `1` ✅ | `auto_obv_min_confidence` | `0.95` |
| `auto_obv_capital_per_stage` | `400` | `auto_obv_daily_limit` | `3` |
| `auto_obv_leverage` | `2` | `auto_obv_stage2_trigger` | `-5.0` |
| `auto_obv_stage3_trigger` | `-5.0` | `auto_obv_tp1` ~ `tp4` | `15.0 / 25.0 / 35.0 / 45.0` |

#### 5-6. 손절 / 증거금

| 키 | 값 | 해설 |
|---|---|---|
| `force_sl_short_enabled` | `true` | ✅ SHORT 강제 손절 |
| `force_sl_short_roi` | `80` | ROI −80% 에서 강제 손절 |
| `force_sl_long_roi` | `80` | LONG 〃 |
| `force_sl_unlock_unreachable_stage` | `true` | ✅ 도달 불가 단계로 손절이 잠기던 교착 해제 |
| `auto_add_margin_usdt` | `300` | 자동 증거금 추가액 |

#### 5-7. 제안(suggestion) 엔진

| 키 | 값 | 해설 |
|---|---|---|
| `suggestion_auto_execute_enabled` | `false` | ❌ **자동 실행 꺼짐** (제안만 하고 주문 안 냄) |
| `suggestion_confidence_threshold` | `0.85` | 자동 실행 최소 신뢰도 |
| `suggestion_daily_auto_limit` | `3` | 자동 실행 일일 한도 |
| `suggestion_auto_dismiss_hours` | `24` | 제안 자동 폐기 시간 |
| `suggestion_current_default_profile` | `safe` | 기본 프로필 |
| `suggestion_default_profiles` | (큰 JSON) | `safe` / `aggressive` / `conservative` 3종 프로필 정의 — UI 에서 편집 |

#### 5-8. 🤖 워커가 자동 생성하는 캐시 (사람이 편집하지 말 것)

| 키 | 정체 | 크기 |
|---|---|---|
| `learning_agent_insights` | 학습 에이전트 결과 JSON, 매시 갱신 (마지막 `2026-09-03 05:52`) | 수 KB |
| `pattern_learning_insights_v187` | 패턴 학습 결과 JSON (표본 2,395건), 매시 갱신 (`2026-09-03 06:52`) | 수십 KB |
| `post_liquidation_analysis_v212` | 청산 후 분석 JSON (`2026-08-21` 이후 갱신 없음) | 작음 |

> 새 환경으로 DB 를 옮길 때 이 3개는 **복사할 필요 없다.** 워커가 다시 채운다.

전체 목록을 새 PC 에서 다시 뜨는 명령 (거대 JSON 3개는 제외):

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for k,v in db.execute(text(\"select key,value from system_settings where length(value)<200 order by key\")).fetchall():
    print(f\"{k} = {v}\")
"'
```

---

### 6. `exchange_accounts` / `users` — 개수와 플래그만

VPS 실조회. **키 값은 읽지 않았고 존재 여부만 확인했다.**

| id | user_id | 거래소 | 시장 | 헤지모드 | 테스트넷 | 활성 | 계정별 손실한도 | api_key 있음 | secret 있음 | passphrase | 생성일 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | binance | usds_m_futures | ✅ | ❌ **mainnet** | ✅ **활성** | NULL (전역값 사용) | ✅ | ✅ | 없음 | 2026-04-25 |
| 2 | 2 | binance | usds_m_futures | ✅ | ✅ testnet | ❌ 비활성 | NULL | ✅ (더미 3자) | ✅ (더미) | 없음 | 2026-04-25 |

**→ 실제로 돈이 도는 계정은 `id=1` 하나뿐이다.**

`users` 테이블: 2명, 둘 다 `role=admin`, `is_active=true`, `timezone=Asia/Seoul`.
(id=1 은 `he***@gmail.com` = 사장님. id=2 는 이메일에 `@` 가 없는 값이라 마스킹 처리했다 — ⚠️ 정체 확인 못 함)

- `daily_loss_limit_usdt` 가 둘 다 NULL → 전역 `.env` 의 `DAILY_LOSS_LIMIT_USDT=0` 을 따르고, **0 이므로 일일 손실 한도가 비활성**이다 (`app/models/exchange_account.py:20-23`, `app/core/config.py:33`).

새 PC 에서 같은 조회를 하는 명령:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"select id,user_id,is_testnet,is_active,(api_key_enc is not null) as has_key from exchange_accounts order by id\")).fetchall():
    print(dict(r._mapping))
"'
```

> 🚨 **함정**: `docker compose exec db psql` 로 조회하면 **빈 DB** 가 나온다. 실제 DB 는 외부 Neon 인데 로컬 `db` 컨테이너도 같이 떠 있기 때문이다 (`docker-compose.yml:2-16`, 컨테이너 `binance-auto-trader-db` 가 3주째 가동 중). 반드시 위처럼 **api 컨테이너의 앱 세션**으로 접근할 것.

---

### 7. 🚨 새 PC 이전 — 하면 안 되는 것 / 해야 하는 것

#### 7-1. 절대 하면 안 되는 것

| 🚨 | 왜 |
|---|---|
| **`.env` 를 채팅·이메일·텔레그램·깃에 붙여넣기** | `.gitignore:7-10` 이 `backend/.env` 를 막고 있지만, 사람이 손으로 붙여넣는 건 못 막는다 |
| **`ENCRYPTION_KEY` 를 새로 생성해서 기존 DB 에 붙이기** | DB 의 API 키가 즉시 복호화 불가가 된다. §3-3 |
| **새 PC 에서 `docker compose up -d` 를 그냥 실행** | 🚨 **로컬 `.env` 의 DATABASE_URL 이 운영 Neon 을 가리키고 ENCRYPTION_KEY 도 같다** → scheduler / user-stream 이 VPS 와 **동시에** 실계좌로 주문을 낸다. 중복 주문 사고. ⚠️ 지금 이 순간은 그 DATABASE_URL 의 **비밀번호가 만료돼 인증 실패**하는 덕에 우연히 막혀 있다 (§4-1 실측). **최신 DATABASE_URL 을 채워 넣는 순간 이 우연한 방어가 사라진다** |
| **`check_binance_key.py` 를 새 PC 에서 실행 / 출력을 캡처해 공유** | 🚨 초안은 「키 앞 10자」라고만 했는데 **틀렸다. API Key 앞 10자 + API Secret 앞 10자를 둘 다 찍는다** (`scripts/check_binance_key.py:38-39`, 실코드 확인). 게다가 이 스크립트는 **바이낸스에 실제로 서명 요청을 3번 보낸다**(ping / get_balance / get_account) → 화이트리스트에 없는 새 PC 에서 돌리면 **IP ban 위험**. §7-2b |
| **`key-rotation-backup-*.json` 을 방치** | 옛 암호문 전체가 들어있다. ⚠️ **`--dry-run` 만 돌려도 이 파일이 생긴다** (`rotate_encryption_key.py:274`) |
| **`rotate_encryption_key.py` 출력을 캡처해 공유** | 옛/새 `ENCRYPTION_KEY` 의 **앞 8자**를 화면에 찍는다 (`scripts/rotate_encryption_key.py:257-258`, `old_key head=… / new_key head=…`) |
| **`alembic upgrade head` 를 `.env` 확인 없이 실행** | 🚨 운영 Neon DB 에 DDL 이 걸린다. 되돌리는 스크립트가 없다. §7-2 ⑥ |
| **`rotate_encryption_key.py` 를 운영 DB 에 그냥 실행** | 🚨 VPS 컨테이너는 **옛 키를 메모리에 들고 있다** → DB 만 새 키가 되는 순간 실매매가 즉시 멈춘다. §3-3 (B) |
| **`git stash` / `git stash pop` 을 맨손으로 사용** | 🚨 이 저장소는 **worktree 를 공유**한다(`.claude/worktrees/…`). stash 는 저장소 전역이라 다른 worktree 의 작업까지 빨아들이고, `pop` 은 충돌 시 stash 를 남긴 채 반쯤 적용돼 되돌리기 어렵다. 임시 보관이 필요하면 `git stash` 대신 **브랜치를 하나 파서 커밋**할 것 |
| **`git reset --hard` / `git clean -fd` / `git push --force`** | 이 문서 어디에도 필요 없는 명령이다. `--hard` 는 `.env` 는 안 지우지만(`.gitignore` 대상) 미커밋 코드 변경을 **복구 불가**하게 날린다 |
| **VPS 에서 재시작·배포·설정변경** | 실자금이 돌고 있다. 이번 조사는 전부 읽기 전용으로 했다 |
| **VPS 의 `.env` 를 새 PC 에서 `scp` 로 덮어쓰기** | CRLF `.env` 를 VPS 에 올리면 값 끝에 `\r` 이 붙어 `DATABASE_URL`·`ENCRYPTION_KEY` 가 조용히 깨진다. ⚠️ **정정**: 이 저장소는 `core.autocrlf=true` 이지만 `.env` 는 `.gitignore:7` 로 깃 추적 대상이 아니라 **git 이 변환하지 않는다.** 실제로 사무실 `.env` 는 지금 **LF**(CR 0개, 실측)다. CRLF 는 **Windows 메모장 같은 편집기로 저장할 때** 생긴다 — 그쪽을 조심할 것. 확인: `file .env && grep -c $'\r' .env` |
| **비밀 값을 명령줄에 적기** — `NEW_ENCRYPTION_KEY="…" python …`, `psql "postgres://…:비번@…"` 같은 형태 | 그 줄이 `~/.bash_history` 에 **파일로 영구히 남고**, 실행 중에는 같은 서버의 `ps aux` 로 누구나 본다. ssh 로 보내면 **VPS 히스토리에도** 남는다. §3-3 (B) 의 파일 방식을 쓸 것 |
| **비밀 값을 Claude(나) 나 다른 AI 채팅창에 붙여넣기** | 이 문서를 만드는 동안 나는 `.env` 의 **값을 한 번도 읽지 않았다.** 앞으로도 값은 사장님만 다루신다. 진단에 필요한 건 값이 아니라 **지문**(§4)이다 |
| **`.env` 나 USB 사본을 OneDrive / 구글드라이브 같은 동기화 폴더에 두기** | 저장소 경로가 이미 사용자 폴더 밑(`C:\Users\user\…`)이다. 동기화 폴더 안으로 옮기면 `.gitignore` 와 **무관하게** 클라우드로 올라간다 |
| **터미널 출력을 그대로 캡처해 공유** | `.env` 를 실수로 `cat` 한 화면, `docker compose config`(→ `.env` 값을 전부 펼쳐 출력한다), `env` / `printenv` 출력이 전부 해당된다 |
| 🚨 **이 문서(`docs/handoff/2026-09-03/secrets.md`)를 커밋해서 push** | **저장소가 public 이다** (`"visibility": "public"` 실측). `docs/handoff/` 는 이미 추적되는 경로라 커밋하면 바로 공개된다. VPS IP·root SSH·**열린 redis**·해제된 안전장치가 전부 공개 문서가 된다. 문서 맨 위 경고 참고 |

#### 7-2. 새 PC 에서 로컬 스택을 굳이 띄워야 한다면

> ## 🚨🚨 먼저: 이 절의 초안에는 **치명적 오류**가 있었다 (검증에서 발견, 수정 완료)
>
> 초안은 「`.env.local-safe` 사본을 만들어 거기만 고치고 `docker compose up` 하라」고 했다.
> **그렇게 하면 안전해지지 않는다.** `backend/docker-compose.yml` 은 서비스마다
> `env_file: - .env` 로 **파일 이름이 박혀 있다** (`docker-compose.yml:31,45,58,74` — api/scheduler/user-stream/mark-price-stream 네 곳 전부).
> compose 는 `.env.local-safe` 를 **쳐다보지도 않는다.**
> → 사본을 만들고 「안전하게 바꿨다」고 믿은 채 `docker compose up -d` 하면
> **운영 Neon DB + 운영 ENCRYPTION_KEY 로 그대로 뜬다.** 위험 2·4 가 그대로 realize 된다.
>
> 실제로 갈아끼우려면 **`.env` 그 파일 자체를 바꿔야 한다.** 아래 절차를 그대로 따를 것.

**결론부터: 가장 안전한 선택은 「로컬 스택을 안 띄우는 것」이다.**
운영 화면은 VPS 의 `http://159.65.137.250:8000` 을 그대로 쓰면 된다. 새 PC 에서
코드만 편집하고 push 하는 것으로 충분하다. 아래는 **정말로 로컬 기동이 필요할 때만.**

> **전제: 새 PC 에 Docker 가 깔려 있어야 한다.** 이 문서의 `docker compose …` 는 전부
> **Docker Desktop for Windows** (WSL2 백엔드) 를 전제로 한다. 없으면 `bash: docker: command not found` 가 난다.
> 확인:
> ```bash
> docker --version && docker compose version
> ```
> 둘 다 버전이 찍히지 않으면 https://www.docker.com/products/docker-desktop/ 에서 설치하고 **Docker Desktop 을 실행한 상태**로 둔다 (앱이 꺼져 있으면 `error during connect` 가 난다).
> ⚠️ VPS 에 대고 치는 `ssh … docker compose …` 명령들은 **VPS 쪽 도커를 쓰므로 새 PC 에 Docker 가 없어도 된다.** §8 검증 체크리스트는 Docker 없이도 전부 돈다.

**① 운영 `.env` 를 먼저 백업한다 (되돌리기 지점)**

```bash
cd "/c/Users/<사용자>/바이낸스/binance-auto-trader/backend" && cp -n .env .env.PROD-BACKUP && ls -l .env .env.PROD-BACKUP
```

`cp -n` 이라 이미 백업이 있으면 덮어쓰지 않는다. 두 파일이 **같은 크기**로 보여야 한다.

**② 로컬용 사본을 만들고 편집한다**

```bash
cd "/c/Users/<사용자>/바이낸스/binance-auto-trader/backend" && cp .env .env.local-safe
```

`.env.local-safe` 를 편집기로 열어 아래 **네 줄**을 고친다. (초안은 두 줄만 시켰는데
부족하다 — 텔레그램·Sentry 를 그대로 두면 로컬 테스트 알림이 **운영 알림 채널로** 날아가
사장님이 실매매 알림과 구분할 수 없게 된다.)

- `DATABASE_URL=postgresql+psycopg2://postgres:<같은 파일의 POSTGRES_PASSWORD 값>@db:5432/binance_auto_trader`
- `APP_ENV=local`
- `TELEGRAM_BOT_TOKEN=` ← **빈 값으로**
- `SENTRY_DSN=` ← **빈 값으로**

> 🚨 **첫 줄의 비밀번호를 `postgres` 로 쓰면 안 된다** (초안이 그렇게 시켰는데 틀렸다).
> `docker-compose.yml:10` 이 db 컨테이너를 `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}` 로 띄운다 —
> 즉 **`.env` 에 있는 `POSTGRES_PASSWORD` 값**으로 postgres 가 초기화된다. 로컬 `.env` 에는 그 키가 실제로 들어 있다(§1-3 목록 6번).
> 새 PC 는 볼륨이 비어 있으니 그 값으로 처음 만들어지고, DSN 에 `postgres` 를 적으면 `password authentication failed` 가 난다.
> → **같은 `.env.local-safe` 파일 안의 `POSTGRES_PASSWORD=` 줄 값을 그대로 복사해 넣는다.**
> 값은 이 문서에 적지 않는다. 파일 안에서 복사·붙여넣기만 하면 되고, **화면에 출력할 필요도 없다.**
> (URL 에 넣을 때 `@ : / ? #` 같은 문자가 값에 있으면 퍼센트 인코딩이 필요하다. `token_urlsafe` 로 만든 값이면 그런 문자가 없어 그냥 붙이면 된다.)

`ENCRYPTION_KEY` 는 **그대로 둔다.** 형식이 틀리면 api 가 부팅 즉시 죽는다 (`main.py:46`).
로컬 DB 는 비어 있어 복호화할 대상 자체가 없으므로 위험하지 않다.

**③ `.env` 를 로컬용으로 실제 교체한다 — 이 단계를 빼면 ①②가 전부 무의미하다**

```bash
cd "/c/Users/<사용자>/바이낸스/binance-auto-trader/backend" && cp .env.local-safe .env
```

**④ 🚨 교체가 진짜 됐는지 검증한다. 이 검증을 통과하기 전에는 어떤 compose/alembic 명령도 치지 말 것.**

```bash
cd "/c/Users/<사용자>/바이낸스/binance-auto-trader/backend" && n=$(grep -c "^DATABASE_URL=" .env); if [ "$n" -ne 1 ]; then echo "🚨 STOP: DATABASE_URL 줄이 $n 개다 (1개여야 한다) — 옛 줄을 지울 것"; elif grep "^DATABASE_URL=" .env | grep -q "neon.tech"; then echo "🚨 STOP: .env 가 아직 운영 Neon 을 가리킨다 — 여기서 멈출 것"; elif grep "^DATABASE_URL=" .env | grep -q "@db:5432/"; then echo "SAFE: .env 가 로컬 DB 를 가리킨다"; else echo "🚨 STOP: DATABASE_URL 이 로컬도 Neon 도 아니다 — 눈으로 확인할 것"; fi
```

`SAFE:` 가 나오지 않으면 **여기서 멈춘다.** `neon.tech` 가 한 글자라도 남아 있으면 안 된다.

> 줄 개수를 세는 이유: `.env` 에 `DATABASE_URL` 이 **두 줄** 남아 있으면(옛 줄을 지우지 않고
> 새 줄을 밑에 추가한 경우) 눈으로는 로컬로 바꾼 것처럼 보이는데, 어느 줄이 이기는지가
> 로더에 따라 달라진다. **한 줄만 남기는 것이 유일하게 확실하다.**

**⑤ 컨테이너를 띄운다 — `api` 만. `scheduler` / `user-stream` / `mark-price-stream` 은 띄우지 않는다**

`docker compose up -d` 를 **인자 없이 치면 9개 서비스가 전부 뜬다.** 반드시 이름을 지정한다.

```bash
cd "/c/Users/<사용자>/바이낸스/binance-auto-trader/backend" && docker compose up -d db redis api
```

**⑥ 스키마 생성 — alembic 은 `.env` 의 `DATABASE_URL` 을 그대로 따라간다**

> 🚨 **`alembic upgrade head` 는 읽기 명령이 아니라 DDL 이다.** ④ 검증을 건너뛰고 이걸 치면
> **운영 Neon DB 에 마이그레이션이 걸린다.** alembic 의 `downgrade` 는 이 프로젝트에서
> 한 번도 실행·검증된 적이 없으므로 **되돌릴 방법이 사실상 없다.**
> 아래는 컨테이너 안에서 접속 대상을 한 번 더 확인한 뒤에만 실행한다.

```bash
cd "/c/Users/<사용자>/바이낸스/binance-auto-trader/backend" && docker compose exec -T -e PYTHONPATH=/app api python -c "from app.core.config import settings; h=settings.database_url.split('@')[-1]; print('TARGET =', h); assert 'neon.tech' not in h, 'STOP: 운영 DB 다'; print('OK: 로컬 DB')"
```

`OK: 로컬 DB` 가 찍힌 다음에만:

```bash
cd "/c/Users/<사용자>/바이낸스/binance-auto-trader/backend" && docker compose exec -T -e PYTHONPATH=/app api alembic upgrade head
```

참고: 2026-09-03 기준 운영 DB 의 alembic 버전 = `0034_surge_ladder`, 저장소 최신 마이그레이션 = `0034_surge_ladder_state.py`. **둘이 일치한다** → 지금 코드에는 운영에 미적용된 마이그레이션이 없다 (VPS 실조회로 확인).

**⑦ 끝나면 운영 `.env` 로 되돌린다 (롤백)**

로컬 실험이 끝나면 반드시 되돌려 놓는다. 안 되돌리면 다음에 이 폴더에서 무심코 친 명령이
**로컬 빈 DB** 를 보고 「데이터가 사라졌다」는 오진으로 이어진다.

```bash
cd "/c/Users/<사용자>/바이낸스/binance-auto-trader/backend" && docker compose down && cp .env.PROD-BACKUP .env && grep -c "neon.tech" .env
```

마지막 숫자가 `1` 이상이면 운영 `.env` 로 복구된 것이다.

> ## 🚨 `docker compose down` 은 **새 PC 안에서만** 친다
>
> 이 명령은 컨테이너를 **정지하고 삭제**한다. 같은 명령을 **VPS 에서 치면 실매매가 통째로 멈춘다**
> — api·scheduler·user-stream 이 다 내려가고, **열려 있는 포지션의 손절·익절이 나가지 않는다.**
> 이 문서에서 `docker compose down` 이 등장하는 곳은 **여기 한 곳뿐**이고, 앞의 `cd "/c/Users/…"`
> 가 반드시 붙어 있어야 한다.
>
> **ssh 창과 로컬 Git Bash 창을 헷갈리는 것이 이 사고의 실제 원인이다.** 치기 전에 한 번 확인:
> ```bash
> hostname   # 새 PC 이름이어야 한다. binance-trader-prod 가 나오면 VPS 다 — 즉시 멈출 것
> ```

> ⚠️ **이 §7-2 절차는 실제로 돌려보지 않았다** (VPS 읽기 전용 원칙 + 로컬 컨테이너 미기동).
> `env_file: - .env` 가 박혀 있다는 사실과 alembic/모듈 경로는 파일로 확인했지만,
> 기동 자체는 미검증이다.

#### 7-2b. 🚨 로컬 스택을 띄울 때의 바이낸스 IP ban 위험

`.env` 를 로컬 DB 로 갈아끼웠어도, **로컬 DB 에 실 API 키를 등록하면 안 된다.**

- 새 PC 의 공인 IP 는 바이낸스 API 키의 신뢰 IP 목록에 **없다** (§10 미확인 항목).
- 등록되지 않은 IP 에서 서명 요청을 보내면 전부 거부되고, 워커가 자동 재시도를 돌리면
  **418 / -1003 IP ban** 으로 번진다. 2026-08-26 에 실제로 발생한 사고다.
- 밴은 **키가 아니라 IP** 에 걸린다. 사무실·집 회선이 VPS 와 같은 NAT 를 타는 상황이면
  운영까지 영향을 받을 수 있다.

→ 로컬은 **테스트넷 키**(`is_testnet=True`)로만 붙이거나, 아예 거래소 계정을 등록하지 않고
UI/스키마만 확인한다.

#### 7-3. SSH 개인키 — 두 가지 방법

**방법 A (간단, 키 재사용)**: 사무실 PC 의 `~/.ssh/id_ed25519` 와 `id_ed25519.pub` 두 파일을 USB 로 새 PC 의 같은 경로에 복사.

```bash
ls -l ~/.ssh/id_ed25519 ~/.ssh/id_ed25519.pub
```

> ⚠️ **Windows 에서는 `chmod` 가 진짜 관문이 아니다 — NTFS 권한(ACL)이 관문이다.** Git Bash 는 `ls -l` 에 `-rw-r--r--` (644) 로 보여주지만 그건 **흉내낸 표시**다. 2026-09-03 사무실 PC 실측: `icacls` 로 본 실제 권한은 `Administrators / SYSTEM / 본인` 세 주체뿐이라 충분히 잠겨 있고, **Git Bash 의 `ssh` 도 PowerShell 의 `ssh.exe` 도 둘 다 정상 접속된다.** 즉 지금 사무실 PC 는 문제가 없다.
>
> 문제는 **USB 를 거쳐 새 PC 로 복사할 때**다. 복사된 파일이 상위 폴더의 느슨한 ACL 을 물려받으면 Windows 기본 `ssh.exe` 가 `UNPROTECTED PRIVATE KEY FILE` 로 **접속을 거부**한다. 옮기자마자 **PowerShell 에서** 아래를 실행해 확실히 잠근다 (Git Bash 의 `chmod` 는 NTFS ACL 을 못 고치는 경우가 있다):
>
> ```powershell
> icacls "$env:USERPROFILE\.ssh\id_ed25519" /inheritance:r /grant:r "$env:USERNAME:(R)"
> icacls "$env:USERPROFILE\.ssh\id_ed25519"
> ```
>
> 두 번째 줄의 출력에 `Users` 나 `Everyone` 이 **없어야** 정상이다. Git Bash 만 쓴다면 아래도 같이 해두면 좋다:
>
> ```bash
> chmod 600 ~/.ssh/id_ed25519 && chmod 644 ~/.ssh/id_ed25519.pub && ls -l ~/.ssh/id_ed25519*
> ```
>
> 🚨 **개인키를 옮긴 USB 는 반드시 정리한다.** 이 파일 하나로 운영 서버 root 에 들어갈 수 있다. 복사가 끝나고 새 PC 접속이 확인되면 USB 의 사본을 지우고 휴지통도 비울 것. 클라우드 드라이브·이메일·채팅에 올리지 말 것.

**방법 B (더 안전, 새 키 발급)**: 새 PC 에서 새 키를 만들고 **공개키만** VPS 에 추가. 이건 VPS 에 쓰기 작업이라 **사장님이 직접** 하셔야 한다 (이번 세션은 VPS 읽기 전용).

> ## 🚨 방법 B 는 「서버에서 잠길 수 있는」 유일한 절차다 — 아래 3가지를 반드시 지킬 것
>
> 1. **기존 SSH 세션을 열어둔 채로 작업한다.** 새 키가 안 먹혀도 그 열린 창으로 되돌릴 수 있다.
>    작업이 끝나고 **새 창에서 새 키로 접속이 되는 걸 확인하기 전까지 그 창을 닫지 말 것.**
> 2. `authorized_keys` 에 넣을 때 **반드시 `>>` (추가)** 를 쓴다. **`>` (덮어쓰기) 를 쓰면 기존
>    `binance-trader-vps` 키가 지워져 사무실 PC 가 즉시 잠긴다.** 현재 등록된 키는 딱 1개라 여유가 없다.
> 3. 그래도 잠겼다면 마지막 수단은 **DigitalOcean 웹 콘솔**(Droplet → Access → Launch Droplet Console) 이다.
>    거기서 로그인하려면 **root 비밀번호**가 필요하다 — 🚨 **지금 그 비밀번호를 알고 계신지 이전 전에 미리 확인**하실 것.
>    모르면 콘솔에서 비밀번호 재설정이 필요하고, 그 사이 VPS 를 못 만진다 (매매는 계속 돌지만 손을 못 댄다).
>
> ⚠️ **방법 A 로 이미 키를 옮겼다면 방법 B 는 할 필요가 없다.** 둘 다 하지 말 것 —
> 아래 `ssh-keygen` 은 같은 경로(`~/.ssh/id_ed25519`)를 쓰므로 **방금 옮긴 키를 덮어쓸 수 있다**
> (덮어쓰기 전에 `Overwrite (y/n)?` 를 묻는다. **여기서 `y` 를 치면 옮겨온 키가 사라진다 — `n` 을 칠 것**).
> 굳이 둘 다 두려면 `-f ~/.ssh/id_ed25519_newpc` 처럼 **다른 파일명**을 쓴다.

새 PC 에서 키 생성:

```bash
ssh-keygen -t ed25519 -C "binance-trader-newpc" -f ~/.ssh/id_ed25519_newpc
```

접속 확인:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'hostname && uptime'
```

`binance-trader-prod` 가 나오면 성공이다 (2026-09-03 실측 호스트명).

> ⚠️ **`-o StrictHostKeyChecking=no` 에 대해** — 이 문서의 모든 ssh 명령에 붙어 있다. 이건
> **서버 신원 확인을 끄는 옵션**이다. 새 PC 는 `known_hosts` 가 비어 있어서 첫 접속의
> 대화형 확인 프롬프트를 넘기려고 쓴 것이지, 안전해서 쓴 게 아니다.
> **첫 접속 한 번만 이 옵션을 쓰고, 그 뒤로는 떼는 것을 권한다.** 한 번 접속하면
> `~/.ssh/known_hosts` 에 서버 지문이 저장되어 다음부터는 옵션 없이 붙는다.
> 옵션을 계속 달고 다니면 **서버가 바뀌어도(= 중간자 공격이어도) 경고 없이 접속**한다 —
> root 로 들어가는 서버라 위험이 크다.

#### 7-4. GitHub

원격은 HTTPS 이고 credential helper 는 `manager` 다.

```bash
git -C /c/Users/<사용자>/바이낸스/binance-auto-trader remote -v
```

→ `https://github.com/herosys1-crypto/binance-auto-trader.git`
새 PC 첫 `git push` 때 Git Credential Manager 가 브라우저 로그인을 띄운다. **사장님이 직접 로그인**하시면 된다. PAT 를 파일에 적어둘 필요 없다.

---

### 8. 이전 후 검증 체크리스트

순서대로 실행. 하나라도 실패하면 다음으로 넘어가지 말 것.

> **전제 (이게 안 돼 있으면 ① 부터 전부 「파일 없음」으로 실패한다)**
> - **Git Bash 에서** 실행한다. `sha256sum`·`awk`·`grep` 은 PowerShell·cmd 에 없다 (PowerShell 대안은 §4 참고).
> - 저장소가 이미 새 PC 에 **clone** 돼 있어야 한다. 아직이라면 먼저:
>   ```bash
>   mkdir -p /c/Users/<Windows사용자명>/바이낸스 && cd /c/Users/<Windows사용자명>/바이낸스 && git clone https://github.com/herosys1-crypto/binance-auto-trader.git
>   ```
> - `backend/.env` 는 **깃에 없다**(`.gitignore:7`). clone 만으로는 생기지 않는다 — §4 의 방법으로 **직접 옮겨 놓은 뒤**에 ① 을 실행한다.
> - 아래 `<Windows사용자명>` 은 새 PC 의 로그인 계정명이다 (`echo $USERNAME`).
> - **clone 전에** 사무실 PC 와 같은 줄바꿈 설정을 맞춘다. 안 맞추면 전 파일이 diff 로 뜨거나
>   `.sh` 가 `bad interpreter: ^M` 으로 안 돈다 (§9-7b).
>   ```bash
>   git config --global core.autocrlf true
>   ```
> - ⚠️ **clone 한 새 PC 에서 `git push` 를 서두르지 말 것.** 운영 VPS 는 `main` 의 `ded22f3` 을
>   그대로 돌리고 있다(2026-09-03 실측). 새 PC 에서 실수로 옛 커밋을 올리면 다음 배포 때
>   운영 코드가 되돌아간다. push 전에 `git log -1` 로 HEAD 를 확인할 것.

**① `.env` 가 제대로 옮겨졌는지 (값을 보지 않고)**

```bash
cd /c/Users/<사용자>/바이낸스/binance-auto-trader/backend && awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/ {k=$1; v=substr($0, index($0,"=")+1); print k, (length(v)>0 ? "SET" : "EMPTY")}' .env
```

**② `ENCRYPTION_KEY` 지문이 `1728f1f33e3b` 인지**

```bash
cd /c/Users/<사용자>/바이낸스/binance-auto-trader/backend && printf '%s' "$(grep '^ENCRYPTION_KEY=' .env | cut -d= -f2-)" | sha256sum | cut -c1-12
```

`1728f1f33e3b` 가 아니면 **줄바꿈(CRLF) 오염을 먼저 의심할 것** — §4 의 마지막 경고 참고.

**②-b `ENCRYPTION_KEY` 길이가 44자인지 (Fernet 형식 즉시 확인)**

지문이 맞아도 이 검사를 한 번 더 한다. 44자가 아니면 **api 가 부팅과 동시에 죽는다** (`main.py:46`).

```bash
cd /c/Users/<사용자>/바이낸스/binance-auto-trader/backend && printf 'ENCRYPTION_KEY len=%s (44 여야 정상)\n' "$(grep '^ENCRYPTION_KEY=' .env | cut -d= -f2- | tr -d '\n\r' | wc -c)"
```

**②-c `DATABASE_URL` 이 실제로 붙는지 (이걸 안 재면 조용히 실패한다)**

지문·길이가 다 맞아도 **DB 비밀번호가 만료돼 있으면 아무것도 안 돈다.** 2026-09-03 사무실 PC 가 정확히 그 상태였다 (§4-1). 값은 화면에 찍지 않는다.

```bash
cd /c/Users/<사용자>/바이낸스/binance-auto-trader/backend && python -c "
import psycopg2
u=[l.split('=',1)[1].strip() for l in open('.env',encoding='utf-8') if l.startswith('DATABASE_URL=')][0]
try:
    c=psycopg2.connect(u.replace('postgresql+psycopg2://','postgresql://'), connect_timeout=15)
    c.cursor().execute('select 1'); c.close(); print('DB CONNECT_OK')
except Exception as e:
    print('DB CONNECT_FAIL:', 'AUTH_FAIL' if 'authentication' in str(e).lower() else type(e).__name__)
"
```

> ⚠️ **이 명령의 출력 문자열을 한글로 바꾸지 말 것.** Windows 콘솔 기본 인코딩이 `cp949` 라
> `python -c` 안에서 한글이나 `—` 같은 문자를 `print` 하면 실행 자체가
> `UnicodeEncodeError: 'cp949' codec can't encode character` 로 죽는다 (2026-09-03 실측).
> 그래서 위 출력은 전부 ASCII 다. (컨테이너 안에서 도는 명령은 UTF-8 이라 한글이 안전하다.)

판정:
- `DB CONNECT_OK` → 붙었다
- `DB CONNECT_FAIL: AUTH_FAIL` → **비밀번호 만료.** §4-1 대로 최신 `DATABASE_URL` 로 교체해야 한다
- `DB CONNECT_FAIL: OperationalError` → 네트워크·방화벽 문제 (Neon 은 5432/TCP 아웃바운드가 필요하다)
- `psycopg2` 가 없다는 오류(`ModuleNotFoundError`)가 나면: `pip install psycopg2-binary`
- 🚨 `DB CONNECT_OK` 가 나오면 **새 PC 가 운영 DB 에 붙은 것이다.** 여기서 `docker compose up -d` 를 치면 VPS 와 중복으로 실매매가 나간다 (§7-1). 확인만 하고 **컨테이너는 띄우지 말 것.**

**③ VPS SSH 접속**

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'hostname'
```

**④ VPS 컨테이너가 전부 살아있는지**

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ps --format "table {{.Name}}\t{{.Status}}"'
```

2026-09-03 조사 시점 기준 9개 컨테이너 전부 `Up`: api / scheduler / user-stream / mark-price-stream / db / redis / prometheus / grafana / db-backup.

**⑤ 암호화 키가 실제로 복호화하는지**

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "from app.core.crypto import validate_encryption_key; validate_encryption_key(); print(\"ENCRYPTION_KEY OK\")"'
```

**⑥ GitHub push 권한**

```bash
git -C /c/Users/<사용자>/바이낸스/binance-auto-trader ls-remote origin HEAD
```

**⑦ 🚨 마지막 — 「내가 이전하는 동안 실매매가 멀쩡했는가」**

①~⑥ 은 전부 「새 PC 가 준비됐는가」를 잰다. **운영이 상했는지는 안 잰다.**
이전 작업 전후로 이 한 줄을 돌려 **숫자가 늘고 있는지** 확인한다.

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
print(\"ACTIVE_STRATEGIES =\", db.execute(text(\"select count(*) from strategy_instances where status not in (\x27COMPLETED\x27,\x27STOPPED\x27,\x27CANCELLED\x27)\")).scalar())
print(\"LAST_ORDER_AT     =\", db.execute(text(\"select max(created_at) from orders\")).scalar())
"'
```

- `LAST_ORDER_AT` 이 **몇 시간째 그대로**면 매매가 멈춘 것이다. 조용히 멈추는 건 이 시스템의
  대표적 고장 양상이다 (§3-2). 이전 작업과 무관하게라도 즉시 원인을 찾아야 한다.
- 컨테이너 로그로 복호화 실패가 났는지 확인 (값은 안 찍힌다):
  ```bash
  ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 30m scheduler | grep -i "invalid token\|CryptoError" | tail -20'
  ```
  출력이 **비어 있어야 정상**이다. 뭔가 나오면 `ENCRYPTION_KEY` 불일치다 (§3-3 B 의 사고 양상).

✅ **이 쿼리는 실제로 돌려서 확인했다** (2026-09-03, 읽기 전용). 그때의 기준값:

```
ACTIVE_STRATEGIES = 24
LAST_ORDER_AT     = 2026-09-03 08:59:18+00:00   (UTC — KST 는 +9시간)
```

이전 작업 뒤에 다시 재서 `LAST_ORDER_AT` 이 **이 값보다 나중**이면 매매가 살아 있는 것이다.

---

### 9. 추가로 발견한 것 (이전과 직접 관계는 없지만 알아두실 것)

| # | 발견 | 근거 |
|---|---|---|
| 🚨 1 | **VPS `.env` 권한이 `-rw-r--r--` (644)** — 템플릿은 `chmod 600` 을 지시하고 있다. 루트 단독 서버라 실피해는 없지만 지시와 다르다 | VPS `ls -l .env` / `.env.production.template:7` (「3. chmod 600 .env」 — 초안의 `:4` 는 오기, 재확인함) |
| ⚠️ 2 | **VPS 에 `APP_ENV` 가 없어 `local` 로 운영 중** | `config.py:6` 기본값 |
| ⚠️ 3 | **`SENTRY_ENV=mainnet` 은 죽은 키** — 읽는 코드가 0곳 | `grep -rn "SENTRY_ENV\|sentry_env" backend/app/` 결과 없음 |
| ⚠️ 4 | 안전장치 4개가 사실상 해제 상태: `DAILY_LOSS_LIMIT_USDT=0`, `MIN_LIQUIDATION_DISTANCE_PCT=0`, `MAX_LEVERAGE=125`, `MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE=100` | VPS `.env` 실조회 |
| 🚨 5 | `ufw` 방화벽 **inactive** 인데 **redis 가 `6380:6379` = 0.0.0.0 바인딩이고 비밀번호가 없다**. compose 에 `requirepass` 가 없고 `REDIS_URL` 에도 비번이 없다 → 인터넷에서 `159.65.137.250:6380` 으로 **인증 없이 접속 가능**한 상태다. Redis 에는 mark price·kill-switch·재진입 대기 상태가 들어있다. 함께 0.0.0.0 인 것: api `8000`, prometheus `9090`. `127.0.0.1` 로 안전하게 묶인 것: db `5433`, grafana `3000` | VPS `ufw status` = inactive / VPS `docker-compose.yml:24,36,89` (2026-09-03 읽기 전용 재확인) |
| 🚨 5b | Grafana admin 비밀번호가 **`docker-compose.yml:98-99` 에 평문으로 깃에 커밋돼 있다** (사람이 정한, 사전에 나오는 약한 비번). **그리고 이 저장소는 public 이다** → 이미 **누구나 볼 수 있는 상태**다. `127.0.0.1:3000` 바인딩이라 인터넷에서 직접 두드릴 수는 없지만, 위험 5 로 서버에 발을 들이면 그대로 쓰인다. 🚨 **값은 이 문서에 옮겨 적지 않는다** — 필요하면 저장소의 해당 줄을 직접 볼 것. **조치: 비번을 바꾸고 `.env` 변수(`GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD}`)로 빼서 compose 에서 지울 것** | `backend/docker-compose.yml:98-99` / GitHub API `"visibility": "public"` |
| ⚠️ 6 | `WALLET_LIMIT_PCT` 는 `config.py` 에 정의가 없고 `os.environ` 으로만 읽힌다. `settings_sync_worker` 가 매시간 `.env` 와 대조해 불일치 알림을 보낸다 | `app/services/capital_calculator.py:38`, `app/workers/settings_sync_worker.py:35-49` |
| ✅ 7 | ~~VPS `docker-compose.yml` 은 4011 bytes, 저장소 것은 4147 bytes. **내용이 다르다**~~ → 🚨 **이 주장은 틀렸다. 검증에서 반증됨.** 두 파일은 **내용이 완전히 같다.** 136 바이트 차이는 전부 **줄바꿈(CRLF vs LF)** 이다 — 정확히 136줄 × 1바이트. LF 로 정규화한 SHA-256 이 양쪽 `5fefef90b795…` 로 **일치**한다. VPS `git status`/`git diff` 도 깨끗하고 HEAD 가 `ded22f3` 로 저장소와 같다. **배포 담당이 이걸 쫓아다닐 필요 없다.** | 로컬 `tr -d '\r' < docker-compose.yml \| sha256sum` = VPS `sha256sum docker-compose.yml` = `5fefef90b795…` / 양쪽 `wc -l` = 136 / VPS `git status --porcelain` 무출력 |
| ⚠️ 7b | 위 오진의 **원인이 더 중요하다**: 이 PC 는 `git config core.autocrlf=true` 다. 체크아웃되는 모든 텍스트 파일이 **CRLF** 로 저장된다(compose 파일에 CR 282개 실측). → ① **`ls -l` 바이트 수로 로컬↔VPS 를 비교하면 안 된다**(항상 다르게 보인다). 비교는 `tr -d '\r' \| sha256sum` 으로. ② 새 PC 에도 같은 설정을 넣어야 diff 지옥이 안 생긴다. ③ **`scp` 로 파일을 VPS 에 직접 올리면 CRLF 가 딸려간다** — `.sh` 는 `bad interpreter: ^M`, `.env` 는 값 끝에 `\r`. VPS 로 코드를 옮길 땐 반드시 `git pull` 을 쓸 것 | `git config --get core.autocrlf` = `true` / `od -c \| grep -o '\\r' \| wc -l` = 282 |
| ℹ️ 8 | GitHub Actions 는 `sajangnim_sasang_audit.yml` 하나뿐이고 `secrets.*` 를 **전혀 쓰지 않는다** → CI 쪽 비밀 이전 작업 없음 | `grep -rn "secrets\." .github/workflows/` 결과 없음 |
| ℹ️ 9 | 깃에 추적되는 env 파일은 `backend/.env.example` 과 `backend/.env.production.template` 둘뿐 (둘 다 값 없음) | `git ls-files \| grep .env` |

---

### 10. ⚠️ 확인 못 함

| 항목 | 왜 확인 못 했나 |
|---|---|
| **바이낸스 API 키의 IP 화이트리스트에 어떤 IP 가 등록돼 있는지** | 바이낸스 계정 로그인이 필요하고, 이 세션은 금융 계정에 접속하지 않는다. VPS 공인 IP 는 `159.65.137.250` 하나로 확인됐다. 메모리에는 「2 IP」 기록이 있어 사무실 IP 도 등록돼 있을 가능성이 있다 — **사장님이 직접 바이낸스에서 확인**하실 것 |
| **바이낸스 키의 권한 설정** (Futures ON / 출금 OFF 여부) | 위와 동일 |
| ~~**`DATABASE_URL` 이 로컬과 VPS 에서 정확히 어디가 다른지**~~ | ✅ **해결됨 (2026-09-03 재조사)** — 조각별 지문 비교로 **비밀번호만 다르다**는 것, 그리고 사무실 쪽 비밀번호는 이미 **만료(AUTH_FAIL)** 라는 것까지 실측했다. §4-1 |
| **`users.id=2` 가 누구인지** | 이메일에 `@` 가 없는 값이라 마스킹만 하고 내용을 보지 않았다 |
| **Neon 콘솔 로그인 자격증명** | 조사 범위 밖. 사장님만 접근 가능 |
| **§7-2 로컬 스택 기동 절차가 실제로 동작하는지** | 로컬 컨테이너를 띄우지 않았다 (운영 DB 오접속 위험 회피). `env_file: - .env` 가 박혀 있다는 사실·alembic 대상·모듈 경로는 파일로 확인했지만 **기동 자체는 미검증** |
| ~~**VPS `docker-compose.yml` 과 저장소 버전의 구체적 차이**~~ | ✅ **해결됨 — 차이가 없다.** LF 정규화 SHA-256 이 양쪽 `5fefef90b795…` 로 동일. 「내용이 다르다」던 초안 주장은 **CRLF 오인**이었다. §9-7 |
| **§3-3 (B) 키 회전 절차가 실제로 동작하는지** | 운영 DB 에 쓰는 작업이라 이번 세션(읽기 전용)에서 **`--dry-run` 조차 돌리지 않았다.** 스크립트 코드와 자체 docstring 을 읽고 정리한 것이다. `docker compose exec --env-file` 지원 여부도 미검증 |
| **§8 ⑦ 의 「매매 살아있음」 판정 기준값이 정상 범위인지** | 쿼리는 실행해 확인했다(`ACTIVE_STRATEGIES=24`, `LAST_ORDER_AT=2026-09-03 08:59 UTC`). 다만 **이 숫자가 「정상」인지 아닌지는 판단하지 않았다** — 매매 판단은 사장님 영역 |
| **DigitalOcean 웹 콘솔 root 비밀번호를 사장님이 알고 계신지** | 계정 접근이 필요해 확인 불가. **SSH 가 잠겼을 때의 유일한 탈출구**이므로 §7-3 대로 **이전 전에 미리 확인**하실 것 |
| **새 PC 의 공인 IP** | 아직 그 PC 가 없다. 바이낸스 화이트리스트·Neon IP 제한에 영향이 있으니 세팅 후 확인 |
