# 국면(regime) 판정 배선 감사 — 2026-09-03

> **목적**: 사장님 지시 「자료를 만들어 저장해서 **포지션 진입에 모두 사용**해줘」의
> 마지막 다섯 글자를 지키기 위한 사전 조사. **Fix 247**(계산은 하는데 진입에 안 쓰이던
> `strategy_confluence.evaluate`)과 같은 자리를 **또 만들지 않기 위한** 배선도다.
>
> **이 문서는 조사 보고서다. 코드는 한 줄도 고치지 않았다. 배포·재시작도 하지 않았다.**
>
> 모든 주장에 `파일:줄번호` 근거를 달았다. 확인하지 못한 것은 「미확인」이라고 적었다.

---

## 0. 세 줄 요약

1. **`chart_patterns` 0건의 확정 원인은 「신뢰도 컷」도 「예외 삼킴」도 아니다.**
   `chart_pattern_scan` 잡의 **본문이 단 한 번도 실행된 적이 없다.** APScheduler 기본
   misfire 유예(1초)에 걸려 부팅 직후 첫 실행이 매번 버려지고, 두 번째 기회인
   「부팅 + 6시간」에 도달하기 전에 스케줄러가 재시작된다(**72시간에 57회 재시작**).
2. **새 국면 판정을 꽂을 단일 지점은 `app/services/execution_service.py:188 `start_stage1`** 이다.
   `chg24_entry_gate` 가 정확히 그 자리(`:207-228`)에 붙어 있고, 그것이 따라야 할 본보기다.
   **`trigger_next_stage`(`:265`)에는 절대 걸지 않는다.**
3. **국면 판정은 이미 두 개가 존재한다.** 하나(`pump_dump_regime`)는 진입에 배선돼 있고,
   다른 하나(`bb_middle_scan._detect_regime`, 사장님 v169 4구간)는 API 라우터 파일 안에
   숨어 있지만 **진입 경로에서 실제로 호출된다.** 새 모듈은 이 둘을 **대체하거나 흡수**해야지,
   세 번째로 늘리면 안 된다.

---

## 1. `chart_patterns` 0건 — 확정된 원인

### 1.1 사실 확인

| 항목 | 확인 결과 | 근거 |
|---|---|---|
| 테이블 존재 | **존재한다** (마이그레이션 적용됨) | 운영 DB(Neon) 조회. alembic head = `0034_surge_ladder`, 마이그레이션 `alembic/versions/0031_chart_patterns.py:42` |
| 행 수 | **0건** (`outcome_status` 집계 빈 결과, `max(detected_at)` = NULL) | 운영 DB `select count(*) from chart_patterns` = 0 |
| 스케줄 등록 | **등록돼 있다** | `app/workers/scheduler_runner.py:513-524` |
| 실행 로그 | **7일간 0줄** | VPS `docker compose logs --since 168h scheduler \| grep -c chart_pattern` = **0** |

`run_full_scan` 의 **첫 문장**이 조건 없는 로그다:

```
app/agents/chart_pattern_learning_team/team_lead.py:37
    logger.info("[chart_pattern_learning] cycle 시작 (top_n=%d)", top_n)
```

이 줄이 7일 로그에 **0줄**이라는 것은 함수 본문에 **진입조차 하지 않았다**는 뜻이다.
즉 「탐지했는데 저장이 안 됐다」가 아니라 **「돌지 않았다」** 이다.

### 1.2 왜 돌지 않는가 — 두 가지가 겹쳤다

**(A) 부팅 직후 첫 실행이 misfire 로 버려진다**

```
app/workers/scheduler_runner.py:74
    scheduler = BlockingScheduler(timezone="Asia/Seoul")
```

`job_defaults` 가 없다 → `misfire_grace_time` 은 APScheduler 3.x **기본값 1초**.
잡 등록 시점과 `scheduler.start()` 사이에 약 2초가 흐르므로, 등록 시각으로 잡힌
첫 실행 시각은 시작 시점에 이미 지나 있다. 실제 로그가 그렇게 말한다:

```
2026-08-31 21:52:40,586 WARNING [apscheduler.executors.default]
Run time of job "... (trigger: interval[6:00:00], next run at: 2026-09-01 03:52:38 UTC)"
was missed by 0:00:01.954563
```

`0:00:01.95 > 1초` → **misfire → 폐기**. 다음 실행은 **부팅 + 6시간**으로 밀린다.

**(B) 스케줄러가 6시간을 못 버틴다**

VPS 실측(72시간 창):

| 지표 | 값 |
|---|---|
| 스케줄러 부팅 횟수 (`became leader, registering jobs`) | **57회** (평균 약 76분마다) |
| `interval[6:00:00]` — `Running job` | **0** |
| `interval[6:00:00]` — `executed successfully` | **0** |
| `interval[6:00:00]` — `was missed` | **18** |
| `interval[4:00:00]` — `Running job` / `was missed` | 14 / 4 |
| `interval[1:00:00]` — `Running job` / `was missed` | 424 / 8 |

**1시간·4시간 잡은 실행된다. 6시간 잡만 72시간 동안 실행 0회다.**
72시간 안의 최장 연속 가동 시간이 4시간과 6시간 사이라는 뜻이고,
6시간 주기 잡은 **구조적으로 굶는다**.

> 같은 이유로 굶고 있는 또 하나: `binance_changelog_monitor`
> (`app/workers/scheduler_runner.py:580`, 역시 `IntervalTrigger(hours=6)`).
> 72시간 로그에 본문 로그 **0줄**.

### 1.3 후보 원인들을 하나씩 **반증**한다

| 가설 | 판정 | 근거 |
|---|---|---|
| 신뢰도 컷 `conf < 0.85` 가 너무 높다 | **반증. 이 컷은 무의미(no-op)하다** | 세 신호 함수 모두 `detected=True` 일 때 confidence 를 **0.85 하한으로 클램프**한다 — `bb_4h_band_analyzer.py:462`, `:625`, `:784` (`min(max(confidence, 0.85), 0.95)`). 따라서 `pattern_detector.py:59` 의 `if conf < 0.85: continue` 는 **한 건도 거르지 않는다** |
| classmethod 를 언바운드로 불러 전부 예외 | **반증** | 세 함수 전부 `@classmethod` — `bb_4h_band_analyzer.py:372/508/673`. `BB4HBandAnalyzer.bounce_failure_signal(slice_kl)` 호출은 정상 |
| `run_full_scan` 이 예외를 삼킨다 | **원인 아님(다만 사실)** | `team_lead.py:100-102` 이 모든 예외를 `logger.warning` + `{"error": ...}` 로 삼킨다. 그러나 그 warning 조차 7일간 0줄이므로 **함수에 들어가지도 못했다** |
| commit 누락 | **반증** | `pattern_memory.py:62-63` 에 `if stored: db.commit()` 존재 |
| 리더 아님 / 락 점유로 스킵 | **반증** | 스킵 시 `_note_skip` 이 `[scheduler] job 'chart_pattern_scan' 건너뜀` 을 남긴다(`scheduler_runner.py:109-115`). 7일 로그에 `chart_pattern` 문자열 **0회** = 스킵 로그도 없다 |

### 1.4 부수적으로 발견한 결함 (돌기 시작해도 물릴 것)

1. **캔들 길이 기준 불일치.**
   수집은 `len(kl) >= 60` 이면 반환(`pattern_collector.py:28`)하는데, 탐지는
   `len(klines_4h) < 100` 이면 **조용히 빈 리스트 반환**(`pattern_detector.py:33-34`).
   → 60~99봉 심볼은 수집은 되고 탐지는 통째로 건너뛴다. 로그 없음.
2. **한 사이클 API 호출량이 크다.**
   `get_24hr_ticker` 1회 + 심볼 100개 × `get_klines(limit=200)` + `track_outcomes` 의
   추가 klines 조회(`pattern_memory.py:86`) ≒ **200회 안팎의 연속 호출**.
   이 저장소는 IP ban(418) 사고 전력이 있다(Fix 117/122). 되살릴 때 반드시 고려할 것.
3. **`store` 의 예외가 `logger.debug`** (`pattern_memory.py:59`) — 운영 로그 레벨에서 보이지 않는다.

### 1.5 🚨 더 중요한 것 — **되살려도 진입에는 안 쓰인다**

`ChartPattern` 을 **읽는** 코드 전수:

| 위치 | 용도 |
|---|---|
| `app/agents/chart_pattern_learning_team/pattern_memory.py:34,70` | **쓰기**(중복 확인 / outcome 갱신) |
| `app/api/v1/chart_patterns.py:33,103` | **화면**(`/summary`, `/recent`) |

**진입 판정에서 `chart_patterns` 를 읽는 코드는 0곳이다.**
즉 스케줄 문제를 고쳐 행이 쌓이기 시작해도, 그것은 **Fix 247 과 똑같은 모양**
(계산·저장은 하는데 진입은 안 봄)으로 남는다. **두 가지를 같이 고쳐야 한다.**

### 1.6 수동 확인 경로 (실행하지 않았음)

`POST /api/v1/chart-patterns/scan-now` (`app/api/v1/chart_patterns.py:124-133`) 가
`run_full_scan` 을 즉시 호출한다. api 컨테이너는 6시간 재시작 문제와 무관하므로
**이 경로로 부르면 실제로 돈다**. 다만 DB 에 행을 쓰고 바이낸스 API 를 약 200회
호출하므로 이번 감사에서는 **호출하지 않았다**.

---

## 2. 신규 진입이 실제로 지나는 관문

### 2.1 단일 관문 = `ExecutionService.start_stage1`

```
app/services/execution_service.py:188    def start_stage1(self, strategy_id: int) -> Order:
```

여기가 **1단계 실 주문이 나가는 유일한 지점**이다. 호출처 전수(정의 제외):

| # | 호출처 | 경로 |
|---|---|---|
| 1 | `app/api/v1/strategies/control.py:47` | 화면/API 수동 시작 |
| 2 | `app/workers/auto_bb_breakdown_worker.py:2029` | **공용 생성 깔때기 `_create_auto_bb_strategy` 내부** |
| 3 | `app/workers/pump_split_entry_worker.py:1040` | 볼밴 분할(급등락 분할) |
| 4 | `app/workers/auto_reentry_worker.py:163` | 청산 후 재진입 |
| 5 | `app/workers/ladder_restart_worker.py:310` | 사다리 재시작 |
| 6 | `app/workers/scheduled_entry_worker.py:231` | 예약 진입 |
| 7 | `app/services/surge_ladder_entry.py:311` | 급등 사다리(정점 사다리) |

**2번이 결정적이다.** `_create_auto_bb_strategy`(`auto_bb_breakdown_worker.py:1404`)가
전략을 만들고 **자기가 직접** `start_stage1` 을 부른다(`:2029`). 그리고 이 깔때기를
쓰는 워커가 7개다:

`auto_bb_breakdown_worker.py:653` / `auto_long_at_bottom_worker.py:1139` /
`auto_short_at_top_worker.py:273` / `pending_hc_fast_worker.py:117` /
`realtime_reentry_worker.py:1673` / `success_pyramiding_worker.py:372` /
`unified_15m_entry_worker.py:433`

→ **7개 직접 호출 + 7개 깔때기 경유 = 신규 1단계 진입 전부가 `start_stage1` 을 지난다.**

### 2.2 본보기 — `chg24_entry_gate` 가 붙은 방식 (그대로 따라야 할 형태)

```python
app/services/execution_service.py:207-228

        try:
            from app.services.chg24_entry_gate import passes as _chg24_passes
            _tpl_name = None
            try:
                from app.models.strategy_template import StrategyTemplate as _STpl
                _t = (self.db.get(_STpl, strategy.strategy_template_id)
                      if strategy.strategy_template_id else None)
                _tpl_name = _t.name if _t else None
            except Exception:
                _tpl_name = None
            _ok24, _why24 = _chg24_passes(
                self.db, self.client, strategy.symbol, template_name=_tpl_name,
            )
        except Exception as _ge:      # 게이트 자체가 깨져도 매매를 막지 않는다
            logger.warning("[Fix310] 게이트 오류 → 통과: %s", _ge)
            _ok24, _why24 = True, "게이트 오류 (fail-open)"
        if not _ok24:
            logger.info(
                "[Fix310] %s #%s 1단계 진입 차단 — %s",
                strategy.symbol, strategy.id, _why24,
            )
            raise ValueError(f"[Fix310] {strategy.symbol} 진입 차단: {_why24}")
```

이 형태에서 반드시 베껴야 할 다섯 가지 (근거는 `app/services/chg24_entry_gate.py:19-41`):

1. **위치** — `stage_plan` 확인 직후, `ensure_isolated_margin`(`:230`) **앞**.
   실주문 부수효과가 나가기 전이다.
2. **설정 스위치 + 기본 OFF** — `gate_enabled(db)`(`chg24_entry_gate.py:78`).
   사장님이 켜고 끄고 값을 바꿀 수 있어야 한다.
3. **수동(`_quick_`) 제외** — `_is_manual`(`chg24_entry_gate.py:119-121`).
   사장님이 손으로 넣으신 것에 자동 규칙을 얹지 않는다.
4. **fail-open** — 판정 실패는 통과. 게이트 하나가 자동매매 전체를 멈추면 안 된다
   (`chg24_entry_gate.py:37-41`, Fix 305 「영구 정지」 전력).
5. **차단 사유를 예외 메시지에 넣는다** — 호출자 7곳이 각자 로그를 남기므로
   사유가 그대로 운영 로그에 흐른다.

### 2.3 네 가지 진입 방식 — 실제 구분 기준

🚨 **지적하신 대로 `trigger_mode` 로는 갈라지지 않는다.**
`trigger_mode` 는 **2단계 이후** 판정에만 쓰인다(`stage_trigger_worker.py:450-465`).
1단계 진입은 네 방식 모두 `start_stage1` 을 그대로 지난다.

| 방식 | 실제 구분자 (파일:줄) | 후보/전략 생성 | 1단계 발주 | 2·3차 판정 |
|---|---|---|---|---|
| **기본 방식** (가격 도달) | 템플릿 `trigger_mode` 기본값 `"PRICE_DOWN_PCT"` — `stage_trigger_worker.py:450` (조회 실패 시 기본값), enum 정의 `app/schemas/strategy.py:120-121`, `alembic/versions/0022_strategy_template_trigger_mode.py:8-39` | 여러 워커 | `start_stage1` | `stage_trigger_worker` 가격 비교 |
| **OBV 자동** | `_is_obv_mode = (_tpl_trigger_mode == "OBV_REVERSE")` — `stage_trigger_worker.py:464` | 여러 워커 | `start_stage1` | `stage_entry_signal.check_stage_entry_signal` (`app/services/stage_entry_signal.py:58`) — 호출 `stage_trigger_worker.py:714,824,1050` / `scheduled_entry_worker.py:157` / `ladder_restart_worker.py:255` |
| **v219 사다리** | `strategy_type=f"auto_bb_break{strategy_type_suffix}"` — `auto_bb_breakdown_worker.py:1862` | `_create_auto_bb_strategy` (`auto_bb_breakdown_worker.py:1404`) | 같은 함수 `:2029` | `stage_trigger_worker` |
| **볼밴 분할** | `capital_management_mode == "split_entry"` — 마커 기록 `pump_split_entry_worker.py:981`, 상수 `app/core/strategy_status.py:155`, 읽는 곳 `stage_trigger_worker.py:480`·`:898` | `pump_split_entry_worker` 자체 | `pump_split_entry_worker.py:1040` | `stage_trigger_worker` + `reanchor_from_fill`(Fix 209) |

> 참고: 예약 진입은 또 다른 마커 `capital_management_mode == "scheduled"`
> (`scheduled_entry_worker.py:20`, 조회 `:125`)를 쓴다. 즉 `capital_management_mode`
> 는 「자본 관리 방식」 컬럼을 **경로 구분 마커로 전용(轉用)** 하고 있다.

### 2.4 방향(LONG/SHORT)을 정하는 자리

| 워커 | 방향 결정 | 근거 |
|---|---|---|
| `pump_split_entry_worker` | `side = "LONG" if chg > 0 else "SHORT"` (급등→눌림목 LONG / 급락→반등 SHORT) | `:888` |
| `unified_15m_entry_worker` | `side = "SHORT" if c1h > 0 else "LONG"` (1시간 부호), 3시간 창도 동일 | `:116`, `:122` |
| `auto_short_at_top_worker` | 고정 `SHORT` | `:150+` |
| `auto_long_at_bottom_worker` | 고정 `LONG` | `:1139` 호출 |
| `long_bottom_detector_worker` / `bb_upper_breakout_short_worker` | 방향 미결정 — Redis 알람만 생성, 소비 워커가 방향을 갖는다 | — |
| `realtime_reentry_worker` / `ladder_restart_worker` / `auto_reentry_worker` | **기존 전략 side 상속** | — |
| `surge_peak_ladder_worker` / `surge_ladder_entry` | 자체 판정. **공용 깔때기를 의도적으로 우회한다** | `surge_peak_ladder_worker.py:20`, `surge_ladder_entry.py:3` |

🚨 **`unified_15m_entry_worker.py:116` 의 「부호만 본다」가 이미 사고 이력이 있다.**
`auto_bb_breakdown_worker.py:1602-1611` 주석이 그것을 명시한다 — BTRUSDT #1488
(단일 최대 손실 −6,552.45)에서 **−44% 붕괴를 「급락」으로 보고 LONG 을 샀다**.
그 대응이 Fix 251 되돌림 게이트(`:1612-1639`)이고, **공용 깔때기로 올렸다**.
새 국면 판정도 같은 이유로 워커마다 심지 말고 공용 지점에 올려야 한다.

---

## 3. 국면 판정을 어디에 꽂아야 하는가 — 구체적 제안

### 3.1 층을 셋으로 나눈다 (하나에 몰면 사다리가 멈춘다)

| 층 | 무엇을 판정하나 | 꽂을 정확한 자리 | 왜 |
|---|---|---|---|
| **① 진입 가부 (전 경로 강제)** | 「이 심볼·이 방향은 지금 국면에서 들어가도 되는가」 | **`app/services/execution_service.py:188 start_stage1`** — `chg24` 게이트 블록(`:207-228`) **바로 아래**, `ensure_isolated_margin`(`:230`) **앞** | 신규 1단계 진입 **전부**가 지나는 유일한 지점(§2.1). `strategy.side` 와 `strategy.symbol` 이 모두 여기서 접근 가능 |
| **② 방향·후보 정합 (자동 경로)** | 「국면이 말하는 방향과 워커가 정한 side 가 어긋나는가」 | **`app/workers/auto_bb_breakdown_worker.py:1404 _create_auto_bb_strategy`** — Fix 251/247 블록(`:1612-1654`) 바로 뒤 | 이미 되돌림·합의 판정이 방향을 뒤엎는 자리. `side` 가 인자(`:1405`)로 들어와 있다 |
| **③ 후보 선별 (사전 필터)** | 「스캔 대상 100개를 국면으로 좁힌다」 | `app/services/market_movers.py:67 top_movers` / `:95 rank_map` 을 쓰는 자리 | API 호출량을 늘리지 않고 대상만 줄인다 |

### 3.2 🚨 단계 진입(2·3차)에는 절대 걸지 않는다

```
app/services/execution_service.py:265    def trigger_next_stage(...)
```

`chg24_entry_gate` 가 이 함수를 **일부러 비워 둔 이유**가 문서에 남아 있다
(`app/services/chg24_entry_gate.py:26-28`, `execution_service.py:202-204`):

> 1단계 진입 때 12% 였다가 2단계 트리거 시점에 8% 로 떨어지면 사다리가 그 자리에서
> **영원히 멈춘다.** 이미 자금이 들어간 전략의 사다리를 변동률로 끊으면 안 된다.

국면도 똑같다. 1차에 「급등」이던 것이 2차 트리거 시점에 「보합」이 되면
**자본이 들어간 사다리가 그대로 잠긴다.** 이 저장소는 같은 함정을 이미 두 번 밟았다:
Fix 203(볼밴 2·3차 지표 게이트 제외 — 물타기에 「하락 멈춰야 산다」는 정면 충돌),
Fix 235(도달 불가 단계가 강제손절을 영구히 잠근 교착).

### 3.3 ② 층만으로는 부족하다 — 빠지는 경로 4개

`_create_auto_bb_strategy` 를 **타지 않는** 신규 진입:

| 경로 | 근거 |
|---|---|
| `pump_split_entry_worker` (볼밴 분할, 주력 68건) | 자체 생성 `:981` + 자체 발주 `:1040` |
| `surge_ladder_entry` / `surge_peak_ladder_worker` | **의도적 우회를 문서화** — `surge_ladder_entry.py:3` "왜 공용 관문을 쓰지 않는가", `surge_peak_ladder_worker.py:20` "공용 관문은 구조적 차단 5건에 걸리므로" |
| `scheduled_entry_worker` / `ladder_restart_worker` / `auto_reentry_worker` | 기존 전략을 복제·재시작 |
| `api/v1/strategies/control.py:47` | 화면 수동 시작 |

→ **「진입에 모두 사용」을 문자 그대로 지키려면 ① 층(`start_stage1`)이 필수다.**
② 층은 방향 정합을 위한 보강이지 대체가 아니다.

### 3.4 새 모듈이 만들어야 할 것 / 만들면 안 되는 것

**만들 것 — 라벨링 함수 하나.**

```
app/services/market_regime.py   (신설 제안)
    def classify(...) -> tuple[str, dict]     # 5국면 라벨 + 근거 dict
    def passes(db, bc, symbol, side) -> tuple[bool, str]   # chg24_entry_gate 와 같은 시그니처
```

`passes` 의 시그니처를 `chg24_entry_gate.passes`(`chg24_entry_gate.py:124`)와
**동일하게** 맞추면 `start_stage1` 에 붙이는 블록이 기존 것의 복사본이 된다.

**만들면 안 되는 것 — 지표 재계산.** 아래는 이미 있고, 이미 진입에서 쓰인다:

| 필요한 값 | 이미 있는 것 | 진입에서 쓰이나 |
|---|---|---|
| 타임프레임별 OHLCV + RSI/MACD/BB/OBV | `ChartAnalyzer.analyze_timeframe` — `app/services/chart_analyzer.py:232` | **Y** (20곳 이상. 사실상 표준) |
| 볼밴 위치·기울기·거래량비 블록 | `mtf_snapshot._tf_block` `app/services/mtf_snapshot.py:108`, `capture` `:133`, `merge_into` `:236` | **Y** (`auto_bb_breakdown`, `auto_long_at_bottom`, `obv_gate`, `auto_short_at_top`) |
| 되돌림 비율(급등 후 조정 vs 원점 회귀) | `retracement.retracement_ratio` — `app/services/retracement.py:69` | **Y** (`auto_bb_breakdown_worker.py:1621`) |
| 24h 순위/변동률 | `market_movers.change_pct/top_movers/rank_map` — `app/services/market_movers.py:51/67/95` | **Y** (`chg24_entry_gate.py:172`) |
| 4H 볼밴 상태·결합 | `BB4HBandAnalyzer.state` `app/services/bb_4h_band_analyzer.py:108`, `combine` `:181` | 부분 |
| 반전 점수 | `ChartAnalyzer.compute_reversal_score` — `chart_analyzer.py:326` | **Y** (`long_bottom_detector`, `pump_top_detector`, `time_reverse_exit`) |

### 3.5 🚨 국면 판정은 **이미 두 개 있다** — 세 번째를 만들지 말 것

**(가) `app/services/pump_dump_regime.py` — 진입에 배선돼 있다**

```
app/services/pump_dump_regime.py:18   def check_pump_dump_regime(bc, symbol) -> tuple
app/services/pump_dump_regime.py:63   def is_regime_blocked_for_long(bc, symbol)
app/services/pump_dump_regime.py:71   def is_regime_blocked_for_short(bc, symbol)
```

라벨: `pump_active` / `pump_completed_dumping` 등(`:21`, `:66`).
**진입 판정 호출처 8곳** — `stage_entry_signal.py:103`,
`auto_long_at_bottom_worker.py:1485`·`:1803`, `auto_short_at_top_worker.py:232`,
`bb_upper_breakout_short_worker.py:479`, `long_bottom_detector_worker.py:801`,
`macd_reversal_15m_worker.py:594`·`:599`, `pump_dump_early_detector_worker.py:314`.

> 🚨 메모리 기록상 `pump_completed_dumping` 이 **사장님 사상과 정반대로** 급락 SHORT 를
> 차단하고 있다는 지적이 있다(2026-08-31 사상 vs 코드 감사). 새 5국면이 이 함수를
> **대체**한다면 그 정반대 동작도 함께 정리된다. 별도로 두면 두 국면 판정이 서로
> 다른 답을 내는 자리가 생긴다.

**(나) `app/api/v1/bb_middle_scan.py:170 _detect_regime` — 사장님 v169 4구간, 진입 경로에 있다**

```
app/api/v1/bb_middle_scan.py:170   def _detect_regime(closes, highs, lows, up, lo) -> str
        UPTREND / PEAK_VOLATILE / DOWNTREND_STRONG / BOTTOM_BOUNCE / NEUTRAL
```

문서 주석(`:174-182`)이 사장님 CYSUSDT 4H 예시를 그대로 옮겨 놓았고,
`:639-675` 에서 **방향별 가점/감점**까지 매긴다
(예: SHORT 는 `DOWNTREND_STRONG` +0.10 / `BOTTOM_BOUNCE` **−0.15**).

**이것이 진입에 닿는 경로:**
`_detect_regime` 호출(`:753`) → 같은 파일의 `scan_bb_breakdown`(`:346`) 내부 →
`auto_bb_breakdown_worker.py:133-142` 가 이 함수를 직접 import 해서 호출 →
후보 `success_probability` 에 반영 → 진입.

즉 **사장님이 요구하신 5국면과 거의 같은 것이 이미 있고, 진입에 쓰이고 있다.**
다만 **API 라우터 파일 안의 비공개 함수(`_` 접두)** 로 숨어 있어 재사용이 불가능하다.

**신 5국면과의 대응 (제안):**

| 사장님 신 5국면 | 기존 v169 라벨 | 기존 `pump_dump_regime` |
|---|---|---|
| 급등 | `UPTREND` / `PEAK_VOLATILE` | `pump_active` |
| 급락 | `DOWNTREND_STRONG` | `pump_completed_dumping` |
| 보합 | `NEUTRAL` | — |
| 지지 반등 | `BOTTOM_BOUNCE` | — |
| 지지선 추가 하락 | (없음 — **신설 필요**) | — |

→ **권고**: `_detect_regime` 을 `app/api/v1/bb_middle_scan.py` 에서
`app/services/market_regime.py` 로 **끌어올려** 5국면으로 확장하고,
`bb_middle_scan` 과 `pump_dump_regime` 이 그 하나를 부르게 한다.
새 파일을 옆에 하나 더 만들면 **국면 판정이 셋이 된다.**

---

## 4. 「계산만 하고 진입에 안 쓰는」 자리 — Fix 247 유형 전수

판정 기준: **신규 포지션의 진입 여부/방향 결정**에 결과가 쓰이면 Y, 화면·학습·제안에만
가면 N.

| 기능 | 정의 위치 | 호출처 | 진입 판정? |
|---|---|---|---|
| `ChartPattern` 테이블 조회 | `app/models/chart_pattern.py:19` | `pattern_memory.py:34,70`(쓰기) / `api/v1/chart_patterns.py:33,103`(화면) | **N** — 게다가 데이터 0건 |
| `ChartAnalyzer.check_obv_reverse_signal` | `app/services/chart_analyzer.py:192` | **0곳** (주석 언급만 — `stage_entry_signal.py:11`, `stage_trigger_worker.py:801`) | **N** (완전 사문) |
| `retracement.is_round_trip` | `app/services/retracement.py:129` | **0곳** (`__all__` 등재 `:40` 뿐) | **N** — 실제 판정은 `auto_bb_breakdown_worker.py:1622` 가 `RETRACE_BLOCK_MIN` 과 직접 비교 |
| `retracement.is_pullback_zone` | `app/services/retracement.py:138` | **0곳** (`__all__` 등재 `:41` 뿐) | **N** — 사장님 사상 ②「급등 후 조정에 LONG」의 판정식인데 아무도 안 부른다 |
| `BB4HBandAnalyzer.analyze` | `app/services/bb_4h_band_analyzer.py:1130` | `api/v1/analysis.py:310`(화면) / `learning_sync_worker.py:123`(학습) / `bb_4h_scanner.py:169`(제안) | **N** |
| `BB4HBandAnalyzer.big_move_signal` | `:842` | `bb_4h_scanner.py:229` (제안) | **간접** — 제안이 confidence ≥ 0.85 면 `auto_bb_breakdown_worker.py:209-215` 가 집어간다 |
| `BB4HBandAnalyzer.long_uptrend_reversal_signal` | `:991` | `bb_4h_scanner.py:202` | **간접** (동상) |
| `BB4HBandAnalyzer.bottom_reversal_signal` | `:674` | `bb_4h_scanner.py:252` / `pattern_detector.py:51`(학습, 현재 미실행) | **간접** |
| `BB4HBandAnalyzer.top_reversal_signal` | `:373` | `bb_4h_scanner.py:302` / `pattern_detector.py:52` | **간접** |
| `BB4HBandAnalyzer.bounce_failure_signal` | `:509` | `bb_4h_scanner.py:277` / `pattern_detector.py:50` | **간접** |
| `BBTopAnalyzer.analyze` | `app/services/bb_top_analyzer.py:537` | `api/v1/analysis.py:298`(화면) / `strategy_suggestion_generator.py:229`(제안) / `learning_sync_worker.py:105`(학습) | **간접** |
| `BBTopAnalyzer.bb_mid_state` | `:332` | `bb_top_analyzer.py:562`(자기 내부) + 단위테스트뿐 | **N** |
| `PumpDumpLiveAnalyzer.analyze` | `app/services/pump_dump_live_analyzer.py:635` | `api/v1/analysis.py:305`, `api/v1/live_pump_dump.py:95`, `learning_sync_worker.py:110` | **N** |
| `PumpDumpLiveAnalyzer.pump_reversal_signal` | `:287` | `api/v1/live_pump_dump.py:119` + 자기 내부 `:458` | **N** |
| `PumpContinuationAnalyzer.analyze` | `app/services/pump_continuation_analyzer.py:274` | `api/v1/analysis.py:313`, `learning_sync_worker.py:120` | **N** |
| `strategy_confluence.evaluate` | `app/services/strategy_confluence.py:42` | `confluence_gate.py:97` → `auto_bb_breakdown_worker.py:1641` | **Y** (Fix 247 로 배선됨. 단 **기본 OFF** — `confluence_gate.py:53`, 설정 `confluence_gate_enabled`) |

### 4.1 「간접」의 함정 — 제안(suggestion) 경로

`bb_4h_scanner` / `strategy_suggestion_generator` 의 산출물은 `StrategySuggestion` 행이 되고,
`auto_bb_breakdown_worker.py:209-215` 가 `status == "PENDING" AND confidence_score >= 0.85`
인 것을 최대 20건 집어 자동 진입 후보로 만든다.

즉 이 신호들은 **진입에 닿기는 하지만, 「신호 → 판정」이 아니라 「신호 → 제안 행 →
신뢰도 숫자 하나」로 납작해진 뒤**에 닿는다. 어떤 국면이었는지는
`strategy_suggestion_generator.py:110` 에서 `"regime": p.get("regime", "NEUTRAL")` 로
config 에 실려 `auto_bb_breakdown_worker.py:232` 가 되읽지만, **그 값으로 막거나
방향을 바꾸는 코드는 확인되지 않았다**(이 문서 작성 시점 기준 미확인 — 추가 조사 필요).

또한 이 제안 생성 팀(`StrategySuggestionTeamLead`)의 스케줄은
`scheduler_runner.py:206`(일간 예측), `:218`(시간별 정리), `:230`(자동 실행),
`:243`(브리핑)에 등록돼 있다. 트리거 종류는 이번 감사에서 개별 확인하지 않았다(미확인).

---

## 5. 배선 시 반드시 지킬 것 (체크리스트)

- [ ] **① `start_stage1`(`execution_service.py:188`) 에 건다.** `chg24` 블록(`:207-228`) 바로 아래.
- [ ] **`trigger_next_stage`(`:265`) 에는 걸지 않는다.** 사다리가 잠긴다.
- [ ] **기본 OFF + SystemSetting 스위치.** 먼저 「막았을 것」 로그만 남기고 사장님이 켠다
      (Fix 247 이 `confluence_gate.py:36-38` 에서 쓴 방식).
- [ ] **수동 `_quick_` 제외** (`chg24_entry_gate.py:119-121` 과 동일).
- [ ] **fail-open** — 판정 실패는 통과 + 경고 로그.
- [ ] **새 지표를 계산하지 않는다.** §3.4 표의 기존 함수를 조립한다.
- [ ] **국면 판정을 세 번째로 늘리지 않는다.** `bb_middle_scan._detect_regime`(`:170`)을
      서비스로 끌어올려 확장하고, `pump_dump_regime` 을 그 위에 얹는다(§3.5).
- [ ] **저장한 자료를 읽는 코드가 진입 경로에 있는지 확인한다.**
      `chart_patterns` 가 지금 그 반례다(§1.5). 「저장했다」는 「쓴다」가 아니다.
- [ ] **API 호출량 확인.** `start_stage1` 은 진입 1건당 1회이므로 안전하지만,
      후보 스캔 층(③)에 붙이면 후보 수 × 캔들 조회가 된다(IP ban 전력 — Fix 117/122).
- [ ] **6시간 주기 스케줄을 쓰지 않는다.** §1.2 대로 6시간 잡은 실행되지 않는다.

---

## 부록 A. 이번 감사에서 실행한 검증 명령 (전부 읽기 전용)

```bash
# 운영 DB (Neon) — api 컨테이너 경유
docker compose exec -T api python -c "... select count(*) from chart_patterns ..."
  → alembic head = 0034_surge_ladder / chart_patterns = 0건 / max(detected_at) = NULL

# 스케줄러 로그
docker compose logs --since 168h scheduler | grep -c "chart_pattern"        → 0
docker compose logs --since 72h  scheduler | grep 'interval\[6:00:00\]' | grep -c 'Running job'  → 0
docker compose logs --since 72h  scheduler | grep 'interval\[6:00:00\]' | grep -c 'was missed'   → 18
docker compose logs --since 72h  scheduler | grep 'interval\[4:00:00\]' | grep -c 'Running job'  → 14
docker compose logs --since 72h  scheduler | grep 'interval\[1:00:00\]' | grep -c 'Running job'  → 424
docker compose logs --since 72h --timestamps scheduler | grep -c 'became leader'                 → 57
docker inspect binance-auto-trader-scheduler --format '{{.RestartCount}}'                        → 5
```

**주의**: `.env` 의 `DATABASE_URL` 은 로컬 `db` 컨테이너가 아니라 **외부 Neon** 을 가리킨다.
`docker compose exec db psql -d binance_auto_trader` 로 조회하면 **빈 DB** 가 나와
「테이블이 없다」는 잘못된 결론에 이른다(이번 감사에서 실제로 한 번 그랬다).
반드시 앱 컨테이너의 `SessionLocal` 을 경유할 것.

## 부록 B. 확인하지 못한 것 (정직하게 남긴다)

1. `StrategySuggestion.strategy_config["regime"]` 값이 **진입을 막거나 방향을 바꾸는지**
   — `auto_bb_breakdown_worker.py:232` 에서 읽어 넣는 것은 확인했으나, 그 뒤 소비처는 추적 못 함.
2. `StrategySuggestionTeamLead` 의 4개 잡(`scheduler_runner.py:206/218/230/243`)의
   트리거 종류와 실제 실행 여부 — 6시간 잡과 같은 함정에 걸려 있는지 미확인.
3. 스케줄러가 72시간에 57번 재시작하는 **원인** — 배포인지 크래시 루프인지 구분하지 못했다.
   (2026-08-27 로그에 `[scheduler] another node is leader; exiting` 이 15초 안에 5회 연속
   찍힌 구간이 있어 리더 경합 재시작 루프가 섞여 있을 가능성. 미확인.)
4. `chart_pattern_scan` 을 `/scan-now` 로 실제 호출했을 때 몇 건이 탐지되는지
   — DB 쓰기와 대량 API 호출을 유발하므로 실행하지 않았다.
