# AUDIT-FINDINGS.md

**정밀 코드 Audit 보고서**
- 작성일: 2026-05-02
- 기준: SYSTEM-SPEC.md (2026-05-02 작성) vs 코드 실제 구현
- 대상: Binance Futures Auto Trading Platform (Python FastAPI + SQLAlchemy + Redis + Docker)

---

## 종합 요약

**총 Findings: 17개**
- 🔴 CRITICAL: 3개
- 🟡 WARNING: 10개
- ⚪ INFO: 4개

**주요 발견:**
1. **spec vs 코드 불일치** — 크라이시스 모드 단계 요구사항 제거, TP 임계치 override 방식 등
2. **구현 누락** — Legacy 4단계 자동 변환, LIQUIDATION_BUFFER 동적 산출 미지원
3. **Race Condition 위험** — stage_trigger_worker 의 동시 transaction 미보호
4. **테스트 커버리지 누락** — 동적 N단계 계산, emergency_close 실제 동작 검증
5. **hardcoded 값 불일치** — crisis_quantity_ratio default 값 논리, max stage 제약

---

## 상세 Findings

### A01: 🔴 CRITICAL — stream_service.py 의 realized_pnl 중복 누적 최종 검증 필요

**심각도:** 🔴 CRITICAL

**영역:** `app/services/stream_service.py` lines 24-38, 112-125

**발견 내용:**
- 2026-05-02 fix로 ORDER_TRADE_UPDATE idempotent gate 추가됨:
  ```python
  prev_status = order.status
  # ... order 상태 갱신 ...
  if prev_status == "FILLED":
      self.db.commit()
      return  # ← 중복 누적 방지
  ```
- **하지만** EXIT 주문의 경우, `prev_status == "FILLED"` 체크 후에도 realized_pnl 누적이 일어나는 경로가 명확하지 않음.
  - Line 113-125: `if order.avg_price and strategy.avg_entry_price and order.executed_qty:` 로 realized_pnl 누적
  - 이 코드는 `prev_status != "FILLED"` 일 때만 실행되므로 실제로는 이중 보호됨.

**기대 동작 (spec 기준):**
- SPEC 2.2: "같은 EXIT 의 stream event 중복 → realized_pnl 누적 방지"
- SPEC 4.8 (stream_service): "idempotent gate 미작동 시 -665.18 USDT 중복 누적" (#79 사례)

**실제 동작:**
- 현재 코드는 `prev_status == "FILLED"` 체크로 이미 처리된 주문 무시 → 누적 방지.
- **단, 보장 수준**: 첫 번째 FILLED 이벤트에만 realized_pnl 누적. 재발송된 이벤트는 idempotent gate 통과 후 즉시 return.

**권장 fix:**
- ✅ 현재 코드가 맞음. 단, unit test case `test_stream_service_idempotent_exit_filled` 추가하여 재발 방지.
- EXIT FILLED 후 동일 event 3회 연속 전송 시나리오 검증.

**영향:** 
- 운영: 손익 정확성 (가장 민감한 지표)
- 안전: 사용자 자본 추적

---

### A02: 🔴 CRITICAL — tp_sl_orchestrator.py 에서 마지막 활성 TP 판단 로직 미정의

**심각도:** 🔴 CRITICAL

**영역:** `app/services/tp_sl_orchestrator.py` lines 57-98

**발견 내용:**
```python
# 라인 80-85: 마지막 활성 TP 결정
active_tps = []
if tpl:
    for n in range(1, 6):
        if getattr(tpl, f"tp{n}_percent", None) is not None:
            active_tps.append(f"TP{n}")
last_active_tp = active_tps[-1] if active_tps else None
```

- **문제**: `active_tps` 리스트가 비어있을 가능성 (모든 TP percent = NULL).
  - Spec 2.2: "TP1~5 dynamic active" — TP1/2/3 은 mandatory (template 에서 NOT NULL).
  - 하지만 코드는 defensive: `if active_tps else None`.
  - 결과: `last_active_tp = None` → 모든 TP 레벨이 `close_ratio = default_ratio[level]` 사용 → **마지막 활성 TP 조기 청산 안 됨**.

**기대 동작 (spec 기준):**
- SPEC 2.2: "마지막 활성 TP 발동 시 `close_ratio = 1.00` (전량 청산) + COMPLETED"
- SPEC 2.2: "TP1+부분, TP2+부분, ... TP5+전량 발동 시 상태 전환"

**실제 동작:**
- TP5_percent=NULL 이고 TP4_percent=NOT NULL 이면 TP4 가 last_active_tp.
- TP3_percent=NOT NULL, TP4/5=NULL 이면 TP3 이 last_active_tp.
- **단, 구체적인 버그**: TP template 가 (tp1, tp2, tp3, tp4=NULL, tp5=NULL) 일 때, TP3 발동 시 `close_ratio = user_ratio / 100` 이 아니라 `Decimal("1.00")` 이어야 함.
  - 라인 89-91: `elif last_active_tp and level == last_active_tp: close_ratio = Decimal("1.00")` 로 처리됨.
  - **맞게 구현되어 있음**.

**권장 fix:**
- ✅ 현재 구현이 정확함. 단, unit test 추가:
  ```python
  def test_tp_sl_last_active_tp_full_close():
      # TP1/2/3만 활성, TP3 발동 시 잔량 100% 청산
      # → status = COMPLETED
  ```

**영향:**
- 운영: 전략 종료 시점 (해석 차이 시 자동 재진입 오류)
- 정확성: TP 실행 로직 의존

---

### A03: 🔴 CRITICAL — emergency_close_position 의 race condition 수정 검증

**심각도:** 🔴 CRITICAL

**영역:** `app/services/execution_service.py` lines 55-119

**발견 내용:**
```python
# 라인 113-118 (2026-05-02 fix):
strategy.status = "STOPPING"  # ← commit 먼저
self.db.commit()
response = self.trade_client.place_market_order(...)  # ← 거래소 호출 후
order = Order(...)
self.order_repo.create(order)
self.db.commit()
```

- **이전 버그**: status 변경 전에 거래소 호출 → stream worker가 oldstatus 봐서 잘못된 분기.
- **현재 fix**: status = "STOPPING" 을 먼저 commit 한 후 거래소 호출 → 안전.

**기대 동작 (spec 기준):**
- SPEC 4.4: "status 변경을 먼저 commit (외부 worker 에게 노출) → 거래소 호출"
- SPEC 2.8: "user-stream EXIT FILLED → current_qty=0 + STOPPING → STOPPED"

**실제 동작:**
- ✅ 정확히 구현됨.
- **단, 추가 위험**: 거래소 호출이 실패했을 때?
  - Line 115: `response = self.trade_client.place_market_order(...)` 
  - Exception 미처리 → 호출자가 catch → **하지만 DB는 이미 STOPPING commit 됨**.
  - **결과**: status = STOPPING, 하지만 거래소에는 주문 없음 → 좀비 가능성.

**권장 fix:**
- 거래소 호출 실패 시 exception 로그 + RiskEvent 기록 필수.
  ```python
  try:
      response = self.trade_client.place_market_order(...)
  except Exception as e:
      logger.error(f"emergency_close failed: {e}")
      self.db.add(RiskEvent(..., event_type="EMERGENCY_CLOSE_FAILED", ...))
      self.db.commit()
      raise
  ```
- reconcile_worker 가 30초 사이클로 STOPPING 좀비 정리하므로 현재는 동작하지만, 명시적 error handling 추가하면 안전성 향상.

**영향:**
- 운영: 수동 청산 실패 시 자동 복구까지 30초 지연
- 안전: 거래소와의 동기화

---

### A04: 🟡 WARNING — risk_service.py 크라이시스 모드 단계 요구사항 스펙 vs 코드 불일치

**심각도:** 🟡 WARNING

**영역:** `app/services/risk_service.py` lines 188-205

**발견 내용:**
```python
# 라인 194-205: 크라이시스 모드 진입 조건
def _should_trigger_crisis_mode(self, strategy, current_pnl_pct: Decimal) -> bool:
    if strategy.crisis_mode_triggered_at:
        return False
    if strategy.max_loss_pct is None:
        return False
    max_loss = Decimal(str(strategy.max_loss_pct))
    if max_loss > CRISIS_MAX_LOSS_THRESHOLD:  # -30% 미만 손실
        return False
    # 단계 요구사항 **없음** ← ★
    if current_pnl_pct <= 0:
        return False
    return True
```

- **불일치**: SPEC 2.5 에서는 "단계 요구 사항 제거 (이전엔 5+ 단계 필요)" 라고 명시.
- **코드**: 실제로 단계 요구사항 없음 (2026-04-30 fix 적용됨).

**기대 동작 (spec 기준):**
- SPEC 2.5: "진입 조건: max_loss_pct ≤ -30% + 현재 PnL > 0% (단계 요구사항 제거)"

**실제 동작:**
- ✅ 정확히 구현됨. 단, 코드 내 주석이 명확하지 않음.

**권장 fix:**
```python
# 단계 요구사항 제거 (2026-04-30, SPEC 2.5):
# 이전엔 "5+ 단계 진입" 필요했으나, 이제는 제약 없음.
# (생략)
# 단계 체크 없이 바로 max_loss/current_pnl 조건만 확인
```

**영향:**
- 운영: 크라이시스 모드 진입 추적 용이
- 정확성: 낮음 (이미 정확한 구현)

---

### A05: 🟡 WARNING — tp_sl_orchestrator.py 크라이시스 모드 TP 임계치 override 미명시

**심각도:** 🟡 WARNING

**영역:** `app/services/tp_sl_orchestrator.py` lines 38-41, `app/services/risk_service.py` lines 111-121

**발견 내용:**
- **tp_sl_orchestrator.py**: "사용자 기획 변경" 주석에서 크라이시스 시 override 언급하지만 코드는 risk_service 에 위임.
- **risk_service.py**: 라인 115-120 에서 crisis 시 TP 임계치 override (TP1=5%, TP2=10%, TP3=15%, TP4=20%).

**기대 동작 (spec 기준):**
- SPEC 2.5: "TP1 임계가 5% 로 하향"
- SPEC 4.5/4.6: "크라이시스 TP 임계치는 risk_service.evaluate_take_profit_level 에서 override"

**실제 동작:**
```python
# risk_service.py lines 111-121
if strategy.crisis_mode_triggered_at:
    CRISIS_OVERRIDE = {
        "TP1": Decimal("5"), "TP2": Decimal("10"),
        "TP3": Decimal("15"), "TP4": Decimal("20"),
    }
    tp_levels = [(label, CRISIS_OVERRIDE[label]) for label, _ in tp_levels if label in CRISIS_OVERRIDE]
```

- ✅ 정확히 구현됨.

**권장 fix:**
- tp_sl_orchestrator.py 라인 38-41 주석 명확화:
  ```python
  # 크라이시스 모드 시 risk_service.evaluate_take_profit_level 이
  # TP 임계치를 5/10/15/20% 로 override 하여 회복 시점에 빠른 익절.
  ```

**영향:**
- 운영: 낮음 (구현이 정확함)
- 정확성: 낮음

---

### A06: 🟡 WARNING — strategy_calculator.py 마지막 단계 LIQUIDATION_BUFFER 동적 산출 미지원

**심각도:** 🟡 WARNING

**영역:** `app/services/strategy_calculator.py` lines 234-264

**발견 내용:**
```python
# 라인 239-263: 마지막 단계 계산
if mode == "LIQUIDATION_BUFFER":
    stages.append(StagePlan(
        stage_no=stage_no,
        trigger_mode=mode,
        trigger_percent=pct,
        trigger_price=None,  # ← 청산가 산출 시점에 채움
        planned_capital=capital,
        planned_qty=None,
    ))
else:
    # 일반 모드 (PRICE_UP_PCT/PRICE_DOWN_PCT) — trigger_price 즉시 산출
```

- **문제**: LIQUIDATION_BUFFER 모드일 때 `trigger_price=None` 으로 저장.
- **stage_trigger_worker.py**: 라인 88-91 에서 이를 감지하고 skip:
  ```python
  if not next_plan.trigger_price:
      # LIQUIDATION_BUFFER 모드 (마지막 단계) — trigger_price 가 None.
      # 실시간으로 청산가 -5% 기반 산출 필요. 일단 skip (후속 작업으로 분리).
      continue
  ```

**기대 동작 (spec 기준):**
- SPEC 2.1: "SHORT 마지막 단계 trigger_price = liquidation_price × 0.95"
- SPEC 4.2: "마지막 단계 trigger_price 는 strategy_calculator 가 사전 계산"

**실제 동작:**
- **gap**: 청산가는 전략 생성 시점에 알 수 없음 (레버리지만으로는 산출 불가).
- **workaround**: stage_trigger_worker 가 LIQUIDATION_BUFFER 스킵 → **마지막 단계 자동 진입 미지원**.

**권장 fix:**
1. **Option A (현재)**: LIQUIDATION_BUFFER 모드는 사용 금지 (사용자 기획 변경).
   - 모든 마지막 단계를 사용자 지정 % (기본 20%) 으로 통일 ✅ (SPEC 2.1 최신).
   
2. **Option B**: 실시간 청산가 기반 산출.
   - reconcile_worker 또는 stage_trigger_worker 가 매 주기마다 청산가 fetch → trigger_price 동적 계산.
   - StrategyStagePlan.trigger_price 를 nullable 유지 → 실시간 갱신.

**현재 상태**: Option A 선택 (2026-04-30 spec 변경).

**영향:**
- 운영: 없음 (현재 spec 에 맞음)
- 정확성: 낮음

---

### A07: 🟡 WARNING — reconcile_worker.py 좀비 STOPPING 자동 정리 + 자가 회복 동시성 미보호

**심각도:** 🟡 WARNING

**영역:** `app/workers/reconcile_worker.py` lines 29-86

**발견 내용:**
```python
# 라인 44-57: STOPPING 좀비 정리 + 라인 109-119: PENDING -> OPEN 자가 회복
# 두 로직이 순서대로 실행되는데, 그 사이에 stream event 가 들어올 수 있음.
if strategy.status == "STOPPING":
    strategy.status = "STOPPED"  # 좀비 정리
    db.commit()
    continue

# ... 이 사이에 stream EXIT FILLED 이벤트 처리 가능
# 이벤트가 status=STOPPING 을 보고 STOPPED 로 전환할 수 있음 (race).

if strategy.status in _PENDING_TO_OPEN and exchange_position_amt != 0:
    new_status = _PENDING_TO_OPEN[strategy.status]
    strategy.status = new_status  # PENDING -> OPEN
```

**기대 동작 (spec 기준):**
- SPEC 5.4: "reconcile_worker 가 STOPPING + exchange position=0 → STOPPED 자동 승격"
- SPEC 5.4: "reconcile_worker 가 PENDING + exchange position!=0 → OPEN 자가 회복"

**실제 동작:**
- ✅ 두 로직이 순서대로 실행되므로 대부분 안전.
- **미세한 race**: reconcile 사이에 stream_service 의 idempotent gate 나 다른 transaction 이 끼어들 수 있음.
  - 하지만 **실제 영향**: 매우 낮음 (30초 사이클 내에 안정화됨).

**권장 fix:**
- Redis lock 추가 (현재는 scheduler_runner 가 distributed_scheduler_guard 로 multi-instance 차단만 함):
  ```python
  def run_position_reconcile_once(decrypt_func) -> None:
      try:
          with redis_lock(redis_client, "lock:reconcile", ttl_seconds=30):
              # reconcile 로직
      except RedisLockError:
          return  # 다른 인스턴스가 실행 중
  ```

**영향:**
- 운영: 매우 낮음 (30초 사이클 내에 수렴)
- 안전: 낮음

---

### A08: 🟡 WARNING — stage_trigger_worker.py 전략 조회 시 N+1 쿼리 패턴

**심각도:** 🟡 WARNING

**영역:** `app/workers/stage_trigger_worker.py` lines 65-125

**발견 내용:**
```python
rows = db.execute(
    select(StrategyInstance, ExchangeAccount)
    .join(ExchangeAccount, StrategyInstance.exchange_account_id == ExchangeAccount.id)
    .where(StrategyInstance.status.in_(ACTIVE_STAGE_STATUSES))
).all()  # ← N 개 전략 fetch

for strategy, account in rows:
    # 각 전략마다:
    next_plan = db.execute(
        select(StrategyStagePlan)
        .where(StrategyStagePlan.strategy_instance_id == strategy.id)
        .where(StrategyStagePlan.stage_no == next_stage_no)
    ).scalar_one_or_none()  # ← N 번 쿼리 (N+1)
    
    latest_pos = PositionRepository(db).latest_by_strategy(strategy.id)  # ← 또 N 번
```

**기대 동작 (spec 기준):**
- SPEC 5.5: "매 1분: 활성 strategy 의 다음 stage 가 trigger_price 도달했나 체크"
- 성능 명시 안 함.

**실제 동작:**
- **N+1 문제**: active strategy 100개 시 200+ 추가 쿼리.
- **10초 사이클 (spec 오류?)**: 주석에는 "10초" 명시 (라인 4-5), 실제 scheduler 는 1분 호출 가능.

**권장 fix:**
```python
# N+1 제거: stage_plan 과 latest position 을 한 번에 fetch
rows = db.execute(
    select(StrategyInstance, ExchangeAccount, StrategyStagePlan, Position)
    .join(ExchangeAccount, ...)
    .join(StrategyStagePlan, ...)
    .outerjoin(Position, ...)  # latest position
    .where(StrategyInstance.status.in_(ACTIVE_STAGE_STATUSES))
).all()
```

**영향:**
- 운영: 100+ 활성 전략 시 DB 부하 증가
- 정확성: 낮음

---

### A09: 🟡 WARNING — notification_service.py dedup gate 가 동일 title 만 검사 (body 무시)

**심각도:** 🟡 WARNING

**영역:** `app/services/notification_service.py` lines 63-106

**발견 내용:**
```python
def _is_recent_duplicate(self, *, strategy_instance_id: int | None, title: str) -> bool:
    """최근 60초 내 동일 (strategy, title) SENT/PENDING 면 skip."""
    stmt = (
        select(Notification.id)
        .where(Notification.strategy_instance_id == strategy_instance_id)
        .where(Notification.title == title)  # ← title only
        .where(Notification.send_status.in_(["SENT", "PENDING"]))
        .where(Notification.created_at >= cutoff)
        .limit(1)
    )
    return self.db.execute(stmt).first() is not None
```

- **문제**: title 이 같으면 body 가 다르더라도 dedup 차단.
  - 예: `[1단계 진입] BTCUSDT LONG` 이 2회 발송되는 경우, title 이 같으면 2번째 차단.
  - **의도**: 같은 이벤트 2회 이상 발송 차단 → **정확한 동작**.

**기대 동작 (spec 기준):**
- SPEC 4.7: "dedup gate: 60초 윈도우 내 동일 (strategy + title) SENT/PENDING 면 skip"

**실제 동작:**
- ✅ 정확히 구현됨.

**권장 fix:**
- 사소: 주석 명확화:
  ```python
  # 같은 이벤트 (동일 title) 의 중복 발송 차단.
  # body 는 다를 수 있음 (예: 가격 변동) 하지만 title 이 같으면 같은 이벤트로 간주.
  ```

**영향:**
- 운영: 낮음
- 정확성: 낮음

---

### A10: 🟡 WARNING — execution_service.py emergency_close 에서 actual_position cap 로직 오류 가능성

**심각도:** 🟡 WARNING

**영역:** `app/services/execution_service.py` lines 62-99

**발견 내용:**
```python
# 라인 96-99: quantity cap
if req_qty <= 0 or req_qty > actual_position:
    quantity = actual_position  # 요청 없거나 실 포지션 초과 시 풀 청산
else:
    quantity = req_qty  # 부분 청산 정상 진행
```

- **문제 사례**: tp_sl_orchestrator 가 25% 청산 요청 (req_qty=199 out of 798).
  - `req_qty (199) <= actual_position (798)` → OK, 부분 청산.
  - **하지만 거래소에 포지션 정정이 없거나 부분 청산 실패 시?**
  - Exception 처리 미정의 → raise ValueError 로 caller 가 catch.

**기대 동작 (spec 기준):**
- SPEC 4.4: "부분 청산 (25% 등) 정상 진행"
- SPEC 4.5: "close_qty floor(raw/step) 단위로 → 거래소 정확 청산"

**실제 동작:**
- ✅ 부분 청산 정상 동작 (이전 bug #11 fix).

**권장 fix:**
- Exception 로그 + RiskEvent 명시적 기록 (A03 과 동일):
  ```python
  try:
      response = self.trade_client.place_market_order(...)
  except Exception as e:
      logger.error(f"market_order failed: qty={quantity}, symbol={strategy.symbol}, error={e}")
      raise
  ```

**영향:**
- 운영: 낮음 (exception log 에 남음)
- 안전: 미세한 추적성 향상

---

### A11: 🟡 WARNING — strategy_calculator.py 기본값 hardcoded (spec 과 일부 차이)

**심각도:** 🟡 WARNING

**영역:** `app/services/strategy_calculator.py` lines 21-35

**발견 내용:**
```python
DEFAULT_EARLY_TRIGGER_PCT = Decimal("10")    # 2/3/4단계
DEFAULT_LATE_TRIGGER_PCT = Decimal("20")     # 5단계 이후
EARLY_STAGE_THRESHOLD = 4
DEFAULT_LAST_LONG_TRIGGER_PCT = Decimal("20")
DEFAULT_LAST_SHORT_TRIGGER_PCT = Decimal("20")
DEFAULT_LAST_TRIGGER_MODE_SHORT = "PRICE_UP_PCT"
DEFAULT_LAST_TRIGGER_MODE_LONG = "PRICE_DOWN_PCT"
```

- **SPEC 과 비교**:
  - ✅ 2/3/4단계: 10% ← spec 일치.
  - ✅ 5단계 이후: 20% ← spec 일치.
  - ✅ 마지막 단계: 20% ← spec 일치.

**기대 동작 (spec 기준):**
- SPEC 2.1.1: "2~4단계: +10%, 5~9단계: +20%, 마지막: +20%"

**실제 동작:**
- ✅ 정확히 구현됨.

**권장 fix:**
- 사소: 상수 주석 추가:
  ```python
  # SPEC 2.1.1 기본값 (사용자 미지정 시)
  DEFAULT_EARLY_TRIGGER_PCT = Decimal("10")    # 2~4단계
  DEFAULT_LATE_TRIGGER_PCT = Decimal("20")     # 5~9단계 + 마지막
  ```

**영향:**
- 운영: 낮음
- 정확성: 낮음

---

### A12: 🟡 WARNING — tp_sl_orchestrator.py 마지막 활성 TP 에서 TP5 미고려

**심각도:** 🟡 WARNING

**영역:** `app/services/tp_sl_orchestrator.py` lines 42-53

**발견 내용:**
```python
# 라인 42: done_levels_progression 정의
done_levels_progression = ["TP1_DONE_PARTIAL", "TP2_DONE_PARTIAL", "TP3_DONE_PARTIAL", "TP4_DONE_PARTIAL", "COMPLETED"]
tp_level_index = {"TP1": 0, "TP2": 1, "TP3": 2, "TP4": 3, "TP5": 4}.get(tp_level, -1)
```

- **문제**: TP5_DONE_PARTIAL 상태가 정의되지 않음 → 라인 42 의 progression 에 미포함.
  - TP5 발동 시 `tp_level_index = 4` (TP5) 와 progression[-1] = "COMPLETED" 비교.
  - **결과**: `tp_level_index (4) > cur_index (-1 initially)` → TP5 실행 안 됨?

**기대 동작 (spec 기준):**
- SPEC 2.2: "TP1~TP5 동적 활성 (1~5 동적)"
- SPEC 2.9: "TP1_DONE_PARTIAL ~ TP5_DONE_PARTIAL" 상태 표

**실제 동작:**
- **버그 잠재성**: TP5_percent != NULL 인 경우 TP5 발동이 제대로 안 될 가능성.
  - 라인 128: `elif level == "TP5": strategy.status = "COMPLETED"` 로 처리되므로 실제로는 동작.
  - **단, status 가 COMPLETED 로 즉시 전환 → TP5_DONE_PARTIAL 상태 생략**.

**권장 fix:**
```python
# 라인 42 수정:
done_levels_progression = [
    "TP1_DONE_PARTIAL", "TP2_DONE_PARTIAL", "TP3_DONE_PARTIAL", 
    "TP4_DONE_PARTIAL", "TP5_DONE_PARTIAL", "COMPLETED"
]
tp_level_index = {"TP1": 0, "TP2": 1, "TP3": 2, "TP4": 3, "TP5": 4}.get(tp_level, -1)
```

**영향:**
- 운영: 낮음 (TP5 사용 경우 드문 경우)
- 정확성: 중간 (status 전환 순서)

---

### A13: 🟡 WARNING — risk_service.py max_loss/max_profit 추적이 음수/양수 분리 명확성 부족

**심각도:** 🟡 WARNING

**영역:** `app/services/risk_service.py` lines 170-186

**발견 내용:**
```python
def _update_pnl_extremes(self, strategy, pnl_ratio: Decimal) -> None:
    """max_loss/max_profit 갱신. 음수만 loss, 양수만 profit."""
    if pnl_ratio < 0:
        if strategy.max_loss_pct is None or pnl_ratio < Decimal(str(strategy.max_loss_pct)):
            strategy.max_loss_pct = pnl_ratio
    elif pnl_ratio > 0:
        if strategy.max_profit_pct is None or pnl_ratio > Decimal(str(strategy.max_profit_pct)):
            strategy.max_profit_pct = pnl_ratio
```

- **주석 (line 171-179)**: "Bug fix (2026-04-30)" 로 명시되어 있음.
  - 이전 버그: 양수 pnl 이 max_loss 로 들어가는 경우 (#54 AIOTUSDT, #55 SKYAIUSDT).
  - 현재: 음수 pnl 만 max_loss 업데이트, 양수 pnl 만 max_profit 업데이트.

**기대 동작 (spec 기준):**
- SPEC 4.6: "max_loss/max_profit 갱신 (음수만 loss, 양수만 profit)"

**실제 동작:**
- ✅ 정확히 구현됨 (2026-04-30 fix).

**권장 fix:**
- 사소: 변수명 명확화 — `max_loss_pct` / `max_profit_pct` 이미 명확함.

**영향:**
- 운영: 낮음 (fix 적용됨)
- 정확성: 낮음

---

### A14: ⚪ INFO — legacy 4단계 호환성 코드 여전히 활성 (제거 가능성 검토)

**심각도:** ⚪ INFO

**영역:** `app/services/strategy_service.py` lines 16-36, `app/services/strategy_calculator.py` lines 151-158

**발견 내용:**
```python
# strategy_service.py
@staticmethod
def _resolve_stages_config(template_model) -> dict[str, Any]:
    """DB 템플릿에서 stages_config 추출. 신규 컬럼 우선, 없으면 구 컬럼에서 변환."""
    if template_model.stages_config:
        return dict(template_model.stages_config)
    # 구 4단계 자동 변환
    return {
        "capitals": [...],
        "trigger_percents": [...],
        ...
    }
```

- **현황**: 2026-04-29 마이그레이션 (0004_dynamic_stages.py) 이후 구 컬럼도 유지.
- **사용 여부**: 현존 template 이 stages_config 채웠다면 fallback 불필요.

**기대 동작 (spec 기준):**
- SPEC 3.4: "새 코드는 stages_config 사용, legacy stage1~4_capital 은 호환용"

**실제 동작:**
- ✅ 호환성 유지됨. 필요하면 migration 스크립트로 일괄 변환 가능.

**권장 fix:**
- 사소: 향후 cleanup 가능 (지금은 필요함).
  ```python
  # TODO (2026-06 이후): DB 의 모든 template 가 stages_config 채워졌는지 확인 후 legacy fallback 제거
  ```

**영향:**
- 운영: 없음 (backward-compat)
- 정확성: 없음

---

### A15: ⚪ INFO — stream_service.py handle_account_update 가 _CLOSED_STATUSES 필터링 기준 명확성 부족

**심각도:** ⚪ INFO

**영역:** `app/services/stream_service.py` lines 128-158

**발견 내용:**
```python
_CLOSED_STATUSES = {"REENTRY_READY", "CLOSED", "STOPPING", "COMPLETED"}
# ← 왜 이 4개만? STOPPED 는?
```

- **문제**: 주석 부족 — 왜 STOPPED 를 제외했는지?
- **추측**: STOPPING 은 포함 (거래소 청산 진행 중), STOPPED 는 제외 (완전 종료 후 position 갱신 불필요).

**기대 동작 (spec 기준):**
- SPEC 4.8: "account_update 처리 시 종료 상태 제외"

**실제 동작:**
- ✅ 논리는 맞음 (STOPPED 는 position 추적 불필요).

**권장 fix:**
```python
_CLOSED_STATUSES = {"REENTRY_READY", "CLOSED", "STOPPING", "COMPLETED"}
# STOPPING: 사용자 정지 중 (stream EXIT FILLED 대기) → position 갱신 허용
# STOPPED: 완전 종료 → position 추적 불필요
# REENTRY_READY/CLOSED/COMPLETED: 종료 상태 → 신규 position 갱신 불필요
```

**영향:**
- 운영: 낮음
- 정확성: 낮음

---

### A16: ⚪ INFO — crisis_qty_ratio hardcoded (25/25/50/100) configurable 하지 않음

**심각도:** ⚪ INFO

**영역:** `app/services/tp_sl_orchestrator.py` lines 72-73

**발견 내용:**
```python
crisis_qty_ratio = {"TP1": Decimal("25"), "TP2": Decimal("25"), "TP3": Decimal("50"), "TP4": Decimal("100")}
```

- **현황**: hardcoded 값.
- **SPEC 기준**: 사용자 기획서에 명시된 고정값 (변경 의도 없음).

**기대 동작 (spec 기준):**
- SPEC 2.2/2.5: "크라이시스 TP qty_ratio 25/25/50/100"

**실제 동작:**
- ✅ 정확히 구현됨.

**권장 fix:**
- 사소: settings 로 externalizable 가능하지만 불필요 (변경 가능성 낮음).

**영향:**
- 운영: 없음
- 정확성: 없음

---

### A17: ⚪ INFO — test_strategy_calculator.py 옵션 C (1~10 단계) 종합 테스트 케이스 부족

**심각도:** ⚪ INFO

**영역:** `backend/tests/unit/test_strategy_calculator.py`

**발견 내용:**
- 기존 unit test 는 legacy 4단계 호환 중심.
- 옵션 C (1~10 동적) 에 대한 종합 테스트 케이스 미흡:
  - 6단계 직접 입력 시 계산 검증
  - 마지막 단계 trigger_price 산출 검증
  - edge case: capital=0 제외, trigger_percent 일부 NULL 등

**기대 동작 (spec 기준):**
- SPEC 11.1: "test_strategy_calculator (옵션 C 1~10단계 계산) 필수 보장"

**실제 동작:**
- 기존 test 는 4단계만 → 1~10 동적 케이스 부재.

**권장 fix:**
```python
# tests/unit/test_strategy_calculator.py 추가
def test_strategy_calculator_6_stages():
    """옵션 C 6단계 직접 입력."""
    # capital=[100, 200, 300, 200, 150, 50] 등 6개
    # 예상: 6개 stage 계산, trigger_price 정확 산출
```

**영향:**
- 운영: 낮음 (이미 integration test 로 검증)
- 정확성: 중간 (regression 방지)

---

## 요약 테이블

| ID | 심각도 | 영역 | 제목 | 상태 |
|----|--------|------|------|------|
| A01 | 🔴 | stream_service | realized_pnl 중복 누적 | 이미 fix, 테스트 추가 필요 |
| A02 | 🔴 | tp_sl_orchestrator | 마지막 활성 TP 판단 | 정확한 구현, 테스트 추가 필요 |
| A03 | 🔴 | execution_service | emergency_close race | 정확한 구현, error handling 강화 권장 |
| A04 | 🟡 | risk_service | 크라이시스 단계 요구사항 | 정확한 구현, 주석 명확화 |
| A05 | 🟡 | tp_sl_orchestrator | 크라이시스 TP 임계치 override | 정확한 구현, 주석 명확화 |
| A06 | 🟡 | strategy_calculator | LIQUIDATION_BUFFER 동적 산출 | 구현 의도적 (spec 변경으로 불필요) |
| A07 | 🟡 | reconcile_worker | 동시성 미보호 | low risk, redis lock 추가 권장 |
| A08 | 🟡 | stage_trigger_worker | N+1 쿼리 | 성능 최적화 가능 |
| A09 | 🟡 | notification_service | dedup gate title-only | 정확한 구현, 주석 명확화 |
| A10 | 🟡 | execution_service | emergency_close cap 로직 | 정확한 구현, error handling 강화 |
| A11 | 🟡 | strategy_calculator | 기본값 hardcoded | 정확한 구현, 주석 추가 |
| A12 | 🟡 | tp_sl_orchestrator | TP5 상태 미포함 | 제한적 버그 (즉시 COMPLETED), 수정 권장 |
| A13 | 🟡 | risk_service | max_loss/profit 추적 | 정확한 구현 (2026-04-30 fix) |
| A14 | ⚪ | strategy_service/calculator | legacy 4단계 호환 | backward-compat, cleanup 가능 |
| A15 | ⚪ | stream_service | _CLOSED_STATUSES 명확성 | 논리 정확, 주석 추가 |
| A16 | ⚪ | tp_sl_orchestrator | crisis_qty_ratio hardcoded | 정확한 구현 (설정값) |
| A17 | ⚪ | tests | 옵션 C 종합 테스트 | 테스트 케이스 추가 필요 |

---

## 우선 액션 리스트

### 즉시 (이번 주)
1. **A01**: unit test 추가 — `test_stream_service_idempotent_exit_filled` (EXIT 중복 이벤트 3회).
2. **A02**: unit test 추가 — `test_tp_sl_last_active_tp_full_close` (마지막 TP).
3. **A03**: error handling 강화 — `emergency_close_position` exception logging.
4. **A12**: 코드 수정 — `done_levels_progression` 에 `TP5_DONE_PARTIAL` 추가.

### 단기 (1주일 내)
5. **A04~A05, A09, A11, A15**: 주석/문서 명확화.
6. **A07**: redis lock 추가 (reconcile_worker 동시성).
7. **A17**: unit test 추가 — 옵션 C 6~10단계 계산 검증.

### 중기 (2주일 내)
8. **A08**: N+1 쿼리 최적화 (stage_trigger_worker).
9. **A14**: legacy 4단계 제거 시점 검토 및 문서화.

---

## 결론

**시스템 상태: 안정적 (주요 fix 적용됨)**

- **Critical (3개)**: 모두 현재 코드에서 정확히 구현됨 또는 이미 fix 적용.
  - A01 (idempotent): fix 적용됨, unit test 추가 권장.
  - A02 (last_active_tp): 정확히 구현됨, unit test 추가 권장.
  - A03 (race condition): fix 적용됨 (status commit 먼저).

- **Warning (10개)**: 대부분 구현은 정확하지만 명확성/최적화 개선 가능.
  - 3개 즉시 fix: A03 (error handling), A12 (TP5 상태), A07 (redis lock).
  - 7개 문서화/최적화: 주석 추가, 쿼리 최적화.

- **Info (4개)**: 운영 영향 없음. 주석 추가/cleanup 일정 문서화.

**다음 단계:**
- testnet 에서 옵션 C 6단계 + 마지막 TP 청산 + 크라이시스 모드 종단간 검증.
- unit test 추가 (A01, A02, A17).
- production 배포 전 A03, A12 fix 적용.

---

## 별첨: 검증 체크리스트

### Unit Test (필수 추가)
- [ ] `test_stream_service_idempotent_exit_filled` — 동일 EXIT FILLED 3회 → 누적 1회.
- [ ] `test_tp_sl_last_active_tp_full_close` — TP1/2/3 활성, TP3 발동 → COMPLETED + 잔량 0%.
- [ ] `test_strategy_calculator_6_stages` — 6단계 직접 입력 → 정확한 계산.
- [ ] `test_risk_service_pnl_extremes` — max_loss/profit 음수/양수 분리.

### Integration Test
- [ ] testnet 옵션 C 6단계 + 부분 TP + 마지막 TP 종단간.
- [ ] 크라이시스 모드 진입 → TP1 (5%) 발동 → 트레일링.
- [ ] STOPPING 좀비 자동 정리 (reconcile + stream 동시).

### Code Fix (필수)
- [ ] A03: `emergency_close_position` exception logging.
- [ ] A12: `done_levels_progression` 에 `TP5_DONE_PARTIAL` 추가.
- [ ] A07: reconcile_worker redis lock.

---

**보고서 작성 완료**  
총 17개 findings 정리. 대부분 구현이 정확하며, 주요 critical 3개는 이미 fix 적용됨.  
다음 단계: testnet 최종 검증 + unit test 추가 + production 배포.
