## 코드 구조 지도 — 어디를 봐야 하나

작성 기준: worktree `.claude/worktrees/infallible-euler-6dc297`, **앱 코드 기준 커밋
`ded22f3`** (= VPS 배포본 — 아래 §9 에 확인 명령 있음).

ℹ️ 그 뒤 이 핸드오프 문서·자산을 저장소에 넣은 `e51d9a8` (chore) 이 얹혀 있어
`git log -1` 은 `e51d9a8` 을 보여준다. **`backend/app` · `backend/alembic` 변경은 0건**
(`git show --stat --name-only e51d9a8`)이므로 아래 줄번호는 전부 그대로 유효하다.

🚨 **`main` 에 push 해도 VPS 는 바뀌지 않는다.** VPS 는 `main` 을 체크아웃한 별도
사본이라, 반영은 VPS 에서 pull + 컨테이너 재시작을 해야 일어난다.
**그 재시작은 사장님만 한다** — 이 문서의 어떤 명령도 배포가 아니다.
줄번호가 안 맞으면 문서가 틀린 게 아니라 **코드가 움직인 것**이니 위 명령으로 먼저 대조한다.

### 🚨 경로 — 새 PC 에서 이 문서의 명령이 안 도는 첫 번째 이유

이 문서를 쓴 환경은 git worktree(`.claude/worktrees/infallible-euler-6dc297`)였지만
**그 경로는 `.gitignore:106` 의 `.claude/worktrees/` 에 걸려 clone 에 따라오지 않는다.**
아래 명령들은 전부 `docs/handoff/RESTORE-2026-09-03.md` **방법 A** 로 clone 한 경로를 쓴다.

```
C:/Users/user/바이낸스/binance-auto-trader          ← 저장소 루트
C:/Users/user/바이낸스/binance-auto-trader/backend  ← 파이썬 앱 루트 (pytest·alembic 은 여기서)
```

다른 경로에 clone 했다면 위 앞부분만 그 경로로 바꿔 읽는다.
Git Bash 기준이고, 경로에 한글이 있으므로 **따옴표를 반드시 붙인다**
(안 붙이면 `No such file or directory`).

clone 이 이 문서와 같은 코드인지 **한 줄로 확인**한다 (2026-09-03 기준
`origin/main` = `e51d9a8`, 그 아래가 코드 커밋 `ded22f3`):

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader" && git log --oneline -2 && ls backend/app/services/*.py | wc -l
```

`59` 가 나와야 한다. **더 작게 나오면 checkout 이 옛 상태다** — `git pull` 하고
다시 센다.

> 🚨 `git pull` 전에 `git status` 를 먼저 본다. 커밋 안 된 변경이 남아 있으면
> pull 이 거부되거나 머지가 생긴다. 그때 **`git stash` / `git reset --hard` 로
> 밀어버리지 마라** — 이 저장소는 worktree 를 공유해서 남의 작업까지 사라진다.
> 남길 게 있으면 브랜치를 파서 커밋한다: `git switch -c wip/설명 && git add -A && git commit -m wip`.
> 버려도 되는 게 확실하면 그때만, **무엇을 버리는지 `git status` 로 확인한 뒤** 정리한다.

(옛 PC 의 main 체크아웃이 실제로 `2586555` 에서 멈춰 `services/` 가 53 이었다.
아래 줄번호·개수는 전부 `ded22f3` 이후 기준이라 옛 checkout 에서는 하나도 안 맞는다.)

### 🚨 명령을 돌리기 전에 한 번만 — 의존성 설치

`pytest` 명령은 의존성이 깔려 있어야 돈다. clone 직후에는 `ModuleNotFoundError` 가 난다.

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend" && python -m pip install -r requirements.txt
```

`fastapi`·`starlette` 는 2026-06-24 전 API 500 사고 때문에 **버전이 핀 고정**돼 있다
(`requirements.txt` 상단 주석). 핀을 풀지 마라.
🚨 **가상환경을 먼저 만들고 설치하라 — 전역 설치는 다른 프로젝트를 깨뜨린다.**
이 PC 에는 다른 파이썬 작업 환경이 같이 산다. 전역 `pip install -r requirements.txt` 는
핀 고정된 `fastapi`·`starlette` 등을 **시스템 전역에 강제**해 그쪽을 망가뜨릴 수 있고,
반대로 나중에 그쪽에서 설치한 패키지가 **이 프로젝트의 핀을 덮어** 2026-06-24 의
「전 API 500」 드리프트 사고를 재현한다.

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend" && python -m venv .venv && source .venv/Scripts/activate && python -m pip install -r requirements.txt
```

되돌리기: venv 를 쓰면 `.venv` 폴더만 지우면 원상복구다(전역은 되돌릴 방법이 사실상 없다).
이후 §8·§9 의 `python` 명령은 **이 venv 를 활성화한 셸에서** 돌린다.

---

### 0. 30초 요약 — 새 PC 에서 처음 열 파일 다섯 개

| 순서 | 파일 | 왜 먼저 보나 |
|---|---|---|
| 1 | `backend/app/services/execution_service.py` (2,269줄) | **모든 진입 주문이 여기를 지난다.** `start_stage1`(188) / `trigger_next_stage`(305) |
| 2 | `backend/app/services/tp_sl_orchestrator.py` (828줄) | **모든 익절·손절이 여기서 나간다.** 손절 함수가 **두 개**라 사고가 났다 (§5) |
| 3 | `backend/app/workers/stage_trigger_worker.py` (1,525줄) | 단계 진입 판정. 네 방식의 분기가 여기 있다 |
| 4 | `backend/app/workers/scheduler_runner.py` (764줄) | **워커가 언제 도는지의 유일한 진실** (§6) |
| 5 | `backend/app/core/strategy_status.py` | 상태 집합·모드 마커의 단일 출처 |

🚨 이 저장소에서 반복해서 난 사고는 전부 같은 모양이다 —
**「게이트는 만들었는데 그 함수가 실제로 안 불렸다」**.
그래서 코드를 읽기 전에 §8(실행 테스트)을 먼저 알아두는 편이 낫다.

---

### 1. 저장소 레이아웃

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader" && ls -d */ *.md | head -60
```

| 경로 | 내용 |
|---|---|
| `backend/app/` | **애플리케이션 전부** (Python 281 파일) |
| `backend/alembic/versions/` | DB 마이그레이션 **32개** (`0034_surge_ladder_state.py` 가 최신 — 번호 `0025`/`0026` 은 결번이라 파일 수 ≠ 최신 번호) |
| `backend/tests/` | 테스트 159 파일 (§8) |
| `backend/memory/` | 워커가 읽는 운영 메모리 |
| `docs/` | 기획서·사양서 (`docs/spec/`, `docs/handoff/`) |
| 저장소 루트 `*.md` | 구버전 핸드오프·사양 **42개**(`ls *.md | wc -l`). **오래된 것이 많다** — 최신 진실은 코드와 `docs/` |
| `deploy/`, `docker-compose.production.yml` | 배포 |

---

### 2. `backend/app/` 층별 지도

파일 수는 아래 명령으로 재현된다.

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend/app" && for d in */; do echo "$d $(find "$d" -name '*.py' -not -path '*__pycache__*' | wc -l)"; done
```

| 디렉터리 | .py | 역할 | 대표 파일 (줄수) |
|---|---:|---|---|
| `services/` | 59 | **비즈니스 로직의 중심.** 주문 실행·리스크·게이트·지표 판정 | `execution_service.py` (2269), `risk_service.py` (1266), `tp_sl_orchestrator.py` (828), `stream_service.py` (551) |
| `workers/` | 64 | 주기 실행 작업. **후보 생산자 + 단계 트리거 + 감시자** | `auto_bb_breakdown_worker.py` (2241), `auto_long_at_bottom_worker.py` (1949), `realtime_reentry_worker.py` (1807), `stage_trigger_worker.py` (1525), `scheduler_runner.py` (764) |
| `agents/` | 55 | 「오케스트라」 에이전트 **`*_team` 폴더 17개 + `orchestrator/`** (분석·학습·감사). **매매 주문을 직접 내지 않는다** | `orchestrator/`(5), `strategy_suggestion_team/`(9), `coding_team/`(6), `planning_team/`(6) |
| `api/` | 36 | FastAPI 라우터. `api/router.py` 가 **22개** 라우터를 `/api/v1` 아래 묶는다 | `v1/strategies/{crud,control,lifecycle,calculate,helpers}.py`, `v1/admin/*`, `v1/strategy_suggestions.py` |
| `models/` | 20 | SQLAlchemy ORM | `strategy_instance.py`, `strategy_template.py`, `strategy_stage_plan.py`, `system_setting.py` |
| `core/` | 14 | 설정·DB·Redis·**암호화**·상수 | `config.py`, `database.py`, `crypto.py` 🔐, `redis_client.py`, `redis_lock.py`, `strategy_status.py`, `risk_constants.py` |
| `integrations/` | 9 | 바이낸스 클라이언트 + 주문 어댑터 | `binance/client.py`, `binance/execution/{router,plain_order_adapter,algo_order_adapter}.py` |
| `repositories/` | 7 | DB 접근 래퍼 | `strategy_repository.py`, `position_repository.py`, `order_repository.py` |
| `schemas/` | 7 | Pydantic 요청/응답 | `strategy.py`, `position.py`, `order.py`, `risk.py` |
| `middleware/` | 2 | `idempotency.py` |
| `observability/` | 2 | `metrics.py` (Prometheus) |
| `db/` / `utils/` | 2 / 2 | `db/base.py`, `utils/backoff.py` |
| `static/` | 0 | **프런트엔드** — HTML **9개** + JS 43개, CSS 파일 0 (스타일은 HTML 안에). 빌드 없음, 그대로 서빙 |

`app/main.py` 가 FastAPI 앱 진입점, `app/api/router.py:25` 이 `/api/v1` prefix.

#### 2-1. 🔐 `core/crypto.py` — 새 PC 이전에서 가장 위험한 파일

바이낸스 API 키는 평문으로 저장되지 않는다. `encrypt_text()` 가 Fernet 으로 암호화해
`exchange_accounts.api_key_enc` / `api_secret_enc` 에 넣고, 쓸 때마다
`decrypt_text()` 로 푼다 (**호출처 154곳** — `grep -rn 'decrypt_text(' backend/app | grep -v 'def ' | wc -l`).

🚨 **Fernet 키는 `.env` 의 `ENCRYPTION_KEY` 단 하나다** (`crypto.py:35` `settings.encryption_key`).
**이 값을 잃거나 새 PC 에서 새로 생성하면 DB 의 `api_key_enc` 는 영원히 복호화할 수 없다.**
Fernet 은 대칭키라 백도어도 복구 절차도 없다 — 바이낸스에서 **키를 새로 발급**받는 것
말고는 방법이 없다. `decrypt_text` 는 그때 `CryptoError("Failed to decrypt: invalid token")`
로 죽는다 (`crypto.py:52-54`).

→ 새 PC 로는 `ENCRYPTION_KEY` 를 **글자 하나도 바꾸지 말고 그대로** 옮긴다.
   이전 절차·값 획득처·검증법은 **`docs/handoff/2026-09-03/secrets.md` §3** 에 있다.
   (이 문서는 값을 담지 않는다 — 키 **이름**만 적는다.)

🚨 `validate_encryption_key()` 가 startup 에서 기본값(`change_me`)과 형식 오류를 잡아
**즉시 죽인다** (`crypto.py:12-30`, 호출은 `main.py:46`). 새 PC 에서 api 가 뜨자마자
`CryptoError` 로 죽으면 코드 문제가 아니라 **`.env` 를 안 옮긴 것**이다.

🚨 **층 사이의 방향**: `workers → services → repositories → models`.
워커가 거래소 API 를 직접 부르는 곳도 있으니(후보 스캔) 「주문」만은 반드시
`ExecutionService` 를 지난다고 기억하면 된다.

---

### 3. 🚨 네 가지 진입 방식 — 이 시스템에서 가장 헷갈리는 곳

#### 3-1. 결론 먼저: `trigger_mode` 로는 구분되지 않는다

실서버 DB 실측(아래 §9 명령으로 재현) — **네 방식 대부분이 `PRICE_DOWN_PCT` 다**:

```
strategy_type                     trigger_mode      capital_management_mode   건수
DYNAMIC_SHORT                     PRICE_DOWN_PCT    fixed                     475
auto_bb_break_SAJANGNIM_TOP       PRICE_DOWN_PCT    fixed                     317
DYNAMIC_LONG                      PRICE_DOWN_PCT    fixed                     257
auto_bb_break_SAJANGNIM_BOTTOM    PRICE_DOWN_PCT    fixed                     158
pump_split                        PRICE_DOWN_PCT    split_entry                68
auto_bb_break                     PRICE_DOWN_PCT    fixed                      43
DYNAMIC_SHORT                     OBV_REVERSE       fixed                      40
DYNAMIC_LONG                      OBV_REVERSE       fixed                      40
bb_mid_line                       PRICE_DOWN_PCT    fixed                      39
```
(2026-09-03 VPS 조회, `strategy_instances` 전건 1,487)

코드도 같은 말을 한다 — `app/services/stage_entry_timing.py:24-25`
(모듈 docstring. 파일을 열면 첫 화면에 있다):

> 세 방식 모두 `trigger_mode = PRICE_DOWN_PCT` 라 **trigger_mode 로는 구분되지 않는다.**
> 그래서 `strategy_type` 접두사로 가른다.

#### 3-2. 진짜 구분자 표

| # | 방식 | **실제 구분자 (코드)** | 근거 |
|---|---|---|---|
| ① | **기본 방식** — 사장님이 화면에서 만드는 단계 전략. 정해진 트리거 단가에 **즉시** 진입 | `template.trigger_mode ∈ {PRICE_DOWN_PCT, PRICE_UP_PCT}` **AND** 아래 ②③④ 마커가 전부 아님 | `workers/stage_trigger_worker.py:1128` `_is_price_mode = _tpl_trigger_mode in ("PRICE_DOWN_PCT","PRICE_UP_PCT")` |
| ② | **OBV 자동** — 4중 게이트로 「좋은 자리」를 판정 | `template.trigger_mode == "OBV_REVERSE"` | `workers/stage_trigger_worker.py:464` `_is_obv_mode`, 분기 `:792` |
| ③ | **v219 사다리** — 1단계 자본 10 → 300 → 600 | `template.strategy_type.startswith("auto_bb_break_SAJANGNIM")` **또는** `instance.capital_management_mode == "stage_ladder"` | `services/stage_entry_timing.py:74` `TYPES_DEFAULT="auto_bb_break_SAJANGNIM"` / `services/sajangnim_capital.py:329` `STAGE_LADDER_MODE="stage_ladder"` (판정 함수는 같은 파일 `is_stage_ladder`) |
| ④ | **볼밴 분할** — 100+200+300 **동시 보유**, 물타기가 설계 | `instance.capital_management_mode == "split_entry"` | `core/strategy_status.py:155` `SPLIT_ENTRY_MODE`, `workers/pump_split_entry_worker.py:138` `MODE_MARKER` |

보조 마커 (같은 컬럼을 쓴다 — 마이그레이션 없이 모드를 늘리는 관행, 헌법 127):

| `capital_management_mode` | 뜻 | 실서버 건수 |
|---|---|---:|
| `fixed` | 기본 (①②③ 대부분) | 1,413 |
| `split_entry` | 볼밴 분할 (④) | 68 |
| `auto_deduct` | v131 청산 후 재진입 + 손실 자동 차감 | 5 |
| `scheduled` | 예약 진입 (`workers/scheduled_entry_worker.py:20`) | 1 |
| `stage_ladder` | v219 사다리 마커 (Fix 315/321) | **0** ⚠️ 아래 참조 |

🚨 **`stage_ladder` 는 아직 실서버에 0건이다.** 마커는
`workers/auto_bb_breakdown_worker.py:1931-1933` 에서
`stages_config["stages_count"] > 1` 일 때만 저장되는데,
24시간 내 만들어진 SAJANGNIM 전략 9건이 전부 `capital_management_mode='fixed'` +
`stage_plans` **1개**였다(가장 최근이 `#2045 HYPEUSDT`, 2026-09-02 23:12 UTC —
2026-09-03 재검증에서도 그대로였다). 관련 코드(Fix 315/327)는 조회 시점 기준 12분 전
재시작으로 배포는 되어 있었으므로, **배포 이후 새 전략이 아직 안 생긴 것**으로 보인다.
새 PC 에서 제일 먼저 확인할 것 = 「사다리가 실제로 3단계로 생성되는가」(§9 명령).
👉 §9 마지막 명령을 돌려 **`#2045` 보다 큰 id 가 나오는지** 먼저 본다. 안 나오면
아직 새 전략이 없는 것이고, 나오는데 `plans` 가 1이면 그때가 진짜 버그다.

#### 3-3. 방식별 상세

**① 기본 방식** — `stage_trigger_worker.py:1103-1132` (Fix 232)
> 사장님 verbatim: "기본방식은 가격만 본다"
- 2단계 이상에서 **지표 게이트를 일부러 전부 뺐다.** 가격이 트리거에 닿으면 그냥 들어간다.
- 이전에는 `confirm_peak` 이 또 막아서 「왜 안 들어가는지 알 수 없는」 상태가 됐다(#1873).
- 🚨 그 대가로 **떨어지는 칼에도 지정가에 들어간다** → 손절이 그만큼 중요하다(§5).

**② OBV 자동** — `services/stage_entry_signal.py` (193줄), 호출 `stage_trigger_worker.py:720 / :830`
4중 게이트를 **자동 진입 워커와 같은 함수·같은 순서**로 부른다 (새 판정 로직을 만들지 않는다):

| 순서 | 게이트 | 함수 |
|---|---|---|
| ① | 4H OBV 극단 = 세력 반대면 차단 | `services/obv_gate.check_obv_gate` |
| ② | 양방향 연속 실패 종목 차단 | `services/bidirectional_blocklist.is_bidirectional_blocked` |
| ③ | 국면 차단 (SHORT 전용) | `services/pump_dump_regime.is_regime_blocked_for_short` |
| ④ | **핵심** — 15m 반복 정점/저점 ≥2회 + 지표 꺾임 ≥2/3 | `services/peak_confirmation.confirm_peak` |

- 각 게이트는 **fail-open**(판정 실패 시 통과)이지만, 그 사실을 `detail` 에 남긴다.
- 🚨 여기에 Fix 312 대기 로직을 또 얹으면 **Fix 232 가 없앤 중복 게이트가 부활한다**
  (`stage_entry_timing.py:16-18` 가 명시).

**③ v219 사다리** — `workers/auto_bb_breakdown_worker.py` + `services/sajangnim_capital.py`
- 자본 사다리 `10 / 300 / 600` (실서버 설정 `sajangnim_capital_ladder = "10,300,600"`).
- **단계 간격 기본 1.5%** (`sajangnim_capital.py:SETTING_STAGE_GAP` / `STAGE_GAP_DEFAULT`).
  🚨 **간격은 손절폭보다 작아야 한다** — SHORT 손절 ROI −5% / 레버2 = 가격 2.5%.
  간격이 2.5% 이상이면 손절이 항상 먼저 와서 **2단계에 영원히 도달하지 못한다**
  (실측 850사이클: 간격 2.5% → SHORT 2·3단계 0건 / 1.5% → +2,636).
- 1단계 10 USDT 는 「자리 탐색」이라 **손절할 것이 없다** → `stage_trim` 이 스킵
  (`services/stage_trim.py:MIN_TRIM_RATIO_DEFAULT=2`).

**④ 볼밴 분할** — `workers/pump_split_entry_worker.py` (1,069줄)
- 자본 모델이 ③과 **정반대**: 100+200+300 = 600 을 **동시 보유**해 평단을 만든다.
- 진입 = 15m 기준선 대비 −3 / −5 / −7% 이탈. 2·3차는 `stage_plan.trigger_price` 로 심어
  **기존 `stage_trigger_worker` 가 처리**한다 (새 진입 경로를 만들지 않는다).
- 🚨 **다른 워커가 여기에 계획 밖 진입을 얹으면 평단이 설계와 반대로 밀린다.**
  2026-08-29 피라미딩이 4건에 300씩 얹어 **−252.18 USDT**(Fix 213).
  그래서 `stage_trim` 은 `split_entry` 를 **설정으로도 켤 수 없게 코드에 박아** 제외한다
  (`services/stage_trim.py:75` `ALWAYS_EXCLUDED_MODES`).

---

### 4. 공용 진입 관문 — `execution_service.start_stage1`

`backend/app/services/execution_service.py:188`.
**신규 진입은 전부 여기를 지난다.** 직접 호출은 **7곳**이고, 다음 명령으로 재현된다:

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend/app" && grep -rn "start_stage1(" --include=*.py . | grep -v "def start_stage1"
```

| 호출자 | 파일:줄 |
|---|---|
| API(수동·화면) | `api/v1/strategies/control.py:47` |
| 급등 정점 사다리 | `services/surge_ladder_entry.py:311` |
| BB 붕괴 자동 (= **공용 전략 생성 함수** `_create_auto_bb_strategy`) | `workers/auto_bb_breakdown_worker.py:2029` |
| 청산 후 재진입 | `workers/auto_reentry_worker.py:163` |
| 사다리 재시작 | `workers/ladder_restart_worker.py:310` |
| 볼밴 분할 | `workers/pump_split_entry_worker.py:1040` |
| 예약 진입 | `workers/scheduled_entry_worker.py:231` |

🚨 **`unified_15m_entry` 는 이 목록에 없다 — 없는 게 아니라 간접이다.**
`unified_15m_entry_worker.py:173-179` 이 `auto_bb_breakdown_worker` 에서
`_create_auto_bb_strategy` 를 import 해(호출은 `:433`) 그쪽 `start_stage1` 로 들어간다. §6-3 에서 `auto_bb_breakdown` **잡**이
주석 처리돼 있는데도 **모듈은 살아 있다**고 적은 이유가 이것이다.
그래서 `unified_15m_entry` 를 읽을 때는 `auto_bb_breakdown_worker` 를 **한 쌍으로** 봐야 한다.
(다만 `unified_entry_enabled=0` 이라 **지금 실서버에서는 이 경로가 안 돈다** — §6-1 끝의 경고.)

(`services/chg24_entry_gate.py:23-25` 는 「8개 경로」라고 적고 7개만 나열한다 —
`unified_15m` 이 간접이라 세다 말았다. 숫자보다 위 표를 믿을 것.)

#### 4-1. 게이트 순서 (위에서 아래로)

| 순 | 줄 | 게이트 | 설정 키 | 코드 기본 | **실서버 현재값** | fail 방향 |
|---:|---:|---|---|---|---|---|
| 1 | `:192` | 계정 Kill-Switch | (DB `account_kill_switch`) | — | — | 차단 |
| 2 | `:199-227` | **Fix 310/325 당일 변동률·순위** — 상승 50 + 하락 50 = 100개 | `entry_chg24_gate_enabled` / `entry_rank_top_n`(50) / `entry_chg24_gate_mode`(`rank`) | **OFF** | **ON (`1`)** | fail-**open** |
| 3 | `:231-267` | **Fix 327 지지선 7점** — LONG score≥6 / SHORT score≤1, 2~5 는 진입 금지 | `support_score_gate_enabled` | **OFF** (`support_score.py:128`) | **미설정 = OFF** | fail-**open** |
| 4 | `:270` | ISOLATED 마진 보장 | — | 항상 | — | 예외 |
| 5 | `:271` | 레버리지 적용 | — | 항상 | — | 예외 |
| 6 | `:272 → _place_stage_entry_order:1154` | **Fix 303 제외 심볼** (`_assert_symbol_allowed:1908`) | `excluded_symbols` | **ON**(코드 내장 목록) | 미설정 = 내장 11종 | 차단 (fail-**closed**) |
| 7 | `:272` | 실제 주문 발사 (MARKET or LIMIT) | — | — | — | — |
| 8 | `:277-303` | 추가 증거금 자동 투입(옵션) | `stage_plan.additional_margin_usdt` | 없으면 skip | — | 실패해도 진입은 유지 |

Fix 303 의 내장 제외 목록 (`services/symbol_exclusion.py:54-61` `DEFAULT_EXCLUDED`):
`BTCUSDT / BTCUSDC / BTCUSD1`(MIN_NOTIONAL 50), `ETHUSDT / ETHUSDC / LTCUSDT /
LINKUSDT / ETCUSDT / BCHUSDT`(20), `BTCUSDT_261225 / BTCUSDT_260925`(stepSize).
이유 = 「10 USDT 잔량」을 남길 수 없어 **팔 수 없는 dust** 가 된다.
🚨 이 저장소는 dust orphan **하나로 계정 전체가 막힌 전력**이 있다.

🚨🚨 **`excluded_symbols` 를 빈 값으로 저장하면 제외가 전부 풀린다 — 절대 하지 마라.**
`symbol_exclusion.py:79-82` 를 그대로 옮기면:

| `excluded_symbols` 값 | 결과 |
|---|---|
| 행 자체가 없음 / `NULL` | 내장 11종 유지 ✅ |
| 조회 실패(예외) | 내장 11종 유지 ✅ (fail-safe) |
| **빈 문자열 `""`** | `frozenset()` = **제외 0건** 🚨 BTCUSDT 까지 진입 대상이 된다 |
| `"AAAUSDT"` | **AAAUSDT 하나만** 제외 = 내장 11종이 **전부 풀린다** 🚨 |

즉 이 키는 **추가(add)가 아니라 대체(replace)** 다. 심볼을 하나 더 빼고 싶으면
**내장 11종을 전부 다시 나열한 뒤 그 뒤에 붙여야** 한다. 한 종목만 적으면
BTCUSDT 에 10 USDT 잔량을 남기려다 dust orphan → **계정 전체 차단**으로 간다.
되돌리는 법: 그 설정 **행을 지우면** 즉시 내장 11종으로 복귀한다(재배포 불필요).

🚨 **Fix 303 만 주문 함수 세 곳에 걸려 있다** —
`_place_stage_entry_order:1155`, `_place_market_entry:1940`, `_place_limit_entry:2165`.
후보 생산자(워커)마다 거는 방식은 이 저장소에서 **반복해서 실패**했다
(「게이트는 있는데 한 경로가 그 함수를 안 부른다」). 주문 직전에 두면 어떤 워커가
만들어도 새어나갈 수 없다. `tests/test_symbol_exclusion.py` 가 세 곳을 고정한다.

#### 4-2. 🚨 `trigger_next_stage` 에는 왜 걸면 안 되나

`execution_service.py:305`.

> 1단계 진입 때 12% 였다가 2단계 트리거 시점에 8% 로 떨어지면 사다리가
> **그 자리에서 영원히 멈춘다.** 이미 자금이 들어간 전략을 변동률로 끊으면 안 된다.
> — `execution_service.py:203-205`, `chg24_entry_gate.py:29-33`

같은 이유가 Fix 327 에도 적혀 있다 (`execution_service.py:250`:
"여기(1단계)에만 건다. `trigger_next_stage` 에 걸면 사다리가 멈춘다").

한 문장으로: **1단계 = 「안 사면 그만」이라 fail-closed 해도 되고,
2단계 이후 = 「이미 돈이 들어가 있다」라 막으면 탈출로가 사라진다.**

#### 4-3. `trigger_next_stage` 가 대신 갖는 게이트

| 순 | 줄 | 내용 | 설정 키 | 코드 기본 | 실서버 |
|---:|---:|---|---|---|---|
| 1 | `:328` | Kill-Switch (2026-05-04 fix — 예전엔 1단계에만 있었다) | — | 항상 | — |
| 2 | `:355 → _trim_before_stage:1784` | **Fix 312 「좋은 포지션」 대기** (v219 사다리 + SHORT 한정) | `stage_wait_for_turn_enabled` / `stage_wait_for_turn_sides`(SHORT) / `_types`(`auto_bb_break_SAJANGNIM`) / `_klines`(120) | **OFF** | **ON (`1`)** |
| 3 | 같은 곳 | **Fix 304 「10 USDT 만 남기고 청산」** 후 다음 단계 진입 | `stage_trim_before_next_enabled` / `stage_keep_notional_usdt` | **OFF** | **ON (`1`)** |
| 4 | `:357` | 주문 발사 (`_place_stage_entry_order` → Fix 303) | — | — | — |

🚨 `_trim_before_stage` 는 **자동(`trigger_next_stage:355`)과 수동
(`enter_stage_at_market` — 함수 시작은 `:1267`, 호출은 그 안 `:1331`) 양쪽**에서
불린다 (Fix 305).
한쪽만 걸면 그 경로로 물타기가 그대로 일어난다.

🚨 **fail 방향이 반대다**: 여기 Fix 304 는 **fail-CLOSED**
(남길 수량을 확정 못 하면 단계 진입 자체를 안 한다 — 실자금이라
"반쯤 실행된 상태"가 가장 위험). 반면 Fix 312 대기는 **fail-OPEN**
(캔들 조회 한 번 실패로 단계가 영구 정지하면 안 된다 — Fix 305 함정).

---

### 5. 🚨 손절 경로 — 함수가 **두 개**다 (여기서 사고가 났다)

디스패치는 한 곳이다 — `services/tp_sl_orchestrator.py:89-97`:

```
if self.risk_service.evaluate_force_stop_loss(strategy.id):
    self._execute_force_stop_loss(strategy)      # ← 사장님 −5% / −10% 는 여기로 온다
    return
if self.risk_service.evaluate_stop_loss(strategy.id):
    self._execute_stop_loss(strategy)            # ← −80~90% 일반 SL
    return
```

| | `_execute_force_stop_loss` (`:545`) | `_execute_stop_loss` (`:686`) |
|---|---|---|
| **누가 발동시키나** | `risk_service.evaluate_force_stop_loss` (`:367`) | `risk_service.evaluate_stop_loss` |
| **임계값** | 사장님 설정 ROI. 전역 `force_sl_{long,short}_*` + 전략별 `force_sl_roi_override` 우선 (−3 / −5 / −10 …) | 템플릿 `stop_loss_percent_of_capital` 기반 = 실질 **−80~90%** |
| **누가 쓰나** | 🚨 **사장님이 실제로 쓰는 손절** | 사실상 최후 안전망 |
| **단계 게이트** | 없음 (아무 단계에서나) — 단 v130 「다음 단계 남으면 보류」 게이트가 있었고 Fix 317/321/322 로 면제됨 | 같은 면제 규칙 공유 (Fix 321) |
| **재진입** | ❌ `mark_reentry_ready` **호출 안 함** = 사장님 손절 의사 = 그 전략 종료 | ✅ `mark_reentry_ready(strategy.id)` 호출 |
| **부분 손절** | Fix 319/326 (`:596-640`) | Fix 318/326 (`:720-757`) — **지금은 양쪽 다 있다** |
| **호출 주기** | `tp_sl` 잡 = **15초** | 동일 |

#### 5-1. 왜 헷갈리는가 — Fix 318 사고

`tp_sl_orchestrator.py:555-563` 이 직접 적어 놓았다:

> Fix 318 은 `_execute_stop_loss`(−80~90% 일반 SL)에 붙어서 **실제로는 아무 효과가
> 없었다.** #2046 AKEUSDT 가 전량 청산된 것도 이 함수를 탔기 때문이다.
> 사전 검증을 하지 않아 함수를 잘못 골랐다.

혼동의 원인 세 가지:
1. **이름이 거의 같다** — `_execute_stop_loss` vs `_execute_force_stop_loss`.
2. **둘 다 「손절」이고 둘 다 부분 청산 로직을 갖는다.** 코드를 봐서는 어느 쪽이
   사장님 설정과 연결되는지 알 수 없다 — 연결은 `risk_service` 의 **평가 함수 이름**에 있다.
3. **정적 검사가 통과한다.** 「소스에 이 문자열이 있나」는 통과했고 배포까지 됐다.

🚨 **기억할 한 줄: 「사장님이 화면에서 고른 손절 %」= `force_sl_*` = `_execute_force_stop_loss`.**

#### 5-2. 부분 손절의 세 갈래 (양쪽 함수 공통)

`services/stage_trim.compute_trim` 이 반환하는 `action` 으로 갈린다:

| action | 처리 | 왜 |
|---|---|---|
| `TRIM` | **10 USDT 만 남기고** 청산 → **전략을 종료하지 않는다** (`STOPPING` 안 찍음, 미체결 LIMIT 도 안 지움) | 사장님 "전략 인스턴스에 남겨둬야 겠어" |
| `SKIP` | **손절하지 않고 그대로 둔다** (Fix 326) | 이미 잔량 수준. 여기서 전량 청산하면 다음 사이클이 사양을 지운다 |
| `BLOCK` | 전량 청산 (안전측) | 판정 불가일 때 손절을 막으면 손실이 커진다 |

🚨 **같은 `BLOCK` 이 호출처에 따라 정반대로 동작한다 — 헷갈리면 손절이 멈춘다.**
상수는 소문자(`ACTION_BLOCK = "block"`, `stage_trim.py:109`)이고, 호출처가 둘뿐인데
**둘이 다르게 다룬다**:

| 호출처 | `BLOCK` 처리 | 방향 |
|---|---|---|
| `execution_service._trim_before_stage:1884` (단계 진입 전, Fix 304) | **명시적 분기 — 단계 진입을 중단** | fail-**CLOSED** ("안 사면 그만") |
| `tp_sl_orchestrator:605·729` (손절, Fix 318/319/326) | **`ACTION_BLOCK` 분기가 아예 없다.** import 도 `ACTION_SKIP, ACTION_TRIM` 둘뿐 → BLOCK 은 그냥 **아래로 흘러 전량 청산** | fail-**OPEN**(손절은 반드시 나간다) |

- 그래서 `grep ACTION_BLOCK app/services/tp_sl_orchestrator.py` 는 **0건이 정상**이다.
  「문서가 틀렸다」가 아니다.
- 🚨 **여기에 `elif _act == ACTION_BLOCK: return` 같은 분기를 「일관성」이라며 넣지 마라.**
  판정 불가(시세 결손·필터 결손)일 때 손절이 통째로 멎어 **손실 상한이 사라진다.**
  진입 쪽과 손절 쪽의 fail 방향이 다른 것은 **의도**다(§4-3 과 같은 원칙).

🚨 **Fix 326 의 교훈** (`tp_sl_orchestrator.py:576-597`) — 실서버 로그가 잡았다:
```
07:55:00  MARSCOIN #2091 부분 손절 → 184 잔여 (명목 20.04)   ✅
08:00:22  MARSCOIN #2091 「남길 것이 없다」 → 전량 청산       ❌ 5분 뒤
```
> **부분 청산을 만들면 「남긴 것」이 다음 사이클에 어떻게 취급되는지 반드시 따라가라.**
> 한 번의 부분 손절은 성공해도 다음 사이클이 그것을 지우면 구현되지 않은 것과 같다.

#### 5-3. 단계 게이트 면제 — `risk_service._stage_gate_exempt` (`:165`)

「단계가 남으면 손절 보류」(v130 물타기 전제)를 면제하는 판정.
🚨 예전엔 **세 곳에 흩어져** 있었고 면제는 force SL 한 곳에만 있었다(Fix 321).
지금은 한 함수로 모아 세 게이트가 같은 판정을 쓴다.

면제 대상: 청산 후 재진입 / `split_entry` / `stage_ladder` / Fix 304 ON /
**사장님이 그 전략에 손절 ROI 를 명시한 경우**(Fix 322).
실측: 단계 계획이 있는 전략 **1,221건 중 371건(30%)** 이 이 게이트에 걸려
손절이 마지막 단계까지 보류되고 있었다.

---

### 6. 워커 지도 — `scheduler_runner.py` 가 유일한 진실

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend/app" && grep -n 'id="' workers/scheduler_runner.py
```

🚨 위 grep 은 **id 만** 보여준다. 주기와 락 TTL 은 `add_job(...)` 이 여러 줄로 쪼개져
있어 같은 줄에 없다. **주기까지 한 번에 보려면** 아래를 쓴다 (아래 표를 통째로 재생성한다):

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend/app" && grep -n -A6 'scheduler.add_job' workers/scheduler_runner.py | grep -E 'guarded_job\("|IntervalTrigger|CronTrigger|id="'
```

APScheduler `BlockingScheduler(timezone="Asia/Seoul")` (`scheduler_runner.py:74`),
`DistributedSchedulerGuard` 로 리더 1대만 실행 (생성 `:76`, 실제 판정은 모든 job 을
감싸는 `guarded_job` `:117-131`).

#### 6-1. 매매에 직접 관여하는 워커 (중요도 순)

| 주기 | job id | 모듈 | 하는 일 |
|---|---|---|---|
| **15초** | `tp_sl` | `run_workers.run_tp_sl_once` → `TPSLOrchestratorService` | **모든 익절·손절** (§5) |
| **15초** | `stage_trigger` | `stage_trigger_worker` | **단계 진입 판정** — 네 방식 분기 |
| 15초 | `auto_add_margin` | `auto_add_margin_worker` | 자동 증거금 추가 |
| 30초 | `realtime_reentry` | `realtime_reentry_worker` | 실시간 재진입 |
| 30초 | `success_pyramiding` | `success_pyramiding_worker` | 이익 시 추가 진입 (🚨 `split_entry` 제외) |
| 30초 | `auto_long_at_bottom` | `auto_long_at_bottom_worker` | LONG 저점 진입 |
| 30초 | `auto_short_at_top` | `auto_short_at_top_worker` | SHORT 정점 진입 |
| 30초 | `surge_peak_ladder` | `surge_peak_ladder_worker` | 급등 정점 사다리 |
| 30초 | `resistance_reversal` | `resistance_reversal_worker` | 저항 반전 SHORT |
| 30초 | `peak_break_reversal` | `peak_break_reversal_worker` | 정점 붕괴 반전 |
| **30초** | `unified_15m_entry` | `unified_15m_entry_worker` | **v224 통합 진입 소스** (`:505-510` `IntervalTrigger(seconds=30)`, TTL 25s). 🚨 **실서버에서는 지금 아무것도 진입하지 않는다** — 아래 참조 |
| 60초 | `auto_reentry` | `auto_reentry_worker` | 청산 후 재진입 |
| 1분 | `daily_loss_check` | `daily_loss_aggregator` | 일일 손실 한도 |
| 1분 | `liquidation_risk` | `liquidation_risk_worker` | 청산 위험 사전 알림 |
| 3분 | `macd_reversal_15m` | `macd_reversal_15m_worker` | 15m MACD 반전 |
| 5분 (시작 +150초) | `long_bottom_detector` | `long_bottom_detector_worker` | LONG 저점 후보 |
| 5분 | `bb_upper_breakout_short` | `bb_upper_breakout_short_worker` | BB 상단 돌파 SHORT |
| 5분 | `pump_top_detector` | `pump_top_detector_worker` | 급등 정점 감지 |
| 5분 | `pump_dump_early_detector` | `pump_dump_early_detector_worker` | 급등락 조기 감지 |
| 5분 | `ladder_restart` | `ladder_restart_worker` | 사다리 재시작 |
| 5분 | `scheduled_entry` | `scheduled_entry_worker` | 예약 진입 (`mode=scheduled`) |
| 15분 | `pump_split` | `pump_split_entry_worker` | **볼밴 분할 (④)** |
| 15분 | `bb_mid_line` | `bb_mid_line_worker` | BB 중단선 전략 |
| 15분 | `realtime_watchlist` | `realtime_watchlist_worker` | 감시 목록 갱신 |

🚨🚨 **「등록돼 있다」와 「진입한다」는 다르다 — `unified_15m_entry` 가 그 예다.**
2026-09-03 실서버 실측:

```
unified_entry_enabled       0        ← 워커 첫 줄에서 return
auto_bb_break_daily_limit   0        ← 통과해도 두 번째 줄에서 return
```

`unified_15m_entry_worker.py:162-170` 이 이 둘을 차례로 보고 **하나라도 0 이면 즉시
`{"entered": 0}` 로 나간다** (지금은 둘 다 0 이라 첫 줄에서 끝난다).
즉 30초마다 돌기는 하지만 **주문은 한 건도 안 낸다.**
따라서 진입은 §6-3 아래쪽에 **다시 등록된** `pump_top_detector`(5분) /
`auto_short_at_top`(30초) 등 **v224 이전 경로**에서 나온다.
⚠️ 다만 그 워커들의 **자체 ON 스위치까지는 확인하지 못했다** — 같은 방식으로
각자의 설정 키를 §9 명령에 추가해 확인할 것.

🚨 이 저장소가 반복해서 당한 함정이 정확히 이 모양이다 — 「스케줄러에 있으니 돌겠지」.
**워커를 조사할 때는 ① 등록됐나 ② 락에 안 걸리나(§6-4) ③ 자기 ON 스위치가 켜졌나
세 가지를 다 본다.** ③ 은 §9 의 설정 조회 명령으로 확인한다.

#### 6-2. 감시·정합성·학습 워커

| 주기 | job id | 하는 일 |
|---|---|---|
| 1분 | `silent_bug_detector` | 잠재 silent bug 감지 |
| 2분 | `position_reconcile` | 거래소 ↔ DB 정합 회복 (🚨 고아 정리는 `position_amt == 0` **정확히 0** 일 때만) |
| 2분 | `tp_miss_detector` | TP 도달했는데 미실행 감지 |
| 2분 | `reentry_alert` | 재진입 알람 |
| 5분 | `trade_anomaly_monitor` / `stage_calc_audit` / `user_intent_validator` / `edit_mode_validator` / `auto_fix_proposer` / `telegram_retry` / `learning_sync` / `martingale_gate_validator` / `orchestra_health` | 자동 가드·학습 |
| 변수 | `heartbeat` (`:593`) | 주기가 상수가 아니라 변수 `hours=hb_hours` 다 — 값은 파일에서 확인 |
| 3분 | `setting_preservation` | 사장님 설정 영구 유지 |
| 10분 | `pump_bb_watcher` | 급등 + BB중단 알람 |
| 30분 | `listenkey_keepalive` / `endpoint_health_monitor` / `failure_pattern_analyzer` | |
| 1시간 | `self_check` / `spec_audit` / `mainnet_safety` / `settings_sync` / `suggestion_cleanup` / `market_obs_update` / `pattern_learning` / `prediction_outcome` | |
| 4시간 | `market_obs_snapshot` / `learning_team_cycle` | |
| 6시간 | `binance_changelog_monitor` / `chart_pattern_scan` | |
| Cron | `symbol_sync_daily`(03:00) / `suggestion_daily_predict`(06:30) / `suggestion_auto_execute`(07:00) / `daily_briefing`(22:30 UTC=KST 07:30) / `daily_summary`(15:00) / `memory_consolidator`(18:00) / `daily_report`(UTC 00:00=KST 09:00) | |

#### 6-3. ⛔ 등록이 **주석 처리된** 워커 (파일은 남아 있다 — 착각 주의)

| 워커 | 줄 | 왜 껐나 |
|---|---:|---|
| `auto_bb_breakdown` | `:315-320` | v224 통합 → `unified_15m_entry` 로 대체. 🚨 **모듈 자체는 살아 있고 다른 곳에서 import 된다** |
| `pending_hc_fast` | `:376-381` | 같은 통합 |
| `pump_top_detector` (구 5분판) / `auto_short_at_top` (구 30초판) | `:391-404` | 통합 후 **아래쪽 `:663-692` 에서 다시 등록됨** — 같은 id 가 두 번 나오니 grep 만 보고 「꺼졌다」고 판단하지 말 것 |
| `time_reverse_exit` | `:645-652` | 비활성 |

🚨 롤백 방법이 각 주석에 적혀 있다 (`scheduler_runner.py:311`):
**주석 해제 + `unified_entry_enabled=0`**.

🚨 **실서버는 그 롤백이 「반만」 된 상태다** — 설정은 이미 `unified_entry_enabled=0`
인데 **주석은 그대로**다. 그래서 `auto_bb_breakdown`(BB 4H)과 `pending_hc_fast` 는
**어느 쪽으로도 안 돈다**(잡 미등록 + 통합 경로 OFF). 반대로 `pump_top_detector` /
`auto_short_at_top` 은 아래쪽에 다시 등록돼 있어 **그대로 돈다.**
→ 「BB 4H 진입이 왜 없지?」의 답이 여기 있다. 되살리려면 위 주석을 해제한다
(코드 수정 + 재배포이므로 **사장님 승인 없이 하지 말 것**).

🚨 **되살릴 때 순서를 틀리면 실자금으로 이중 진입이 난다.**
`unified_15m_entry` 와 `auto_bb_breakdown` 은 **같은 15m 급등/급락 후보**를 본다.
둘이 동시에 돌면 같은 심볼에 진입이 두 번 나가고, 그건 롤백이 아니라 **물량 2배**다.

| 순서 | 할 일 | 왜 이 순서인가 |
|---:|---|---|
| 1 | DB 설정 `unified_entry_enabled=0` **을 먼저 확인**(이미 0이면 그대로) | 설정은 재배포 없이 즉시 먹는다 |
| 2 | 통합 경로 진입이 실제로 멎었는지 로그로 확인 | 「설정했다」와 「멎었다」는 다르다 |
| 3 | 그 다음에 주석 해제 → 커밋 → **사장님이** pull + 재시작 | 코드는 재시작 전엔 안 먹는다 |

되돌리기(rollback of the rollback): **주석을 다시 넣기 전에** `unified_entry_enabled=1`
로 올리지 말 것 — 순서가 3→1 이 되면 그 사이에 둘 다 도는 창이 생긴다.
반드시 **주석 원복 + 재시작 → 그 다음 `unified_entry_enabled=1`**.

ℹ️ 참고: 주석 안의 `auto_bb_breakdown` 등록은 `IntervalTrigger(hours=1)` 이다
(15분이 아니다 — 되살려도 시간당 1회다).

#### 6-4. 🚨 워커가 조용히 안 도는 두 가지 이유

`scheduler_runner.py:91-131` (Fix 139 — 이유는 주석 `:91-106`, 코드는 `guarded_job:117-131`):
1. 리더가 아님 (`refresh_leader` 실패)
2. **이전 실행이 아직 락을 쥐고 있음** (`acquire_job_lock` 실패)

`guarded_job(job_name, ttl_seconds, fn)` 의 두 번째 인자가 **락 TTL**이다.
🚨 예: `success_pyramiding` 은 TTL 25s / 주기 30s → 한 번이라도 25초를 넘기면
그 뒤로 계속 건너뛸 수 있다. 지금은 **연속 skip 1회째와 20회마다** 경고 로그가 남는다.

---

### 7. 최근 신설 모듈 7개 (2026-09-03 세션)

| 모듈 | 줄 | 하는 일 | 설정 키 | 코드 기본 | 실서버 | 걸리는 곳 |
|---|---:|---|---|---|---|---|
| `services/stage_trim.py` | 412 | **「10 USDT 만 남기고 청산」** 수량 계산. `TRIM/SKIP/BLOCK` 반환 | `stage_trim_before_next_enabled`, `stage_keep_notional_usdt`(10), `stage_min_trim_ratio`(2), `stage_max_cumulative_loss_usdt`, `stage_trim_exclude_modes` | OFF | **ON** | 단계 진입 전(Fix 304) + 손절 양쪽(Fix 318/319) |
| `services/support_score.py` | 403 | **지지선 7점 판정.** LONG≥6 / SHORT≤1, 2~5 관망 | `support_score_gate_enabled`, `support_score_min_long`, `support_score_max_short` (🚨 `support_score_gate_*` 아님) | **OFF** | 미설정 = OFF | `start_stage1:253` |
| `services/chg24_entry_gate.py` | 184 | **당일 상승 50 + 하락 50 = 100개**만 신규 진입 | `entry_chg24_gate_enabled`, `entry_rank_top_n`(50), `entry_chg24_gate_mode`(`rank`/`abs`), `entry_min_abs_chg24`(10) | OFF | **ON** | `start_stage1:208` |
| `services/symbol_exclusion.py` | 121 | **자동매매 제외 심볼** 11종 (MIN_NOTIONAL > 10) | `excluded_symbols` (있으면 내장 목록을 **대체**) | **ON**(내장) | 내장 | 주문 함수 3곳 |
| `services/trend_4h_gate.py` | 220 | **4H MACD hist 「상승 중 AND > 0」** = 확정 흐름이 내 편인가 | `trend_4h_gate_enabled` | **OFF** (`trend_4h_gate.py:69-79`) | 🚨 **ON (`1`)** | `auto_bb_breakdown_worker:1545`, `bb_mid_line_worker:260`, `success_pyramiding_worker:756` |
| `services/sajangnim_capital.py` | 393 | **자본 사다리 10/300/600** + 단계 간격 + `stage_ladder` 마커 | `sajangnim_capital_ladder`(10,300,600), `sajangnim_ladder_stages_enabled`, `sajangnim_stage_gap_pct`(1.5) | 사다리 ON | **ON**, 사다리 `10,300,600` | `auto_bb_breakdown_worker`, `risk_service._stage_gate_exempt` |
| `services/stage_entry_timing.py` | 154 | **「좋은 포지션」 대기** — 트리거 도달 후 꺾임을 기다린다 | `stage_wait_for_turn_enabled` / `_sides`(SHORT) / `_types`(`auto_bb_break_SAJANGNIM`) / `_klines`(120) — 앞은 전부 `stage_wait_for_turn_` 접두사 (`stage_entry_timing.py:68-75`) | OFF | **ON** | `_trim_before_stage:1809` |

🚨 **적용 대상이 각각 다르다 — 전부에 걸린다고 착각하기 쉽다:**
- `chg24_entry_gate` / `support_score` → **신규 1단계만**
- `stage_entry_timing` → **v219 사다리 + SHORT 만** (기본방식·OBV 제외)
- `stage_trim` → **`split_entry` 는 코드로 영구 제외**
- `trend_4h_gate` → 워커 3곳에서 각각 호출 (공용 관문 아님)

🚨 **`trend_4h_gate` 는 통과율이 21%** 다. 켜면 진입이 1/5 로 준다.
그리고 **실서버는 이미 켜져 있다** — 2026-09-03 재조회에서 `trend_4h_gate_enabled='1'`.
「진입 후보는 많은데 실제 진입이 적다」를 조사할 때 **여기를 먼저 보라.**
🚨 `auto_bb_breakdown_worker:1545` 는 **`_create_auto_bb_strategy`(:1404-2167) 안**이다.
즉 잡이 주석 처리된 `auto_bb_breakdown` 뿐 아니라 **`unified_15m_entry` 로 만드는 전략도
이 게이트를 지난다** (§4 의 간접 경로). 「그 워커는 꺼져 있으니 상관없다」가 아니다.

실서버 ON/OFF 를 추측하지 말고 **§9 「게이트 ON/OFF 실제값」 명령으로 매번 다시 확인**한다.
사장님이 화면에서 언제든 바꾸므로 이 표의 「실서버」 열은 **찍은 순간의 값**이다.

🚨 **`support_score` 의 가장 중요한 발견**(`support_score.py:14-31`):
> **반등을 보고 들어가면 진다.** 아래꼬리·RSI 상향전환·거래량 급증은 전부
> 부호가 반대이거나 "이미 반등해서 비싸게 사는" 아티팩트였다.
> 15m MACD hist 「상승 중」은 **역방향 지표**로 채택했다.

---

### 8. 테스트 지도 — 「정적 검사는 증명하지 못한다」

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend" && python -m pytest -q
```

#### 8-0. 🚨 전체 실행 결과를 미리 알고 시작하라 — **지금도 52건이 실패한다**

2026-09-03, `ded22f3` 코드 + Windows / Python 3.14.2 에서 실제로 돌린 결과:

```
52 failed, 1714 passed in 696.68s (0:11:36)
```

- **12분쯤 걸린다.** 멈춘 게 아니다. 급하면 §8-1 의 두 파일만 돌린다(1초).
- **52건 실패는 새 PC 환경 탓이 아니다.** 표본으로 확인한
  `tests/unit/test_strategy_status_constants.py` 는
  「`TERMINAL_STATUSES` 는 7개」라고 단언하는데 코드는 이미 8개다
  (`STOPPED_CAPITAL_EXHAUSTED` 추가) — **코드가 앞서고 테스트가 뒤진 것**이다.
- 그래서 **「전부 green」을 목표로 삼지 마라.** 새 PC 에서 처음 한 번 돌려
  위 숫자와 **같은지**만 확인하고, 그 숫자를 기준선으로 삼는다.
  코드를 고친 뒤 실패가 **52건보다 늘면** 그게 내가 낸 것이다.

실패가 몰린 파일 (⚠️ 52건 중 **29건분만 기록**했다 — 실행 출력 끝부분만 남겨서
전수는 아니다. 전수가 필요하면 아래 명령을 `tail` 없이 다시 돌린다):

| 파일 | 실패 |
|---|---:|
| `tests/unit/test_martingale_stage_entry.py` | 7 |
| `tests/unit/test_v7_short_exit_partial_stage.py` | 4 |
| `tests/unit/test_stream_service_partial_close.py` | 4 |
| `tests/integration/test_verify_tp_sl_entry.py` | 3 |
| `tests/unit/test_strategy_status_constants.py` / `test_risk_constants_centralization.py` | 2 / 2 |

기준선을 다시 재려면 (요약만 남긴다):

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend" && python -m pytest -q 2>&1 | tail -3
```

실패 **전수를 파일별로** 보려면 (기준선을 새로 적어 둘 때 이걸 쓴다):

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend" && python -m pytest -q 2>&1 | grep '^FAILED' | sed 's/::.*//' | sort | uniq -c | sort -rn
```

| 위치 | 파일 수 | 성격 |
|---|---:|---|
| `tests/` (루트) | 20 (`conftest.py` 포함 = 테스트 19) | **최근 사양 검증** — Fix 303~327 대부분 여기 |
| `tests/unit/` | 80 | 순수 함수·계산·상수 고정 |
| `tests/integration/` | 58 | sqlite in-memory + FastAPI (`tests/conftest.py`) |
| `tests/e2e/` | 1 | `test_sajangnim_scenarios.py` |

`tests/conftest.py` = sqlite `:memory:` 세션 픽스처. **실 DB·실 거래소를 쓰지 않는다.**
`pytest.ini` 가 `pythonpath = .` / `testpaths = tests` 를 정하므로 **반드시 `backend/`
에서** 돌린다 (저장소 루트에서 돌리면 `tests` 를 못 찾는다).

**디렉터리별로 나눠 재면 52건이 어디 있는지 바로 보인다** (2026-09-03 실측):

| 대상 | 결과 | 시간 |
|---|---|---:|
| `tests/` 루트만 (`--ignore=tests/unit --ignore=tests/integration --ignore=tests/e2e`) | **317 passed, 0 failed** ✅ | 15초 |
| `tests/unit` | 1001 passed, **24 failed** | 82초 |
| `tests/integration tests/e2e` | 396 passed, **28 failed** | 502초 |

🚨 **Fix 303~327 사양을 담은 `tests/` 루트는 지금 100% green 이다.**
그러니 진입·손절을 고친 뒤에는 12분짜리 전체 대신 **루트 317건(15초)을 먼저** 돌린다.
여기서 하나라도 빨개지면 **그건 100% 내가 낸 것**이다 — 기준선 핑계가 없다.

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend" && python -m pytest -q tests/ --ignore=tests/unit --ignore=tests/integration --ignore=tests/e2e
```

🚨 **`.env` 를 실서버 값으로 채운 채 테스트를 짜지 마라 — 실 DB 를 때릴 수 있다.**
`app/core/database.py` 는 **import 시점에** `settings.database_url`(=`.env` 의
`DATABASE_URL`)로 엔진을 만든다. 지금 있는 테스트는 워커마다
`monkeypatch.setattr("app.workers.X.SessionLocal", ...)` 로 **하나하나 갈아끼워서**
안전한 것이지, 구조적으로 막혀 있는 게 아니다.
- 새 테스트에서 `SessionLocal` 패치를 **빼먹으면 그 워커가 실서버 Neon DB 에 쓴다.**
- 워커 함수(`run_*_once()`)를 REPL·스크립트에서 맨손으로 부르는 것도 같다.
- 안전책: 새 PC 의 로컬 `.env` 는 `DATABASE_URL` 을 **실서버가 아닌 값**으로 두고,
  실서버 조회는 §9 의 VPS 명령으로만 한다.

#### 8-1. 🚨 「실행 테스트」 두 개가 특별한 이유

**`tests/test_stop_loss_execution_path.py`** — 파일 상단이 이유를 직접 적었다:

> 지금까지 내 테스트는 전부 **정적 검사**였다 — "소스에 이 문자열이 있나".
> 그건 **「그 함수가 실제로 불린다」를 증명하지 못한다.**
> (…) 같은 이름의 손절 함수가 둘인데 아래쪽을 고쳤다.
> **정적 검사 13건이 전부 통과**했고 배포까지 됐는데, 사장님 손절은 여전히
> 전량으로 나가 #2046 이 전량 청산됐다.

무엇을 하나:
- `TPSLOrchestratorService` 를 **실제로 실행**하고 거래소로 나가는
  `emergency_close_position(quantity=...)` 를 가로채 **수량을 검사**한다.
- 손절이 어느 함수를 타든 상관없다 — **주문이 부분인지만 본다.**
- 함수를 잘못 고르면 **즉시 실패**한다.
- 잔량을 남겼는데 `STOPPING` 을 찍으면 실패 / 부분인데 미체결 주문을 취소하면 실패.

**`tests/test_stage_flow_execution.py`** — 같은 방식으로 `trigger_next_stage` 를
실행해 **주문의 순서와 수량**을 검사한다. 상단에 사고 3건이 적혀 있다:

| 사고 | 정적 검사 결과 |
|---|---|
| Fix 318 — 엉뚱한 손절 함수에 붙였다 | 13건 **전부 통과** |
| Fix 311 — 1단계 진입을 통째로 막았다 | 57건 **전부 통과** |
| Fix 315 — 마커를 저장 안 해 손절을 다시 잠갔다 | **테스트가 없었다** |

검증 대상 사양:
```
기본 방식 : 트리거 단가 도달 → 10 USDT 남기고 청산 → 그 단가에 다음 단계 진입
OBV 자동  : 같은 흐름 (판정만 stage_entry_signal 이 한다)
1단계 10  : "손절없이 그냥" → 정리 없이 바로 다음 단계
볼밴 분할 : 물타기가 설계 → 정리하지 않는다
```

🚨 **새 PC 에서 진입/손절 코드를 건드리면 이 두 파일을 반드시 돌려라.**

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend" && python -m pytest -q tests/test_stop_loss_execution_path.py tests/test_stage_flow_execution.py
```

✅ 이 두 파일은 **`28 passed in ~1s`** 가 나와야 한다 (2026-09-03 실행 확인).
위 전체 실행의 52건 실패와 달리 **여기는 하나도 실패하면 안 된다** — 1건이라도
빨간색이면 진입·손절 실행 경로가 깨진 것이므로 **거기서 멈춘다.**

#### 8-2. 구조를 고정하는(회귀 방지) 테스트

| 파일 | 무엇을 고정하나 |
|---|---|
| `tests/test_symbol_exclusion.py` | Fix 303 이 주문 함수 **세 곳 모두**에 있는지 |
| `tests/unit/test_pyramiding_excludes_bbsplit.py` | `SPLIT_ENTRY_MODE` ↔ `MODE_MARKER` 문자열 동기화 |
| `tests/test_stage_gate_exempt.py` / `tests/test_force_sl_stage_gate.py` | 단계 게이트 면제 규칙 |
| `tests/test_partial_stop_loss.py` / `tests/test_stage_trim.py` | 부분 손절 수량 계산 |
| `tests/unit/test_status_set_centralization.py` / `test_strategy_status_constants.py` | 상태 집합 단일 출처 ⚠️ 후자는 **현재 2건 실패**(위 기준선) |
| `tests/unit/test_codebase_guards.py` / `test_static_assets_integrity.py` | 코드베이스 가드 / `?v=` 해시 ⚠️ **각 1건 실패** |
| `tests/unit/test_last_stage_trigger_single_source.py` | 「같은 칸이 두 저장소」 재발 방지 |
| `tests/test_chg24_entry_gate.py` / `test_support_score.py` / `unit/test_trend_4h_gate.py` | 신설 게이트 |

---

### 9. 새 PC 에서 바로 쓸 확인 명령

#### 9-0. ⛔ 새 PC 에서 **절대 하면 안 되는 것 네 가지**

이 문서의 명령은 전부 「읽기」다. 아래 넷은 읽기처럼 보이지만 **실자금이 나간다.**

| ⛔ 하지 마라 | 무슨 일이 나나 | 대신 |
|---|---|---|
| **로컬에서 스케줄러 실행** (`python -m app.workers.scheduler_runner`, `docker compose up`) | 리더 선출은 Redis `sched:leader` **한 키**로 한다(`distributed_scheduler_guard.py:11`). 로컬 Redis 는 VPS 와 **다른 Redis** 라 로컬 인스턴스가 **즉시 자기 리더**가 되고, `.env` 의 실서버 DB + 실 API 키로 **41개 워커 전부**를 돈다 → VPS 와 **동시에 같은 심볼에 주문**한다 | 실행은 VPS 에서만. 로컬은 §9 의 조회 명령만 |
| **로컬에서 `uvicorn app.main:app`** | 같은 이유. API 만 띄워도 `/api/v1` 의 진입·청산 엔드포인트가 **실서버 DB + 실 계정**에 붙는다 | 화면 확인이 필요하면 VPS 의 실제 화면을 본다 |
| **로컬에서 바이낸스 API 를 직접 호출** (심볼 루프, 캔들 수집, `client.py` 를 REPL 에서 부르기) | ① 가중치 한도는 **IP 단위** → `-1003` / HTTP **418 IP ban**. 이 저장소는 ban 을 **스스로 연장한 전력**이 있다. ② 주문·요청 카운트 일부는 **계정 단위** → 로컬이 태운 몫만큼 **VPS 의 실매매가 굶는다**. 실제로 이 이유로 `tp_sl`·`stage_trigger` 주기를 10s→15s 로 낮췄다(`scheduler_runner.py:533-534`) | 시세·포지션은 §9 의 **VPS DB 조회**로 본다 |
| **`alembic upgrade head` 를 로컬에서** | `.env` 가 실서버 Neon 을 가리키면 **운영 DB 스키마가 바뀐다.** 되돌리기가 가장 어려운 작업이다 | 마이그레이션은 배포 절차의 일부 — 사장님 승인 + VPS 에서만 |

🚨 **위 넷의 공통 방아쇠는 하나 — 실서버 값이 든 `.env`.**
새 PC 로컬 `.env` 는 `DATABASE_URL` / `REDIS_URL` / 바이낸스 키를 **실서버가 아닌 값**으로
두는 것이 유일하게 안전한 상태다. 실서버 값이 필요하면 그때만, VPS 안에서 쓴다.

🚨 **코드를 만질 때 — 이 저장소는 worktree 를 공유한다.**
`git stash` / `git stash pop` 을 맨손으로 쓰지 마라. stash 는 **저장소 전역**이라
다른 worktree·다른 세션이 만든 stash 와 섞이고, `pop` 이 충돌하면 어느 쪽 변경인지
분간이 안 된다. 임시 보관이 필요하면 **브랜치를 하나 파서 커밋**한다
(`git switch -c wip/설명 && git add -A && git commit -m wip`).
같은 이유로 `git reset --hard` / `git clean -fd` / `git push --force` 도
**현재 worktree 밖의 남의 작업을 지운다** — 쓰지 마라.

**로컬 — 코드 구조 확인** (읽기만 한다)

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend/app" && for d in */; do echo "$d $(find "$d" -name '*.py' -not -path '*__pycache__*' | wc -l)"; done
```

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend/app" && grep -n 'id="' workers/scheduler_runner.py
```

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend/app" && grep -n "^    def " services/execution_service.py
```

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend" && python -m pytest -q tests/test_stop_loss_execution_path.py tests/test_stage_flow_execution.py
```

**VPS — 읽기 전용 조회** (🚨 재시작·설정변경·DB 쓰기 금지)

🚨 **`system_settings` 는 재시작 없이 즉시 먹는다 = 되돌릴 「배포」가 없다.**
워커들이 매 사이클 DB 에서 값을 다시 읽으므로, 한 줄 UPDATE 가 **다음 15초 안에**
실매매 동작을 바꾼다. 그래서 값을 바꾸는 일은 사장님 몫이고, 부득이 바꿔야 한다면
**바꾸기 전에 옛 값을 반드시 먼저 찍어서 남긴다** (이게 유일한 rollback 기록이다):

```bash
# ① 바꾸기 전 — 현재 값 백업 출력 (읽기)
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"select key, value from system_settings where key = :k\"), {\"k\":\"바꿀_키_이름\"}):
    print(\"BEFORE\", r)
"'
```
행이 **하나도 안 나오면** 그 키는 「미설정」이고, 되돌릴 때는 값을 되쓰는 게 아니라
**그 행을 지워야** 원래 상태가 된다 (「미설정」과 「빈 값」은 다르다 —
`excluded_symbols` 가 바로 그 예, §4-1).

⛔ **선행 조건**: 아래 `ssh` 가 `Permission denied (publickey)` 로 막히면 코드 문제가
아니다. 서버는 **비밀번호 로그인이 꺼져 있고** 등록된 공개키가 1개뿐이라, 그 짝인
개인키(`~/.ssh/id_ed25519`)가 새 PC 에 없으면 **어떤 방법으로도 못 들어간다.**
옮기는 절차는 `secrets.md` §7 / `vps-ops.md` 를 볼 것 — **이 문서에는 없다.**
(개인키를 옮기는 건 사장님이 직접 한다. 채팅·메일로 보내지 말 것.)

> 🔐 **아래 명령을 응용하기 전에 — 컨테이너 안에서는 비밀이 평문으로 튀어나온다.**
> 이 recipe 는 api 컨테이너 안에서 **앱 코드를 그대로 실행**한다. 그래서 아래 세 가지는
> 실행하는 순간 터미널 스크롤백·채팅 로그·스크린샷에 **실키가 남는다.**
>
> | ❌ 절대 하지 말 것 | 왜 |
> |---|---|
> | `print(settings)` / `print(settings.model_dump())` | `config.py` 는 `SecretStr` 을 안 쓴다 — 전 필드가 평문 `str` 이라 `ENCRYPTION_KEY`·`DATABASE_URL`·`TELEGRAM_BOT_TOKEN`·`SECRET_KEY` 가 **한 줄에 전부** 찍힌다 (`app/core/config.py:8-26`, 저장소 전체에서 `SecretStr` 사용 **0곳**) |
> | `print(decrypt_text(account.api_key_enc))` | 바이낸스 **실계좌 API 키 평문**. 앱 코드는 `decrypt_text()` 결과를 로그·print 로 내보내는 곳이 **0곳**이다(`grep -rnE '(logger\|print)\..*decrypt_text' app` = 무결과) — 조회하겠다고 그 규칙을 깨지 말 것 |
> | `select * from exchange_accounts` | `api_key_enc` / `api_secret_enc` 암호문이 통째로 나온다. `ENCRYPTION_KEY` 를 가진 사람에게는 평문과 같다 |
> | `env` / `cat .env` / `docker compose config` | 같은 이유 |
>
> ✅ 대신 **존재·길이·성공여부만** 본다 —
> `print(bool(settings.encryption_key), len(settings.encryption_key))`,
> `try: print("DECRYPT_OK", len(decrypt_text(a.api_key_enc)))` / `except Exception as e: print("FAIL", type(e).__name__)`.
> (🚨 `decrypt_text` 는 실패 시 **falsy 를 반환하지 않고 `CryptoError` 를 던진다** —
> `if decrypt_text(...) else` 식으로 쓰면 FAIL 이 찍히는 게 아니라 그냥 죽는다.)
> 값을 대조해야 하면 **지문**으로 — `sha256` 앞 12자만 비교한다 (`secrets.md` §4 가 이 방식을 쓴다).
>
> 🔑 **비밀을 새 PC 로 옮기는 방법은 이 문서에 없다** — `secrets.md` §3/§7 을 볼 것.
> 카카오톡·이메일·채팅·이 대화창에 키를 붙여넣지 마라. `.env` 는 git 에 없고
> (저장소 루트 `.gitignore:1-10` — `.env` / `backend/.env` / `*.pem` / `*.key` 전부 제외.
> 추적되는 건 값 없는 `.env.example` 과 `.env.production.template` 둘뿐이다),
> 있어야 할 곳은 **각 PC 의 디스크뿐**이다.
>
> ⚠️ 아래 명령의 `-o StrictHostKeyChecking=no` 는 **서버 신원 확인을 끄는 옵션**이다.
> 사무실 PC 는 이미 `known_hosts` 에 이 서버가 있어서 무해했지만, **새 PC 는 처음
> 접속이라 「어떤 서버든 그냥 받아들인다」**는 뜻이 된다 — 그 세션으로 mainnet 키를
> 쥔 서버에 root 로 들어간다. 새 PC 에서 **첫 접속 한 번만은 옵션 없이** 붙어
> 지문을 눈으로 확인하고 `yes` 를 치는 편이 안전하다. 한 번 등록되면 그 뒤로는
> 아래 명령을 그대로 써도 된다.

배포 커밋 확인:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && git log --oneline -3 && docker compose ps'
```

네 방식의 실제 분포:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"select t.strategy_type, t.trigger_mode, s.capital_management_mode, count(*) from strategy_instances s left join strategy_templates t on t.id=s.strategy_template_id group by 1,2,3 order by 4 desc limit 25\")):
    print(r)
"'
```

게이트 ON/OFF 실제값:

🚨 **없는 키는 「꺼짐」이 아니라 「미설정 = 코드 기본값」이다.** 이 저장소는
「모름」을 「꺼짐」으로 표시했다가 사고가 난 전력이 있다(fail-OFF). 그래서 아래는
`like` 로 있는 것만 긁지 말고 **볼 키를 먼저 적고 없으면 없다고 찍는다.**

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
KEYS = [
 \"unified_entry_enabled\",\"auto_bb_break_daily_limit\",
 \"entry_chg24_gate_enabled\",\"entry_rank_top_n\",\"entry_chg24_gate_mode\",
 \"support_score_gate_enabled\",\"trend_4h_gate_enabled\",\"excluded_symbols\",
 \"stage_trim_before_next_enabled\",\"stage_keep_notional_usdt\",\"stage_min_trim_ratio\",
 \"stage_wait_for_turn_enabled\",\"sajangnim_ladder_stages_enabled\",
 \"sajangnim_capital_ladder\",\"sajangnim_stage_gap_pct\",
]
rows = dict(db.execute(text(\"select key, value from system_settings where key = any(:ks)\"), {\"ks\": KEYS}).all())
for k in KEYS:
    print(k.ljust(34), rows.get(k, \"(미설정 = 코드 기본값)\"))
"'
```

2026-09-03 실측 결과 — 이 표가 「코드 기본」과 다른 곳이 곧 사장님이 손댄 곳이다:

```
unified_entry_enabled              0                      ← 🚨 통합 진입 OFF
auto_bb_break_daily_limit          0                      ← 🚨 일일 한도 0 = 진입 없음
entry_chg24_gate_enabled           1
entry_rank_top_n                   (미설정 = 코드 기본값 50)
entry_chg24_gate_mode              (미설정 = 코드 기본값 rank)
support_score_gate_enabled         (미설정 = OFF)
trend_4h_gate_enabled              1                      ← 🚨 켜져 있다 (통과율 21%)
excluded_symbols                   (미설정 = 내장 11종)
stage_trim_before_next_enabled     1
stage_keep_notional_usdt           (미설정 = 코드 기본값 10)
stage_min_trim_ratio               (미설정 = 코드 기본값 2)
stage_wait_for_turn_enabled        1
sajangnim_ladder_stages_enabled    1
sajangnim_capital_ladder           10,300,600
sajangnim_stage_gap_pct            (미설정 = 코드 기본값 1.5)
```

(옛 버전의 `like` 방식도 남겨 둔다 — **위 목록에 없는 키를 찾을 때만** 쓴다.)

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"select key, value from system_settings where key like :a or key like :b or key like :c or key like :d\"), {\"a\":\"%ladder%\",\"b\":\"stage_%\",\"c\":\"%chg24%\",\"d\":\"%gate_enabled%\"}):
    print(r)
"'
```

🚨 **사다리가 진짜 3단계로 생기는지** (§3-2 미확인 항목):

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"select s.id, s.symbol, s.capital_management_mode, count(p.id) plans, s.created_at from strategy_instances s left join strategy_stage_plans p on p.strategy_instance_id=s.id join strategy_templates t on t.id=s.strategy_template_id where t.strategy_type like :st group by 1,2,3,5 order by s.id desc limit 10\"), {\"st\":\"auto_bb_break_SAJANGNIM%\"}):
    print(r)
"'
```

🚨 **함정**: DB 는 로컬 `db` 컨테이너가 아니라 **외부 Neon** 이다.
`docker compose exec db psql` 로 조회하면 **빈 DB** 가 나와 「테이블이 없다」는
오진에 이른다. 반드시 위처럼 `api` 컨테이너의 앱 세션(`PYTHONPATH=/app`)으로 접근한다.
쿼리가 실패하면 `db.rollback()` 을 해야 다음 쿼리가 돈다.

---

### 10. 🚨 새 PC 가 빠지기 쉬운 함정 모음

| 함정 | 왜 위험한가 | 확인법 |
|---|---|---|
| **`trigger_mode` 로 방식을 판단** | 네 방식 대부분이 `PRICE_DOWN_PCT` 다 (§3-1) | `strategy_type` 접두사 + `capital_management_mode` 를 같이 봐라 |
| **손절 함수를 잘못 고름** | Fix 318 사고. 정적 검사 13건 전부 통과했다 | 사장님 % = `force_sl_*` = `_execute_force_stop_loss` |
| **`trigger_next_stage` 에 진입 게이트 추가** | 이미 자금이 들어간 사다리가 **영원히 멈춘다** | `execution_service.py:203-205, 250` |
| **스케줄러에 있으니 돈다고 판단** | `unified_15m_entry` 는 30초마다 도는데 `unified_entry_enabled=0` / `auto_bb_break_daily_limit=0` 이라 **진입 0건**이다 | §6-1 끝 + §9 설정 조회 |
| **설정 조회 결과에 없는 키를 「꺼짐」으로 해석** | 「모름」을 「꺼짐」으로 보여줘 사고가 난 전력(fail-OFF) | §9 의 **키 목록 명시형** 조회를 쓴다 |
| **`python -m pytest -q` 가 다 통과할 거라 기대** | 지금도 **52건 실패**가 기준선이다. 「내 환경이 깨졌나」로 오진한다 | §8 기준선 표 |
| **worktree 경로 그대로 복사** | `.claude/worktrees/` 는 `.gitignore` 라 새 PC 에 없다 | 문서 상단 「경로」 블록 |
| **`split_entry` 에 정리·피라미딩을 얹음** | 평단이 설계와 반대로 밀린다. 실측 −252.18 USDT | `stage_trim.py:75` `ALWAYS_EXCLUDED_MODES` |
| **단계 간격을 손절폭보다 크게** | 손절이 항상 먼저 와서 2단계에 **영원히 도달 못 함** | `sajangnim_capital.py` 실측표. 기본 1.5% |
| **주석 처리된 워커를 「살아 있다」고 판단** | `pump_top_detector` / `auto_short_at_top` 은 아래에서 다시 등록된다 | `grep -n 'id="' workers/scheduler_runner.py` 로 **중복 id** 확인 |
| **워커 로그가 없으면 죽었다고 판단** | 락 TTL 초과로 조용히 skip 될 수 있다 | 「연속 N회 건너뜀」 경고 로그를 찾아라 |
| **`docker compose exec db psql` 로 DB 조회** | 빈 DB → 「테이블이 없다」 오진 | §9 의 api 컨테이너 방식 |
| **fail 방향을 통일** | Fix 304 는 fail-CLOSED, Fix 312·310·327 은 fail-OPEN. **일부러 다르다** | 각 함수 docstring |
| **10 USDT 미만 잔량을 남김** | reduceOnly 거부 = 영원히 못 파는 dust. **계정 전체가 막힌 전력** | `symbol_exclusion.py` 제외 목록 |
| 🔐 **`ENCRYPTION_KEY` 를 새 PC 에서 새로 생성** | DB 의 `api_key_enc` 를 **영원히** 복호화 못 함. 바이낸스 키 재발급밖에 답이 없다 | §2-1 / `secrets.md` §3 |
| 🔐 **컨테이너에서 `print(settings)`** | `SecretStr` 을 안 써서 전 비밀이 평문 한 줄로 찍힌다 — 스크롤백·채팅 로그에 남는다 | §9 상단 🔐 블록 |
| 🔐 **키를 채팅·메일로 전달** | 이 문서를 포함해 **어떤 문서에도 값을 적지 않는다**. 이름과 획득처만 | `secrets.md` §7 |
| 💸 **로컬에서 스케줄러·`uvicorn` 실행** | 리더 키가 Redis 별로 따로라 로컬이 **즉시 자기 리더**가 된다 → VPS 와 **동시에 실주문** | §9-0 |
| 💸 **로컬에서 바이낸스 API 직접 호출** | IP 단위 418 ban + **계정 단위 주문 한도**를 VPS 실매매와 나눠 쓴다 | §9-0 |
| 💸 **로컬에서 `alembic upgrade head`** | `.env` 가 실서버면 **운영 스키마가 바뀐다.** 되돌리기가 가장 어렵다 | §9-0 |
| 💸 **`excluded_symbols` 에 한 종목만 적음** | 이 키는 add 가 아니라 **replace** — 내장 11종이 **전부 풀린다** → BTCUSDT dust → 계정 차단 | §4-1 표 |
| 💸 **주석 워커 롤백 순서를 뒤집음** | `unified` 와 `auto_bb_breakdown` 이 같은 후보를 봐서 **같은 심볼에 이중 진입** | §6-3 순서표 |
| 💸 **새 테스트에서 `SessionLocal` 패치 누락** | 엔진이 `.env` 의 `DATABASE_URL` 로 import 때 만들어진다 → **실 DB 에 쓴다** | §8 경고 블록 |
| 🧨 **`git stash pop` / `reset --hard` / `push --force` 를 맨손으로** | worktree 를 공유해서 **다른 세션의 작업이 사라진다** | §9-0 |

---

### 11. ⚠️ 확인 못 함

- **`stage_ladder` 모드로 만들어진 전략이 실서버에 아직 0건.** 코드(Fix 315/321)는
  배포돼 있고 `sajangnim_ladder_stages_enabled=1` 이지만, 최근 24h SAJANGNIM 전략 9건은
  전부 `fixed` + `stage_plans` 1개였다. api/scheduler 가 조회 시점 기준 12분 전
  재시작이라 **「배포 이후 새 전략이 아직 없어서」인지 「stages_config 가 여전히
  1단계로 계산되어서」인지 구분하지 못했다.** §9 마지막 명령으로 확인할 것.
  (2026-09-03 재조회에서도 최신이 `#2045`(09-02 23:12 UTC) 그대로였다 = 그 사이
  새 SAJANGNIM 전략이 아예 안 생겼다. `unified_entry_enabled=0` 과 관련이 있을 수
  있으나 **인과는 확인하지 못했다.**)
- **`agents/` 17개 팀(+`orchestrator/`)의 실행 경로.** `scheduler_runner` 에
  `learning_team_cycle`(4h) 등 일부만 보였다. 각 팀이 어떤 워커에서 불리는지는
  전수 추적하지 않았다. (`agents/TEAMS.md` 는 「13개 팀」이라고 적혀 있는데 **낡았다** —
  실제 폴더는 17개다. 그 파일의 숫자를 믿지 말 것.)
- **`static/js` 43개 파일의 화면-코드 대응.** UI 담당 섹션이 별도로 있으므로 여기서는
  `cm-submit.js:217, 261` (진입 방식 전송)만 확인했다.
- **`api/v1` 36개 파일의 엔드포인트 전수 목록.** 라우터 등록(`api/router.py`)만 확인했다.
- **워커 상당수의 내부 로직.** 26,790줄 중 진입·손절·스케줄에 직접 관계된 것만 읽었다.
- **§9-0 「로컬 실행」 위험의 severity 는 코드로 추론한 것이지 실측이 아니다.**
  실제로 띄워 보는 것 자체가 실주문 위험이라 **일부러 시험하지 않았다.**
  근거는 `distributed_scheduler_guard.py:10-26`(리더 키 `sched:leader` 하나) +
  `core/database.py`(엔진을 import 시점에 `.env` 로 생성) 두 가지다.
  Neon 이나 바이낸스 쪽에 IP 허용목록이 걸려 있어 로컬 연결이 그냥 막힐 가능성은
  **확인하지 못했다** — 막힌다는 보장이 없으므로 위험으로 취급한다.
- **바이낸스 한도의 IP 단위 / 계정 단위 경계를 실측하지 않았다.** §9-0 의 근거는
  `scheduler_runner.py:533-534` 주석(「API Ban -1003 여러 번 발생 → interval 10s→15s」)과
  이 저장소의 418 ban 전력이다. 정확한 한도 표는 바이낸스 문서를 볼 것.
- **실패 52건의 전수 목록.** 디렉터리별 집계(루트 0 / unit 24 / integration+e2e 28)까지만
  확인했고, 개별 테스트 이름은 §8-0 의 일부만 적었다. 전수는 §8-0 의 `grep '^FAILED'` 명령으로.
