## 현재 운영 상태 — 무엇이 돌고 있나

> 조사 시각: **2026-09-03 18:15 KST** (= 09:15 UTC)
> 조사 방법: VPS 읽기 전용 SSH + api 컨테이너 앱 세션 SQL + 로컬 저장소 코드/커밋 감사
> 이 섹션의 모든 숫자에는 근거(명령 출력 또는 `파일:줄번호`)가 붙어 있다.

---

### 0. 한눈에 보기 (새 PC에서 제일 먼저 알아야 할 것)

| 항목 | 값 | 비고 |
|---|---|---|
| VPS 배포 커밋 | `ded22f3` (Fix 327) | **런타임 코드의 최신 커밋.** 조사 시점엔 로컬 워크트리 HEAD 와 같았으나, 그 뒤 핸드오프 문서 커밋 `e51d9a8` 이 얹혀 지금 워크트리는 `e51d9a8` 이다 — `backend/app/` 실행 경로 차이는 **0건** (§2) |
| GitHub `main` | `e51d9a8` | VPS 보다 1커밋 앞 — **핸드오프 문서만** (런타임 코드 무관) |
| 실행 컨테이너 | api = **`2026-09-03T08:51:26Z`** / scheduler = **`08:51:57Z`** 에 시작 | 배포 반영됨 (아래 §2 검증). 🚨 「Up N minutes」 같은 **상대 시각은 읽는 시점마다 달라지므로 쓰지 말 것** — 절대 시각으로 기록한다 |
| 포지션 보유 전략 | **8건** (전부 `STAGE1_OPEN`, 전부 레버리지 2) | §3 |
| 오늘(KST) 진입 | 자동 32건 / 수동 18건 | §4 |
| 오늘(KST) 실현손익 (진입일 기준) | 자동 **−36.91** / 수동 **+229.30** | §4 — 🚨 수동은 2건이 전부 |
| Kill-Switch | **OFF** (`is_enabled=false`, 2026-08-31 해제됨) | §6 |
| alembic 버전 | `0034_surge_ladder` | §6 |
| 스케줄러 프로세스 시작 | 9.5시간에 **14회** (= 오늘 배포 횟수와 일치, 크래시 루프 아님) | §7 ① — 「40분마다 재시작」이 아니다. 연속 가동 최장 **5h04m** |
| `chart_patterns` 테이블 | **0건** | §7 미해결 ① — 데이터 0 은 사실, 원인 단정은 금지 |

---

### 0.5 🚨🚨 새 PC 첫날 — 실제로 돈이 날아가는 5가지 (이 섹션을 먼저 읽어라)

이 문서의 나머지는 **조회**다. 아래 5개는 **한 줄로 실자금 사고가 나는 것들**이다.
지금 실계정에 **포지션 8건**(§3)이 물려 있고 스케줄러가 **초 단위로 주문을 낸다**.

| # | 절대 하지 마라 | 왜 — 무슨 일이 나는가 |
|---|---|---|
| **1** | 새 PC에서 `docker compose up` / `python -m app.workers.scheduler_runner` | 🚨 **가장 위험.** 실계정 API 키는 `.env` 가 아니라 **DB 에 암호화되어**(`exchange_accounts.api_key_enc` / `api_secret_enc`) 들어 있고, `.env` 의 **`DATABASE_URL`(운영 Neon) + `ENCRYPTION_KEY`** 두 개만 맞으면 **그대로 복호화된다**. 즉 로컬에서 띄우는 순간 **VPS 스케줄러와 같은 계정·같은 DB 에 붙은 두 번째 스케줄러**가 된다 → 같은 전략에 **중복 주문**, 단계 전환·손절이 **두 프로세스에서 동시에** 나간다. 이 저장소는 이미 「부분 손절 12~17초 뒤 전량 청산」 사고(Fix 326)를 겪었다 — 그건 **한 프로세스일 때** 얘기다. |
| **2** | 로컬에서 Binance REST 직접 호출 (조사 스크립트 포함) | 🚨 **IP ban(418)** 전력이 있다 (2026-08-26, 가드가 ban 을 스스로 연장). 새 PC 는 **새 IP** 다. 실계정 키가 VPS IP 화이트리스트에 묶여 있으면 실패하고, 안 묶여 있으면 **레이트리밋을 VPS 와 나눠 쓰다가 운영 계정 전체가 밴된다**. 시세·포지션은 전부 **VPS api 컨테이너를 통해** 보라 (§8). |
| **3** | 로컬에서 `alembic upgrade head` / `alembic downgrade` | 🚨 `alembic/env.py:27-30` 이 **`DATABASE_URL` 환경변수를 그대로 쓴다.** 그 값은 **운영 Neon DB** 다. 로컬에서 실행하면 **운영 DB 스키마가 바뀐다.** 현재 `0034_surge_ladder`. 마이그레이션은 **VPS 에서, 사장님 승인 후에만.** (참고: `pytest` 는 안전하다 — `tests/conftest.py:6` 이 인메모리 SQLite 를 쓴다.) |
| **4** | `git stash` / `git stash pop` | 🚨 이 저장소는 **worktree 를 공유**한다. stash 는 저장소 전역이라 다른 worktree 작업까지 빨아들이고, `pop` 이 충돌하면 **어느 쪽 것이었는지 복구가 어렵다.** 임시 보관이 필요하면 stash 말고 **브랜치를 새로 파서 커밋**하라 (`git switch -c wip/$(date +%m%d-%H%M) && git add -A && git commit -m wip`). |
| **5** | VPS 에서 `git pull` 을 「조회」라고 생각하기 | 🚨 `docker-compose.yml` 이 `.:/app` **바인드 마운트**다 (`backend/docker-compose.yml`, api·scheduler 양쪽). 즉 **`git pull` 하는 순간 컨테이너 안 파일이 바뀐다.** 재시작 전까지 실행 중인 프로세스는 **옛 코드와 새 코드를 섞어 import** 할 수 있다 (파이썬은 함수 안 import 를 그때그때 읽는다 — 이 저장소에 그런 지연 import 가 많다). **`git pull` = 배포의 시작이지 조회가 아니다.** |

#### 🚨 사고가 났을 때 — 지금 당장 멈추는 법 (외워 둘 것)

거래를 즉시 멈추는 **정식 경로는 Kill-Switch API** 다. DB 를 손으로 고치는 것보다 먼저 이것을 쓴다.

```
POST /api/v1/admin/kill-switch/{exchange_account_id}/enable      ← 멈춤
POST /api/v1/admin/kill-switch/{exchange_account_id}/disable     ← 해제
```
(`app/api/v1/admin/operations.py:257`, `:274` — 라우터 prefix 는 `app/api/router.py:26` 의 `/api/v1` + `/admin`. 로그인 토큰 필요, 계정 소유권 검증 있음.)

⚠️ **Kill-Switch 는 만능이 아니다** — 메모리 확정 사항(2026-08-26 「Kill-Switch 3대 공백」):
- KS 를 켜도 **증거금 주입은 계속된다**.
- **해제하는 순간 밀려 있던 알람이 일괄 발사**된다 → 해제 전에 무엇이 대기 중인지 먼저 보라.
- dust orphan 포지션 하나가 **계정 전체를 차단**한 전력이 있다.

더 확실하게 멈추려면 **스케줄러만** 세운다 (api 는 살려 두어야 화면·수동 청산이 된다).
🚨 이것은 **쓰기 작업이고 사장님 승인 사항**이다. 되돌리는 법을 같이 적어 둔다:
```bash
# 멈춤 (승인 후)
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose stop scheduler'
# 되돌리기
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose start scheduler'
```
⚠️ 스케줄러를 세우면 **자동 손절·단계 전환·재진입이 전부 멈춘다.** 포지션 8건이 무방비가 된다는 뜻이다 — 「멈추는 것」도 위험한 선택지다. 세웠으면 **화면에서 수동으로 지켜볼 것.**

---

### 1. Fix 300~327 이력 (한 줄 요약)

로컬 `git log` 기준. 전부 **2026-09-02~09-03 이틀 사이**에 만들어졌다.

아래 명령은 **저장소 루트**(`backend/` 가 아니다)에서 돌린다. `-60` 은 커밋이 더 쌓이면 모자라므로
Fix 299 커밋(`8010e6f`)까지 범위로 지정하는 편이 안전하다.

```bash
cd /path/to/binance-auto-trader          # 새 PC: git clone 한 디렉터리
git log --format='%h|%ad|%s' --date=format:'%Y-%m-%d %H:%M' 8010e6f~1..HEAD \
  | grep -E 'Fix 2?3?[0-9]{2}'
```
> 표 첫 줄의 Fix 299 도 함께 보려면 위처럼 범위를 쓴다. 원래 쓰던
> `git log … -60 | grep -E 'Fix (3[0-2][0-9])'` 은 **Fix 299 를 걸러내고**, 커밋이 60개 넘게
> 쌓이면 오래된 Fix 를 놓친다.

| Fix | 커밋 | 시각(KST) | 한 줄 요약 |
|---|---|---|---|
| 299 | `8010e6f` | 09-03 02:46 | 변동성 연동 TP1 — 급등락 15% / 안정 3~5% |
| **300** | `9b51273` | 09-03 03:18 | 추가(피라미딩) 진입 트리거 ROI 를 하드코딩 → **설정**으로 (사장님 「+2%부터」) |
| **301** | `560e8fb` | 09-03 03:27 | 재진입 「대기 모니터링」을 Redis+API 로 화면에 남긴다 (99% 잔량은 쓸 수 없음이 밝혀져서) |
| **301b** | `b21c59a` | 09-03 03:31 | 재진입 대기 화면 = 「종료 숨김」과 **독립된** 접이식 패널 |
| **302** | `4619735` | 09-03 06:34 | 🚨 손실률 분모가 틀렸다 — `isolatedMargin` → **`isolatedWallet`** (−96.74% 로 뜨던 게 실제 −49.85%) |
| **303** | `b6fc9a2` | 09-03 07:06 | BTC/ETH 계열 11종 자동매매 제외 (MIN_NOTIONAL > 10 이라 「10 USDT 남기기」 불가) |
| **304** | `807fa26` | 09-03 07:15 | 단계 전환 시 「10 USDT 만 남기고 청산」 = 물타기 → 손절 후 재진입. **기본 OFF** |
| **305** | `030ebd9` | 09-03 07:32 | Fix 304 의 차단 요인 5건 (재시도가 잔량까지 던짐 / 전량 폴백이 단계 LIMIT 삭제 / 시세오류 알림폭탄 / 사각지대 영구정지 / 수동 ▶다음단계가 정리 건너뜀) |
| **306** | `33b88df` | 09-03 08:02 | 단계 청산으로 **확정된 손실이 화면·손절 판정에서 사라지던** 것 — 화면 realized 합산 + 누적손실 상한 게이트 + retry/정리 모드 충돌 가드 |
| **307** | — | — | ⚠️ 독립 커밋 없음 (306 또는 308 에 흡수된 것으로 보임 — **확인 못 함**) |
| **308** | `f8a052b` | 09-03 08:23 | 🚨 OBV 자동 30일 0건의 진짜 이유 — **이벤트 이름 불일치** (`FORCE_STOP_LOSS_TRIGGERED` 를 기록하는데 워커는 존재하지 않는 3개 이름을 조회) |
| **309** | `8c91bba` | 09-03 08:32 | OBV 알람을 `market_observations` 에 관찰 기록으로 남긴다 (Redis TTL 24h 라 사후 검증 불가였음) |
| **310** | `eb27d39` | 09-03 08:38 | 당일 **\|24h\| ≥ 10%** 심볼만 신규 진입 (`start_stage1` 한 곳에만, 단계 진입엔 미적용, 수동 `_quick_` 제외) |
| **311** | `defa0d7` | 09-03 09:01 | 1단계(10 USDT)는 정리하지 않는다 — 청산분이 잔량의 2배 미만이면 스킵 |
| **312** | `defa0d7` | 09-03 09:01 | 다음 단계는 「좋은 포지션」을 기다린다 (Fix 276 꺾임 판정, **SHORT 만** 기본 적용) |
| **313** | `d42b23c` | 09-03 09:16 | 🚨 Fix 304 부분손절이 **전역 스위치 1개**라 볼밴 분할(`split_entry`, 일부러 물타기하는 설계)을 파괴 → `split_entry` 코드 레벨 제외 |
| **314** | `d42b23c` | 09-03 09:16 | 🚨 「설정만 수정」이 `trigger_mode` 미복사로 **OBV 전략을 기본전략으로 영구 강등** |
| **315/317** | `aec3208` | 09-03 09:52 | 🚨 다단계 전략에서 **손절이 마지막 단계까지 보류**되던 v130 교착 |
| **316** | `65fbc8c` | 09-03 09:48 | 내가 만든 Fix 311 이 사장님 사양을 통째로 막고 있었다 (SKIP/BLOCK 분리 도입) |
| **318** | `8e0fc72` | 09-03 09:56 | 손절도 「10 USDT 남기는 부분 손절」이어야 하는데 전량 청산으로 나가고 있었다 |
| **319** | `7fcd332` | 09-03 10:03 | 🚨 Fix 318 이 **엉뚱한 함수**에 붙어 있었다 — 사장님 손절은 `_execute_force_stop_loss` 로 간다 |
| **320** | `77edfc9` | 09-03 10:34 | 손절 실행 경로 **통합(실행) 테스트** 신설 — 정적 검사 13건이 못 잡던 사고를 즉시 잡음을 증명 |
| **321** | `ddb8fb6` | 09-03 10:45 | 🚨 내가 Fix 315 로 손절을 다시 잠갔다 (`stage_ladder` 마커 대입 0곳) — **검증이 잡았고 실피해 0**. 게이트 면제를 3곳 전부에 적용 |
| **322** | `fcd8462` | 09-03 10:51 | 기본 방식: **손절 ROI 가 명시된 전략은 단계 게이트를 면제** (스위치 하나에 손절이 매달려 있던 것) |
| **323** | `fcd8462` | 09-03 10:51 | OBV 자동이 2단계에 영원히 도달 못하던 것 (Fix 177 의 우회가 정상 단계진입을 통째로 스킵) |
| **324** | `61e19a8` | 09-03 15:55 | 사장님 수치로 확정 — 「10 usdt」는 **증거금**(명목 = 10×레버), 1단계는 **정리하지 않는다**(SKIP) |
| **325** | `0459e8f` | 09-03 16:50 | 진입 대상을 절대값 → **「상승 50 + 하락 50 = 100개」 순위**로 (`entry_chg24_gate_mode` 기본 `rank`) |
| **326** | `1d04598` | 09-03 17:25 | 🚨 남긴 10 USDT 를 **다음 사이클이 전량 청산**하고 있었다 (`ACTION_SKIP` 을 전량으로 처리) |
| **327** | `ded22f3` | 09-03 17:51 | 차트분석 에이전트팀 — 지지선 **7점 판정**을 진입에 배선. **기본 OFF** (`support_score_gate_enabled`) |

🚨 **Fix 315→321, 318→319→321, 311→316→324, 304→305→326 은 「내가 만든 것을 내가 되돌린」 연쇄다.** 새 PC에서 이 영역(부분 손절 / 단계 게이트)을 건드릴 때는 반드시 `tests/test_stage_flow_execution.py`, `tests/test_sajangnim_ladder_numbers.py`, 손절 실행 테스트(Fix 320)를 먼저 돌려라.

---

### 2. 배포 상태 — VPS vs 로컬

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader && git log -1 --format="%H %ad %s" --date=iso'
```

출력:
```
ded22f3ed23018313410287f387c5002613a6f79 2026-09-03 17:51:09 +0900 feat(Fix 327): 차트분석 전문가 에이전트팀 — 지지선 7점 판정을 진입에 배선
```

| 위치 | 커밋 | 상태 |
|---|---|---|
| VPS `~/binance-auto-trader` (branch `main`) | `ded22f3` | Fix 327 까지 배포 완료 |
| 로컬 워크트리 `claude/infallible-euler-6dc297` | `e51d9a8` | 조사 시점엔 `ded22f3` 로 VPS 와 일치했고, 그 뒤 **핸드오프 문서 커밋 1개**(`e51d9a8`)가 얹혔다. `backend/app/` 실행 경로 차이 **0건** — 재검증 시 `git log -1` 이 `e51d9a8` 로 나와도 정상이다 |
| GitHub `refs/heads/main` | `e51d9a8` | VPS 보다 **1커밋 앞** |
| 로컬 `main` 브랜치 (워크트리 밖) | `2586555` (Fix 292c) | 🚨 **25커밋 뒤처짐** — 새 PC에서 clone 하면 이 문제는 사라진다 |

**VPS 가 1커밋 뒤처진 것은 무해하다** — `e51d9a8` 은 `chore(handoff): 저장소 밖 자산을 저장소 안으로` 이고 diff 102개 파일 전부 `docs/handoff/...` 및 `wip-backup-*` 백업 사본이다. `backend/app/` 실행 경로 변경 **0건**.

직접 확인하는 법 (저장소 루트에서):
```bash
git diff --stat ded22f3 e51d9a8 | tail -1          # → 102 files changed, 13150 insertions(+)
git diff --name-only ded22f3 e51d9a8 | sed -E 's#/.*##' | sort | uniq -c   # → 102 docs  (docs/ 뿐)
git diff --stat ded22f3 e51d9a8 -- backend/app | wc -l                     # → 0  ★ 실행 경로 무변경
```
마지막 줄이 **`0`** 이면 「VPS 가 1커밋 뒤처져도 무해하다」가 증명된 것이다.

#### 🚨 「배포됐나」 판정은 파일 mtime 이 아니라 **프로세스 시작 시각과 대조**해야 한다 (메모리 확정 교훈)

🚨 `docker inspect -f "{{.State.StartedAt}}" A B` 는 **시각만 두 줄** 뱉어서 어느 컨테이너 것인지 알 수 없다.
반드시 `{{.Name}}` 을 같이 넣어라. `date -u` 도 함께 찍어야 「이 시각이 몇 분 전인지」를 스스로 계산할 수 있다.

```bash
ssh root@159.65.137.250 'docker inspect -f "{{.Name}} {{.State.StartedAt}}" binance-auto-trader-api binance-auto-trader-scheduler; date -u; stat -c "%y %n" ~/binance-auto-trader/backend/app/services/execution_service.py'
```

실제 출력 (2026-09-03 재검증, **가공하지 않은 원문**):
```
/binance-auto-trader-api 2026-09-03T08:51:26.932467002Z
/binance-auto-trader-scheduler 2026-09-03T08:51:57.679240765Z
Thu Sep  3 09:38:43 UTC 2026
2026-09-03 08:51:24.932421513 +0000 /root/binance-auto-trader/backend/app/services/execution_service.py
```
파일 수정(08:51:24) → api 시작(08:51:26) → scheduler 시작(08:51:57) 순서이므로 **현재 실행 중인 코드가 `ded22f3` 이다.**
(반대로 파일 mtime 이 시작 시각보다 **뒤**면 = 파일만 바뀌고 재시작이 안 된 것 = **미배포**다.)
컨테이너 안에서도 확인:

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T api grep -c support_score_gate_enabled /app/app/services/execution_service.py'
```
→ `1` (Fix 327 마커 존재)

#### 컨테이너 현황

🚨 `docker compose` 는 `docker-compose.yml` 이 있는 **`~/binance-auto-trader/backend`** 에서만 돈다.
`cd` 를 빼면 `no configuration file provided` 로 실패한다 — 이 문서의 모든 compose 명령에 `cd` 가 붙어 있는 이유다.

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ps --format "table {{.Name}}\t{{.Status}}"'
```

아래 「상태」는 **조사 시점(09:15 UTC) 스냅샷**이다. 지금 돌리면 숫자가 다르게 나오는 것이 정상이다
— 판정은 상대 시각이 아니라 위의 `StartedAt` 절대 시각으로 하라.

| 컨테이너 | 상태 (조사 시점) |
|---|---|
| `binance-auto-trader-api` | Up 9 minutes (= `08:51:26Z` 시작) |
| `binance-auto-trader-scheduler` | Up 9 minutes (= `08:51:57Z` 시작) |
| `binance-auto-trader-user-stream` | Up 22 hours |
| `binance-auto-trader-mark-price-stream` | Up 8 days |
| `binance-auto-trader-db` | Up 3 weeks — 🚨 **비어 있는 껍데기. 실 DB 는 외부 Neon** |
| `binance-auto-trader-redis` / `prometheus` / `grafana` / `db-backup` | Up 3 weeks |

#### ⚠️ VPS 작업트리에 커밋 안 된 파일 31개

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader && git status --short'
```
31개 전부 `??`(untracked)이고 전부 `backend/*.py` 형태의 **1회용 조사 스크립트**(`analyze_stopped.py`, `flip_v4.py`, `loss24.py` 등)다. 추적 파일 변경은 **0건**이다. 다만 새 PC에서 clone 해도 이 파일들은 오지 않으니 **VPS 에만 있는 일회용 자산**임을 알아둘 것.

> 🚨 **「추적 파일 변경 0건이니 `git pull` 이 안전하다」는 결론으로 넘어가지 마라.** 두 가지가 더 걸린다.
> 1. **untracked 도 pull 을 막는다.** 앞으로 저장소에 `backend/loss24.py` 같은 **같은 이름의 파일이 추가되면** git 이 `error: untracked working tree files would be overwritten by merge` 로 **중단**한다. 그때 `-f`·`checkout .`·`clean -fd` 로 밀어붙이지 마라 — 조사 스크립트가 사라진다. 막히면 **그 파일만 `mv` 로 옮기고** 다시 pull 하라.
> 2. **`git pull` 자체가 배포다** (§0.5 #5, 바인드 마운트). 당겼으면 **반드시 재시작까지 이어져야** 코드가 일관된 상태가 된다 — 「당겨만 놓고 나중에」가 가장 위험하다.
>
> **되돌리는 법 (배포 롤백)** — 🚨 사장님 승인 후에만:
> ```bash
> # 1) 현재 커밋을 먼저 적어 둔다 (이게 없으면 되돌릴 곳을 잃는다)
> ssh root@159.65.137.250 'cd ~/binance-auto-trader && git log -1 --format=%H'
> # 2) 되돌리기 = 옛 커밋으로 checkout (reset --hard 를 쓰지 마라 — untracked 31개와
> #    추적 파일 상태를 한꺼번에 날릴 위험이 있고, 실수 시 복구 지점이 사라진다)
> ssh root@159.65.137.250 'cd ~/binance-auto-trader && git checkout <되돌릴커밋>'
> # 3) 코드가 바뀌었으므로 재시작해야 반영된다 (재시작은 사장님)
> ```
> ⚠️ 롤백에 **alembic 되돌리기가 포함되면 얘기가 완전히 다르다.** 스키마를 내리면 데이터가 사라질 수 있다. 현재 `0034_surge_ladder`. **downgrade 는 이 문서의 권한 밖이다 — 사장님과 상의.**

---

### 3. 살아있는 전략 (포지션 보유) — **8건**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"\"\"
select si.id, si.symbol, si.side, si.status, st.name, si.current_stage,
       si.current_position_qty, round(si.unrealized_pnl::numeric,2), round(si.realized_pnl::numeric,2),
       si.leverage, si.force_sl_roi_override
from strategy_instances si left join strategy_templates st on st.id=si.strategy_template_id
where si.status not in (\x27STOPPED\x27,\x27COMPLETED\x27,\x27CANCELLED\x27,\x27FAILED\x27,\x27REENTRY_READY\x27)
order by si.id desc\"\"\")).fetchall(): print(r)
"'
```

> ✅ 위 명령은 **그대로 복사해 붙여넣으면 돈다** (2026-09-03 재실행 확인).
> `\x27` 는 작은따옴표(`'`)의 Python 이스케이프다 — 바깥 `'…'` 안에 `'` 를 못 넣기 때문에 쓴 우회이니 **고치지 마라**.
>
> 🚨 아래 표는 **살아 있는 데이터의 스냅샷**이다. 지금 돌리면 id·심볼은 같아도 **미실현 손익은 반드시 다르게 나온다**
> (재검증 시 실제로 `−0.82 → +1.22` 로 바뀌었다). 「숫자가 다르다」로 고장을 의심하지 마라.
> 구조(8건 / 전부 `STAGE1_OPEN` / 전부 레버 2)가 바뀌었는지만 보면 된다.
>
> 🚨 `force_sl_roi_override` 컬럼의 **원값은 양수**다 (`10.00` / `5.00` / `3.64`).
> 아래 표의 `−10%` 는 「ROI 가 −10% 이하면 발동」이라는 **의미로 부호를 붙인 것**이다 — DB 값과 부호가 다르다고 놀라지 마라.

| id | symbol | side | status | 단계 | 템플릿 (=전략 종류) | qty | 미실현 | 실현 | 레버 | 강제손절 |
|---|---|---|---|---|---|---|---|---|---|---|
| 2096 | ARCUSDT | SHORT | STAGE1_OPEN | 1 | `BB_MIDLINE_…` = 볼밴 중단선 | −2,765 | **−0.82** | −0.01 | 2 | −10% |
| 2093 | BRUSDT | LONG | STAGE1_OPEN | 1 | `_quick_…` = **수동** | 4,312 | **+57.33** | −0.08 | 2 | −3.64% |
| 2090 | MAGMAUSDT | LONG | STAGE1_OPEN | 1 | `_quick_…_inplace_…` = **수동** | 2,473 | **+19.80** | −0.20 | 2 | −5% |
| 2088 | CRDOUSDT | SHORT | STAGE1_OPEN | 1 | `BB_MIDLINE_…` | −1.19 | −0.12 | −0.03 | 2 | −10% |
| 2034 | PYTHUSDT | SHORT | STAGE1_OPEN | 1 | `BB_MIDLINE_…` | −3,483 | +0.39 | −0.10 | 2 | −10% |
| 2009 | MSTRUSDT | SHORT | STAGE1_OPEN | 1 | `AUTO_BB_…` | −0.16 | −0.25 | −0.01 | 2 | −5% |
| 2005 | BMNRUSDT | SHORT | STAGE1_OPEN | 1 | `AUTO_BB_…` | −0.86 | −0.19 | −0.01 | 2 | −5% |
| 1988 | TQQQUSDT | SHORT | STAGE1_OPEN | 1 | `AUTO_BB_…` | −0.28 | −0.18 | −0.01 | 2 | −5% |

**합계: 미실현 +75.96 / 실현 −0.45.** 이익의 거의 전부(+77.13)가 **수동 LONG 2건**이다.

전략 종류 판별 (템플릿 접두사 → 생산 워커):

| 접두사 | 생산자 | 근거 |
|---|---|---|
| `BB_MIDLINE_` | 볼밴 중단선 4종 (Fix 278 로 분리된 별도 전략) | `app/workers/bb_mid_line_worker.py:68` `TEMPLATE_PREFIX = "BB_MIDLINE"` |
| `AUTO_BB_` | `_create_auto_bb_strategy` (공용 진입 생성자) | `app/workers/auto_bb_breakdown_worker.py:1861` |
| `auto_bb_break_SAJANGNIM_TOP/BOTTOM` | v219 사다리 | `app/services/stage_entry_timing.py:23` — **현재 활성 0건** |
| `_quick_` / `DYNAMIC_*` | **사장님 수동** | `app/services/chg24_entry_gate.py` (게이트가 일부러 통과시킴) |

🚨 **8건 전부 `current_stage = 1`.** 사장님 3단 사다리(10/300/600)가 **2단계로 올라간 살아있는 전략이 지금 0건**이다. Fix 311/312/316/323/324/326 이 전부 이 문제를 겨냥한 수정이고, 그 효과는 **아직 실전에서 확인되지 않았다**.

#### 전체 상태 분포

| status | 건수 |
|---|---|
| STOPPED | 1,173 |
| COMPLETED | 290 |
| REENTRY_READY | 16 |
| STAGE1_OPEN | **8** |

⚠️ `REENTRY_READY` 16건은 **`created_at` 기준 2026-07-14 ~ 08-28 에 멈춘 좀비**다.
16건 중 **14건이 `_quick_`(수동)**, 2건이 `AUTO_BB_`(#1116 BLESSUSDT / #1272 MELANIAUSDT). 9월 들어 갱신 0건 = 최소 6일 방치. → §7 미해결 ⑦.

전량을 직접 뽑는 명령:
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"\"\"
select si.id, si.symbol, si.side, left(coalesce(st.name,\x27\x27),22), si.created_at::date
from strategy_instances si left join strategy_templates st on st.id=si.strategy_template_id
where si.status=\x27REENTRY_READY\x27 order by si.created_at\"\"\")).fetchall(): print(r)
"'
```

---

### 4. 오늘(KST 2026-09-03) 진입 — **진입일 기준** 집계

> 🚨 이 저장소의 확정 교훈: **청산일이 아니라 진입일**로 갈라야 한다.
> `created_at` 은 `timestamptz` 로 UTC 에 정확히 저장돼 있다 (pg TimeZone=GMT). KST 경계는 아래처럼 잡는다.

로컬에 `ops_today.py` 를 만들어 VPS 로 보낸 뒤 컨테이너 안에서 실행한다.
(아래 3 블록을 **위에서부터 차례로** 실행하면 끝난다. §8-3 에도 같은 3단계가 나온다.)

**① 로컬(새 PC)에서 파일 생성** — Git Bash 에서. 만들어지는 위치는 **현재 디렉터리**이니
`cd ~` 등으로 위치를 정해 두고 실행하라:

```bash
cat > ops_today.py <<'PYEOF'
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
SQL = """
select case when st.name like '%quick%' then '수동' else '자동' end as kind,
       case when si.started_at is null then '미진입' else '진입' end as entered,
       count(*) as n,
       round(sum(coalesce(si.realized_pnl,0))::numeric,2) as realized,
       round(sum(coalesce(si.unrealized_pnl,0))::numeric,2) as unrealized
from strategy_instances si
left join strategy_templates st on st.id = si.strategy_template_id
where si.created_at >= (date_trunc('day', (now() at time zone 'Asia/Seoul')) at time zone 'Asia/Seoul')
group by 1,2 order by 1,2
"""
for r in db.execute(text(SQL)).fetchall():
    print(" | ".join(str(v) for v in r))
PYEOF
```

**② VPS 로 보낸다:**
```bash
scp -o StrictHostKeyChecking=no ops_today.py root@159.65.137.250:/root/ops_today.py
```

**③ 컨테이너에 넣고 실행한다** (🚨 `PYTHONPATH=/app` 을 빼면 `ModuleNotFoundError`):
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose cp /root/ops_today.py api:/tmp/t.py && docker compose exec -T -e PYTHONPATH=/app api python /tmp/t.py'
```

> 🚨 **이 쿼리는 「2026-09-03」이 아니라 「오늘」을 본다.** `now()` 를 쓰기 때문에, 다른 날 실행하면
> 그날 KST 자정 이후 데이터가 나온다 — 아래 결과표와 숫자가 다른 게 정상이다.
> 특정 날짜를 보려면 `where` 절을 다음으로 바꾼다:
> ```sql
> where si.created_at >= (date '2026-09-03' at time zone 'Asia/Seoul')
>   and si.created_at <  (date '2026-09-04' at time zone 'Asia/Seoul')
> ```
>
> ⚠️ **수동/자동 분류는 `st.name like '%quick%'` 뿐이다.** §3 표에는 수동에 `DYNAMIC_*` 도 적혀 있지만
> 이 SQL 은 `DYNAMIC_*` 을 **자동으로 센다**. 오늘은 `DYNAMIC_*` 템플릿이 0건이라 결과가 같지만,
> 다른 날 재실행할 때는 `like '%quick%' or st.name like 'DYNAMIC%'` 로 바꿔야 §3 과 기준이 맞는다.

핵심 SQL (KST 경계 잡는 부분이 요점이다):

```sql
select case when st.name like '%quick%' then '수동' else '자동' end as kind,
       case when si.started_at is null then '미진입' else '진입' end as entered,
       count(*), round(sum(coalesce(si.realized_pnl,0))::numeric,2)
from strategy_instances si
left join strategy_templates st on st.id = si.strategy_template_id
where si.created_at >= (date_trunc('day', (now() at time zone 'Asia/Seoul')) at time zone 'Asia/Seoul')
group by 1,2;
```

#### 결과

| 구분 | 생성 | 실제 진입 | 미진입 | 실현손익 | 미실현 |
|---|---|---|---|---|---|
| **수동** (`_quick_`) | 18 | 18 | 0 | **+229.30** | +77.13 |
| **자동** | 32 | 14 | **18** | **−36.91** | −0.55 |
| ─ `BB_MIDLINE_*` | 29 | — | — | −29.12 | −0.55 |
| ─ `AUTO_BB_*` | 3 | — | — | −7.79 | 0.00 |

> ✅ 재검증(같은 날 09:38 UTC): 건수 18/14/18 과 실현손익 `+229.30` / `−36.91` 이 **글자 그대로 재현**됐다.
> 다만 미실현은 `+77.13 → +63.88` 로 달라졌다 — **미실현은 시세라서 매번 다르다.** 재현 여부는 **실현손익과 건수**로만 판단하라.

#### 🚨 수동 +229.30 은 「자동보다 잘했다」는 뜻이 아니다

18건 중 **2건이 전부**다:

| id | symbol | side | 실현 |
|---|---|---|---|
| 2032 | AKEUSDT | SHORT | **+280.14** |
| 2094 | BULLAUSDT | LONG | **+138.72** |
| **나머지 16건 합계** | | | **−189.56** |

그리고 메모리에 기록된 **반복 패턴이 오늘도 그대로 재현됐다**:
- `AKEUSDT` 수동 진입이 **하루에 7건** (2032/2035/2036/2038/2039/2040/2041/2046) — 큰 이익(+280.14) 직후 같은 종목 반복.
- 그 7건의 합계는 **+240.02** 이지만, 첫 건(+280.14)을 빼면 **−40.12**.
- 16:43~16:53 **10분 사이에 수동 7건 연속 진입** (2089~2095) → 합계 **+53.36**, 그중 BULLA(+138.72) 빼면 **−85.36**.
- 🚨 메모리 확정: `_quick_` 수동 경로에는 **중복 진입 가드가 없다**.

#### 🚨 자동 32건 중 18건이 「생성만 되고 진입 못함」

전부 `BB_MIDLINE_*` 이고 `started_at IS NULL`, `realized_pnl = 0.00` 이다 (11:07 에 11건, 13:22 에 4건, 13:37 에 3건 등 배치로 생성). 이 워커가 후보를 만들고 **진입 관문에서 걸러진 뒤 STOPPED 로 정리되는 흐름**으로 보이나, 어느 게이트가 걸렀는지는 **⚠️ 확인 못 함** (로그에 전략 id 로 추적 가능한 차단 사유가 남아 있지 않다).

#### 참고 — 일일 리스크 테이블(청산일·UTC 기준)은 숫자가 다르다

```
account_daily_risk_limits: 2026-09-03 → realized −39.92 (status ACTIVE)
```
위 진입일 기준 합계(+192.39)와 다른 것이 **정상**이다. 하나는 청산일·UTC, 하나는 진입일·KST 다. **두 숫자를 섞어 쓰지 말 것.**

---

### 5. 최근 로그의 반복 패턴 상위 (스케줄러, 2026-09-02 23:32 ~ 09-03 09:06 UTC = 약 9.5시간)

> ⚠️ **아래 첫 명령은 「조회」가 아니라 운영 서버에 파일을 쓰는 명령이다.**
> `> /root/sch.log` 는 **매번 약 52 MB** 를 VPS 디스크에 쓰고, 같은 이름이므로 **기존 파일을 말없이 덮어쓴다**.
> 현재 여유는 `48G 중 24G` (실측 `df -h /` → `51% used`)라 한 번은 문제없지만, **습관적으로 매일 돌리면 쌓인다.**
> 파일을 남길 필요가 없으면 **쓰지 말고 파이프로 바로 흘려라** — 이게 진짜 읽기 전용이다:
> ```bash
> ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --no-color --tail 200000 scheduler 2>&1 | grep -E " WARNING " | head -50'
> ```
> 굳이 파일로 받아야 하면 **이름에 날짜를 넣어 덮어쓰기를 피하고**, 다 쓴 뒤 **경로를 눈으로 확인하고** 지운다:
> ```bash
> # 🚨 rm 이다. 경로에 오타가 나면 다른 것이 지워진다. 반드시 ls 로 먼저 확인할 것.
> ssh root@159.65.137.250 'ls -la /root/sch-2026-09-04.log'      # ← 먼저 이걸로 확인
> ssh root@159.65.137.250 'rm -i /root/sch-2026-09-04.log'       # ← 그 다음에만
> ```
> `rm -rf`, 와일드카드(`rm /root/*.log`), `rm` + 변수 조합은 **쓰지 마라.** 실자금이 도는 서버다.

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --no-color --tail 200000 scheduler > /root/sch.log; wc -l /root/sch.log'
```
```bash
ssh root@159.65.137.250 'grep -E " WARNING " /root/sch.log | sed -E "s/^.*WARNING //; s/[A-Z0-9]+USDT//g; s/[0-9]+(\.[0-9]+)?/N/g" | cut -c1-95 | sort | uniq -c | sort -rn | head -18'
```

로그 레벨 분포를 세는 명령 (근거):
```bash
ssh root@159.65.137.250 'for L in INFO WARNING ERROR; do printf "%-8s %s\n" "$L" "$(grep -c " $L " /root/sch.log)"; done'
```
→ **INFO 156,904 / WARNING 42,780 / ERROR 6** (합 199,690 ≈ 200,000줄. 재검증에서 **글자 그대로 재현**됐다.)

> 🚨 **「9.5시간」은 `--tail 200000` 이 마침 그만큼을 덮은 결과이지, 고정된 창이 아니다.**
> 로그가 더 빨리 쌓이는 날에는 같은 20만 줄이 **더 짧은 시간**만 덮는다. 시간으로 자르고 싶으면
> `--tail 200000` 대신 `--since 24h` 를 써라 (§8-6).

> 🚨 **아래 「건수」는 정확한 총계가 아니라 위 `sed`+`cut -c1-95` 파이프라인이 만든 버킷 크기다.**
> 심볼 치환 `s/[A-Z0-9]+USDT//g` 가 **소문자·한자 심볼(`龙虾USDT` 등)을 못 지우고**, 남은 길이 차이 때문에
> 같은 메시지가 여러 버킷으로 갈린다. 실제로 1위 메시지의 **진짜 총계는 27,257건**인데 표에는 26,906 으로 잡혔다
> (재실행하면 26,690 처럼 또 달라진다 — `cut -c` 는 로케일에 따라 바이트/문자 기준이 갈린다).
>
> **정확한 건수가 필요하면 메시지 원문을 직접 세라** (로케일·자르기와 무관):
> ```bash
> ssh root@159.65.137.250 'grep -c "소소한 반등 = LONG 아님" /root/sch.log'          # → 27257
> ssh root@159.65.137.250 'grep -c "auto_long_at_bottom_worker" /root/sch.log'      # → 43285
> ```
> 순위표는 **「무엇이 로그를 지배하는가」를 보려는 용도**다. 건수를 근거로 인용하지 마라.

| # | 건수(버킷) | 워커 | 패턴 = 무엇을 막고 있나 |
|---|---|---|---|
| 1 | **26,906** (실제 27,257) | `auto_long_at_bottom_worker` | `🚫 <SYM> 소소한 반등 = LONG 아님 — OBV 회복 부족` |
| 2 | 4,569 | `auto_long_at_bottom_worker` | `SKIP: 지표 꺾임 N/N (아직 …)` |
| 3 | 3,869 | `auto_short_at_top_worker` | `SKIP: 지표 꺾임 N/N` |
| 4 | 2,098 | `realtime_reentry_worker` | `LONG 재진입 차단: 지표 꺾임` |
| 5 | 1,126 | `realtime_reentry_worker` | `완료: scanned=N candidates=N reentered=N` (요약 로그가 WARNING) |
| 6 | 1,111 | `resistance_reversal_worker` | `DONE: {scanned, approached, reversed, entered}` (요약) |
| 7 | 1,043 | `peak_break_reversal_worker` | `DONE: {scanned, processed, entered, errors}` (요약) |
| 8 | **432** | `apscheduler` | 🚨 `Run time of job … was missed by 0:00:01` = **misfire** |
| 9 | 149 | `macd_reversal_15m_worker` | `완료: scanned/detected/skipped` (요약) |
| 10 | **147** | `auto_bb_breakdown_worker` | `🚫 <SYM> SHORT 진입 차단 — 합의 판정 AVOID` (Fix 247 합의 게이트) |

**읽는 법:**
- 1~4위(총 **37,442건**)는 **진입 게이트가 정상적으로 후보를 거르는 소리**다. 고장이 아니다. 다만 `auto_long_at_bottom_worker` 혼자 로그의 **43,285줄(전체의 22%)** 을 쓴다 — 로그 노이즈로 다른 신호를 덮는다.
- 5~7·9위는 **정상 완료 요약인데 WARNING 레벨**로 찍힌다. 🚨 **「WARNING 42,780건」을 보고 놀라지 마라. 진짜 문제는 6건의 ERROR 와 432건의 misfire 다.**
- 10위 = Fix 247 합의 게이트가 9.5시간에 **147건 차단** = 살아서 일하고 있다.
- chg24 진입 게이트 로그는 **`[Fix310]` 76건 / `[Fix325]` 0건**이다 (아래로 재현 가능. 초안의 「125건」은 어떤 grep 으로 센 것인지 근거가 없어 **삭제했다**):
  ```bash
  ssh root@159.65.137.250 'grep -c "Fix310" /root/sch.log; grep -c "Fix325" /root/sch.log'   # → 76 / 0
  ```
  🚨 **`Fix325` 가 0 이라고 「Fix 325 가 안 돈다」로 읽지 마라.** ① Fix 325 는 **17:51 KST 배포분**이라 이 로그 창(≈09:06 UTC 까지)에 **15분밖에 안 들어 있고**, ② `chg24_entry_gate.py:158,174` 의 `[Fix325]` 로그는 **fail-open(조회·산출 실패) 때만** 찍힌다. **0 = 실패 0건**이라는 뜻이다. 정상 차단은 `[Fix310] <SYM> 진입 차단: 24h ±N%` 로 남는다.

#### misfire 분포 (🚨 §7 미해결 ① 의 직접 증거)

```bash
ssh root@159.65.137.250 'grep -oE "trigger: interval\[[0-9:]+\][^)]*\)\" was missed" /root/sch.log | grep -oE "interval\[[0-9:]+\]" | sort | uniq -c | sort -rn'
```
```
174 interval[0:00:30]    146 interval[0:05:00]     33 interval[0:03:00]
 21 interval[0:00:15]     20 interval[0:01:00]     16 interval[0:15:00]
 12 interval[0:30:00]      7 interval[0:02:00]      3 interval[1:00:00]
```
🚨 **`interval[6:00:00]` 이 목록에 아예 없다.** 6시간 잡은 misfire 조차 안 난다 — **한 번도 실행 시각에 도달하지 못했기 때문**이다 (§7 ①).

#### ERROR 6건 = 전부 같은 것 (🚨 새로 발견)

```bash
ssh root@159.65.137.250 'grep -m1 -A14 " ERROR \[apscheduler" /root/sch.log'
```
```
File "/app/app/workers/mainnet_safety_worker.py", line 139, in _check_exchange_accounts
    "name": a.name,
AttributeError: 'ExchangeAccount' object has no attribute 'name'
```
**1시간 주기 잡이 매번 100% 실패**한다 — UTC `02:52 / 03:52 / 04:52 / 05:52 / 06:52 / 07:56` = **6회/9.5h**.
「정각」이 아니라 **`52분`**(= 스케줄러 시작 시각에서 1시간씩 더해진 자리)이므로, 로그에서 찾을 때 정각을 뒤지지 마라.
단서는 ERROR 한 줄에 찍히는 **`trigger: interval[1:00:00]`** 이다. → §7 미해결 ⑤.

---

### 6. 현재 설정 스냅샷 (`system_settings` 63행 전량)

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for k,v in db.execute(text(\"select key, left(value,60) from system_settings order by key\")).fetchall(): print(k, \"=\", v)
"'
```

#### 🚨 실자금에 직접 영향을 주는 스위치 (지금 켜져 있는 것)

| 키 | 값 | 의미 |
|---|---|---|
| `stage_trim_before_next_enabled` | **1 (ON)** | 🚨 단계 전환 시 「10 USDT 만 남기고 청산」 = Fix 304/324/326 이 실제로 돈다 |
| `stage_wait_for_turn_enabled` | **1 (ON)** | Fix 312 — 다음 단계는 꺾임을 기다린다 (SHORT 만) |
| `sajangnim_ladder_stages_enabled` | **1 (ON)** | 🚨 Fix 315. **Fix 321 때 긴급히 0 으로 껐다가 오늘 16:22 KST 에 다시 1 로 켰다** |
| `entry_chg24_gate_enabled` | **1 (ON)** | Fix 310/325 진입 대상 제한 |
| `adaptive_tp_enabled` | **1 (ON)** | 🚨 켜져 있는데 **v219 경로에만 배선돼 있다** → §7 ④ |
| `auto_obv_enabled` | 1 (ON) | OBV 자동 (일 3건 / 건당 400 USDT = 최대 노출 1,200) |
| `confluence_gate_enabled` | true | Fix 247 합의 게이트 (9.5h에 147건 차단) |
| `force_sl_unlock_unreachable_stage` | true | Fix 235 |
| `pump_split_enabled` / `pump_split_capitals` | 1 / `100,200,500` | 볼밴 분할 (일부러 물타기하는 설계 — Fix 313 이 부분손절에서 제외) |
| `sajangnim_capital_ladder` | `10,300,600` | 사장님 3단 사다리 |
| `sajangnim_pyramid_trigger_roi` | **2** | Fix 300 — 사장님 「+2%부터」 |
| `bb_mid_line_mode` | on | 볼밴 중단선 = **현재 활성 전략 4/8건의 출처** |
| `trend_4h_gate_enabled` / `long_surge_gate_enabled` | 1 / 1 | |
| `scheduled_entry_enabled` | 1 | |
| `split_peak_stall_enabled` | 1 | Fix 260 정점-주춤 |
| `force_sl_short_enabled` = `true`<br>`force_sl_long_roi` = **80**<br>`force_sl_short_roi` = **80** | 🚨 | **§7 ③ 을 읽기 전에 이 세 줄을 먼저 보라 — 초안에는 빠져 있었다.** 이건 **전역 백스톱**이고 값이 **ROI −80%** 다(양수로 저장, `ROI <= -80%` 에서 발동).<br>우선순위는 `app/services/risk_service.py:381-390` 이 명시한다 — *「전역 설정(모든 전략 기본) + 전략별 override 우선 (NULL = 전역 상속)」*, `resolve_force_sl(override_…, global_…)`.<br>→ 지금 살아 있는 8건은 **전부 `force_sl_roi_override`(3.64 / 5 / 10)를 갖고 있어 이 80 은 적용되지 않는다.** 즉 §7 ③ 의 「전 경로 −5%」와 **모순이 아니다.**<br>키 정의: `app/core/risk_constants.py:71,73` |
| `sajangnim_max_stage` = `3` / `sajangnim_default_capital` = `50.0` | | 사다리 최대 단계 / 기본 자본 |
| `sajangnim_reentry_daily_limit` = `10` / `sajangnim_reentry_concurrent_slots` = `10` | | Fix 262/263 (재진입 전용 한도·슬롯) |

#### 꺼져 있는 것 / 없는 것

| 키 | 상태 | 의미 |
|---|---|---|
| `support_score_gate_enabled` | **행 자체 없음 = OFF** | 🚨 **Fix 327(오늘 마지막 커밋)이 배포는 됐지만 켜지지 않았다.** 지지선 7점 판정이 진입에 전혀 영향을 주지 않는다 |
| `entry_chg24_gate_mode` | 행 없음 → 코드 기본 **`"rank"`** | `app/services/chg24_entry_gate.py:62` `MODE_DEFAULT = "rank"` → Fix 325 순위 방식이 기본으로 동작 |
| `entry_rank_top_n` / `entry_min_abs_chg24` | 행 없음 → 코드 기본 (50 / 10.0) | |
| `stage_keep_notional_usdt` / `stage_min_trim_ratio` / `stage_max_cumulative_loss_usdt` / `stage_trim_exclude_modes` | 행 없음 → 코드 기본 | 🚨 `stage_max_cumulative_loss_usdt` 미설정 = **누적 손실 무제한** (Fix 306 의 의도된 기본값) |
| `excluded_symbols` | 행 없음 → 코드 기본 목록 적용 | Fix 303 BTC/ETH 11종 제외가 코드 기본으로 작동 |
| `auto_bb_breakdown_enabled` | **0 (OFF)** | v224 통합으로 스케줄러에서도 주석 처리됨 (`scheduler_runner.py:307-318`) |
| `unified_entry_enabled` | **0 (OFF)** | 🚨 v224 「유일한 진입」으로 만들어 놓고 꺼져 있다 |
| `success_pyramiding_enabled` | 0 (OFF) | Fix 213 사고 이후 |
| `support_breakdown_short_enabled` | 0 (OFF) | |
| `surge_ladder_mode` | `shadow` | 실 진입 안 함 |
| `whitelist_enabled` | false | |
| `auto_obv_min_confidence` | 0.95 | 🚨 **가짜 게이트** — 한 번도 비교되지 않는다 (Fix 308 커밋에 명시) |

#### 안전장치 상태

```
account_kill_switches: is_enabled = FALSE
  reason_code   = ZOMBIE:ORPHAN_EXCHANGE_POSITION
  reason_message= 거래소 FLOCKUSDT SHORT 포지션 (amt=-550) 에 매칭 strategy 없음
  triggered_at  = 2026-08-31 01:43:26 UTC
  cleared_at    = 2026-08-31 01:45:26 UTC   ← 2분 만에 해제됨
```
→ **Kill-Switch 는 현재 OFF (정상 거래 중)**. 마지막 발동은 3일 전 좀비 포지션 때문이었다.

```
alembic_version = 0034_surge_ladder
account_daily_risk_limits (2026-09-03, UTC) = realized −39.92 / status ACTIVE
```

✅ **좋은 소식 — 지금은 밀린 마이그레이션이 없다.** 저장소의 최신 리비전 파일이 `alembic/versions/0034_surge_ladder_state.py` 이고 (총 32개), 운영 DB 의 `alembic_version` 도 **`0034_surge_ladder`** 다. **DB 와 코드가 같은 지점에 있다.**
```bash
ls backend/alembic/versions/ | sort | tail -3     # → 0032 / 0033 / 0034_surge_ladder_state.py
```
🚨 **그래서 지금 `alembic upgrade` 를 실행할 이유가 없다.** 새 PC에서 「일단 upgrade 한번 돌려보자」는 **하지 마라** — 로컬에서 돌리면 `DATABASE_URL` 때문에 **운영 DB 를 건드린다**(§0.5 #3).
⚠️ 반대로 **앞으로 `0035` 이후가 추가되면 그때는 배포 순서가 중요해진다** — 코드만 배포하고 마이그레이션을 빠뜨리면 **컬럼 없음 오류로 워커가 죽는다**(이 저장소는 「전 API 500」 사고 전력이 있다). 새 리비전이 생겼을 때의 배포 절차·순서는 **이 문서 범위 밖이다 — `vps-ops.md` 의 배포 절차를 따르고, 실행은 사장님이 한다.**

학습 파이프라인은 살아 있다: `market_observations` 최근 7일 **2,803건**, `trade_learning_records` 최근 7일 **385건**.

---

### 7. 미해결 과제 목록

#### ① 🚨 `chart_patterns` **0건** — 데이터 0 은 **확정(사실)**, 「6시간 잡이 굶어서」는 **유력 가설**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal; from sqlalchemy import text
print(SessionLocal().execute(text(\"select count(*) from chart_patterns\")).scalar())"'
```
→ **`0`**

세 가지가 겹쳐서 확정된다:

1. **잡 등록에 `misfire_grace_time` 이 없다** → APScheduler 기본값 **1초**.
   ```bash
   cd /path/to/binance-auto-trader     # 🚨 저장소 루트. backend/ 안에서 돌리면 경로가 없어 "No such file" 이 난다
   git grep -n "misfire_grace_time" -- backend/app/
   ```
   → 출력 **0줄** (2026-09-03 재검증). `git grep` 이라 `__pycache__` 가 섞이지 않는다. `backend/app/workers/scheduler_runner.py:513-524` 를 보면 `chart_pattern_scan` 은 `IntervalTrigger(hours=6)` + `coalesce=True` 뿐이다.
2. **스케줄러 프로세스가 9.5시간에 14번 새로 시작했다.**
   ```bash
   ssh root@159.65.137.250 'grep -c "Scheduler started" /root/sch.log'
   ```
   → **`14`**. `IntervalTrigger(hours=6)` 는 start_date 가 없으면 **첫 실행이 프로세스 시작 6시간 뒤**로 잡히므로, 프로세스가 6시간을 못 버티면 그 주기 동안은 실행되지 않는다.

   🚨 **여기서 「평균 40분마다 재시작하는 크래시 루프」라고 읽으면 오진이다 — 재검증했다.** 실제 시각 분포:
   ```
   23:32 23:39 00:02 00:17 00:49 00:53 00:57 01:04 01:46 01:52
                    ← 5시간 04분 무중단 →
   06:56 07:57 08:25 08:52   (08:52 UTC = 17:51 KST = Fix 327 배포 시각과 정확히 일치)
   ```
   - **균등하지 않다.** 앞부분에 몰려 있고 **01:52 → 06:56 은 5h04m 연속 가동**이다.
   - 이 시각들은 **오늘 배포한 커밋 시각(Fix 300~327, 하루 20여 개)과 겹친다.** 즉 **배포 때문에 재시작한 것**이지 스스로 죽는 것이 아니다.
   - 도커 관점 확인: `docker inspect` → `RestartCount=4`, `OOMKilled=false`, `ExitCode=0`, 컨테이너 `Created=2026-08-22` (12일 전). **도커가 자동 복구한 흔적은 12일에 4번뿐**이다. 호스트도 `up 114 days`, 메모리 여유 6.2 GB.
   - ⇒ **「영원히 실행되지 않는다」는 과한 표현이다.** 정확히는 **「배포가 잦은 날에는 6시간을 못 채워 건너뛴다」**. 배포 없는 날이 하루 있으면 이론상 실행된다.
3. **로그에 흔적이 0건이다.**
   ```bash
   ssh root@159.65.137.250 'grep -ci "chart_pattern" /root/sch.log; grep -ci "changelog" /root/sch.log'
   ```
   → **`0`** / **`0`** (다른 6시간 잡인 `binance_changelog_monitor`(`scheduler_runner.py:580`)도 마찬가지로 0건).
   misfire 분포에도 `interval[6:00:00]` 이 **없다** — 실행 시각에 도달조차 못 했다는 뜻이다.

**결론(신뢰도 구분):**
- ✅ **사실** — `chart_patterns` 는 **0행**이다. 테이블은 스키마(17컬럼: `pattern_type`, `confidence`, `outcome_price_24h/48h/7d`, `outcome_max_favorable_pct` …)만 존재한다.
- ✅ **사실** — 최근 9.5시간 로그에 `chart_pattern` / `changelog` 흔적이 **0건**이고 `interval[6:00:00]` misfire 도 **0건**이다.
- 🔶 **가설(강함)** — 2026-08-16 에 만든 차트분석 팀(`ChartPatternLearningTeamLead`)이 **한 번도 성공적으로 돈 적이 없다.** 로그 보존 범위가 9.5시간뿐이라 **「지금까지 한 번도」는 관측 범위를 넘는 주장**이다. 이 저장소는 이런 확대 해석으로 여러 번 오진했다.

⚠️ **다만 「6시간 잡이 굶는다」가 `chart_patterns=0` 의 **유일한** 원인이라고 단정하지 마라.** 위 3근거가 보여주는 것은 「9.5시간 로그 안에서 실행 흔적이 없다」까지다. 아직 배제하지 못한 가설:
- 잡이 과거에 돌았지만 **`run_full_scan` 이 아무 행도 쓰지 않았다**(내부 조기 return / 예외를 `guarded_job` 이 삼킴).
- 6시간 잡 자체가 **`chart_patterns` 에 쓰는 경로가 아니다**.
확인 방법은 **재시작 없이** 가능하다 — 6시간 잡의 다음 실행 예정 시각을 직접 물어보면 된다. (읽기 전용)
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --no-color --since 24h scheduler 2>&1 | grep -iE "chart_pattern|ChartPattern|changelog" | head -20'
```

🚨 **이 문제를 「고치려고」 스케줄러 코드를 건드리는 것이 이 항목의 진짜 위험이다.**
`scheduler_runner.py` 는 **모든 자동매매 잡이 등록되는 파일**이다. 여기에 `misfire_grace_time` / `start_date` 를 넣는 수정은 배포 = **스케줄러 재시작**을 부르고, 재시작하면 **포지션 8건을 지키는 손절·단계 전환 잡이 잠깐 멈춘다.**
- `chart_patterns` 는 **학습용 데이터**다. 비어 있어도 **실매매는 지금 정상 작동한다**(§5 의 게이트 로그가 증거). **급하지 않다.**
- 고치더라도 **포지션이 0건인 시간**에, **사장님 승인 후**, `tests/` 를 돌린 뒤에 하라.
- 되돌리는 법: 이 변경은 `scheduler_runner.py` 한 파일이므로 `git revert <커밋>` → 재배포 → 재시작이면 원복된다.

#### ② 🚨 신설 스위치를 켤 UI·API 가 없다 — **확정 (사실)**

🚨 **`grep -r` 로 세면 새 PC 와 숫자가 달라진다. 반드시 `git grep` 을 써라.** 이유 두 가지:
> 1. `grep -r` 은 **`__pycache__/*.pyc`(컴파일된 바이트코드)까지 센다.** 예를 들어 `adaptive_tp_enabled` 는
>    `.py` 2개인데 `grep -r` 로는 **4** 로 나온다. **새로 clone 한 PC 에는 `.pyc` 가 없으므로 절반으로 떨어진다.**
> 2. `grep -r` 은 **커밋 안 된 작업 중 파일**까지 센다. 실제로 이 워크트리에는 조사 시점 이후 만들어진
>    커밋 전 파일(`app/api/v1/terminal.py`)이 있어서 `grep -r` 이 `api=2` 를 뱉는다 — **VPS 에 배포된 코드에는 없다.**
>
> `git grep` 은 **추적 중인 파일만** 보므로 새 PC 의 clone 과 결과가 항상 같다.

**저장소 루트**에서 실행한다 (`backend/` 아니다):

```bash
cd /path/to/binance-auto-trader
for k in support_score_gate_enabled entry_chg24_gate_enabled entry_rank_top_n \
  stage_trim_before_next_enabled stage_wait_for_turn_enabled sajangnim_ladder_stages_enabled \
  adaptive_tp_enabled stage_max_cumulative_loss_usdt excluded_symbols; do
  printf "%-38s api=%s ui=%s code=%s\n" "$k" \
    "$(git grep -l "$k" -- backend/app/api/ | wc -l)" \
    "$(git grep -l "$k" -- backend/app/static/ | wc -l)" \
    "$(git grep -l "$k" -- backend/app/services backend/app/workers | wc -l)"; done
```

실제 출력 (2026-09-03 재검증, `.pyc` 없는 **참값**):
```
support_score_gate_enabled             api=0 ui=0 code=2
entry_chg24_gate_enabled               api=0 ui=0 code=1
entry_rank_top_n                       api=0 ui=0 code=1
stage_trim_before_next_enabled         api=0 ui=0 code=3
stage_wait_for_turn_enabled            api=0 ui=0 code=1
sajangnim_ladder_stages_enabled        api=0 ui=0 code=1
adaptive_tp_enabled                    api=0 ui=0 code=2
stage_max_cumulative_loss_usdt         api=0 ui=0 code=1
excluded_symbols                       api=0 ui=0 code=1
```

<details><summary>참고 — 조사 때 쓴 원래 명령 (`.pyc` 포함이라 code 값이 부풀려져 있다)</summary>

```bash
cd backend && for k in support_score_gate_enabled entry_chg24_gate_enabled entry_rank_top_n \
  stage_trim_before_next_enabled stage_wait_for_turn_enabled sajangnim_ladder_stages_enabled \
  adaptive_tp_enabled stage_max_cumulative_loss_usdt excluded_symbols; do
  printf "%-38s api=%s ui=%s code=%s\n" "$k" \
    "$(grep -rl "$k" app/api/ 2>/dev/null | wc -l)" \
    "$(grep -rl "$k" app/static/ 2>/dev/null | wc -l)" \
    "$(grep -rl "$k" app/services app/workers 2>/dev/null | wc -l)"; done
```

그때의 출력 (조사 시점, `.pyc` 가 섞여 code 가 1씩 큼):
```
support_score_gate_enabled             api=0 ui=0 code=3
entry_chg24_gate_enabled               api=0 ui=0 code=2
entry_rank_top_n                       api=0 ui=0 code=2
stage_trim_before_next_enabled         api=0 ui=0 code=4
stage_wait_for_turn_enabled            api=0 ui=0 code=2
sajangnim_ladder_stages_enabled        api=0 ui=0 code=2
adaptive_tp_enabled                    api=0 ui=0 code=4
stage_max_cumulative_loss_usdt         api=0 ui=0 code=2
excluded_symbols                       api=0 ui=0 code=2
```
</details>

**9개 전부 `api=0 ui=0`.** 이 스위치들을 켜고 끄는 방법은 **`system_settings` 직접 쓰기**뿐이다.

> ⚠️ **`git grep` 대신 옛 `grep -rl` 을 쓰면 5개 키가 `api=2` 로 보인다** — 위 `git grep` 판을 쓰면 나지 않는 현상이다:
> ```
> support_score_gate_enabled  api=2   entry_chg24_gate_enabled  api=2   entry_rank_top_n  api=2
> stage_trim_before_next_enabled api=2   excluded_symbols  api=2
> ```
> **결론은 바뀌지 않는다.** 그 2건의 정체를 실제로 열어 보면:
> 1. `app/api/v1/terminal.py:954-955` — **docstring 안에 키 이름이 나열된 것뿐**이다. 그 엔드포인트(`GET /api/v1/terminal/symbol-status`)는 **명시적으로 읽기 전용**이고 docstring 자체가 *"진입 게이트 설정은 전부 `SystemSetting` 에만 있고 어떤 라우터·JS 로도 노출된 적이 없다"* 라고 적고 있다.
>    🚨 그리고 이 파일은 조사 시점 기준 **아직 커밋되지 않은 작업 중 파일**이라 **VPS 에도, 새 PC 의 clone 에도 존재하지 않는다** (`git grep` 이 0 을 내는 이유). 즉 **운영 코드에는 이 5건조차 없다.**
> 2. `app/api/v1/__pycache__/terminal.cpython-314.pyc` — **컴파일 캐시(바이너리)**. 소스가 아니다.
>
> 🚨 **이게 교훈이다: `grep -rl` 의 숫자만 보고 「API 가 있다」고 믿지 마라.** `__pycache__` 와 주석/문서열이 섞여 든다. 재현하려면 이렇게 좁혀라:
> ```bash
> cd backend && grep -rn "$k" app/api/ --include=*.py | grep -v __pycache__
> ```
> **「쓰는 엔드포인트가 있는가」는 라우트 데코레이터로 확인해야 한다** (`@router.post` / `@router.patch` 와 같은 줄에 그 키가 다뤄지는지).

🚨 **이것이 실무에서 왜 위험한가:** 오늘 Fix 321 때 `sajangnim_ladder_stages_enabled` 를 긴급히 0 으로 내렸다가 다시 1 로 올렸다. 즉 **이 스위치들의 사고 대응 경로가 「DB 에 손으로 upsert」 하나뿐**이다.

✅ **그렇다고 「멈출 방법이 아예 없다」는 뜻은 아니다 — 이 오해가 더 위험하다.**
급할 때는 **스위치를 하나씩 끄는 것보다 §0.5 의 두 경로가 먼저**다:
1. **Kill-Switch API** — `POST /api/v1/admin/kill-switch/{exchange_account_id}/enable` (`app/api/v1/admin/operations.py:257`). 토큰만 있으면 **DB 접속 없이** 계정 단위로 멈춘다. (한계는 §0.5 참조 — 증거금 주입은 계속되고, 해제 시 알람이 몰려 나간다.)
2. **`docker compose stop scheduler`** — 사장님 승인 후. 자동 손절까지 멈추므로 **멈춘 뒤 화면으로 지켜봐야 한다.**

> 🚨 **그렇다고 새 PC 의 로컬 `backend/.env` 에 운영 `DATABASE_URL` 을 채우지 마라.**
> 위 문장을 「그러니 새 PC에서 DB 에 직접 붙을 수 있게 해두자」로 읽으면 **정확히 반대의 사고**가 난다.
> `secrets.md` §0-2 실측: 사무실 PC 의 `.env` 는 이미 운영 Neon 을 가리키고 있고(비밀번호만 만료), `ENCRYPTION_KEY` 지문이 VPS 와 **완전히 같다.**
> → 로컬 `.env` 의 `DATABASE_URL` 만 최신값으로 채우는 순간 **mainnet API 키가 그대로 복호화되어, VPS 와 똑같은 실계좌로 매매하는 엔진이 하나 더 뜬다.**
> **위험 스위치를 끄는 정상 경로는 VPS 안에서다** — `ssh` → `docker compose exec -T -e PYTHONPATH=/app api python …` (§8 과 같은 형태, **쓰기는 사장님 승인 후**).
> 즉 새 PC가 확보해야 하는 것은 **DB 접속 문자열이 아니라 SSH 접속**이다 (§8 상단 🔑).

⚠️ 실제 값 변경은 쓰기이므로 이 조사에서는 하지 않았다. 필요할 때의 형태만 기록해 둔다 — **실행 전 반드시 사장님 승인**:
```
system_settings (key TEXT PK, value TEXT) 에 upsert 하는 방식.
현재 63행. 없는 키는 코드 기본값이 쓰인다.
```

🚨 **스위치를 바꾸기 전에 반드시 지킬 3가지 (안 지키면 되돌릴 수 없다):**

1. **바꾸기 전 값을 먼저 적어라.** 「행이 없었다」와 「값이 0이었다」는 **다르다**. 행이 없으면 코드 기본값이 쓰이고, `0` 을 넣으면 명시적 OFF 다. 이 저장소는 **「모름」을 「꺼짐」으로 표시한 fail-OFF 사고**(2026-08-28)와 **`0` 을 넣었더니 20 으로 둔갑한 사고**(Fix 107~110)를 둘 다 겪었다.
   ```bash
   # 되돌릴 지점 확보 — 읽기 전용
   ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
   from app.core.database import SessionLocal
   from sqlalchemy import text
   db = SessionLocal()
   r = db.execute(text(\"select key, value from system_settings where key = :k\"), {\"k\": \"바꿀키\"}).fetchall()
   print(r if r else \"행 없음 (= 코드 기본값 사용 중)\")
   "'
   ```
   출력을 **그대로 메모**해 둔다. 「행 없음」이었다면 되돌리기는 **값을 0 으로 넣는 것이 아니라 그 행을 지우는 것**이다.
2. **한 번에 하나만 바꿔라.** 오늘 하루에 Fix 315→321, 318→319, 304→326 연쇄 사고가 났다. 두 개를 동시에 바꾸면 **어느 쪽이 원인인지 영원히 모른다.**
3. **바꾼 뒤 「반영됐는지」를 로그로 확인하라.** 확인한 범위에서는 `system_settings` 를 **호출할 때마다 DB 에서 읽는다** (`app/services/system_settings_service.py` 에 캐시·`lru_cache` 없음, `chg24_entry_gate.py:100~117` 도 매 호출 조회). 즉 **다음 잡 주기에 자연히 반영되고, 스위치 하나 바꾸자고 컨테이너를 재시작할 이유가 없다.**
   ⚠️ 단 **전 설정 키를 다 확인한 것은 아니다.** 모듈 로드 시각에 상수로 읽는 키가 섞여 있을 수 있다 — 바꾼 뒤 **로그에 실제로 새 값이 나타나는지**를 보고 판단하라. 「재시작해야 반영되나?」를 추측으로 결론내지 말 것.

#### ③ 🚨 LONG 손절이 전 경로 −5% 인데 사장님 지시 문서는 −10% — **코드 사실은 확정, 「고쳐야 한다」는 결론은 아니다**

**저장소 루트**에서 (`backend/` 아니다):
```bash
cd /path/to/binance-auto-trader
git grep -n "force_sl_roi_override *=" -- backend/app/ | grep -v "=="
```
→ 18줄. 그중 아래 6개 경로가 **신규 전략에 −5% 를 박는 자리**다
(나머지는 `= None`(해제) · 화면 API · surge_ladder · `pump_split`(설정값 사용) · 주석).

| 경로 | 파일:줄 | 값 |
|---|---|---|
| 기본 방식 (화면 생성) | `app/services/strategy_service.py:578` | `force_sl_roi_override=D("5")` |
| auto_bb 공용 생성자 | `app/workers/auto_bb_breakdown_worker.py:1353`, `:1981` | `Decimal("5")` |
| LONG 저점 워커 | `app/workers/auto_long_at_bottom_worker.py:164` | `LONG_FORCE_SL_ROI = Decimal("5")` (`:1519`, `:1829` 에서 사용) |
| SHORT 고점 워커 | `app/workers/auto_short_at_top_worker.py:291` | `Decimal("5")` |
| 반전 워커 2종 | `peak_break_reversal_worker.py:455`, `resistance_reversal_worker.py:351` | `Decimal("5")` |

**LONG/SHORT 구분이 코드 어디에도 없다. 전부 −5%.**

정책 근거 (사장님 지시):
- `docs/spec/SAJANGNIM_3STEP_LADDER_2026-09-02.md:71` — `반대로 간다 → SHORT −5% / LONG −10% 손절`
- 같은 문서 `:88` — `손절은 −10%(SHORT 보다 넓게) — 변동이 크기 때문이다`
- 같은 문서 `:123` — `**4** | **LONG 손절이 −5%** | auto_bb 가 LONG 도 Decimal("5") | 사장님은 **−10%**. LONG 은 변동이 커서 −5% 면 노이즈에 잘린다.`
- 같은 문서 `:137` — `**③ LONG 손절을 −10% 로** — 사장님 명시 지시이고, LONG 승률 20%의 원인일 수 있다.`

🚨🚨 **여기서 「그럼 −10% 로 바꾸면 되겠네」로 가면 실제로 손실이 커진다. 반드시 아래를 먼저 읽어라.**

**「아직 안 한 것」이 아니다 — 한 번 했다가 실측으로 되돌린 것이다.**
`app/workers/auto_long_at_bottom_worker.py:141-164` 에 그 경위가 통째로 주석으로 남아 있다 (커밋 `b7d6694`, **Fix 253, 2026-09-01**):

| 시각 | 무슨 일 |
|---|---|
| 2026-08-24 | Fix 49 — 사장님 verbatim 「단계별 진입후 −5% 손실이면 청산하고 대기」 |
| 2026-08-25 | Fix 87 — **LONG 만 10% 로 상향.** 근거 = 「레버 2× + 15m 알트 노이즈 = 자연 노이즈 손절」 |
| **2026-09-01** | **Fix 253 — 실측이 그 근거를 반증해서 10% → 5% 로 복귀** |

Fix 253 이 제시한 실측(주석에 그대로 있다):
- LONG 이 **이틀 연속 승자 0명** (08-31 12건 0% / 09-01 11건 0%).
- 손절은 설정대로 정확히 작동했다(초과 중앙값 0.2%p). ⇒ **느슨한 손절이 승률을 올린 게 아니라 잃는 크기만 2배로 키웠다.**
- 「노이즈에 잘린다」도 사실이 아니었다 — 당시 **이익 중이던 LONG 13건의 최저 ROI 가 −0.1 ~ −4.3%**, 즉 **−5% 를 건드린 승자가 한 건도 없었다.**
- 추정 효과: 09-01 LONG **−143 → 약 −72**.

**즉 §7 ③ 의 「사장님 지시 −10%」와 코드의 −5% 는 「미이행」이 아니라 「정면 충돌」이다:**
- 사장님 지시 문서 `SAJANGNIM_3STEP_LADDER_2026-09-02.md` 는 **09-02**,
- 이를 되돌린 코드 결정 Fix 253 은 **09-01** — **지시가 하루 더 최신**이다.
- 그러나 그 지시의 근거(「LONG 은 −5% 면 노이즈에 잘린다」)는 **Fix 253 이 숫자로 반증한 바로 그 문장**이다.

🚨 **그러므로 새 PC에서 할 일은 「−10% 로 고치기」가 아니라 「사장님께 이 충돌을 그대로 보여드리기」다.**
숫자 없이 −10% 로 바꾸면 **패자 손실이 다시 2배**가 된다 — 이 시스템은 이미 그 경로를 한 번 갔다 왔다.
바꾸기로 결정된다면 **바꾸기 전에** 주석이 지정한 재측정을 먼저 하라:

> ⚠️ (`auto_long_at_bottom_worker.py:162-163` 원문) *되돌리려면 이 값만 10 으로 바꾸면 된다. 바꿀 때는 위 실측을 다시 재고 **「이익 중인 LONG 이 −5% 아래로 간 적이 있는가」**를 확인할 것.*

⚠️ 또한 이 값은 **한 곳이 아니다** — 위 표의 **6개 파일**을 모두 바꿔야 일관된다. 하나만 바꾸면 **경로마다 손절이 다른** 상태가 되고, 그게 이 저장소가 반복해서 당한 사고 유형이다. 되돌리는 법은 `git revert` 로 한 커밋에 묶어 두는 것 — **6곳을 한 커밋에** 담아라.

(예외적으로 `pump_split_sl_roi = 10` 은 볼밴 분할 전용으로 설정에 존재한다.)

#### ④ 🚨 적응 TP 가 v219 경로에만 배선 — **확정 (사실), 게다가 스위치는 켜져 있다**

**저장소 루트**에서 (`git grep` 이라 `__pycache__` 가 안 섞인다):
```bash
cd /path/to/binance-auto-trader
git grep -n "from app.services.adaptive_tp\|adaptive_tp import" -- backend/app/
```
실제 출력 — **단 한 줄** (2026-09-03 재검증):
```
backend/app/workers/auto_bb_breakdown_worker.py:1827:        from app.services.adaptive_tp import (
```

- `app/services/adaptive_tp.py` 는 존재하고 `adaptive_tp_enabled` / `pick_tp1` / `tp_ladder_from_tp1` 을 export 한다 (`__all__` = `:74-77`, 기본값 `SURGE_CHG_DEFAULT=15.0` / `TP_SURGE_DEFAULT=15.0` / `TP_CALM_DEFAULT=3.0` = `:85-87`).
- **호출처가 `auto_bb_breakdown_worker` 하나뿐**이다. `strategy_service`(기본 방식 생성 경로)와 `stage_entry_signal`(OBV 자동 판정 경로)에는 **import 조차 없다.**
- 🚨 그런데 `system_settings.adaptive_tp_enabled = **1**` 이다.
  → **사장님은 「급등락 15% / 안정 3~5%」 가 전체에 적용된 줄 알고 계실 가능성이 높다.** 기본 방식과 OBV 자동은 여전히 `TP1_PCT_DEFAULT`(15) 고정을 쓴다 (`strategy_service.py:576` `tp1_pct_override=TP1_PCT_DEFAULT,  # v147: 15% (사장님 지시)`).

Fix 299 커밋 메시지의 실측 근거: 구간별 기대값에서 TP15 가 최선인 건 `|24h| 15~30%` 하나뿐(+0.51)이고 나머지 구간은 −0.94 ~ **−4.30** 이었다. 즉 **배선이 빠진 두 경로가 실측상 가장 손해 보는 구간을 그대로 쓰고 있다.**

#### ⑤ 🚨 (신규 발견) `mainnet_safety_worker` 가 매시간 100% 크래시

```bash
ssh root@159.65.137.250 'grep -c " ERROR \[apscheduler" /root/sch.log'   # → 6
```
```
File "/app/app/workers/mainnet_safety_worker.py", line 139, in _check_exchange_accounts
    "name": a.name,
AttributeError: 'ExchangeAccount' object has no attribute 'name'
```

🚨 위 `grep -c " ERROR \[apscheduler"` 는 §5 에서 만든 **`/root/sch.log` 가 있어야** 돈다.
그 파일을 만들지 않았다면 로그를 바로 흘려 보면 된다 (파일을 쓰지 않는 편이 안전하다):
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --no-color --since 24h scheduler 2>&1 | grep -c " ERROR \[apscheduler"'
```

코드 확인 — **저장소 루트**에서 (2026-09-03 재검증, 두 명령 모두 그대로 돈다):
```bash
cd /path/to/binance-auto-trader
sed -n '130,142p' backend/app/workers/mainnet_safety_worker.py
sed -n '1,30p'   backend/app/models/exchange_account.py
```
`sed` 출력의 139번째 줄이 문제의 `"name": a.name,` 이다.
`ExchangeAccount` 모델의 컬럼은 `id / user_id / exchange_name / market_type / api_key_enc / api_secret_enc / passphrase_enc / hedge_mode_enabled / is_testnet / is_active / daily_loss_limit_usdt / created_at / updated_at` — **`name` 이 없다.** (`app/models/exchange_account.py:9-26`)

**영향: 「mainnet 인지 testnet 인지」를 매시간 확인하는 안전 점검이 9.5시간 동안 6번 전부 실패했다.** 실자금 계정에서 이 점검이 죽어 있는 것은 가볍지 않다. 고치는 것 자체는 `a.name` → `a.exchange_name` 한 줄로 보이지만, **이 조사에서는 코드를 수정하지 않았다.**

> 🚨 **「한 줄이니까 새 PC 첫날에 후딱 고치자」가 이 항목의 함정이다.**
> - 이 저장소는 **오늘 하루에만** 「한 줄 수정」이 엉뚱한 함수에 붙어 사고가 난 사례를 겪었다 (Fix 318 → 319: 손절 수정이 **다른 함수**에 붙어 있었다).
> - 게다가 **코드 수정 = 배포 = 컨테이너 재시작**이다. 재시작하면 **포지션 8건을 지키는 손절·단계 전환 잡이 그 사이 멈춘다.** 「안전 점검을 고치려다 실제 안전장치를 잠깐 끄는」 거래가 된다.
> - ✅ **먼저 확인할 것**: 이 크래시는 **`_check_exchange_accounts` 한 함수**만 죽이는가, 아니면 **`mainnet_safety_worker` 전체**가 죽는가? 후자면 다른 안전 점검도 같이 죽어 있다는 뜻이라 우선순위가 완전히 달라진다. 스택트레이스 전체를 먼저 읽어라 (읽기 전용):
>   ```bash
>   ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --no-color --since 24h scheduler 2>&1 | grep -B5 -A25 "has no attribute .name." | head -60'
>   ```
> - 고칠 때: **한 커밋 · 한 파일**, `git revert` 로 되돌릴 수 있게. **포지션이 적은 시간**에, **사장님 승인 후**.
> - ⚠️ **이 워커가 「testnet 인 줄 알았는데 mainnet」을 잡는 장치라면, 고친 직후 처음 도는 순간 경보가 무더기로 나올 수 있다.** 고친 뒤 첫 1시간은 알림을 지켜볼 것.

> 🚨 **위 컬럼 목록에 나오는 `api_key_enc` / `api_secret_enc` / `passphrase_enc` 를 읽을 때 반드시 알아야 할 것**
> 이 컬럼들은 **평문이 아니라 Fernet 대칭키로 암호화된 값**이고, 그 키는 `.env` 의 **`ENCRYPTION_KEY` 단 하나**다
> (`backend/app/core/crypto.py:33-45` — `Fernet(settings.encryption_key)`).
> **`ENCRYPTION_KEY` 를 잃거나 새 PC에서 새로 생성하면 `api_key_enc` 는 수학적으로 복구 불가능**하다.
> 백도어도 복구 절차도 없고, **바이낸스에서 API 키를 새로 발급받는 것 말고는 방법이 없다.**
> → 새 PC 이전 절차·회전 절차·검증 방법은 **`secrets.md` §3 「`ENCRYPTION_KEY` — 이전에서 가장 위험한 지점」** 을 반드시 먼저 읽을 것.
> (이 문서에는 비밀 **값**이 한 개도 들어 있지 않다. 키 **이름**과 「어디서 얻는가」만 적혀 있다.)

#### ⑥ 🚨 (신규 발견) Fix 327 이 배포됐는데 꺼져 있다

`support_score_gate_enabled` 가 `system_settings` 에 **행 자체가 없다** = 기본 OFF (커밋 메시지 명시: `기본 OFF(support_score_gate_enabled). fail-open.`).
→ 오늘 마지막 커밋인 지지선 7점 판정(승률 LONG 70.6% / SHORT 63.9% 실측)이 **진입에 전혀 관여하지 않고 있다.** 켜려면 §7 ② 때문에 **DB 직접 쓰기밖에 없다.**

> ⚠️ **다만 「배포됐는데 꺼져 있다 = 실수다」로 읽지 마라.** 커밋 메시지가 **`기본 OFF(support_score_gate_enabled). fail-open.`** 이라고 **의도적으로** 적고 있다. 이 저장소의 관행은 **새 게이트를 OFF 로 배포하고 관찰 후 켜는 것**이다(Fix 247 합의 게이트도 같은 방식이었고, 사장님이 직접 켰다).
> 🚨 **켤 때의 위험**: 이 게이트는 **진입을 막는 쪽**으로 작동한다. 켜는 순간 **자동 진입이 급감하거나 0이 될 수 있다** — 「자동매매가 멈췄다」로 보이지만 실제로는 게이트가 일하는 것이다. 그 구분이 안 되면 또 한 번 오진한다.
> ✅ 켜기 전에 **차단 로그가 남는지** 먼저 확인하고(§5 의 Fix 247 게이트처럼 「N건 차단」이 보여야 한다), 켠 뒤 **진입 건수 변화를 §4 방식으로 비교**하라. 되돌리기는 **값을 `0` 으로** 또는 **그 행을 지우는 것**(원래 행이 없었다 — §7 ② 의 1번 참조).

#### ⑦ ⚠️ (신규 발견) `REENTRY_READY` 16건이 최대 50일 방치

재검증 실제 출력 (`created_at` 오름차순, 일부):
```
(465,  'ALLOUSDT',   'LONG',  '_quick_20260714203844',  2026-07-14)   ← 가장 오래됨
(1116, 'BLESSUSDT',  'LONG',  'AUTO_BB_BLESSUSDT_LONG', 2026-08-22)
(1272, 'MELANIAUSDT','LONG',  'AUTO_BB_MELANIAUSDT_LO', 2026-08-24)
(1662, '龙虾USDT',    'SHORT', '_quick_20260828233727',  2026-08-28)   ← 가장 최근
```
16건 중 **14건이 `_quick_`(수동), 2건이 `AUTO_BB_`**(#1116 / #1272)다.
가장 오래된 것이 **2026-07-14**(= 조사일 기준 51일), 가장 최근이 **08-28**. 9월 들어 하나도 갱신되지 않았다.
(전량을 뽑는 명령은 §3 「전체 상태 분포」 끝에 있다.)
> ⚠️ 앞선 초안에 `13건 / 07-15` 로 적혀 있었으나 **재실행 결과 `14건 / 07-14` 가 맞다.** 위 숫자를 쓰라.
⚠️ **이게 「재진입 워커가 이것들을 후보로 안 본다」는 뜻인지, 「정상적으로 대기 중」인지는 확인 못 함.** 메모리 확정 사항(재진입 워커는 `TERMINAL_STATUSES` 에서만 후보를 고른다 / Fix 296 이 화이트리스트에서 `_quick_` 를 어떻게 다루는지)과 대조해 볼 것.

#### ⑧ ⚠️ (신규 발견) 사다리가 2단계로 올라간 실전 사례가 아직 0건

현재 활성 8건 **전부 `current_stage = 1`**. Fix 304~326 이 전부 「단계 전환 시 부분 손절 → 다음 단계」를 겨냥했는데, **그 흐름이 끝까지 성공한 것을 실서버에서 아직 못 봤다.** 오늘 Fix 326 은 실서버 로그에서 「부분 손절 → 12~17초 뒤 전량 청산」 사고 3건(#2091 / #2095 / #2089)을 잡아서 고친 것이고, 그 수정의 효과 확인은 **다음 단계 전환이 일어나야** 가능하다.
→ 🚨 **새 PC에서 제일 먼저 볼 것: `current_stage >= 2` 인 전략이 생기는지.**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
q = \"select current_stage, count(*) from strategy_instances where status like :p group by 1 order by 1\"
print(db.execute(text(q), {\"p\": \"STAGE%\"}).fetchall())
"'
```

#### ⑨ ⚠️ `unified_entry_enabled = 0` — 「유일한 진입」으로 만든 통합 경로가 꺼져 있다

`backend/app/workers/scheduler_runner.py:501-511` 에 `unified_15m_entry` 가 **30초 주기**로 등록돼 있고 주석은 `SystemSetting "unified_entry_enabled" = 1 시만 실 진입!` 인데 설정값은 **0**. 같은 v224 통합으로 `auto_bb_breakdown` 잡은 **주석 처리**됐다 (`scheduler_runner.py:307-318`).
⚠️ 이것이 의도된 상태(다른 워커들이 실제 진입을 담당)인지, 방치된 것인지는 **확인 못 함.** 실제로 진입을 만드는 건 `bb_mid_line_worker`(BB_MIDLINE)와 `auto_short_at_top_worker` / `auto_long_at_bottom_worker`(AUTO_BB) 다.

> 🚨🚨 **「꺼져 있으니 켜 보자」가 이 항목의 사고다. `unified_entry_enabled = 1` 은 절대 가볍게 켜지 마라.**
> - 이 스위치는 **진입 소스를 하나 더 여는 것**이다. v224 설계에서는 `unified_15m_entry` 가 **다른 워커들을 대체**하기로 되어 있었지만, **대체될 워커들은 지금 살아서 실제로 진입을 만들고 있다**(오늘 자동 32건 전부 `BB_MIDLINE_*` / `AUTO_BB_*` — §4).
> - 즉 지금 켜면 **대체가 아니라 추가**가 된다 → 같은 시장에 **두 진입 엔진**이 동시에 후보를 만든다. 동시 보유 상한·일일 한도가 순식간에 소진되고, 같은 심볼에 겹쳐 들어갈 수 있다.
> - 게다가 **30초 주기**로 등록돼 있다(`scheduler_runner.py:502-510`). 잘못 켜면 **되돌리기 전에 이미 여러 건이 들어가 있다.**
> - ✅ 켜야 한다면: **먼저 `bb_mid_line_worker` / `auto_*_worker` 를 끄는 계획**을 세우고, **사장님 승인**을 받고, **포지션이 적은 시간**에, **켠 직후 1시간을 지켜볼 수 있을 때** 켜라. 되돌리는 법(= 값을 다시 `0` 으로)을 **켜기 전에 손에 쥐고** 시작하라.

#### ⑩ ⚠️ Fix 307 커밋을 못 찾았다

Fix 306(`33b88df`)과 Fix 308(`f8a052b`) 사이에 Fix 307 이 없다.

재검증 — **커밋 본문과 코드·문서 전체를 뒤져도 흔적이 0건**이다:
```bash
cd /path/to/binance-auto-trader
git log --format='%h %s%n%b' 8010e6f~1..HEAD | grep -n "Fix 307"   # → 0줄
git grep -n "Fix 307\|Fix307" -- backend/ docs/                    # → 0줄
```
⇒ **「어딘가에 흡수됐다」기보다 번호를 건너뛴 쪽에 가깝다.** 다만 「왜 건너뛰었는지」는 여전히 **확인 못 함**이고,
**실행 코드에 미치는 영향은 없다**(어떤 파일도 Fix 307 을 참조하지 않는다). 이 항목은 안심하고 넘어가도 된다.

---

### 8. 새 PC 첫날 점검 순서 (복사해서 그대로 실행)

> 🔑 **전제 — 이 절의 모든 명령은 VPS SSH 접속이 되어야 돈다.** 새 PC에는 아직 접속 수단이 없다.
> 현재 사무실 PC 는 `~/.ssh/id_ed25519` (개인키) / `id_ed25519.pub` (공개키) 로 `root@159.65.137.250` 에 붙는다.
>
> 🚨 **권장: 개인키를 옮기지 마라. 새 PC에서 새로 만들어라.** 개인키는 옮기는 순간 「어딘가에 복사본이 하나 더 생기는」 자산이고, 옮기는 경로(메일·메신저·클라우드 드라이브·채팅)가 전부 사고 지점이다.
> ```bash
> # 새 PC 에서 (개인키는 이 PC 밖으로 절대 안 나간다)
> ssh-keygen -t ed25519 -C "새PC" -f ~/.ssh/id_ed25519
> cat ~/.ssh/id_ed25519.pub          # ← .pub (공개키) 는 공개해도 안전하다
> ```
> 그 다음 **사장님이 기존 접속되는 PC 에서** VPS `~/.ssh/authorized_keys` 에 위 `.pub` 한 줄을 추가한다(= VPS 쓰기이므로 **사장님이 직접**).
> 이렇게 하면 옛 PC 를 잃어버렸을 때 그 줄만 지우면 되고, 개인키가 전송된 적이 아예 없다.
>
> ⚠️ 개인키(`id_ed25519`)를 꼭 옮겨야 한다면 **채팅·이메일·이슈·스크린샷은 금지.** 물리 매체나 비밀번호 관리자로 옮기고, 새 PC에서 권한을 `chmod 600 ~/.ssh/id_ed25519` 로 조인다. 자세한 원칙은 `secrets.md`.
> (이 문서에는 개인키 내용도, 어떤 비밀 **값**도 들어 있지 않다.)

> ⚠️ **`-o StrictHostKeyChecking=no` 를 습관으로 만들지 마라.** 이 옵션은 **처음 보는 서버 키를 묻지 않고 그대로 받아들인다** — 새 PC 첫 접속에서 편하려고 쓰는 것이지, **안전해서 쓰는 것이 아니다.**
> 이 저장소가 다루는 것은 **실계좌를 조작할 수 있는 서버**다. 첫 접속 때 **한 번만** 지문을 눈으로 확인하고 등록해 두면, 그 뒤로는 이 옵션 없이 쓰는 것이 맞다.
> ```bash
> # 처음 한 번: 지문을 확인하고 등록 (사장님이 알고 있는 값과 대조)
> ssh-keyscan -t ed25519 159.65.137.250 | ssh-keygen -lf -
> ssh root@159.65.137.250 'echo ok'      # ← 이후로는 옵션 없이
> ```
> 이 절의 명령들에 붙은 `-o StrictHostKeyChecking=no` 는 **첫 1회용**으로 읽어라.

> ✅ **아래 1)~6) 은 전부 읽기 전용이다** — 주문을 내지 않고, 설정을 바꾸지 않고, DB 에 쓰지 않는다.
> 단 **3) 만 예외적으로 파일을 쓴다**(로컬 heredoc + `scp` + `docker compose cp`). 그 주의사항은 3) 안에 적어 두었다.

**0) 저장소를 새 PC에 가져온다** — §1 · §2 · §7 ②③ 의 `git log` / `git grep` 명령은 **로컬 clone 이 있어야** 돈다.
```bash
cd ~                                   # 원하는 상위 폴더
git clone https://github.com/herosys1-crypto/binance-auto-trader.git
cd binance-auto-trader
git log -1 --format='%h %s'            # → e51d9a8 chore(handoff): …  (= GitHub main)
```
🚨 **clone 만 한다. `pip install` 도 `docker compose up` 도 하지 마라** — §0.5 #1 참조.
이 절의 모든 조회는 **VPS 컨테이너 안**에서 돌고, 로컬은 **코드를 읽기 위해서만** 필요하다.
이후 문서에 나오는 `cd /path/to/binance-auto-trader` 는 여기서 clone 한 경로를 말한다.

> ⚠️ **VPS(`ded22f3`)와 GitHub main(`e51d9a8`)은 1커밋 다르다.** clone 하면 `e51d9a8` 이 받아진다.
> 차이는 `docs/` 뿐이고 `backend/app/` 은 동일하므로(§2), **코드를 읽는 목적에는 문제가 없다.**
> VPS 와 글자 그대로 같은 상태를 보고 싶으면 `git checkout ded22f3` 한다(읽기 전용 detached HEAD).

**1) 배포 대조**
```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader && git log -1 --format="%H %s"'
```
보는 법: 출력이 `ded22f3…` 이면 조사 시점과 같다. **다른 SHA 가 나오면 그 뒤로 배포가 있었다는 뜻**이니
§1 의 Fix 표와 `git log ded22f3..<새 SHA>` 를 대조해 무엇이 추가됐는지 먼저 파악하라.

**2) 컨테이너 살아있나 + 언제 시작했나**

`docker compose ps` 는 **「Up 9 minutes」 같은 상대 시각만** 준다. 배포 판정에는 쓸 수 없으므로
절대 시각(`StartedAt`)과 서버 현재 시각(`date -u`)을 **같이** 찍는다:
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ps --format "table {{.Name}}\t{{.Status}}"'
ssh root@159.65.137.250 'docker inspect -f "{{.Name}} {{.State.StartedAt}}" binance-auto-trader-api binance-auto-trader-scheduler; date -u'
```
보는 법: **`api` / `scheduler` 두 개가 Up 이어야 한다.** `db` 가 Up 인 것은 의미 없다(빈 껍데기, §9).
`StartedAt` 이 `~/binance-auto-trader/backend/app/**` 파일 mtime 보다 **뒤**면 배포 반영됨 (§2).

**3) 지금 돈이 들어가 있는 전략** — 여러 줄 SQL 은 로컬에 파일로 쓴 뒤 보내는 편이 안전하다.

> ⚠️ **이 단계만 파일을 3곳에 쓴다. 셋 다 「덮어쓰기」다:**
> 1. **로컬 cwd** — `cat > ops_active.py` 는 **같은 이름 파일이 있으면 묻지 않고 덮어쓴다.** 🚨 **저장소 안에서 실행하지 마라** — 커밋에 섞여 들어가고, 나중에 VPS `git pull` 을 막는다(§2 참조). 저장소 **밖의 임시 폴더**에서 하라:
>    ```bash
>    mkdir -p ~/ops-scratch && cd ~/ops-scratch    # ← 여기서 heredoc 실행
>    ```
> 2. **VPS `/root/ops_active.py`** — 같은 이름이면 덮어쓴다. 조사용이라 무해하지만, 이미 `/root` 에 `q1.py`~`q8.py`, `vq.py`, `sch.log` 가 쌓여 있다(§8 하단 참조).
> 3. **컨테이너 안 `/tmp/a.py`** — 🚨 이름이 너무 짧고 흔하다. **두 사람이 동시에 조사하면 서로의 스크립트를 덮어쓴다.** 자기 이름을 붙여라(예: `/tmp/ops_active_0904.py`).
>
> ✅ **파일을 안 쓰고 끝내는 방법도 있다** — 한 줄짜리 조회라면 §3 처럼 `python -c "…"` 로 바로 보내면 된다. 여러 줄이 필요할 때만 위 방식을 쓴다.
> ✅ 이 스크립트들은 **`select` 만** 한다. 새 PC에서 붙여 넣기 전에 **`insert`/`update`/`delete` 가 섞이지 않았는지 눈으로 확인**하라 — 여기서 실행되는 것은 **운영 Neon DB** 다.

먼저 로컬에 `ops_active.py` 를 만든다:
```bash
cat > ops_active.py <<'PYEOF'
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
rows = db.execute(text("""
select si.id, si.symbol, si.side, si.status, st.name, si.current_stage,
       si.current_position_qty, round(si.unrealized_pnl::numeric,2),
       round(si.realized_pnl::numeric,2), si.leverage, si.force_sl_roi_override
from strategy_instances si
left join strategy_templates st on st.id = si.strategy_template_id
where si.status not in ('STOPPED','COMPLETED','CANCELLED','FAILED','REENTRY_READY')
order by si.id desc
""")).fetchall()
for r in rows:
    print(" | ".join("" if v is None else str(v) for v in r))
print("total:", len(rows))
PYEOF
```
보내서 실행한다 (🚨 `PYTHONPATH=/app` 을 빼면 `ModuleNotFoundError`):
```bash
scp -o StrictHostKeyChecking=no ops_active.py root@159.65.137.250:/root/ops_active.py
```
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose cp /root/ops_active.py api:/tmp/a.py && docker compose exec -T -e PYTHONPATH=/app api python /tmp/a.py'
```

> 참고: 이 조사에서 만든 스크래치 파일이 VPS 에 남아 있다 — `/root/q1.py` ~ `/root/q8.py`, **`/root/vq.py`**, `/root/sch.log`(200,000줄, **52.5 MB** = 실측 `52,505,186` 바이트), 컨테이너 안 `/tmp/q*.py`. 지워도 무방하지만 **읽기 전용 원칙** 때문에 이 조사에서는 지우지 않았다.
> 🚨 **지울 때 `rm /root/*.py` 같은 와일드카드를 쓰지 마라.** `/root` 는 사장님이 다른 용도로 쓰는 파일이 섞일 수 있는 곳이다. **`ls` 로 눈으로 확인 → 파일명을 하나씩 지정 → `rm -i`** (§5 의 삭제 절차와 동일). 디스크는 여유가 있다(48G 중 24G) — **급하지 않으니 서두르지 마라.**
> 🔒 **비밀 관점 확인 완료**: `/root/sch.log` 에 자격증명 흔적이 있는지 실제로 훑었다 — `listenKey` **0건**, 50자 이상 연속 토큰 문자열 **0건**. 즉 이 로그를 지우지 않고 둬도 키가 새는 상황은 아니다. 다만 `/root` 는 root 만 읽으므로 **그대로 두되 밖으로 복사하지는 말 것**(로그를 통째로 옮기면 심볼·수량·손익 같은 거래 정보가 같이 나간다).

**4) 오늘 진입 (KST, 진입일 기준, 수동/자동 분리)** — §4 의 SQL 을 쓸 것.

**5) 위험 스위치 현재 값**
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for k,v in db.execute(text(\"select key,value from system_settings order by key\")).fetchall(): print(k,\"=\",v)
"'
```
> ⚠️ 이 명령은 `system_settings` 값을 **자르지 않고 전부** 화면에 뿌린다.
> 2026-09-03 실조회 기준 이 테이블에 비밀 값은 **없다** — 비밀(바이낸스 API 키 · `ENCRYPTION_KEY` · 텔레그램 봇 토큰 · DB 접속문자열)은 전부 `.env` 와 `exchange_accounts` 의 암호화 컬럼에 있고, `system_settings` 63행은 숫자·on/off 토글뿐이다
> (`telegram_bot_token` / `telegram_chat_id` 는 `app/core/config.py:21-22` = **환경변수**이지 `system_settings` 가 아니다).
> 다만 이후 누가 키를 추가했을 수 있으니 **출력을 채팅·스크린샷·이슈에 붙이기 전에 한 번 훑어볼 것.** 훑기 싫으면 §6 처럼 `left(value,60)` 로 잘라서 본다.
>
> 🚨 **실용 경고: 이 명령을 그대로 돌리면 화면이 폭발한다.** 63행 중 **4행이 초장문 JSON** 이다 (실측 길이):
> `pattern_learning_insights_v187` **19,699자** / `learning_agent_insights` **3,688자** / `suggestion_default_profiles` **1,626자** / `post_liquidation_analysis_v212` **330자**.
> 이 넷이 **스크롤을 밀어내서 정작 보려던 위험 스위치가 화면 밖으로 사라진다.** 위험 스위치만 보려면 §6 처럼 자르거나, 길이만 먼저 보라 (값 노출 없음):
> ```bash
> ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
> from app.core.database import SessionLocal
> from sqlalchemy import text
> db = SessionLocal()
> for k,v in db.execute(text(\"select key, left(value,40) from system_settings where length(value) <= 60 order by key\")).fetchall(): print(k,\"=\",v)
> "'
> ```

**6) 지난 밤 사이 ERROR 만 뽑기**

`--tail 200000` 은 52 MB 를 통째로 훑어 느리다. **시간으로 자르는 편이 낫다** (아래는 약 45초):
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --no-color --since 24h scheduler 2>&1 | grep -E " (ERROR|CRITICAL) " | tail -40'
```

🚨 **위 명령만으로는 「무엇이 깨졌는지」를 알 수 없다.** apscheduler 의 ERROR 한 줄은
`Job "…_wrapped (trigger: interval[1:00:00] …)" raised an exception` 이라 **워커 이름이 안 나온다.**
원인은 바로 뒤에 붙는 traceback 에 있으므로 `-A 14` 로 뒤 14줄을 같이 봐야 한다:
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --no-color --since 24h scheduler 2>&1 | grep -A 14 -E " (ERROR|CRITICAL) " | tail -60'
```
지금 나오는 6건은 전부 §7 ⑤ 의 `mainnet_safety_worker` 다 (`interval[1:00:00]` = 1시간 주기가 단서).

**7) 🚨 오늘 제일 중요한 관찰 — 2단계로 올라간 전략이 생겼나** (§7 ⑧)
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
q = \"select current_stage, count(*) from strategy_instances where status like :p group by 1 order by 1\"
print(db.execute(text(q), {\"p\": \"STAGE%\"}).fetchall())
"'
```
- `[(1, N)]` **만** 나오면 = Fix 304~326 의 효과가 **아직 확인 안 됨** (조사 시점 상태).
- `[(1, N), (2, M)]` 처럼 **2 가 등장하면** = 단계 전환이 처음으로 성공한 것 → §7 ⑧ 을 닫을 수 있다.

---

### 9. 🚨 새 PC에서 하면 안 되는 것

| 하지 마라 | 이유 |
|---|---|
| 🚨 새 PC 에서 `docker compose up` / `python -m app.workers.scheduler_runner` 로 앱을 띄우기 | 🚨 **이 표에서 가장 비싼 실수.** `.env` 가 운영 Neon + 실계정 키를 가리키므로 **VPS 스케줄러와 같은 계정에 붙은 두 번째 엔진**이 된다 → 중복 주문 / 손절·단계 전환 이중 실행. 상세는 §0.5 #1 |
| 🚨 로컬에서 `alembic upgrade head` (또는 `downgrade`) | 🚨 `alembic/env.py:27-30` 이 `DATABASE_URL` 을 그대로 쓴다 = **운영 DB 스키마가 바뀐다**. 현재 `0034_surge_ladder`. 마이그레이션은 VPS 에서 사장님 승인 후 (§0.5 #3) |
| 🚨 로컬에서 Binance REST 직접 호출 (조사 스크립트 포함) | 🚨 **IP ban(418) 전력**(2026-08-26). 새 PC = 새 IP. 시세·포지션은 **VPS api 컨테이너를 통해서만** 본다 (§0.5 #2) |
| 🚨 `git stash` / `git stash pop` | 🚨 **worktree 공유 저장소**다. stash 는 저장소 전역이라 다른 worktree 작업까지 삼키고, `pop` 충돌 시 복구가 어렵다. **브랜치 파서 커밋**으로 대체 (§0.5 #4) |
| 🚨 VPS 에서 `git pull` 을 「조회」로 취급 | 🚨 `.:/app` **바인드 마운트**라 pull 즉시 컨테이너 안 파일이 바뀐다. 재시작 전까지 **옛 코드 + 새 코드 혼합 import** 위험. **pull = 배포의 시작** (§0.5 #5, §2) |
| 🚨 `reset --hard` / `checkout .` / `clean -fd` / `rm -rf` 로 막힌 상황 밀어붙이기 | 🚨 VPS 작업트리에 **untracked 조사 스크립트 31개**가 있고 전부 날아간다. `rm` 은 **와일드카드 없이, `ls` 로 경로 확인 후, `-i` 로** (§5) |
| 🚨 `--force` push / 브랜치 강제 덮어쓰기 | 🚨 `main` 이 곧 **배포 대상**이다. 강제 푸시는 다른 PC·VPS 가 이미 가진 커밋을 **되돌릴 수 없게** 만든다. 충돌은 merge 로 풀 것 |
| `docker compose exec db psql …` 로 조회 | 🚨 로컬 `db` 컨테이너는 **빈 껍데기**. 실 DB 는 외부 **Neon**. 「테이블이 없다」는 오진으로 이어진다 |
| `PYTHONPATH=/app` 없이 `docker compose exec api python` | `ModuleNotFoundError` |
| 쿼리 실패 후 그대로 다음 쿼리 | 세션이 막힌다. `db.rollback()` 을 반드시 넣을 것 |
| 파일 mtime 만 보고 「배포됐다」 판정 | 🚨 `docker exec grep` 은 **디스크**를 본다. **프로세스 시작 시각 vs 파일 수정 시각**으로 판정할 것 (§2) |
| `stage_trim_before_next_enabled` / `sajangnim_ladder_stages_enabled` 를 임의로 토글 | 🚨 지금 ON 이고 실자금 8건이 물려 있다. 오늘만 이 계열로 Fix 315→321, 318→319, 304→326 연쇄 사고가 났다 |
| 청산일 기준으로 일일 실적 판정 | 🚨 확정 교훈. **진입일**로 갈라야 한다 (§4) |
| 코드 감사에 `grep -r` 로 **개수 세기** | 🚨 `__pycache__/*.pyc` 와 **커밋 안 된 작업 중 파일**까지 세어 **새 PC 의 clone 과 숫자가 달라진다.** 이 문서의 §7 ② code 값도 그래서 1씩 부풀어 있었다. 개수를 근거로 쓸 거면 **`git grep`**(추적 파일만) 을 써라 (§7 ②) |
| 로그 파이프라인(`sed`+`cut`)의 버킷 크기를 **정확한 건수**로 인용 | 🚨 심볼 치환이 소문자·한자 심볼을 못 지워 같은 메시지가 여러 버킷으로 갈린다. §5 1위는 26,906 으로 보이지만 **실제 27,257** 이고 재실행하면 또 달라진다. 정확한 수는 **메시지 원문을 `grep -c`** (§5) |
| 미실현 손익이 문서와 다르다고 고장 의심 | ⚠️ 미실현은 **시세**다. 재현 판정은 **건수와 실현손익**으로만 하라 (§3 · §4) |
| WARNING 42,780건을 보고 놀라기 | 대부분 정상 게이트 로그와 요약 로그다. 진짜는 **ERROR 6건 + misfire 432건** (§5) |
| VPS 에서 재시작·설정변경·DB 쓰기 | 실자금이 돌고 있다. 배포·재시작은 사장님 |
| 🚨 「한 줄이니까」로 코드 수정 → 바로 배포 | 🚨 **코드 수정 = 배포 = 재시작**이고, 재시작 동안 **포지션 8건을 지키는 손절 잡이 멈춘다.** 오늘만 Fix 318→319(수정이 엉뚱한 함수에 붙음), 315→321(손절을 다시 잠금) 이 났다. `tests/test_stage_flow_execution.py` 등을 **먼저** 돌려라 (§1 하단) |
| 🚨 §7 ③ 을 읽고 LONG 손절을 −10% 로 바꾸기 | 🚨 **그건 이미 했다가 실측으로 되돌린 값**이다 (Fix 253, 2026-09-01). 바꾸면 패자 손실이 다시 2배가 된다. 지시 문서와 실측이 **충돌**하는 사안이니 **사장님께 충돌 자체를 보고**하라 (§7 ③) |
| 🚨 되돌리는 법을 정해두지 않은 채 무언가 바꾸기 | 🚨 설정이면 **바꾸기 전 값**(특히 「행 없음」 vs 「0」), 코드면 **revert 할 커밋**을 먼저 확보. 이게 없으면 사고가 났을 때 **원래 상태를 아무도 모른다** (§7 ②) |
| 🚨 새 PC 에서 `ENCRYPTION_KEY` 를 **새로 생성** (`Fernet.generate_key()` / `deploy/generate-secrets.sh` 통째 붙여넣기) | 🚨 **DB 의 `api_key_enc` / `api_secret_enc` 가 즉시 영구 복호화 불가**가 된다. Fernet 대칭키라 복구 수단이 **없다** — 바이낸스에서 키 재발급뿐. 기존 DB 를 계속 쓸 거면 **글자 하나도 바꾸지 말고 그대로 옮긴다.** 절차는 `secrets.md` §3 |
| 🚨 API 키·시크릿·`ENCRYPTION_KEY`·DB 접속문자열·SSH 개인키를 **채팅·이메일·메신저·스크린샷·이슈**로 전달 | 🚨 그 순간 비밀이 서버 로그·백업·대화 기록에 영구 저장된다. 되돌릴 방법이 없다. **비밀은 사장님이 직접 새 PC 앞에서 손으로 입력**하거나 비밀번호 관리자로 옮긴다. AI 에게 값을 붙여넣어 달라고 하지 말 것 |
| 🚨 명령줄에 비밀 값을 그대로 적기 (`-e KEY="실제값"`, `export KEY=...`) | 셸 히스토리 · `ps` 출력 · docker inspect 에 남는다. 파일(`umask 077`)로 넘기고 끝나면 `history -c`. `secrets.md` §3-3 참조 |
| 🚨 `.env` 를 `cat` 해서 그 출력을 어딘가에 붙여넣기 | 이 저장소의 조사 원칙: **값은 읽지 않는다.** 존재·길이·지문(해시 앞자리)만 비교한다 (`secrets.md` §4 가 값 노출 없이 비교하는 방법) |
