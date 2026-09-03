## VPS 운영환경과 배포 절차

조사 시각: 2026-09-03 09:00~09:05 UTC (KST 18:00~18:05)
조사 방법: SSH 읽기 전용 조회 + 저장소 파일 정독. **VPS 는 아무것도 변경하지 않았다.**

---

> ## 🚨🚨🚨 먼저 읽을 것 — 확인된 비밀 유출
>
> **운영 중인 `SECRET_KEY`(로그인 토큰 서명키)가 공개 GitHub 저장소에 평문으로 들어 있다.**
> 저장소 공개 여부, 커밋된 값, 그 값이 VPS 현재 값과 동일하다는 것(md5 일치), 그리고
> API 포트 8000 이 인터넷에 열려 있다는 것까지 **2026-09-03 에 전부 실측 확인했다.**
>
> 합치면 **누구든 로그인 토큰을 위조해 실자금 자동매매 API 에 접근할 수 있다.**
> 새 PC 이전보다 **이 조치가 먼저다.** → **10장의 「10-A」 절**(문서 내 `10-A` 로 검색)에
> 확인 근거·조치 순서·재검증 명령이 있다.
>
> ✅ 함께 확인한 것: Binance API 키·`ENCRYPTION_KEY`·텔레그램 토큰은 저장소에 커밋되지 **않았고**,
> 저장소에 있던 옛 Neon DB 비밀번호는 **이미 교체되어 있다.** (상세는 10-A 표)

---

### 0. 한눈에 보는 접속 정보

> 🚨 **새 PC 라면 이 문서를 순서대로 읽지 말고 아래 「9장. SSH 키」를 먼저 하라.**
> 1장부터 나오는 모든 명령이 SSH 접속을 전제한다. 키가 등록되기 전에는 **하나도 돌지 않는다.**
> 권장 순서: **9장(SSH 키) → 11장(첫날 체크리스트) → 1장(위험 3가지) → 나머지.**
>
> 새 PC 사전 준비 (셋 다 없으면 SSH 부터 막힌다):
> - **OpenSSH 클라이언트** — Git for Windows(Git Bash)에 포함. `ssh -V` 로 확인.
> - **`git`** — `git --version` 으로 확인.
> - 이 문서의 명령은 전부 **Git Bash** 기준이다. PowerShell 에서는 작은따옴표 인용이 달라 깨진다.
>
> 검증 (새 PC 에서):
>
> ```bash
> ssh -V && git --version
> ```

| 항목 | 값 | 근거 |
|---|---|---|
| VPS IP | `159.65.137.250` (DigitalOcean) | 과제 지시 + `ssh` 실접속 성공 |
| SSH 계정 | `root` | `ssh root@159.65.137.250` 성공 |
| SSH 인증 키 | `~/.ssh/id_ed25519` (현 PC) | `ssh -v` 출력: `Server accepts key: /c/Users/user/.ssh/id_ed25519` |
| 내 공개키 지문 | `SHA256:cbFAdSNFpCEZRnC/fxKsDmI0+4w2uTSUgls9XWbC4KI` | 동상 |
| VPS 호스트키 지문 | `SHA256:NYbjWuJ7a5pBfXRi9E9ys7yyDqWlaupLiuwH12Q2toM` (ED25519) | `ssh-keyscan \| ssh-keygen -lf -` |
| 앱 경로 | `/root/binance-auto-trader/backend` | `ls -la ~/binance-auto-trader/backend` |
| git remote | `https://github.com/herosys1-crypto/binance-auto-trader.git` | `git remote -v` (VPS) |
| VPS 브랜치 / HEAD | `main` / `ded22f3` | `git rev-parse --abbrev-ref HEAD`, `git log --oneline -3` |
| Docker / Compose | Docker 29.4.3 / Compose v5.1.3 | `docker --version`, `docker compose version` |
| Compose 프로젝트명 | **`backend`** (디렉터리명에서 자동) | `docker compose ls` → `NAME=backend` |
| DB | **외부 Neon** `ep-<masked>.ap-southeast-1.aws.neon.tech` / `neondb` | api 컨테이너에서 `DATABASE_URL` 파싱 (비번은 출력 안 함) |
| Alembic 리비전 | `0034_surge_ladder` (current == head, 최신) | `alembic current`, `alembic heads` |
| 웹 접속 | `https://159.65.137.250` (self-signed, 브라우저 경고 1회 무시) | `/etc/nginx/sites-enabled/trader` |
| 스펙 | 2 vCPU / 7.8 GiB RAM / 48G 디스크 (25G 사용, 51%) | `nproc`, `free -h`, `df -h /` |
| 가동 시간 | 114일 23시간 | `uptime` |

---

### 1. 🚨 가장 먼저 알아야 할 3가지 (전부 실측 확인)

#### 🚨 (1) `docker-compose.production.yml` 은 VPS 에 **있지만 적용되어 있지 않다**

먼저 **파일 위치를 헷갈리지 마라.** 이 오버라이드 파일은 `backend/` 안이 아니라 **저장소 루트**에 있다.

| 파일 | 위치 (저장소) | 위치 (VPS) |
|---|---|---|
| `docker-compose.yml` (기본) | `backend/docker-compose.yml` | `/root/binance-auto-trader/backend/docker-compose.yml` |
| `docker-compose.production.yml` (오버라이드) | **저장소 루트** | `/root/binance-auto-trader/docker-compose.production.yml` |

`docker-compose.production.yml` 은 「Neon 을 쓰니 로컬 db 를 끄고, 포트를 127.0.0.1 로 묶는다」는
운영용 오버라이드다. **파일은 VPS 에 git 으로 내려와 있다** (git 추적 파일이므로 당연하다).
문제는 **compose 가 이 파일을 읽지 않는다**는 것이다 — compose 는 실행 디렉터리(`backend/`)의
`docker-compose.yml` + `docker-compose.override.yml` 만 자동으로 읽는데, `docker-compose.override.yml` 이
**없다.**

두 디렉터리를 **모두** 확인해야 한다 (`backend/` 만 보면 「파일이 없다」는 오진에 빠진다):

```bash
ssh root@159.65.137.250 'ls -la ~/binance-auto-trader/docker-compose*.yml ~/binance-auto-trader/backend/docker-compose*.yml'
```

실제 출력 (2026-09-03 재확인):

```
-rw-r--r-- 1 root root 2778 May 31 19:03 /root/binance-auto-trader/docker-compose.production.yml
-rw-r--r-- 1 root root 4011 May 31 19:02 /root/binance-auto-trader/backend/docker-compose.yml
```

→ `backend/` 안에는 `docker-compose.yml` **하나뿐**이고 `docker-compose.override.yml` 은 **없다.**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ls'
```

```
NAME      STATUS         CONFIG FILES
backend   running(9)     /root/binance-auto-trader/backend/docker-compose.yml
```

`CONFIG FILES` 가 `docker-compose.yml` **하나뿐**이다 = **오버라이드가 실제로 안 먹고 있다.**
이것이 결정적 증거다 (파일 존재 여부가 아니라 **이 줄**을 봐야 한다). 그 결과가 아래 (2)(3)이다.

오버라이드를 적용하는 방법은 파일 머리말(`docker-compose.production.yml:4-10`)에 적혀 있다 —
`-f` 로 두 개를 같이 주거나, `backend/docker-compose.override.yml` 로 복사하는 것.
🚨 **둘 다 재시작을 동반하므로 실자금 영향이 있다. 사장님 판단 사항이며 나는 실행하지 않았다.**

> 근거: `docker-compose.production.yml:21-26` (db/db-backup 을 `profiles: ["disabled"]` 로 끔),
> `docker-compose.production.yml:30-31, 73-74, 82-83` (포트를 `127.0.0.1` 로 묶음),
> `docker-compose.production.yml:100-101` (grafana 비번을 `.env` 주입으로 권고)

#### 🚨 (2) 포트가 인터넷에 열려 있다 — Redis 는 **비밀번호도 없다**

내 PC(외부 인터넷)에서 TCP 연결을 시도한 결과:

| 포트 | 서비스 | 외부 접속 | 위험 |
|---|---|---|---|
| 443 | nginx (HTTPS) | OPEN | 정상 (의도된 것) |
| 80 | nginx → 443 리다이렉트 | OPEN | 정상 |
| 8000 | **api (평문 HTTP)** | **OPEN** | 🚨🚨🚨 HTTPS 강제를 우회해서 API 직접 호출 가능. **게다가 JWT 서명키(`SECRET_KEY`)가 공개 저장소에 유출되어 있어 인증까지 위조 가능 → 10-A. 이 둘이 합쳐지는 것이 현재 최대 위험이다.** |
| 9090 | **prometheus** | **OPEN** | 🚨 인증 없음, 운영 지표 전부 노출 |
| 6380 | **redis** | **OPEN** | 🚨🚨 **`requirepass` 가 비어 있음 = 무인증** |

Redis 무인증 확인 (VPS 내부에서):

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T redis redis-cli CONFIG GET requirepass'
```

→ 값이 **빈 문자열**로 돌아온다 (`cat -A` 로 확인: `requirepass$` 다음 줄이 `$` 뿐).

방화벽도 없다:

```bash
ssh root@159.65.137.250 'ufw status'
```

→ `Status: inactive`

🚨 **Redis 에는 IP ban 회로 차단기 상태(`api_backoff:ip:ban_until_ms`), weight 카운터, mark price 캐시,
재진입 대기 사유가 들어 있다.** 외부에서 이 키를 쓰면 자동매매 판정을 조작할 수 있다.
🚨 **이건 이번 이전(migration) 작업과 별개로 사장님이 판단해서 조치할 사안이다. 나는 VPS 를 읽기 전용으로
다뤘으므로 아무것도 바꾸지 않았다.** 조치하려면 오버라이드를 적용하거나(재시작 필요 = 실자금 영향) UFW/DO
클라우드 방화벽으로 6380·9090·8000 을 막는 방법이 있다.

⚠️ 확인 못 함: DigitalOcean **클라우드 방화벽**(VPS 바깥 계층)이 별도로 걸려 있는지는 DO 콘솔을 봐야 안다.
다만 위 TCP 연결이 **실제로 성립**했으므로 최소한 현재는 막혀 있지 않다.

#### 🚨 (3) `db-backup` 은 **빈 데이터베이스를 백업하고 있다** — 백업이 사실상 없다

`db-backup` 은 `POSTGRES_HOST: db` 로 **로컬 postgres 컨테이너**를 백업한다
(`backend/docker-compose.yml:119`). 그런데 앱은 Neon 을 쓰므로 로컬 `db` 는 **비어 있다.**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T db psql -U postgres -d binance_auto_trader -c "\dt"'
```

→ `Did not find any relations.` (테이블 0개)

백업 파일 크기가 그 증거다:

```bash
ssh root@159.65.137.250 'ls -la ~/binance-auto-trader/backend/db_backups/daily/'
```

```
-rw-r--r-- 1 root root  505 Aug 27 00:00 binance_auto_trader-20260827.sql.gz
-rw-r--r-- 1 root root  506 Sep  2 00:00 binance_auto_trader-20260902.sql.gz
-rw-r--r-- 4 root root  505 Sep  3 00:00 binance_auto_trader-20260903.sql.gz
```

**505 바이트.** 압축을 풀어 보면 `CREATE SCHEMA public;` 밖에 없다 = **데이터 0건.**
`db_backups` 폴더 전체가 76K 다.

🚨 **결론: 실거래 데이터(전략·주문·학습기록)의 백업은 VPS 에 존재하지 않는다. 오직 Neon 자체 백업/PITR 에만
의존하고 있다.** 이건 `docker-compose.production.yml:25-26` 이 의도한 바(「Neon 이 처리」)와 같지만,
**그 오버라이드가 적용되지 않아 db-backup 컨테이너가 매일 헛돌며 「백업이 돌고 있다」는 착시**를 만든다.
🚨 **새 PC 로 옮기기 전에 Neon 콘솔에서 백업/PITR 보존기간을 반드시 눈으로 확인할 것.**

⚠️ 확인 못 함: Neon 프로젝트의 백업 보존 정책(플랜별 PITR 기간)은 Neon 웹 콘솔에서만 볼 수 있어 확인하지 못했다.

---

### 2. `db` 컨테이너의 모순 — 죽은 것인가?

**답: 프로세스는 살아 있지만, 애플리케이션 관점에서는 죽었다. 쓰이지 않는다.**

| 질문 | 답 | 근거 |
|---|---|---|
| `db` 컨테이너가 떠 있나? | 예. `Up 3 weeks` | `docker compose ps` |
| 앱이 여기 붙나? | **아니오.** `DATABASE_URL` 은 Neon 을 가리킨다 | api 컨테이너에서 `DATABASE_URL` 호스트 파싱 → `...neon.tech` |
| 안에 데이터가 있나? | **없음. 테이블 0개** | `psql -c "\dt"` → `Did not find any relations.` |
| 그럼 왜 떠 있나? | 운영 오버라이드 파일은 VPS 에 **있지만 compose 가 안 읽는다** (위 1-(1)) | `docker compose ls` CONFIG FILES |
| 디스크는? | 볼륨 `backend_postgres_data` 47M (initdb 기본값 수준) | `du -sh /var/lib/docker/volumes/backend_postgres_data` |

🚨 **여기서 나는 반드시 함정을 경고해야 한다.**
`docker compose exec db psql ...` 로 조회하면 **빈 DB** 가 나오고, 그러면
「테이블이 없다 / 데이터가 날아갔다」는 **완전한 오진**에 이른다. 실제로 이 프로젝트는 이런 종류의
오진으로 여러 번 사고가 났다. **DB 조회는 반드시 api 컨테이너의 앱 세션으로 한다.**

❌ **절대 이렇게 조회하지 마라 (빈 DB 가 나온다):**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T db psql -U postgres -d binance_auto_trader -c "select count(*) from strategy_instances"'
```

✅ **반드시 이렇게 조회하라 (Neon 에 붙는다):**

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
print(db.execute(text(\"select count(*) from strategy_instances\")).scalar())
"'
```

- `PYTHONPATH=/app` 를 빼면 `ModuleNotFoundError` 가 난다.
- 쿼리가 하나라도 실패하면 세션이 오염되므로 다음 쿼리 전에 `db.rollback()` 을 부를 것.
- 여러 줄 스크립트는 로컬에 파일로 쓴 뒤 `scp` → `docker compose cp` → 실행이 안전하다.

---

### 3. 9개 서비스 정리표

정의: `backend/docker-compose.yml` (VPS 에서 실제 사용 중) /
**저장소 루트**의 `docker-compose.production.yml` (파일은 VPS 에 있으나 **compose 가 안 읽음** — 1-(1))

| # | 서비스 | 이미지 | 하는 일 | 명령 | 포트 (실제 VPS) | 볼륨 | depends_on | 실제 상태 |
|---|---|---|---|---|---|---|---|---|
| 1 | `db` | `postgres:16` | 🚨 **미사용.** 앱은 Neon 을 씀. 테이블 0개 | 기본 | `127.0.0.1:5433→5432` | `postgres_data` | — | Up 3 weeks (죽은 것과 같음) |
| 2 | `db-backup` | `prodrigestivill/postgres-backup-local:16` | 🚨 **빈 `db` 를 매일 백업** (@daily, 일7/주4/월6 보관) | `/init.sh` | 미노출 (`ps` 표시는 `5432/tcp`, 헬스체크는 내부 8080) | `./db_backups:/backups` | `db` | Up 3 weeks (healthy) — 하지만 무의미 |
| 3 | `api` | `backend-api` (로컬 빌드) | FastAPI 웹서버 + UI. nginx 가 여기로 프록시 | `uvicorn app.main:app --host 0.0.0.0 --port 8000` | 🚨 **`0.0.0.0:8000`** | `.:/app` (bind) | `db`, `redis` | Up 9 min, 재시작 0 |
| 4 | `scheduler` | `backend-scheduler` | **자동매매 두뇌.** APScheduler 로 워커 수십 개를 주기 실행 (진입/단계/TP·SL/재진입/피라미딩) | `python -m app.workers.scheduler_runner` | 내부 8000 (미노출) | `.:/app` | `db`, `redis` | Up 9 min, **재시작 4회** |
| 5 | `user-stream` | `backend-user-stream` | Binance User Data Stream(WS) 구독 — 체결/포지션 이벤트 수신 | `python -m app.workers.run_user_stream` | 내부 8000 | `.:/app` | `db`, `redis` | Up 22 hours, 재시작 0 |
| 6 | `mark-price-stream` | `backend-mark-price-stream` | markPrice WS 를 1초 주기로 Redis 캐시 갱신 → 라이브 PNL 정확도 (±0.1 USDT) | `python -m app.workers.mark_price_stream_consumer` | 내부 8000 | `.:/app` | `db`, `redis` | Up 8 days, 재시작 0 |
| 7 | `redis` | `redis:7` | 회로차단기 상태 / weight 카운터 / markPrice 캐시 / 대기사유 | 기본 | 🚨 **`0.0.0.0:6380→6379` 무인증** | 없음 (영속화 X) | — | Up 3 weeks, 재시작 1 |
| 8 | `prometheus` | `prom/prometheus:latest` | api `/metrics` 수집 + 알림 규칙 | 기본 | 🚨 **`0.0.0.0:9090`** | `./deploy/prometheus/*.yml` (2개, ro 아님) | `api` | Up 3 weeks |
| 9 | `grafana` | `grafana/grafana:latest` | 대시보드. admin 계정, 익명 접속 차단 | 기본 | `127.0.0.1:3000` (안전) | `./deploy/grafana/provisioning`, `./deploy/grafana/dashboards` | `prometheus` | Up 3 weeks |

> 근거: `backend/docker-compose.yml:1-136` 전체, VPS `docker compose ps -a` 및
> `docker inspect --format "{{.Name}} started={{.State.StartedAt}} restarts={{.RestartCount}}"`

🚨 **`grafana` 의 admin 비밀번호가 `backend/docker-compose.yml:99` 에 평문으로 커밋되어 있다.**
(값은 여기 옮기지 않는다.) 3000 포트는 127.0.0.1 로만 열려 있어 당장 외부 위험은 아니지만,
`docker-compose.production.yml:100-101` 은 이 값을 `.env` 주입으로 바꾸라고 주석으로 권고한다.

**앱 코드를 실행하는 컨테이너는 4개**(`api`, `scheduler`, `user-stream`, `mark-price-stream`)이며,
전부 `.:/app` **bind mount** 를 쓴다 → **`git pull` 후 재시작만으로 새 코드가 반영된다(재빌드 불필요).**
`backend/Dockerfile:17` 의 `COPY . /app` 은 bind mount 에 덮여서 무의미해진다.

#### 새 PC 에서 각 화면에 접속하는 법

| 화면 | 새 PC 에서 여는 법 |
|---|---|
| **웹 UI (본체)** | 브라우저에서 `https://159.65.137.250` — self-signed 인증서라 경고가 뜬다. 「고급 → 계속 진행」 1회 |
| **Grafana** | `127.0.0.1:3000` 이라 **직접 못 연다. SSH 터널이 필요하다** ↓ |
| **Prometheus** | `http://159.65.137.250:9090` 으로 열리긴 하지만 (1-(2)의 보안 문제) **터널로 여는 편이 낫다** ↓ |

SSH 터널 (새 PC 에서 실행, 이 창은 **켜 둔 채로** 브라우저를 연다):

```bash
ssh -N -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 root@159.65.137.250
```

그 다음 브라우저에서 `http://localhost:3000` (Grafana) / `http://localhost:9090` (Prometheus).
Grafana 로그인 계정은 `admin` 이고 **비밀번호는 `backend/docker-compose.yml:99` 에 평문으로 있다**
(값은 이 문서에 옮기지 않는다 — 파일을 직접 볼 것). 터널은 `Ctrl+C` 로 끊는다.

⚠️ nginx 는 `/etc/nginx/sites-enabled/trader` 에서 80 → 443 리다이렉트 후
`proxy_pass http://127.0.0.1:8000` 으로 api 에 넘긴다 (2026-09-03 실측 확인).
즉 **웹 UI 는 nginx 를 거치고, Grafana/Prometheus 는 nginx 를 안 거친다.**

---

### 4. 현재 VPS 실측 상태 (2026-09-03 09:04 UTC)

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ps'
```

```
NAME                                    SERVICE             STATUS
binance-auto-trader-api                 api                 Up 9 minutes
binance-auto-trader-db                  db                  Up 3 weeks
binance-auto-trader-db-backup           db-backup           Up 3 weeks (healthy)
binance-auto-trader-grafana             grafana             Up 3 weeks
binance-auto-trader-mark-price-stream   mark-price-stream   Up 8 days
binance-auto-trader-prometheus          prometheus          Up 3 weeks
binance-auto-trader-redis               redis               Up 3 weeks
binance-auto-trader-scheduler           scheduler           Up 9 minutes
binance-auto-trader-user-stream         user-stream         Up 22 hours
```

재시작 횟수 조회:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'docker inspect --format "{{.Name}} started={{.State.StartedAt}} restarts={{.RestartCount}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}}" $(docker ps -aq)'
```

| 컨테이너 | 시작 시각 (UTC) | 재시작 | 비고 |
|---|---|---|---|
| api | 2026-09-03 08:51:26 | 0 | 오늘 배포 |
| scheduler | 2026-09-03 08:51:57 | **4** | 마지막 종료코드 0, OOM 아님 → 사장님의 수동 배포 재시작으로 보임 (⚠️ 단정 못 함) |
| user-stream | 2026-09-02 11:13:58 | 0 | |
| mark-price-stream | 2026-08-26 00:27:34 | 0 | |
| redis | 2026-08-12 11:31:18 | 1 | |
| db / db-backup / prometheus / grafana | 2026-08-12 03:00 | 0 | |

헬스 확인:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'curl -s -m 10 http://127.0.0.1:8000/health'
```

→ `{"status":"ok"}`

⚠️ **부하 주의**: `uptime` 이 load average `6.16 / 3.99 / 3.67` 인데 **vCPU 는 2개**다.
15분 평균 3.67 = 코어 대비 약 180% 로 **지속적으로 과부하**다. 메모리는 여유(7.8Gi 중 1.6Gi 사용).
⚠️ 원인은 확인하지 못했다 (스캔 워커 밀집이 유력하나 측정 안 함).

---

### 5. 🚨 서비스명 함정 — `api` / `scheduler` 이지 `backend` 가 **아니다**

메모리의 경고를 **확인했고, 사실이다.** 그리고 헷갈리는 진짜 이유까지 찾았다.

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose config --services'
```

```
redis
db
scheduler
user-stream
api
db-backup
prometheus
grafana
mark-price-stream
```

**`backend` 라는 서비스는 없다.** 그런데 왜 자꾸 `backend` 를 치게 되는가:

| 무엇 | 이름 | 왜 헷갈리나 |
|---|---|---|
| Compose **프로젝트**명 | `backend` | 디렉터리명이 `backend` 라서 자동으로 붙는다 (`docker compose ls` → `NAME backend`) |
| **이미지**명 | `backend-api`, `backend-scheduler`, `backend-user-stream`, `backend-mark-price-stream` | 프로젝트명 접두사가 붙어서 `docker compose ps` 의 IMAGE 열에 `backend-` 가 보인다 |
| **컨테이너**명 | `binance-auto-trader-api` 등 | `container_name:` 으로 고정 (`backend/docker-compose.yml:4,20,28,...`) |
| **서비스**명 (compose 명령에 쓰는 것) | **`api`, `scheduler`, ...** | ← 이것만이 `docker compose restart <X>` 에 유효 |

❌ **틀린 명령 (에러):**

```bash
docker compose restart backend
```

✅ **맞는 명령:**

```bash
docker compose restart api scheduler
```

또한 **systemd 서비스는 존재하지 않는다.** `systemctl list-units | grep -iE "trader|binance"` 는
아무것도 반환하지 않았다. 즉 `systemctl restart api` 같은 것도 없다. **전부 docker compose 다.**

---

### 6. 배포 절차 (정확한 명령)

전제: 배포는 **수동 SSH** 다. GitHub Actions 에 배포 워크플로가 **없다**
(`.github/workflows/` 에는 `sajangnim_sasang_audit.yml` 하나뿐이고 SSH/deploy 문자열이 없다).
VPS 에 `crontab -l` 도 없고 배포 스크립트(`*.sh`)도 없다.

🚨 **배포는 실자금이 도는 자동매매를 재시작한다. 사장님 판단으로만 실행한다.**

#### 🚨🚨 6-0. 배포 전에 반드시 알아야 할 것 — **손절은 거래소가 아니라 `scheduler` 가 한다**

`backend/app/integrations/binance/futures_trade.py:75, 102` 에 거래소측 손절/익절 주문을 넣는
`place_stop_market_order` / `place_take_profit_market_order` 가 **정의되어 있지만, 호출하는 곳이
`backend/app` 안에 한 곳도 없다.**

```bash
# 실행 결과: 아무것도 안 나온다 = 호출처 0곳
grep -rn "stop_market\|take_profit_market" backend/app --include=*.py | grep -v futures_trade.py
grep -rn "STOP_MARKET" backend/app --include=*.py     # futures_trade.py 한 파일만
```

🚨 **결론: 포지션에 걸린 거래소측 스톱 주문이 없다. 손절·익절·강제청산은 전부 `scheduler` 컨테이너의
워커가 주기적으로 판정해서 시장가로 낸다.**

➡️ **`scheduler` 가 꺼져 있는 동안 모든 포지션은 손절이 전혀 없는 무방비 상태다.**
`restart` 는 수 초지만 `--build` 는 수 분, `down` 은 사장님이 다시 켤 때까지다.

**따라서 배포는 반드시:**
1. 포지션이 적고 변동성이 낮은 시간에 한다.
2. 재시작 후 **6-6 의 확인을 끝까지 한다.** 「명령을 쳤다」로 끝내지 않는다.
3. 🚨 큰 미실현 손실 포지션을 들고 있을 때는 배포를 **미룬다.**

⚠️ 확인 못 함: 과거에 수동으로/거래소 앱으로 걸어 둔 스톱 주문이 남아 있을 가능성은 배제 못 한다.
위 판정은 **이 저장소 코드가 스톱 주문을 걸지 않는다**는 사실까지만이다.

#### 6-1. 표준 배포 (코드만 바뀐 경우) — 가장 흔한 경우

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250
```

🚨 **① 되돌릴 지점을 먼저 적어 둔다 (이걸 안 하면 롤백이 불가능하다).**

```bash
cd ~/binance-auto-trader/backend && echo "ROLLBACK_TO=$(git rev-parse HEAD)  at $(date -u +%FT%TZ)" | tee -a ~/deploy_rollback_points.txt
```

🚨 **② IP ban 중이 아닌지 확인한다.** ban 중에 재시작하면 회로차단기 상태가 초기화되어
2026-08-26 사고(스스로 ban 을 연장)가 재현될 수 있다 (→ 8장, 6-5).

```bash
cd ~/binance-auto-trader/backend && docker compose exec -T redis redis-cli GET "api_backoff:ip:ban_until_ms"
```

→ **빈 값이어야 배포한다.** 숫자가 나오면 그 시각이 지날 때까지 **배포를 미룬다.**

**③ 받아온다.** 🚨 `git pull` 이 아니라 `git pull --ff-only` 를 쓴다.

```bash
cd ~/binance-auto-trader/backend && git pull --ff-only origin main
```

- 🚨 **왜 `--ff-only` 인가**: 그냥 `git pull` 은 VPS 쪽 이력이 갈라져 있으면 **자동 머지**를 시도한다.
  충돌이 나면 VPS 작업 트리에 **충돌 마커가 박힌 반쪽짜리 `.py` 파일**이 남는데,
  bind mount 라서 **그게 곧바로 실행 중인 코드가 된다.** `--ff-only` 는 이 경우 아무것도
  건드리지 않고 즉시 실패한다 = 안전하다.
  (VPS 는 지금까지도 `pull --ff-only` / `pull -q` 로만 갱신돼 왔다 — `git reflog` 로 확인함.)
- ⚠️ `--ff-only` 가 실패하면 **거기서 멈추고 원인을 확인한다.** 🚨 아래는 절대 하지 마라:
  `git stash` / `git stash pop` / `git reset --hard` / `git clean -fd` / `git push -f` — 이유는 6-5.

**④ 재시작한다.**

```bash
cd ~/binance-auto-trader/backend && docker compose restart api scheduler
```

🚨 **③과 ④ 사이를 길게 두지 마라.** bind mount 라서 `git pull` 이 끝나는 **순간** 디스크 코드는
새 코드다. 그런데 프로세스는 아직 옛 코드로 돌고 있고, 이 프로젝트는 **함수 안 `import`** 를 여러 곳에서
쓴다 → 그 함수가 처음 호출되는 순간 **새 모듈이 옛 프로세스에 섞여 들어온다.**
즉 `pull` 직후는 **옛 코드 + 새 코드가 뒤섞인 상태**다. 실자금이 이 상태로 오래 돌면 안 된다.
③④를 한 줄로 붙여서 실행하는 것이 가장 안전하다:

```bash
cd ~/binance-auto-trader/backend && git pull --ff-only origin main && docker compose restart api scheduler
```

**⑤ 되돌리는 법 (배포 후 이상하면).**

```bash
cd ~/binance-auto-trader/backend && tail -3 ~/deploy_rollback_points.txt
```

```bash
cd ~/binance-auto-trader/backend && git checkout <위에서_적어둔_해시> && docker compose restart api scheduler
```

- `git checkout <해시>` 는 detached HEAD 가 된다(정상). 나중에 복귀는 `git checkout main`.
- 🚨 **`git reset --hard` 를 쓰지 마라.** 되돌아가는 효과는 같지만, 손이 미끄러져 대상을 잘못 적으면
  복구 지점이 사라진다. `checkout` 은 이력을 안 지운다.
- 🚨 **마이그레이션을 이미 돌렸다면 코드만 되돌리는 것으로는 부족하다** → 6-3 의 경고를 볼 것.
- 🚨 **되돌린 뒤에도 6-6 의 「배포 후 3분 확인」을 반드시 한다.** 롤백도 재시작이다.

##### 6-1 보충 — 왜 재빌드가 필요 없나 / 무엇을 재시작하나

- `.:/app` bind mount 덕분에 **재빌드가 필요 없다.** `git pull` 이 호스트 파일을 갱신하면
  컨테이너 안 `/app` 이 그대로 바뀐다. 파이썬 프로세스만 재시작하면 반영된다.
- 🚨 **`docker compose restart` 는 `.env` 변경을 반영하지 않는다.** `restart` 는 기존 컨테이너를
  껐다 켜기만 하고 환경변수는 **컨테이너 생성 시점**에 박힌다. `.env` 를 고쳤다면 **재생성**해야 한다:

  ```bash
  cd ~/binance-auto-trader/backend && docker compose up -d --force-recreate api scheduler user-stream mark-price-stream
  ```

  (`.py` 코드만 바뀐 경우엔 `restart` 로 충분하다 — bind mount 라서.)
  🚨 **서비스명 4개를 반드시 붙여라.** `--force-recreate` 만 쓰고 서비스명을 빼면 `redis` 까지
  재생성되어 IP ban 회로차단기가 지워진다 (→ 6-5).
  🚨 재생성은 `restart` 보다 오래 걸린다 = **손절 없는 구간이 그만큼 길다** (→ 6-0).
  🚨 **`.env` 를 고치기 전에 원본을 복사해 둘 것** — git 에 없어서 되돌릴 방법이 그것뿐이다:
  `cp .env .env.bak.$(date +%F-%H%M)` (🚨 이 백업 파일도 비밀 값이 들어 있다. 저장소 밖에 두고,
  `.gitignore` 가 `backend/.env.*` 를 막지만 방심하지 말 것 → 10장).
- 🚨 **`backend/.env` 가 없으면 compose 자체가 안 뜬다.** 9개 서비스 중 앱 4개가
  `env_file: - .env` 를 쓴다 (`backend/docker-compose.yml:30-31` 등). git 에 없는 파일이므로
  저장소만 clone 해서는 절대 실행되지 않는다 → 10장 참조.
- 🚨 **어떤 컨테이너를 재시작해야 하는지는 바뀐 파일에 달렸다:**

| 바뀐 것 | 재시작해야 할 서비스 |
|---|---|
| `app/api/**`, `app/static/**` (UI), `app/schemas/**` | `api` |
| `app/workers/**`, `app/services/**`, `app/agents/**` | `scheduler` (대부분 `api` 도 같이 쓰므로 **둘 다** 권장) |
| `app/integrations/binance/**`, `app/core/**` | **`api scheduler user-stream mark-price-stream` 전부** |
| 잘 모르겠으면 | 아래 6-2 의 전체 재시작 |

#### 6-2. 앱 4개 전부 재시작 (판단이 안 설 때)

```bash
cd ~/binance-auto-trader/backend && docker compose restart api scheduler user-stream mark-price-stream
```

- 🚨 **재시작 전에 6-1 의 ①(롤백 지점 기록)과 ②(IP ban 확인)를 먼저 한다.** 6-2 만 따로 쓰지 마라.
- 🚨 `restart` 는 서비스명을 **명시한 것만** 건드린다. `redis` 를 넣지 마라 (→ 6-5).
- 🚨 재시작 직후 `scheduler` 가 뜨는 데 실패하면 **손절이 계속 없는 상태**다 (→ 6-0).
  반드시 6-6 으로 **네 컨테이너가 다 살아났는지** 확인한다.

#### 6-3. 마이그레이션이 있는 경우 (alembic)

🚨🚨 **먼저 — alembic 은 새 PC 에서 절대 돌리지 마라. 반드시 VPS 의 `api` 컨테이너 안에서만 돌린다.**

`backend/alembic/env.py:27-30` 은 **환경변수 `DATABASE_URL` 이 있을 때만** 그것을 쓰고,
없으면 `backend/alembic.ini:4` 의 기본값(`localhost:5432` 의 로컬 postgres)으로 **조용히** 넘어간다.

| 어디서 돌리나 | 실제로 어디에 붙나 | 결과 |
|---|---|---|
| VPS `api` 컨테이너 (`env_file: .env`) | ✅ Neon (실데이터) | 정상. **이것만 쓴다** |
| 새 PC, `DATABASE_URL` 없이 | 🚨 `localhost:5432` — 엉뚱한/없는 DB | `current` 가 **거짓말**을 한다. 「미적용이 있다」고 착각해 잘못된 판단을 한다 |
| 새 PC, VPS 에서 복사한 `.env` 로 | 🚨🚨 **운영 Neon** | **노트북에서 실데이터 스키마를 바꾼다.** 절대 금지 |

🚨 **에러가 안 난다는 점이 가장 위험하다.** 조용히 다른 DB 를 보고 그럴듯한 답을 낸다.

**언제 도는가**: `backend/alembic/versions/` 에 **새 파일이 추가되었을 때만.**

✅ **가장 확실한 판정법 — `current` 와 `heads` 를 비교한다.** (git 이력에 의존하지 않는다)

```bash
cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api alembic current && docker compose exec -T -e PYTHONPATH=/app api alembic heads
```

⚠️ alembic 은 `INFO [alembic.runtime.migration] ...` 줄을 **stderr 로** 먼저 뱉는다. 그건 정상이고
**맨 마지막 줄**의 리비전 ID 만 보면 된다. 두 값이 **같으면 돌릴 것이 없다.**

2026-09-03 실행 결과:

```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
0034_surge_ladder (head)      ← current
0034_surge_ladder (head)      ← heads
```

→ 같다 = **미적용 마이그레이션 없음.**

(참고) `git pull` 로 새 마이그레이션 파일이 왔는지 보고 싶으면:

```bash
cd ~/binance-auto-trader/backend && git diff --name-only "HEAD@{1}" HEAD -- alembic/versions/
```

⚠️ 이건 **reflog 에 의존**한다. 새로 clone 했거나 reflog 가 만료됐으면 `HEAD@{1}` 이 없어서 에러가 난다.
그럴 땐 위의 `current` vs `heads` 비교를 쓸 것. (VPS 는 reflog 635개 보유 = 현재는 동작함)

`current` 와 `heads` 가 **다를 때만** 아래를 실행한다:

```bash
cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api alembic upgrade head
```

그 다음에 6-1 의 재시작을 한다. **순서는 `git pull` → `alembic upgrade head` → `restart` 다.**

🚨 **이 순서에는 피할 수 없는 위험 구간이 있다.** `git pull` 이 끝난 순간 디스크는 새 코드인데
스키마는 아직 옛날이다 (bind mount + 함수 안 `import` → 6-1 ③ 참조). 즉
**`pull` 과 `upgrade head` 사이에는 「새 코드 + 옛 스키마」로 실거래가 돈다.**
🚨 **그러므로 마이그레이션이 있는 배포는 세 명령을 한 줄로 붙여서 간격을 최소화한다:**

```bash
cd ~/binance-auto-trader/backend && git pull --ff-only origin main && docker compose exec -T -e PYTHONPATH=/app api alembic upgrade head && docker compose restart api scheduler user-stream mark-price-stream
```

(`&&` 라서 앞이 실패하면 뒤가 안 돈다 = 반쯤 배포되는 사고를 막는다.)

🚨 **alembic 은 Neon(실데이터)을 건드린다. 되돌리기(`alembic downgrade -1`)는 데이터 손실 가능성이 있다.**
🚨 alembic 을 돌리기 전에 Neon 콘솔에서 **브랜치/스냅샷을 하나 떠 두는 것이 안전하다** (VPS 백업은 앞서
설명했듯 비어 있어서 도움이 안 된다).

##### 🚨 마이그레이션을 돌린 뒤 롤백하는 법 (6-1 ⑤ 만으로는 부족하다)

`alembic upgrade` 는 **Neon 의 실제 스키마를 바꾼다.** 코드만 옛 커밋으로 되돌리면
**옛 코드 + 새 스키마** 조합이 된다.

| 상황 | 어떻게 하나 |
|---|---|
| 새 마이그레이션이 **컬럼/테이블 추가만** 한 경우 | ✅ **코드만 되돌리면 된다.** 옛 코드는 새 컬럼을 안 볼 뿐이다. `downgrade` 를 돌리지 마라 |
| 새 마이그레이션이 **컬럼/테이블 삭제·이름변경·타입변경**을 한 경우 | 🚨 코드만 되돌리면 옛 코드가 없어진 컬럼을 찾아 **전 API 500** 이 날 수 있다. 이때만 `downgrade` 를 고려하되 **Neon 스냅샷을 먼저 떠 둔 경우에만** |

🚨 **그래서 순서는 「Neon 스냅샷 → `alembic upgrade` 」다.** 스냅샷 없이 `upgrade` 를 돌리면
되돌릴 방법이 사실상 없다. `db_backups/` 는 비어 있어서 도움이 안 된다 (→ 1-(3)).

🚨 **마이그레이션 내용을 먼저 눈으로 읽어라.** 어느 쪽인지 30초면 안다:

```bash
cd ~/binance-auto-trader/backend && grep -nE "drop_column|drop_table|drop_constraint|alter_column" alembic/versions/00XX_*.py
```

→ 아무것도 안 나오면 「추가만」 = 롤백이 쉬운 쪽이다.

**현재 리비전 (2026-09-03 실측)**:

```
current: 0034_surge_ladder (head)
heads:   0034_surge_ladder (head)
```

→ **최신이며 미적용 마이그레이션 없음.** 대응 파일: `backend/alembic/versions/0034_surge_ladder_state.py`

#### 6-4. `requirements.txt` 가 바뀐 경우 (재빌드 필요)

bind mount 는 파이썬 **소스**만 덮는다. 설치된 패키지는 이미지 안에 있으므로 재빌드해야 한다.

```bash
cd ~/binance-auto-trader/backend && docker compose up -d --build api scheduler user-stream mark-price-stream
```

🚨 이 명령은 컨테이너를 **재생성**한다. 빌드 시간(수 분) 동안 자동매매가 멈춘다.
🚨🚨 **그 수 분 동안 모든 포지션에 손절이 없다** (→ 6-0). 이것이 6-4 의 가장 큰 위험이다.
🚨 프로젝트 이력에 **「mainnet deps 핀 필수」**(fastapi 드리프트로 전 API 500 사고) 교훈이 있다.
재빌드는 requirements 가 핀되어 있는지 확인한 뒤에 한다.

**6-4 를 안전하게 하는 순서:**

1. 🚨 **먼저 이미지를 만들어 두고, 그 다음에 갈아 끼운다.** 이러면 정지 시간이 수 분 → 수 초가 된다.

   ```bash
   cd ~/binance-auto-trader/backend && docker compose build api scheduler user-stream mark-price-stream
   ```

   (`build` 만 하는 동안에는 **현재 컨테이너가 계속 돌아간다** = 손절이 살아 있다.)

2. 빌드가 **성공한 것을 확인한 뒤에만** 갈아 끼운다.

   ```bash
   cd ~/binance-auto-trader/backend && docker compose up -d api scheduler user-stream mark-price-stream
   ```

3. 🚨 **되돌리는 법**: 재빌드 롤백은 `git checkout <해시>` 만으로는 안 된다. **패키지가 이미지 안에
   있으므로 이미지도 되돌려야 한다.** 옛 코드로 체크아웃한 뒤 **다시 빌드**해야 한다.

   ```bash
   cd ~/binance-auto-trader/backend && git checkout <ROLLBACK_TO_해시> && docker compose build api scheduler user-stream mark-price-stream && docker compose up -d api scheduler user-stream mark-price-stream
   ```

   ⚠️ 이때도 되돌리는 빌드에 수 분이 걸리므로, **1번처럼 build 를 먼저 끝내고 up 을 나중에** 한다.

🚨 **`up -d` 는 `docker-compose.yml` 이 바뀌었으면 해당 서비스를 재생성한다.** `git pull` 로
compose 파일이 바뀐 뒤 서비스명을 빠뜨리고 `docker compose up -d` (인자 없이) 를 치면
**`redis` 까지 재생성되어 IP ban 회로차단기 상태가 통째로 지워진다** (→ 6-5). 서비스명을 항상 명시할 것.

#### 6-5. 🚨 절대 쓰면 안 되는 명령 (외우지 말고 **배포 전에 이 표를 다시 볼 것**)

**A. docker 계열**

```bash
# ❌❌ 절대 금지 — 볼륨까지 삭제
docker compose down -v
```

```bash
# ❌ 위험 — 전체 정지. 자동매매가 포지션을 든 채로 멈추고, 그동안 손절이 아예 없다 (6-0)
docker compose down
```

```bash
# ❌ 위험 — IP ban 중이면 회로차단기가 통째로 지워진다 (아래 설명)
docker compose restart redis
docker compose up -d               # ← 서비스명 없이 치면 바뀐 서비스를 전부 재생성
redis-cli FLUSHALL
```

```bash
# ❌ 위험 — 안 쓰는 것처럼 보이는 이미지/볼륨을 지운다. 롤백용 옛 이미지가 날아간다
docker system prune -a
docker volume prune
```

🚨 **왜 `redis` 재시작이 위험한가**: `redis` 서비스에는 **볼륨이 없다**
(`backend/docker-compose.yml:18-24` — `db` 와 달리 `volumes:` 절 자체가 없다) = **영속화 0.**
그런데 IP ban 회로차단기는 **프로세스 메모리(1차) + Redis(2차)** 에만 산다
(`client.py:53-59, 224, 237-253`). 즉 **redis 를 재시작하면 「지금 ban 중」이라는 사실이 사라진다.**
그 상태에서 워커들이 정상 속도로 Binance 를 두드리면 **ban 기간 중의 요청이 다시 카운트되어
ban 이 연장된다** — 2026-08-26 사고와 정확히 같은 경로다 (→ 8-1).

**B. git 계열 — 🚨 이 저장소는 worktree 를 공유한다**

```bash
# ❌❌ 절대 금지 — worktree 공유 저장소에서 다른 작업의 변경을 통째로 삼키고 되돌리기 어렵다
git stash
git stash pop
```

```bash
# ❌❌ 절대 금지 — VPS 에 사장님이 만든 추적되지 않는 조사 스크립트 31개가 있다. 전부 지워진다
git clean -fd
git clean -fdx
```

```bash
# ❌ 위험 — 복구 지점이 사라진다. 되돌릴 땐 6-1 ⑤ 의 git checkout <해시> 를 쓸 것
git reset --hard
git reset --hard origin/main
```

```bash
# ❌❌ 절대 금지 — 원격 이력을 덮어쓴다. 다른 PC/worktree 의 작업이 사라진다
git push -f
git push --force
```

🚨 **`git pull` 이 실패했을 때 `stash` 로 밀어내고 싶어지는 순간이 가장 위험하다.**
VPS 는 지금 **추적 파일 수정이 0건, 추적되지 않는 파일이 31개**다 (`git status --porcelain` 실측).
이 상태에서 `--ff-only` 가 실패한다면 그건 「로컬 변경」때문이 아니라 **이력이 갈라진 것**이므로
`stash` 로 해결되지 않는다. **멈추고 원인을 먼저 본다.**

**C. 애플리케이션 계열**

- 🚨 `clear_ip_ban()` — **실제 ban 중에 쓰면 ban 이 연장된다** (`client.py:306-308` 주석).
- 🚨 `alembic downgrade` — Neon 실데이터에서 컬럼/테이블이 삭제될 수 있다 (→ 6-3).

`OPERATIONS.md:328-331` 에 `down -v` 예시가 있는데 이는 **로컬 개발 초기화**용이다.
운영 VPS 에서 쓰면 안 된다.

#### 6-6. 배포가 실제로 됐는지 판정하는 법

🚨 **`docker exec ... grep` 으로 코드를 확인하는 것은 「디스크」를 보는 것이다.**
bind mount 라서 `git pull` 만 해도 파일은 이미 새 코드다 — **재시작하지 않았어도 grep 은 통과한다.**
반드시 **프로세스 시작 시각 vs 파일 수정 시각**으로 판정한다.

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && echo -n "api   start: " && docker inspect --format "{{.State.StartedAt}}" binance-auto-trader-api && echo -n "sched start: " && docker inspect --format "{{.State.StartedAt}}" binance-auto-trader-scheduler && echo "newest .py:" && find app -name "*.py" -printf "%TY-%Tm-%TdT%TH:%TM %p\n" | sort -r | head -3'
```

2026-09-03 실행 결과 (**정상 배포된 예시**):

```
api   start: 2026-09-03T08:51:26.932467002Z
sched start: 2026-09-03T08:51:57.679240765Z
newest .py:
2026-09-03T08:51 app/services/support_score.py
2026-09-03T08:51 app/services/execution_service.py
2026-09-03T08:25 app/services/tp_sl_orchestrator.py
```

파일 최신 수정(08:51) **≤** 프로세스 시작(08:51:26 / 08:51:57) → **반영됨.**
반대로 파일이 프로세스 시작보다 **나중**이면 → **아직 안 올라간 코드다.**

⚠️ VPS 작업 디렉터리에는 사장님이 조사용으로 만든 추적되지 않는 `.py` 스크립트가 20개 이상 있다
(`git status --porcelain` 실측 = **추적 파일 수정 0건 / 추적되지 않는 파일 31개**).
`git pull` 시 충돌을 일으키진 않지만 `find app -name "*.py"` 결과에는 섞이지 않는다
(전부 `backend/` 직속이라 `app/` 밖). 🚨 **`git clean` 을 쓰면 이 31개가 전부 사라진다** (→ 6-5).

##### 🚨 배포 후 3분 확인 — 「명령을 쳤다」로 끝내지 마라

손절이 `scheduler` 안에 있으므로 (→ 6-0), **재시작이 반쯤 실패한 것을 모르고 지나가는 것**이
이 시스템에서 가장 비싼 실수다. 배포 직후 아래를 순서대로 본다.

**① 네 컨테이너가 다 살아 있고 크래시 루프가 아닌지**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ps api scheduler user-stream mark-price-stream'
```

→ 넷 다 `Up ...` 이어야 한다. `Restarting` / `Exited` 가 하나라도 있으면 **실패다.**

⚠️ `docker compose ps` 는 재시작 **횟수**를 보여주지 않는다. 크래시 루프는 아래로 본다
(같은 명령을 30초 간격으로 두 번 쳐서 `restarts` 숫자가 **늘어나면** 루프다):

```bash
ssh root@159.65.137.250 'for c in api scheduler user-stream mark-price-stream; do docker inspect --format "{{.Name}} restarts={{.RestartCount}} status={{.State.Status}}" binance-auto-trader-$c; done'
```

**② 부팅 중 예외로 죽지 않았는지**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 5m api scheduler | grep -E "Traceback|ImportError|ModuleNotFoundError|ProgrammingError|UndefinedColumn|CRITICAL"'
```

→ 🚨 `UndefinedColumn` / `ProgrammingError` 가 보이면 **마이그레이션을 빠뜨린 것이다** → 6-3.
→ 🚨 `ModuleNotFoundError` 가 보이면 **`requirements.txt` 가 바뀐 배포였다** → 6-4.

**③ 두뇌가 실제로 일을 시작했는지** (로그가 조용하면 `restart` 는 됐는데 워커가 안 도는 것이다)

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 5m scheduler | grep -E "\[stage-trigger\]" | tail -3'
```

→ `[stage-trigger] 완료: 활성=N 검사=N ...` 가 **새로 찍히고 있어야** 한다.

**④ API 가 살아 있는지**

```bash
ssh root@159.65.137.250 'curl -s -m 10 http://127.0.0.1:8000/health'
```

**⑤ 배포가 ban 을 유발하지 않았는지** (재시작 직후 캐시가 비어 스캔이 몰릴 수 있다)

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T redis redis-cli GET "api_backoff:ip:ban_until_ms"'
```

##### 🚨 즉시 롤백해야 하는 신호 (하나라도 해당되면 6-1 ⑤ 를 실행한다)

| 신호 | 뜻 |
|---|---|
| `scheduler` 가 `Restarting` 이거나 `restarts` 가 계속 증가 | 크래시 루프 = **손절이 없는 상태가 계속된다** |
| 로그에 `Traceback` 이 반복 | 워커가 매 주기 죽는다 |
| `[stage-trigger]` 가 5분 넘게 안 찍힘 | 두뇌가 멈췄다 |
| `/health` 가 응답 없음 | api 사망 |
| ban 키에 숫자가 생김 | IP ban 진입 → 🚨 **롤백보다 먼저, 더 이상 재시작하지 마라.** 재시작은 회로차단기를 지운다 (→ 6-5) |

🚨 **판단이 안 서면 롤백이 정답이다.** 옛 코드는 최소한 어제까지 돌던 코드다.

---

### 7. 로그 보는 법 + 자주 쓰는 grep 패턴

#### 기본형

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 10m --tail 50 scheduler'
```

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 1h api scheduler'
```

| 목적 | 명령 조각 |
|---|---|
| 최근 10분 | `--since 10m` |
| 특정 시각 이후 | `--since 2026-09-03T08:00:00` |
| 실시간 추적 | `-f --tail 50` (🚨 SSH 세션이 안 끊기니 Ctrl+C 로 나올 것) |
| 여러 서비스 동시 | `docker compose logs --since 30m api scheduler user-stream` |
| 에러만 | 아래 grep |

#### 실전 grep 패턴 (전부 위 로그 표본에서 실제 형식 확인)

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 1h scheduler | grep -E "ERROR|CRITICAL|Traceback"'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 2h scheduler | grep -E "Fix116|IP ban|418|ip_banned_skip"'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 2h scheduler | grep -E "Fix124|weight budget|weight_throttled"'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 1h scheduler | grep -E "\[stage-trigger\]"'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 6h scheduler | grep -E "진입|청산|손절|익절"'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 1h api | grep -vE "GET /(health|api/v1/(strategies|exchange-accounts)) HTTP.* 200 OK"'
```

(마지막 것: api 로그는 대시보드 폴링 200 OK 로 도배되므로 **정상 요청을 빼고** 봐야 한다.
실제 표본에서 `/health`, `/api/v1/strategies`, `/api/v1/exchange-accounts`,
`/api/v1/admin/system-health`, `/api/v1/reentry-alerts` 등이 초 단위로 찍힌다.)

정상 동작 표본 (2026-09-03 09:03 UTC scheduler):

```
[app.workers.stage_trigger_worker] [stage-trigger] 완료: 활성=8 검사=8 발동=0 ban_skip=0 오류=0
[app.services.risk_service] [risk] Fix183/184 TP1 옵션 적용 strategy=2005 TP1_override=15.00 ...
[app.workers.auto_add_margin_worker] [auto_add_margin] 금액 방식 = 고정 300 USDT
```

`ban_skip=0` 이면 IP ban 이 아니다. **0 이 아니면 즉시 아래 8장을 볼 것.**

#### Redis 로 직접 상태 조회 (로그보다 빠름)

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T redis redis-cli GET "api_backoff:ip:ban_until_ms"'
```

→ **빈 값이면 ban 아님.** (2026-09-03 실측: 빈 값 = 정상)

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && m=$(date -u +%Y%m%d%H%M) && docker compose exec -T redis redis-cli GET "binance:weight:$m"'
```

2026-09-03 실측 최근 4분: `340`, `538`, `574`, `219`
→ 스캔 예산 `1500`, 실제 한도 `2400` 대비 **약 14~24%. 매우 여유 있음.**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && m=$(date -u +%Y%m%d%H%M) && docker compose exec -T redis redis-cli HGETALL "binance:reqcount:$m"'
```

2026-09-03 실측 (1분): `/fapi/v1/klines|200` = 162, `/fapi/v1/ticker/24hr|200` = 3, `/fapi/v2/account|200` = 3

---

### 8. 🚨🚨 IP ban(418) — 새 PC 에서 Binance API 를 직접 때리면 안 되는 이유

#### 8-1. 무슨 일이 있었나 (2026-08-26 사고)

`backend/app/integrations/binance/client.py:637-651` 의 주석이 사고를 그대로 기록하고 있다:

- IP `159.65.137.250` 이 **418 ban** 상태였는데 `peak_break_reversal` 워커가 **2초에 18번** 호출.
- **Binance 는 ban 기간 중의 요청도 카운트해서 ban 을 연장/승격한다.**
- 실측 연장 궤적: `06:08:43 → 06:28:43 → 06:30:44 → 06:34:47` — **스스로 ban 을 계속 밀어냈다.**
- 워커별 가드로는 못 막았다. 워커는 루프 **시작 전에 한 번만** ban 을 확인하고, 루프 도중 ban 이 걸리면
  33개 심볼을 끝까지 두드린다 (`_get_15m_high` 는 418 예외를 **삼키고** `None` 을 반환하며 다음 심볼로 진행).

#### 8-2. 🚨 핵심 — **418 은 「계정」이 아니라 「IP」 ban 이다**

`client.py:53-56`:

> `418 은 「계정」이 아니라 「IP」 ban 이다 → 프로세스/컨테이너 전체가 멈춰야 한다.`

이 한 문장이 새 PC 이전에서 가장 중요한 문장이다.

🚨 **밴은 API 키가 아니라 「나가는 공인 IP」에 걸린다.**
🚨 **그런데 회로 차단기는 Redis(`api_backoff:ip:ban_until_ms`)와 프로세스 메모리에만 산다** —
즉 **VPS 안에서만 공유된다.** 새 PC 는 그 Redis 를 보지 않고(보더라도 IP 가 다르고), 새 PC 의 요청은
**VPS 의 weight 거버너 카운터에도 잡히지 않는다.**

따라서:

| 새 PC 에서 하는 행동 | 결과 |
|---|---|
| VPS 에 SSH 로 붙어서 조회 | ✅ 안전. VPS 의 회로차단기·거버너가 그대로 적용됨 |
| 새 PC 에서 로컬 앱을 띄워 **같은 Neon DB** 를 보게 함 | 🚨🚨 **실계좌로 실제 주문이 나간다.** API 키가 DB 에 암호화되어 있고 `.env` 의 `ENCRYPTION_KEY` 로 복호화된다 |
| 새 PC 에서 Binance REST 를 직접 호출 (스크립트, 백테스트, 스캔) | 🚨 **새 PC 의 IP 가 밴을 먹는다.** 사무실/집이 VPS 와 같은 NAT 를 공유하지 않는 한 VPS 는 무사하지만, 집 IP 가 밴되면 새 PC 에서 아무 조사도 못 한다 |
| 새 PC 가 **VPS 와 같은 공인 IP** 로 나감 (예: VPS 를 프록시/터널로 씀) | 🚨🚨🚨 **VPS 의 실거래가 전면 정지된다.** 절대 금지 |

#### 8-3. 지금 살아 있는 방어 장치 (읽고 확인함)

| Fix | 무엇 | 위치 |
|---|---|---|
| **116** | IP ban 전역 회로 차단기. **네트워크로 나가기 직전** 한 곳에서 차단. 1차=프로세스 메모리, 2차=Redis(컨테이너 4개 공유) | `client.py:53-59, 637-664` |
| **119** | 차단기가 만든 **합성 예외**에 `locally_suppressed=True` 를 달아, 그걸 「거래소가 준 새 rate limit」으로 오인해 ban 을 60초씩 재연장하던 **되먹임**을 끊음 | `client.py:44-49, 664, 688` |
| **117** | 전 심볼 24h 티커 공유 캐시 (weight 40 짜리) TTL 30s | `client.py:61-66` |
| **122** | klines 공유 캐시 — **IP ban 최대 원인 제거**. 봉 길이 비례 TTL(1m=5s … 4h=180s) | `client.py:68-79` |
| **118** | 엔드포인트별 호출 계측을 Redis 에 (`binance:reqcount:{분}`). scheduler 는 `/metrics` 가 없어 Prometheus 로 안 보이므로 이게 유일한 눈 | `client.py:81-86, 177-219` |
| **124** | **weight 거버너** — 「스캔은 버려도 되지만 주문은 절대 막으면 안 된다」. 한도 2400/분, 스캔 예산 **1500/분**. 주문·포지션·계정·마진·레버리지는 **항상 통과** | `client.py:88-118, 666-690` |
| **125** | weight 를 실제 규칙대로 산출 (klines 는 `limit` 에 따라 1/2/5/10, ticker24h 는 symbol 지정 시 1) — 과대평가로 정상 스캔을 막던 것 수정 | `client.py:120-149` |
| **127** | **차단된 요청의 weight 는 되돌린다**(`sign=-1`). 이전엔 차단분까지 누적 → 카운터가 부풀고 → 더 차단하고 → 더 부푸는 악순환. 실측 426회/분(≈450 weight)인데 표본이 **2135** 까지 치솟아 스캔의 18%(274건)를 오차단 | `client.py:668-679, 150-163` |

거버너가 **차단하는 대상**(`_SCAN_ENDPOINTS`, `client.py:110-118`):
`/fapi/v1/klines`, `/fapi/v1/ticker/24hr`, `/fapi/v1/premiumIndex`, `/fapi/v1/ticker/price`, `/fapi/v1/ticker/bookTicker`
→ **주문 관련 엔드포인트는 이 집합에 없다 = 절대 막히지 않는다.** 설계가 옳다.

#### 8-4. 🚨 새 PC 안전 수칙 (반드시 지킬 것)

1. 🚨 **새 PC 에서 `scheduler` / `user-stream` / `mark-price-stream` 을 절대 띄우지 마라.**
   같은 Neon DB 를 보는 두 번째 두뇌가 생기면 **같은 포지션에 중복 주문**이 나간다.
   (VPS 의 동시보유 상한·중복 진입 가드는 **DB 상태 기준**이라 두 프로세스가 동시에 판정하면 둘 다 통과할 수 있다.
   ⚠️ 이 경합 시나리오는 코드로 확인하지 못했다 — 하지만 안전 쪽으로 가정해야 한다.)
2. 🚨 **로컬에서 Binance REST 를 직접 호출하는 스크립트를 돌리지 마라.**
   조회조차도 weight 를 먹고, 그 weight 는 VPS 거버너에 **보이지 않는다.**
3. ✅ **조사·분석은 전부 VPS 안에서 `docker compose exec` 로 하라.** 그러면 회로차단기와 거버너가
   그대로 적용된다.
4. ✅ 데이터만 필요하면 **Neon DB 만 읽어라** (Binance 를 안 거친다). Neon 은 IP 밴과 무관하다.
5. 🚨 **로컬 개발을 꼭 해야 한다면 testnet 을 써라.**
   `BINANCE_FUTURES_TESTNET_BASE_URL=https://testnet.binancefuture.com`
   (`backend/.env.example:18`, `backend/app/core/config.py:17`).
   🚨 단, **mainnet/testnet 은 `.env` 가 아니라 DB `exchange_accounts.is_testnet` 컬럼으로 갈린다.**
   `.env` 만 바꿔서는 testnet 이 되지 않는다. 새 PC 에서는 **testnet 전용 계정 행을 따로 만들어야 한다.**
6. 🚨 **이미 ban 을 먹었다면 `clear_ip_ban()` 을 쓰지 마라.**
   `client.py:306-308` 주석: `운영자 강제 해제 (실 ban 중 사용 금지 — ban 이 연장된다!)`.
   기다리는 것이 유일한 해법이다.
7. 새 PC 가 밴 상태인지 확인하려면 **VPS 가 아니라 새 PC 에서** 아래를 **정확히 한 번만** 실행한다.
   `/fapi/v1/ping` 은 weight **1** 의 가장 가벼운 공개 엔드포인트다.

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" -m 10 https://fapi.binance.com/fapi/v1/ping
   ```

   | 응답 | 뜻 | 해야 할 일 |
   |---|---|---|
   | `200` | 이 IP 는 정상 | 없음 |
   | `429` | rate limit 경고 | **즉시 멈추고** 최소 몇 분 대기 |
   | `418` | 🚨 **이 IP 가 ban** | **아무것도 더 치지 마라.** 재시도 자체가 ban 을 연장한다 (8-1 참조) |
   | `000` / 타임아웃 | 네트워크 문제 (ban 아님) | 인터넷 확인 |

   🚨 **연타·루프·`watch` 금지.** 연타가 바로 2026-08-26 사고의 원인이었다.
   418 을 받았다면 다음 확인은 **최소 수십 분 뒤에 한 번**만.

   🚨🚨 **이 한 번조차도, 새 PC 가 VPS 와 같은 공인 IP 로 나가는 상황이면 치지 마라.**
   (VPS 를 프록시·VPN·SSH 터널로 쓰고 있거나, 사무실 회선이 VPS 와 같은 출구를 공유하는 경우.)
   그 경우 이 `curl` 의 weight 가 **VPS 계정 몫으로 잡히고**, VPS 의 거버너에는 안 보인다.
   현재 나가는 IP 는 이렇게 확인한다 (Binance 를 안 거친다 = 안전):

   ```bash
   curl -s -m 10 https://api.ipify.org; echo
   ```

   → 결과가 `159.65.137.250` 이면 🚨 **VPS 와 같은 IP 다. Binance 를 절대 직접 치지 마라.**

---

### 9. SSH 키 — 새 PC 로 옮기는 절차

현 PC 상태:

| 파일 | 확인 |
|---|---|
| `~/.ssh/id_ed25519` (개인키) | 존재. **내용은 읽지도 출력하지도 않았다** |
| `~/.ssh/id_ed25519.pub` (공개키) | 존재 |
| `~/.ssh/config` | **없음** (그래서 매번 `root@159.65.137.250` 을 직접 친다) |
| 인증에 실제로 쓰이는 키 | `id_ed25519` — `ssh -v` 가 `Server accepts key: /c/Users/user/.ssh/id_ed25519` 로 확인 |
| 지문 | `SHA256:cbFAdSNFpCEZRnC/fxKsDmI0+4w2uTSUgls9XWbC4KI` |

⚠️ 현 PC 의 `id_ed25519` 권한이 `-rw-r--r--` (644) 다. Git Bash 라 OpenSSH 가 넘어가 주지만
원칙적으로는 600 이어야 한다.

#### ✅ 권장: 새 PC 에서 **새 키를 만든다** (개인키가 네트워크를 절대 안 탄다)

새 PC 에서:

```bash
ssh-keygen -t ed25519 -C "sajangnim-newpc-2026-09" -f ~/.ssh/id_ed25519
```

```bash
cat ~/.ssh/id_ed25519.pub
```

🚨 위 `.pub` **한 줄**(공개키 — 노출되어도 안전하다)을 복사한 뒤, **현 PC 에서** VPS 에 등록한다:

🚨🚨 **이 작업의 유일한 실패 모드는 「VPS 에서 영구히 잠기는 것」이다.** 잠기면 실자금이 도는
자동매매를 손댈 수 없게 된다. 아래 안전 절차를 그대로 지킬 것.

**① 현 PC 의 SSH 세션을 하나 열어 두고, 작업이 다 끝날 때까지 절대 닫지 마라.**
(뭔가 잘못돼도 이 살아 있는 세션으로 고칠 수 있다. 닫으면 그 기회가 사라진다.)

**② 등록 전에 지금 등록된 키를 세어 둔다.**

```bash
ssh root@159.65.137.250 'wc -l < ~/.ssh/authorized_keys && cp ~/.ssh/authorized_keys ~/.ssh/authorized_keys.bak.$(date +%F)'
```

**③ 등록한다. 🚨 `>>` 인지 눈으로 두 번 확인하라.**

```bash
ssh root@159.65.137.250 'echo "여기에_새PC의_pub_한줄_붙여넣기" >> ~/.ssh/authorized_keys'
```

🚨🚨 **`>` 를 하나만 쓰면(`> ~/.ssh/authorized_keys`) 기존 키가 전부 지워지고 즉시 잠긴다.**
`>>` (두 개) 여야 「추가」다. 이 한 글자가 이 문서에서 가장 위험한 한 글자다.

**④ 줄 수가 정확히 1 늘었는지 확인한다.** (②의 숫자 + 1)

```bash
ssh root@159.65.137.250 'wc -l < ~/.ssh/authorized_keys'
```

**⑤ 새 PC 에서 접속이 되는 것을 확인한 뒤에야** ①의 세션을 닫는다.

🚨 **되돌리는 법**: ②에서 뜬 백업으로 복구한다 (①의 세션이 살아 있을 때만 가능하다).

```bash
ssh root@159.65.137.250 'cp ~/.ssh/authorized_keys.bak.$(date +%F) ~/.ssh/authorized_keys && wc -l < ~/.ssh/authorized_keys'
```

🚨 **그래도 잠겼다면**: DigitalOcean 콘솔의 **Recovery Console(웹 터미널)** 이 유일한 통로다.
SSH 키와 무관하게 붙을 수 있지만 **root 비밀번호가 필요**하다. 🚨 **새 PC 로 옮기기 전에
DO 계정 로그인과 root 비밀번호(또는 비밀번호 재설정 권한)를 확보해 둘 것.**
⚠️ 확인 못 함: 현재 DO 계정에 root 비밀번호가 설정되어 있는지는 DO 콘솔에서만 알 수 있다.

🚨 이 명령들은 **VPS 의 보안 설정을 바꾼다.** 나는 읽기 전용 지시를 받았으므로 실행하지 않았다.
**사장님이 직접 실행하실 것.**

새 PC 에서 **접속하기 전에** 먼저 호스트키 지문을 대조한다:

```bash
ssh-keyscan -t ed25519 159.65.137.250 2>/dev/null | ssh-keygen -lf -
```

기대 출력 (2026-09-03 현 PC 에서 재확인함):

```
256 SHA256:NYbjWuJ7a5pBfXRi9E9ys7yyDqWlaupLiuwH12Q2toM 159.65.137.250 (ED25519)
```

지문이 다르면 **중간자 공격 의심 — 접속하지 말 것.**

지문이 맞으면 접속한다:

```bash
ssh -o ConnectTimeout=15 root@159.65.137.250 'hostname && uptime'
```

첫 접속에서 `Are you sure you want to continue connecting?` 가 뜨면 화면의 지문이 위와 같은지
한 번 더 보고 `yes`.

🚨 **이 문서의 다른 명령들이 쓰는 `-o StrictHostKeyChecking=no` 는 이 확인을 건너뛴다.**
편의를 위한 것이므로 **첫 접속만큼은 반드시 그 옵션 없이** 위 순서대로 하고,
`~/.ssh/known_hosts` 에 등록된 뒤에 나머지 명령을 쓸 것.

#### 대안: 기존 키를 그대로 옮긴다

정말 옮겨야 한다면 — 🚨 **개인키는 절대 채팅·이메일·클라우드 드라이브·GitHub 에 올리지 마라.**
USB 등 물리 매체로만 옮긴다. 옮긴 뒤 새 PC 에서:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
```

```bash
chmod 600 ~/.ssh/id_ed25519 && chmod 644 ~/.ssh/id_ed25519.pub
```

옮긴 뒤 USB 의 원본은 지운다. (Windows 네이티브 OpenSSH 를 쓸 경우 `icacls` 로 상속을 끊어야 할 수 있다.)

#### 선택: `~/.ssh/config` 로 타이핑 줄이기 (새 PC 에서)

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
```

🚨 **`>>` 다.** `>` 로 쓰면 기존 `~/.ssh/config` 의 다른 호스트 설정이 전부 날아간다.
(새 PC 라 지금은 비어 있겠지만, 나중에 다시 실행할 때를 대비해 습관을 들일 것.)

```bash
printf 'Host trader\n    HostName 159.65.137.250\n    User root\n    IdentityFile ~/.ssh/id_ed25519\n    ServerAliveInterval 30\n' >> ~/.ssh/config
```

⚠️ **두 번 실행하면 `Host trader` 블록이 두 개가 된다.** OpenSSH 는 먼저 나온 것을 쓰므로 당장은
동작하지만 헷갈리니, 다시 실행하기 전에 `grep -n "Host trader" ~/.ssh/config` 로 이미 있는지 볼 것.

```bash
chmod 600 ~/.ssh/config
```

그러면 `ssh trader` 만으로 접속된다. (`mkdir -p` 를 빼면 `~/.ssh` 가 없는 새 PC 에서 `>>` 가
`No such file or directory` 로 실패한다.)

⚠️ 이 문서의 나머지 명령은 전부 `root@159.65.137.250` 을 그대로 쓴다. `config` 를 만들었다면
`ssh trader ...` 로 바꿔 읽으면 된다 — **`scp` 도 `scp trader:~/... ` 형태로 동작한다.**

---

### 10. 백업 정리 — 무엇이 어디에 백업되는가

| 대상 | 백업되나 | 어디에 | 실제 상태 |
|---|---|---|---|
| **Neon DB (진짜 실거래 데이터)** | Neon 자체 기능에만 의존 | Neon 클라우드 | ⚠️ **보존 정책 확인 못 함** (Neon 콘솔 필요) |
| 로컬 `db` 컨테이너 | 예, `db-backup` 이 매일 | `~/binance-auto-trader/backend/db_backups/` | 🚨 **내용이 비어 있다 (505 바이트).** 무의미 |
| `.env` (`ENCRYPTION_KEY` 등) | ❌ **백업 없음** | — | 🚨 이게 없으면 DB 의 API 키를 **영원히 복호화 못 한다** |
| 코드 | 예 | GitHub `herosys1-crypto/binance-auto-trader` | ✅ VPS HEAD `ded22f3` == main |
| Redis | ❌ 영속화 없음 (`volumes:` 자체가 없음) | — | 🚨 재시작하면 캐시·**IP ban 회로차단기 상태가 소실**된다. 평시엔 무해하지만 **ban 중에는 위험하다** — ban 을 잊고 다시 두드려 ban 을 연장한다 (→ 6-5) |

`db-backup` 설정 (`backend/docker-compose.yml:114-133`):
`SCHEDULE=@daily`, `BACKUP_KEEP_DAYS=7`, `BACKUP_KEEP_WEEKS=4`, `BACKUP_KEEP_MONTHS=6`,
`POSTGRES_EXTRA_OPTS="-Z6 --schema=public --blobs"`, 대상 `POSTGRES_HOST=db`(← 로컬, **Neon 아님**).

🚨🚨 **새 PC 이전에서 가장 위험한 단일 지점: `backend/.env` 의 `ENCRYPTION_KEY`.**
Binance API 키는 Neon DB 의 `exchange_accounts.api_key_enc` 에 **암호화**되어 저장되고
(`backend/app/api/v1/exchange_accounts.py:103,226` 에서 `encrypt_text`),
`decrypt_text(account.api_key_enc)` 로 복호화된다 (`app/api/v1/analysis.py:50` 등
**`.py` 파일 60개 / 247줄**에서 호출 — 2026-09-03 재실측:
`grep -rl "decrypt_text" backend/app --include=*.py | wc -l` → `60`,
`grep -rn "decrypt_text" backend/app --include=*.py | wc -l` → `247`).
**`ENCRYPTION_KEY` 를 잃으면 DB 를 그대로 갖고 있어도 거래를 못 한다.**
VPS 의 `.env` 는 git 에 없고 백업도 안 된다 — VPS 디스크가 유일한 사본이다.
2026-09-03 실측으로 확인했다: `find ~ -maxdepth 3 -name ".env*"` 결과가
`/root/binance-auto-trader/backend/.env` **한 개뿐**이다(나머지는 `.example` / `.template`).
🚨 **즉 이 파일 하나가 날아가면 계정의 Binance API 키를 되살릴 방법이 없다.**
새 PC 셋업의 **첫 단계**로 이 파일 사본을 안전한 곳에 확보해 두는 것이 좋다(아래 `scp`).

⚠️ 부수적으로, 이 `.env` 의 권한이 `-rw-r--r--`(644)라 **모든 로컬 사용자가 읽을 수 있다.**
현재 VPS 는 `root` 단독 사용이라 당장의 위험은 낮지만 원칙적으로는 `600` 이어야 한다.
(변경은 사장님 판단 — 나는 읽기 전용이라 실행하지 않았다: `chmod 600 ~/binance-auto-trader/backend/.env`)

VPS `.env` 에 들어 있는 **키 이름 목록** (값은 절대 옮기지 않았다):

```
ACCESS_TOKEN_EXPIRE_MINUTES   ALLOWED_SYMBOLS_CSV   ALLOW_DUPLICATE_SYMBOL_STRATEGIES
BINANCE_FUTURES_BASE_URL      BINANCE_FUTURES_TESTNET_BASE_URL
DAILY_LOSS_LIMIT_USDT         DATABASE_URL          ENABLE_METRICS
ENCRYPTION_KEY                HEARTBEAT_INTERVAL_HOURS   JWT_ALGORITHM
MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT   MAX_LEVERAGE
MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE     MIN_LIQUIDATION_DISTANCE_PCT
POSTGRES_PASSWORD             REDIS_URL             SECRET_KEY
SENTRY_DSN  SENTRY_ENV  SENTRY_PROFILES_SAMPLE_RATE  SENTRY_TRACES_SAMPLE_RATE
TELEGRAM_BOT_TOKEN            TELEGRAM_CHAT_ID      TEST_DATABASE_URL
WALLET_LIMIT_PCT
```

(조회 명령: `grep -oE "^[A-Za-z_][A-Za-z0-9_]*=" .env | tr -d "="` — **값은 출력하지 않는다.**)

#### 🚨🚨🚨 10-A. 확인된 비밀 유출 — 운영 `SECRET_KEY` 가 **공개** GitHub 저장소에 평문으로 있다

**이것이 이 문서 전체에서 가장 급한 항목이다. 새 PC 이전보다 먼저 조치해야 한다.**

2026-09-03 실측으로 **확인**했다(추측 아님):

| # | 확인한 것 | 방법 | 결과 |
|---|---|---|---|
| 1 | 저장소가 **공개**다 | `curl https://api.github.com/repos/herosys1-crypto/binance-auto-trader` | `"private": false`, `"visibility": "public"` |
| 2 | `SECRET_KEY` **값**이 평문으로 커밋되어 있다 | `HANDOFF-2026-04-30-NEXT-SESSION.md:197` 및 `:210` (git 추적 파일) | 값이 그대로 적혀 있음 |
| 3 | 그 값이 **지금 운영에서 쓰는 값과 동일**하다 | VPS `.env` 의 `SECRET_KEY` 와 위 파일의 값을 **md5 로만** 비교 | **md5 일치** (값은 어느 쪽도 출력하지 않았다) |
| 4 | `SECRET_KEY` 는 **JWT 서명키**다 | `backend/app/core/security.py:45,49` — `jwt.encode(payload, settings.secret_key, ...)` / `jwt.decode(...)` | 로그인 토큰을 이 키로 서명·검증 |
| 5 | API 가 **인터넷에 열려 있다** | 내 PC(외부)에서 `curl http://159.65.137.250:8000/health` | `200` (1-(2) 의 8000 OPEN 과 동일) |

🚨 **연결하면**: 누구든 공개 저장소에서 이 키를 읽어 **유효한 로그인 토큰을 직접 위조**할 수 있고,
인터넷에 열린 8000 포트로 **실자금 자동매매 API 에 인증된 상태로 접근**할 수 있다.
(나는 유출을 **확인만** 했고 토큰 위조나 인증 시도는 **하지 않았다.**)

✅ **함께 확인한 것 — 다행인 부분** (같은 방식으로 md5 비교):

| 값 | 상태 |
|---|---|
| Neon DB 비밀번호 | `HANDOFF-2026-04-28-HOME-TO-OFFICE.md:27,138,179` 에 **옛 값이 평문 커밋**되어 있으나, VPS 현재 값과 **md5 불일치 = 이미 교체됨.** 그래도 파일은 지우는 것이 맞다 |
| `TELEGRAM_BOT_TOKEN` | 저장소에는 `<NEW_...>` **자리표시자만** 있다. 실제 값 커밋 없음 |
| `ENCRYPTION_KEY` | 저장소에 실제 값 커밋 **없음** (`.env.example` 은 자리표시자) |
| Binance API 키/시크릿 | 저장소에 커밋 **없음** (Neon DB 에 암호화 저장) |

🚨 **Grafana admin 비밀번호도 `backend/docker-compose.yml:99` (`GF_SECURITY_ADMIN_PASSWORD`) 에
평문 커밋되어 공개 저장소에 있다**(3장 참조). 값은 짧고 흔한 형태라 **사전 공격에 즉시 뚫린다.**
Grafana 는 127.0.0.1 바인딩이라 당장 외부 노출은 아니지만,
**같은 비밀번호를 다른 곳에 재사용했다면 그쪽이 위험하다.**

🚨 **이 문서에는 그 값을 옮겨 적지 않는다.** 확인이 필요하면 저장소 파일에서 직접 볼 것
(`grep -n GF_SECURITY_ADMIN_PASSWORD backend/docker-compose.yml`). 핸드오프 문서는 사장님이
여러 곳에 복사·보관할 가능성이 높으므로 **값이 아니라 「어디에 있는가」만 적는 것이 원칙이다.**

**사장님이 직접 하실 조치 (순서대로).** 🚨 나는 읽기 전용 지시를 받았으므로 **하나도 실행하지 않았다.**

1. **`SECRET_KEY` 를 새로 발급해 VPS `.env` 에 교체한다.** (가장 급함)

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   🚨 **`ENCRYPTION_KEY` 는 절대 함께 바꾸지 마라.** 그것을 바꾸면 DB 의 `api_key_enc` 를
   복호화할 수 없게 된다(10장 본문). **`SECRET_KEY` 와 `ENCRYPTION_KEY` 는 완전히 다른 키다.**
   `SECRET_KEY` 교체의 유일한 부작용은 **기존 로그인 토큰 전부 무효화 = 재로그인**뿐이다.
2. `.env` 를 고쳤으므로 **`restart` 가 아니라 재생성**이어야 반영된다 (6-1 의 함정과 동일):

   ```bash
   cd ~/binance-auto-trader/backend && docker compose up -d --force-recreate api
   ```
3. **8000·9090·6380 포트를 인터넷에서 닫는다** (1-(2) 참조). 키를 바꿔도 포트가 열려 있으면
   다음 유출 때 같은 일이 반복된다.
4. **Grafana admin 비밀번호를 바꾸고**, `docker-compose.yml` 의 평문을 `.env` 주입으로 옮긴다
   (`docker-compose.production.yml` 이 이미 그렇게 권고한다).
5. **공개 저장소에서 비밀이 적힌 핸드오프 파일들을 지운다** — `HANDOFF-2026-04-28-HOME-TO-OFFICE.md`,
   `HANDOFF-2026-04-30-NEXT-SESSION.md`.
   🚨 **파일을 지우는 커밋만으로는 git 이력에 그대로 남는다.** 이력에서 지우려면 저장소를
   **비공개로 전환**하거나 히스토리 재작성이 필요하다. **가장 확실하고 빠른 조치는 「키 교체」(1번)이며,
   이력 정리는 그 다음이다.** 이미 공개된 값은 「유출된 것」으로 간주하고 전부 새로 발급하는 것이 원칙이다.

**나중에 재검증하는 법** (값을 화면에 띄우지 않고 md5 만 비교):

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && sed -n "s/^SECRET_KEY=//p" .env | tr -d "\n\r " | md5sum'
```

교체 후 이 md5 가 `bf9c11c702702c34890def0d6ccbd4b6` (= 공개 저장소에 있는 값의 md5) 와
**달라야** 정상이다. 같으면 아직 안 바뀐 것이다.

🚨 **새 PC 셋업 중에는 위 공개 저장소 핸드오프 파일들의 `.env` 예시를 그대로 복사해 쓰지 마라.**
거기 적힌 Neon 비밀번호는 이미 만료된 값이라 **접속이 안 되고**, `SECRET_KEY` 는 유출된 값이라
**쓰면 안 된다.** `.env` 는 반드시 아래 「어디서 얻는가」 절차대로 VPS 에서 직접 받는다.

**어디서 얻는가**:

| 키 | 출처 |
|---|---|
| `DATABASE_URL` | Neon 콘솔 → 프로젝트 `ep-sparkling-forest-ao116t81` → Connection string |
| `ENCRYPTION_KEY` | 🚨🚨 **VPS `~/binance-auto-trader/backend/.env` 가 유일한 사본이고 재생성이 불가능하다.** 바꾸면 DB `exchange_accounts.api_key_enc` 의 기존 암호문을 **영원히 못 읽는다** = 거래 불가. **절대 새로 만들지 마라, 그대로 복사해 온다.** |
| `SECRET_KEY` | ⚠️ **재생성 가능하다** — JWT 서명키일 뿐이라 바꿔도 부작용은 **재로그인**뿐이다(`app/core/security.py:45,49`). 🚨 그리고 **현재 값은 공개 저장소에 유출되어 있으므로 반드시 새로 발급해야 한다 → 10-A 참조.** 복사해 오지 마라 |
| `TELEGRAM_BOT_TOKEN` / `CHAT_ID` | Telegram BotFather / 대화방 |
| `SENTRY_DSN` | Sentry 프로젝트 설정 |
| Binance API 키 | 🚨 `.env` 에 **없다.** Neon DB 에 암호화 저장 → 웹 UI 의 거래소 계정 화면에서 관리 |

`.env` 를 새 PC 로 옮기는 방법은 백업이 없으므로 VPS 에서 직접 가져오는 것뿐이다.
🚨 **아래 명령은 비밀 값을 화면에 띄우지 않고 파일로만 받는다. 사장님이 직접 실행하실 것.**

```bash
scp root@159.65.137.250:~/binance-auto-trader/backend/.env ~/Downloads/vps.env.backup
```

🚨 받은 파일은 즉시 안전한 곳(암호화된 USB, 패스워드 매니저의 안전 노트)에 넣고
`~/Downloads` 에서 지운다. 절대 git 에 커밋하지 마라.

🚨🚨 **이 파일을 옮기는 방법에 대한 금지 사항** — 이 저장소는 실제로 이 규칙을 어겨서
운영 `SECRET_KEY` 가 공개 저장소에 남았다(10-A). 같은 실수를 반복하지 마라:

- ❌ **채팅(카카오톡·슬랙·디스코드)·이메일·문자로 보내지 마라.** AI 에이전트에게 붙여넣는 것도 안 된다.
- ❌ **구글 드라이브·원드라이브·드롭박스 등 클라우드에 올리지 마라.**
- ❌ **git 저장소 안(하위 디렉터리 포함)에 두지 마라.** 핸드오프 `.md` 에 값을 적는 것도 금지다.
- ❌ **화면 캡처·화면 공유에 띄우지 마라.**
- ✅ 허용: 위 `scp`(SSH 암호화 채널로 PC→PC 직접), 암호화된 USB, 패스워드 매니저의 안전 노트.

`scp` 가 안전한 이유는 값이 **SSH 로 암호화되어 두 기기 사이에서만** 오가고 제3자 서버를
거치지 않기 때문이다. 위 ❌ 항목들은 전부 제3자 서버에 평문 사본을 남긴다.
✅ `.gitignore:2-10` 이 `.env`, `.env.*`, `backend/.env`, `backend/.env.*` 를 모두 제외하고
`!.env.example` / `!backend/.env.example` / `!backend/.env.production.template` 만 예외로 두는 것을 확인했다.
🚨 단, 위 `scp` 처럼 **저장소 밖 다른 이름**(`vps.env.backup`)으로 받은 파일이 저장소 안에 들어오면
이 규칙에 안 걸린다. 저장소 디렉터리 밖에 두어라.

---

### 11. 새 PC 첫날 체크리스트 (전부 읽기 전용, 안전)

> **선행 조건: 9장의 SSH 키 등록이 끝나 있어야 한다.** 안 되어 있으면 여기 명령은 전부
> `Permission denied (publickey)` 로 실패한다. 그건 고장이 아니라 **키가 아직 없다는 뜻**이다.

```bash
ssh -o ConnectTimeout=15 root@159.65.137.250 'hostname && uptime && df -h /'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ps'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && git log --oneline -3 && git rev-parse --abbrev-ref HEAD'
```

```bash
ssh root@159.65.137.250 'curl -s -m 10 http://127.0.0.1:8000/health'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api alembic current'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T redis redis-cli GET "api_backoff:ip:ban_until_ms"'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
print(\"strategy_instances:\", db.execute(text(\"select count(*) from strategy_instances\")).scalar())
"'
```

기대값 (2026-09-03 09:20 UTC 실측 — 전 항목 직접 실행해 대조함):

| 확인 | 기대 출력 | 다르면 |
|---|---|---|
| 컨테이너 | **9개 전부 `Up`** | Exit/Restarting 이 있으면 7장 로그부터 |
| 브랜치 / HEAD | `main` / `ded22f3` (또는 그 이후) | 다른 브랜치면 **배포 상태가 아니다** |
| `/health` | `{"status":"ok"}` | api 가 죽었거나 기동 중 |
| alembic | `0034_surge_ladder (head)`, `current == heads` | 다르면 6-3 |
| ban 키 | **빈 값** (아무것도 안 나옴) | 숫자가 나오면 🚨 8장 즉시 |
| `strategy_instances` | 숫자 출력 — **2026-09-03 실측 `1487`** | 0 이나 에러면 🚨 **`db` 컨테이너로 잘못 조회한 것**(2장) |

🚨 마지막 줄이 가장 중요한 자가진단이다. **숫자가 0 이면 데이터가 날아간 게 아니라
빈 로컬 `db` 를 보고 있는 것**이다 (2장의 함정). `1487` 같은 실수(實數)가 나와야 Neon 에 붙은 것이다.

---

### 12. ⚠️ 확인 못 한 것

- **Neon 백업/PITR 보존 기간** — Neon 웹 콘솔에서만 확인 가능. 🚨 VPS 백업이 비어 있으므로 **이것이 유일한 안전망이다. 반드시 확인할 것.**
- **DigitalOcean 클라우드 방화벽** 설정 유무 — DO 콘솔 필요. (다만 6380/9090/8000 은 실제로 외부에서 연결됐다.)
- `scheduler` 의 **재시작 4회의 실제 원인** — 마지막 종료코드가 0, OOM 아님까지만 확인. 과거 3회는 로그가 남아 있지 않아 단정 못 함.
- **load average 3.67(15분) / 2 vCPU 과부하의 원인** — 프로파일링을 하지 않았다.
- **새 PC 로컬 앱과 VPS 가 같은 DB 를 볼 때의 중복 주문 경합** — 코드로 검증하지 않았다. 안전 쪽으로 「금지」로 기술했다.
- **Grafana / Prometheus 대시보드 내용** — 포트만 확인, 화면은 열어보지 않았다.
- `docker-compose.production.yml` 을 **지금 적용하면 무엇이 깨지는지** — 적용은 재시작을 동반하므로(실자금) 시도하지 않았다. 특히 `db` 를 끄면 `db-backup` 의 `depends_on` 이 어떻게 되는지 등은 검증 안 함.
- **8-4 의 `fapi/v1/ping` 응답표** — 명령 형식은 맞지만 **실행하지 않았다.** 이 PC 에서 Binance 를 치는 것 자체가 8장이 금지하는 행동이라 일부러 피했다. 응답 코드의 의미는 Binance 공식 규약(418=IP ban / 429=rate limit)에 따른 것이다.
- **새 PC 에서의 실제 재현** — 이 문서의 명령은 전부 **현 PC + 운영 VPS** 에서 검증했다. 키가 없는 진짜 새 PC 에서 처음부터 돌려본 것은 아니다.
- **DigitalOcean Recovery Console 로 실제 복구가 되는지 / root 비밀번호가 설정돼 있는지** — DO 콘솔 필요. 🚨 9장의 SSH 키 잠금 사고 시 **유일한 탈출구**이므로 새 PC 로 옮기기 전에 반드시 확인할 것.
- **거래소측 스톱 주문이 실제로 하나도 없는지** — 6-0 은 **저장소 코드가 스톱 주문을 걸지 않는다**는 것까지만 확인했다(`place_stop_market_order` 호출처 0곳). 바이낸스 계정에 과거 수동으로 걸어 둔 주문이 남아 있는지는 **조회하지 않았다**(Binance API 호출을 피하기 위해). 🚨 웹 UI 나 바이낸스 앱에서 미체결 주문 목록을 한 번 눈으로 볼 것.
- **롤백(6-1 ⑤ / 6-4 3번)을 실제로 실행해 본 적은 없다** — 명령 자체는 표준 git/docker 동작이지만, 실자금 시스템이라 리허설하지 않았다. 🚨 처음 롤백하는 순간이 실전이 되므로, 배포 전에 반드시 ①(해시 기록)을 해 둘 것.
- **`git pull --ff-only` 가 실패하는 상황** — 현재 VPS 는 추적 파일 수정 0건이라 실패할 이유가 없다. 실패했을 때의 복구는 「멈추고 원인 확인」까지만 기술했고 시나리오별 절차는 만들지 않았다.

---

#### 이 문서에서 **직접 실행해 대조한 것** (2026-09-03 09:15~09:25 UTC 재검증)

`docker compose ls`(CONFIG FILES 1개) / `ls` 양쪽 디렉터리(오버라이드 파일 위치) / `docker compose ps`(9개 Up) /
`docker compose ps --format {{.Ports}}`(8000·9090·6380 이 `0.0.0.0`) / `ufw status`(inactive) /
`git rev-parse` + `git log`(main, ded22f3) / `docker --version`·`docker compose version` /
`alembic current`·`alembic heads`(둘 다 `0034_surge_ladder`) / `curl /health`(ok) /
`find app -name "*.py" -printf`(6-6 판정법) / `redis-cli CONFIG GET requirepass`(빈 값) /
`redis-cli GET api_backoff:ip:ban_until_ms`(빈 값) / `strategy_instances` 카운트(**1487**) /
`ssh-keyscan | ssh-keygen -lf -`(호스트키 지문 일치) / `grep .env` 키 이름 26개(값 미출력) /
`nginx sites-enabled/trader`(80→443, proxy 8000) / 저장소 line 번호 참조 전건
(`docker-compose.yml:99/114-133/119`, `Dockerfile:17`, `.env.example:18`, `config.py:17`,
`client.py:53-56/306-308/637-645`, `.gitignore:2-10`, `exchange_accounts.py:103,226`, `analysis.py:50`).

**위험 검증(적대적 검토)에서 추가로 대조한 것:**
`git status --porcelain`(VPS = 추적 수정 **0건** / 추적되지 않는 파일 **31개**) /
`git reflog`(VPS 는 지금까지 `pull --ff-only` · `pull -q` 로만 갱신) /
`grep -rn "stop_market\|take_profit_market" backend/app`(**호출처 0곳** → 6-0) /
`grep -n "def place_stop_market_order" futures_trade.py`(75, 102행) /
`docker-compose.yml:18-24`(redis 에 `volumes:` 절 없음 = 영속화 0) /
`docker-compose.yml:30-31,44,57,73`(앱 4개가 `env_file: .env`) /
`alembic/env.py:27-30` + `alembic.ini:4`(**DATABASE_URL 없으면 localhost 로 조용히 폴백** → 6-3) /
`.github/workflows/`(파일 1개 = 배포 워크플로 없음, 문서 주장 확인) /
`Dockerfile`(alembic 자동 실행 **없음** = 마이그레이션은 100% 수동).
