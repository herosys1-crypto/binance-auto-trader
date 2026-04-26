# 크라이시스 복구 모드 + PnL 추적 기획서

작성일: 2026-04-26
대상: Binance Auto Trader 운영자 (이규수)
요구자: 운영자

---

## 1. 요구사항 — 운영자 원문 정리

> **A. PnL 기록**
> 전략이 진입하면 수익에 대한 정보를 각 전략이 기록되길 원함.
>
> **B. 크라이시스 복구 모드 진입 조건**
> 마지막 단계까지 진입하고 손실이 한 번이라도 -30% 이상 기록하면, 또는
> 5단계 이상 진입 후 -30% 이상 손실 후 수익이 나면.
>
> **C. 크라이시스 복구 모드 익절 룰**
> 익절을 +5% 부터 시작 (기존 +10% → +5% 로 낮춤, 같은 분할 비율).
> 수익이 +10% 이상이면 기존 익절 조건 적용.
> 익절 후 최고가 대비 -5% 빠지면 전체 수량 즉시 청산.
>
> **D. 크라이시스 복구 모드 손절 룰**
> +5% 수익 실현 후 -1% 이상 손실 다시 발생하면 모두 손절.

---

## 2. 비즈니스 룰 정리

### 2-1. 모드 정의

| 모드 | 설명 |
|---|---|
| 🟢 **정상 모드** | 기본 — 운영자가 설정한 TP/SL 룰 그대로 적용 |
| 🚨 **크라이시스 복구 모드** | "심각한 손실 한 번 이상 + 깊게 진입한 상태" 에서 발동 — 보수적 익절 + 빠른 손절 |

### 2-2. 크라이시스 복구 모드 진입 조건 (둘 중 **하나라도 충족**)

```
조건 A: 마지막 단계까지 진입(current_stage == total_stages)
        AND 누적 최대 손실(max_loss_pct) ≥ 30%

조건 B: 5단계 이상 진입(current_stage ≥ 5)
        AND 누적 최대 손실(max_loss_pct) ≥ 30%
```

**한 번 발동되면 전략 종료까지 유지** (재진입 시 초기화).

### 2-3. 정상 모드 vs 크라이시스 복구 모드 룰 비교

| 항목 | 정상 모드 | 크라이시스 복구 모드 |
|---|---|---|
| **TP1 임계** | +10% (운영자 설정) | **+5% ⬇️** |
| **TP1 청산 비율** | 25% (운영자 설정) | 25% (동일) |
| **TP2 임계** | +15% | +15% (동일, "+10% 이상은 기존 조건" 의미) |
| **TP2~5 비율** | 25/25/25/50/100% | 동일 |
| **트레일링 임계** | 피크 +20% 이상 → +20% 회귀 → 전량 | **첫 TP 발동 후 피크 -5% → 전량 즉시 ⬇️** |
| **손절 룰** | 총 자본 -50% | **첫 TP 발동 후 PnL -1% → 전량 즉시 ⬇️** |

### 2-4. 시나리오 흐름도

```
정상 모드
    │
    ├─ TP1 (+10%) → 25% 청산 → TP2 / TP3 / ... 진행
    └─ SL (-50%) → 시장가 청산 → 재진입 대기

────────────────────────────────────────────────────────

진입 깊고(5+ 단계) 손실 깊었던(-30%) 케이스
    │
    └─ 🚨 크라이시스 복구 모드 진입
            │
            ├─ TP1 (+5%) → 25% 청산  ← 빠른 익절
            │       │
            │       ├─ 피크 -5% 회귀 → 남은 전량 청산  ← 차익 보호
            │       └─ PnL -1% → 남은 전량 손절  ← 빠른 탈출
            │
            ├─ TP2 (+15%) → 25% 추가 청산 (기존 룰)
            ├─ TP3~5 → 기존 룰
            │
            └─ 어느 시점에든 PnL -1% 도달 → 전량 손절
```

---

## 3. 데이터 모델 변경

### 3-1. `strategy_instances` 테이블 컬럼 추가

| 컬럼명 | 타입 | 의미 |
|---|---|---|
| `max_loss_pct` | NUMERIC(8,4) | 누적 최대 손실 % (음수, e.g. -32.5) |
| `max_profit_pct` | NUMERIC(8,4) | 누적 최대 이익 % (양수) |
| `crisis_mode_triggered_at` | TIMESTAMPTZ NULL | 크라이시스 모드 진입 시각 (NULL = 미진입) |
| `crisis_first_tp_done_at` | TIMESTAMPTZ NULL | 크라이시스 모드에서 첫 TP 발동 시각 |
| `peak_pnl_pct_after_first_tp` | NUMERIC(8,4) NULL | 첫 TP 발동 후 피크 PnL % (트레일링용) |

### 3-2. `strategy_pnl_history` 신규 테이블 (선택적)

```sql
CREATE TABLE strategy_pnl_history (
    id SERIAL PRIMARY KEY,
    strategy_instance_id INT NOT NULL REFERENCES strategy_instances(id) ON DELETE CASCADE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pnl_amount NUMERIC(20,8) NOT NULL,
    pnl_percent NUMERIC(8,4) NOT NULL,
    current_stage INT NOT NULL,
    crisis_mode BOOLEAN NOT NULL DEFAULT FALSE,
    event_type VARCHAR(40),  -- 'STAGE_FILL', 'TP_HIT', 'PEAK_UPDATE', 'CRISIS_TRIGGERED' 등
    note TEXT,
    INDEX idx_strategy_pnl_history_strategy (strategy_instance_id, recorded_at)
);
```

→ 운영자가 전략 종료 후 "이 전략 어떻게 흘러갔지?" 회고용. 대시보드 상세 페이지에 타임라인 표시.

### 3-3. Alembic 마이그레이션

`alembic/versions/0006_pnl_tracking_crisis_mode.py` 신규.

---

## 4. 코드 변경 — 영향 받는 파일

### 4-1. `app/services/risk_service.py` — 핵심 로직

```python
def evaluate_take_profit_level(self, strategy_id: int) -> str | None:
    """크라이시스 복구 모드 인지 → TP 임계 동적 적용."""
    strategy = self.strategy_repo.get_strategy(strategy_id)
    # 1) 현재 PnL% 계산
    pnl_ratio = ...
    # 2) max_loss/max_profit 갱신 (DB 또는 Redis)
    self._update_pnl_extremes(strategy, pnl_ratio)
    # 3) 크라이시스 모드 트리거 검사
    if not strategy.crisis_mode_triggered_at:
        if self._should_trigger_crisis_mode(strategy):
            self._enter_crisis_mode(strategy)
    # 4) TP/SL 평가
    if strategy.crisis_mode_triggered_at:
        return self._eval_crisis_mode_tp_sl(strategy, pnl_ratio)
    return self._eval_normal_tp_sl(strategy, pnl_ratio)


def _should_trigger_crisis_mode(self, strategy) -> bool:
    """진입 조건: (마지막 단계 또는 5+ 단계) AND 최대 손실 ≥ 30%."""
    deeply_entered = (
        strategy.current_stage >= 5
        or strategy.current_stage == self._total_stages(strategy)
    )
    big_loss = strategy.max_loss_pct is not None and strategy.max_loss_pct <= -30
    return deeply_entered and big_loss


def _eval_crisis_mode_tp_sl(self, strategy, pnl_ratio):
    """크라이시스 모드 — TP1 +5%, 트레일링 -5%, 손절 -1%."""
    # TP1 미실행 + 피크 -5% 룰 + 손절 -1% 룰
    ...
```

### 4-2. `app/services/tp_sl_orchestrator.py`

- 크라이시스 모드의 새 액션 처리:
  - `CRISIS_TP1` (+5% 도달, 25% 청산)
  - `CRISIS_TRAIL_FULL` (피크 -5% 회귀, 전량 청산)
  - `CRISIS_HARD_SL` (-1% 도달, 전량 손절)

### 4-3. `app/services/notification_service.py`

신규 알림 추가:
- 🚨 [크라이시스 모드 진입] {symbol}{side} — 최대 손실 -32% 기록
- ⚠️ [크라이시스 첫 TP] +5% 25% 청산
- 🛡 [트레일링 보호] 피크 +X% 후 -5% 회귀, 전량 청산
- 🚨 [긴급 손절] PnL -1%, 전량 청산

### 4-4. `app/static/index.html` (대시보드)

- 전략 인스턴스 행에 **🚨 크라이시스 배지** 표시 (crisis_mode_triggered_at != NULL)
- 상세 패널에 **PnL 타임라인** + max_loss/max_profit 표시

---

## 5. 알고리즘 의사 코드

```python
on_each_pnl_check(strategy):
    pnl_pct = compute_pnl_pct(strategy)
    strategy.max_loss_pct = min(strategy.max_loss_pct or 0, pnl_pct)
    strategy.max_profit_pct = max(strategy.max_profit_pct or 0, pnl_pct)

    # 크라이시스 모드 진입
    if not strategy.crisis_mode_triggered_at:
        if (strategy.current_stage >= 5 or strategy.current_stage == total_stages) and strategy.max_loss_pct <= -30:
            strategy.crisis_mode_triggered_at = now()
            notify_crisis_entered(strategy)

    if strategy.crisis_mode_triggered_at:
        return eval_crisis(strategy, pnl_pct)
    return eval_normal(strategy, pnl_pct)


eval_crisis(strategy, pnl_pct):
    # 1) 첫 TP 미실행 — +5% 도달 시 25% 청산
    if not strategy.crisis_first_tp_done_at:
        if pnl_pct >= 5:
            return ("CRISIS_TP1", 25%)
        return None

    # 2) 첫 TP 이후 — 트레일링 + 손절 감시
    strategy.peak_pnl_pct_after_first_tp = max(strategy.peak_pnl_pct_after_first_tp or 0, pnl_pct)
    peak = strategy.peak_pnl_pct_after_first_tp

    # 손절 -1%
    if pnl_pct <= -1:
        return ("CRISIS_HARD_SL", 100%)

    # 트레일링 — 피크 -5% 회귀 → 전량 청산
    if peak >= 5 and pnl_pct <= peak - 5:
        return ("CRISIS_TRAIL_FULL", 100%)

    # +10% 이상은 기존 TP 룰
    if pnl_pct >= 10:
        return eval_normal_tp_only(strategy, pnl_pct)
    return None
```

---

## 6. UI 표시 (대시보드)

### 전략 인스턴스 표 — 신규 컬럼

```
# | 심볼 | 방향 | 상태 | 단계 | 진입가 | 평균진입 | 포지션 | 미실현 | 최대손실 | 최대이익 | 모드 | 액션
                                                              -32%      +18%     🚨크라이시스
```

### 상세 패널 — PnL 타임라인 (선택)

```
📊 PnL 타임라인
─────────────────────
12:30  STAGE3_FILLED   +0.5%  (max_profit: +0.5%)
13:15  STAGE4_FILLED   -8.2%
14:00  STAGE5_FILLED   -22.5%
14:45  PEAK_LOSS       -31.2%  (max_loss: -31.2%) ← 크라이시스 트리거
14:50  CRISIS_ENTERED  -28.0%
15:30  CRISIS_TP1      +5.3%   (25% 청산)
16:00  PEAK_PROFIT     +12.8%
16:45  TRAIL_ALERT     +7.5%   (피크 -5% 도달, 남은 전량 청산)
```

---

## 7. 구현 순서 (3 Phase)

### Phase D-1 — 데이터 추적 (반나절)
- [ ] Alembic 0006: max_loss_pct, max_profit_pct, crisis_* 컬럼 추가
- [ ] StrategyInstance 모델 업데이트
- [ ] risk_service 가 매 평가 시 max_loss/max_profit 갱신

### Phase D-2 — 크라이시스 모드 로직 (1일)
- [ ] `_should_trigger_crisis_mode` 구현
- [ ] `_eval_crisis_mode_tp_sl` 구현
- [ ] orchestrator 가 새 액션(`CRISIS_TP1`, `CRISIS_TRAIL_FULL`, `CRISIS_HARD_SL`) 처리
- [ ] 알림 4종 추가
- [ ] 단위 테스트

### Phase D-3 — 대시보드 표시 (반나절)
- [ ] 전략 표에 max_loss / max_profit / 모드 컬럼 추가
- [ ] 상세 패널에 PnL 타임라인 (선택)
- [ ] 🚨 크라이시스 배지

---

## 8. 검증 시나리오

testnet 에서 다음 흐름 시뮬레이션 (또는 단위 테스트):

```
1. 전략 시작 → 1단계 진입 → 2단계 → 3단계 → 4단계 → 5단계 진입
2. 시세 급등(SHORT 기준 손실) → PnL -32% 도달 → max_loss = -32% 기록
3. 🚨 크라이시스 모드 진입 → Telegram 알림
4. 시세 회복 → PnL +5% 도달 → CRISIS_TP1 (25% 청산) → Telegram
5. 시세 더 오름 → +12% 도달 → 기존 TP2 (+15% 임계) 까지 대기
6. 시세 약간 하락 → +7% 도달 → 피크(+12%) -5% = 회귀 → CRISIS_TRAIL_FULL (전량 청산)
또는
6'. 시세 급락 → PnL -1% → CRISIS_HARD_SL (전량 손절)
```

---

## 9. 기존 기능과의 관계

| 기능 | 변경 여부 |
|---|---|
| 동적 N단계 진입 | 변경 없음 |
| 기본 TP1~5 | 변경 없음 (정상 모드) |
| 트레일링 (피크 +20% 후 +20% 회귀) | 변경 없음 (정상 모드) |
| 손절 -50% | 변경 없음 (정상 모드) |
| 5단계 익절 분할 | 변경 없음 |

크라이시스 모드는 **별개의 보호 레이어** 로 추가됨. 정상 모드 룰을 망치지 않음.

---

## 10. 다음 세션 시작 안내

다음 세션에서 이렇게 시작:

```
"CRISIS_RECOVERY_MODE_PLAN.md 의 Phase D-1 부터 구현해주세요"
```

→ Phase D-1, D-2, D-3 순으로 차근차근 진행. 각 Phase 완료마다 testnet 검증 가능.

---

작성: Claude (오늘 세션)
검수 필요: 운영자 (이규수)
변경 이력: v1.0 (2026-04-26 초안)
