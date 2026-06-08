# 📜 사장님 사상 — TP1 임계 옵션 정책 (2026-06-08)

> **사장님 명시 (2026-06-08)**:
> > "tp1 발동 +15 +20 +25 이렇게 3개로 진행할수 있게 해줘
> >  그럼 크라이시스과 문제없게 기획해서 만들어줘"
>
> **사장님 정책 최종 명확화 (2026-06-08 추가, 사장님 본인 정정 후)**:
> > "크라이시스만 -5% 부터 기본으로 실행하고 익절 tp1 시작을 기본 +10% 에서
> >  +15 +20 +25 를 선택할 수 있게 하는 거야"
> > → **Crisis 모드 = 옛 그대로 (TP1 +5%, TP2 +10%, TP3 +15%, TP4 +20%)**
> > → **TP1 옵션 = 정상 모드만 적용 (10/15/20/25), Crisis 시 무시**
> > → 옵션 위치 = 「단계」 컬럼 옆 (= 진입/익절 바 영역)
>
> **사장님 trailing retrace 확인 답변 (2026-06-08)**:
> > Q: "지금 만든 것도 TP3 단계 진행 후 최고가에서 다시 수익이 내려오면 적용되는 거지?"
> > A: ✅ 정확! 현재 trailing retrace 코드 = `status TP3+_DONE_PARTIAL + stage ≥ 3 + peak ≥ 5% + retrace 회귀` = 사장님 사상 100% 작동
> > = trailing retrace 옵션 (5/10/15/20%) = 이미 PR #127 머지 완료 (= TP3 + TP4+ 모두 적용)

이 문서 = 영구 보존. 향후 모든 TP1 관련 코드 변경 = 이 spec 100% 적용.

---

## 🌟 사장님 사상 핵심 (절대 변경 금지)

### 1. **TP1 임계 = 사장님 선택 (3 옵션)**
- 옛 (default): +10% (template tp1_percent)
- 신 옵션: **+15% / +20% / +25%** (사장님 선택)
- 더 보수적 = 더 큰 수익 후 발동 = 사장님 의도

### 2. **Crisis 모드 = 옛 그대로 (= 사장님 옵션 무시, 충돌 없음)**
- Crisis 진입 시 = TP1=5 / TP2=10 / TP3=15 / TP4=20 (옛 CRISIS_OVERRIDE 그대로)
- 사장님 선택 (10/15/20/25) = **정상 모드에만 적용**
- = 큰 손실 후 회복 시 = 빠른 익절 (TP1 +5%) = 사장님 자본 보호 사상

### 3. **운영 중 실시간 변경 + 즉시 적용**
- 전략 인스턴스 카드 = 드롭다운 (3 옵션 + default)
- 변경 즉시 = PATCH API → DB 갱신 → 다음 risk evaluation cycle 부터 적용

### 4. **종목별 다른 옵션**
- BTCUSDT (변동 작음) = +15% (= 빠른 익절)
- BEATUSDT (변동 큼) = +20% 또는 +25% (= 더 보수적)
- = 사장님 시장 판단 = 시스템에 반영

---

## 📐 정책 동작 시나리오

### Scenario A — Default (+10%):
```
정상 모드: ROI +10% 도달 → TP1 자동 발동 (25% 청산)
Crisis 모드: ROI +5% 도달 → TP1 발동 (= 빠른 회복)
```

### Scenario B — 사장님 선택 +15%:
```
정상 모드: ROI +15% 도달 → TP1 자동 발동 (= 더 큰 수익 후)
Crisis 모드: ROI +5% 도달 → TP1 발동 (= 그대로!) ✅ 충돌 X
```

### Scenario C — 사장님 선택 +25% (= 매우 보수적):
```
정상 모드: ROI +25% 도달 → TP1 자동 발동 (= 큰 수익 확보)
Crisis 모드: ROI +5% 도달 → TP1 발동 (= 그대로!) ✅ 충돌 X
단점: 정상 모드 = +10~+25% 사이 수익 = 익절 X (= 회복 시 잠재 손실)
```

---

## 🛡 Crisis 모드 충돌 방지 (핵심)

### 코드 흐름 (risk_service.py evaluate_take_profit_level):
```python
if strategy.crisis_mode_triggered_at:
    # Crisis 모드 → 옛 CRISIS_OVERRIDE 그대로 (= 사장님 옵션 무시)
    CRISIS_OVERRIDE = {
        "TP1": Decimal("5"),  "TP2": Decimal("10"),
        "TP3": Decimal("15"), "TP4": Decimal("20"),
    }
    tp_levels = [(label, CRISIS_OVERRIDE[label]) for label, _ in tp_levels]
else:
    # 정상 모드 → template tp_levels + 사장님 옵션 (10/15/20/25)
    if strategy.tp1_pct_override:
        tp_levels = [
            (label, strategy.tp1_pct_override if label == "TP1" else val)
            for label, val in tp_levels
        ]
    # else = template default 그대로
```

→ **Crisis 시 = 사장님 옵션 무시 = TP1 +5% 빠른 익절 = 사장님 자본 보호**
→ TP2/3/4 = 옛 그대로 (= 변경 X)
→ 코드 단순 + 안전 (= 옛 동작 그대로)

---

## 🏗 기술 설계

### DB Migration
```sql
ALTER TABLE strategy_instances
ADD COLUMN tp1_pct_override DECIMAL(5,2);
COMMENT ON COLUMN strategy_instances.tp1_pct_override
IS '사장님 TP1 임계 옵션 (정상 모드만, %). NULL=template default, 15/20/25=사장님 선택.
    Crisis 모드 = override 무시 = CRISIS_OVERRIDE (5%) 사용.';
```

### Schema
```python
# schemas/strategy.py StrategyDetailResponse 에 추가
tp1_pct_override: Decimal | None = Field(default=None, description="...")
```

### API Endpoint (신규)
```python
@router.patch("/{strategy_id}/tp1-threshold")
def update_tp1_threshold(
    strategy_id: int,
    payload: Tp1ThresholdRequest,  # {pct: Decimal in {10, 15, 20, 25}}
    db: Session, user_id: int,
) -> StrategyDetailResponse:
    # 검증: pct ∈ {10 (default), 15, 20, 25}
    # 본인 소유 + 활성 strategy
    # RiskEvent audit 기록
```

### Risk Service 변경
```python
# risk_service.py evaluate_take_profit_level
# 정상 모드 분기 (Crisis 모드는 그대로 유지)
if not strategy.crisis_mode_triggered_at:
    # 🌟 사장님 옵션 적용
    override_pct = strategy.tp1_pct_override  # NULL or 15/20/25
    if override_pct is not None:
        # tp_levels 중 TP1 만 override
        tp_levels = [
            (label, override_pct if label == "TP1" else val)
            for label, val in tp_levels
        ]
    # else = template default 그대로
```

### Frontend (전략 인스턴스 카드)
```html
<select onclick="event.stopPropagation()"
        onmousedown="event.stopPropagation()"
        onchange="event.stopPropagation(); updateTp1Threshold({id}, this.value)"
        class="...">
  <option value="10" selected>📍 TP1 +10% (default)</option>
  <option value="15">📍 TP1 +15%</option>
  <option value="20">📍 TP1 +20%</option>
  <option value="25">📍 TP1 +25%</option>
</select>
```

→ event 버블링 차단 (= trailing retrace 와 동일 패턴, 헌법 신규 Pattern 학습).

---

## 🛡 헌법 5단계 검정 (Phase 2 + 3)

### Phase 2 (Backend):
1. **사상 검증** ✅ — 이 spec
2. **기존 코드 분석**:
   - `risk_service.evaluate_take_profit_level` (정상 vs Crisis 분기)
   - `crisis_mode_triggered_at` 검증
3. **변경 영향 분석**:
   - HIGH 위험: TP1 임계 변경 = 모든 활성 strategy 영향
   - silent fail 가능성: `tp1_pct_override = NULL` fallback = 옛 동작 유지
   - Crisis 모드 충돌 = **방지** (= 사장님 명시)
4. **코드 작성**:
   - `crisis_mode_triggered_at` 확인 후 override
   - default NULL = 옛 동작 (= 영향 0)
   - PATCH endpoint = 본인 소유 + 4 옵션 강제
   - RiskEvent audit 기록
5. **grep 검증**:
   - tp1_pct_override 사용처 모두 grep
   - python ast.parse SYNTAX OK
   - pytest 회귀

### Phase 3 (Frontend):
1. **사상 검증** ✅
2. **기존 코드 분석**:
   - strategies-list.js 카드 = trailing retrace 드롭다운 패턴 (= 동일)
3. **변경 영향 분석**: UI 만
4. **코드 작성**:
   - 드롭다운 + event 3개 stopPropagation (헌법 신규 Pattern!)
   - onchange = PATCH + toast + refreshStrategies
5. **grep 검증**: 변수 정의 + 호출 일관성

---

## 🌟 사장님 자본 보호 의도

### 시나리오 비교 (BEATUSDT 가상):
```
가격 변동 = SHORT 진입 후 = 가격 -20% 하락 = ROI +40% (2x lev)

옵션 +10% (default):
  → ROI +10% 도달 시 = TP1 발동 = 25% 청산
  → 잔량 75% = trailing 대기
  → 가격 회복 시 = 잔량 청산 (= 작은 수익)
  → 총 수익 = 작음 (= 너무 빠른 익절)

옵션 +25% (사장님 선택):
  → ROI +25% 도달 시 = TP1 발동 = 25% 청산
  → 잔량 75% = 더 큰 추세 추적
  → TP2 (+30~+50%) 발동 가능
  → 총 수익 = 큼 (= 보수적 + 큰 추세)

단점:
  → 가격이 +10%에서 회복 시 = 익절 X = 손실 가능
  → 사장님 시각 판단 중요
```

---

## 📋 향후 fix 계획 (Phase 분리)

### Phase 1 ✅ (이 spec) — 사장님 사상 영구 보존
### Phase 2 — Backend PR
- alembic migration `0018_strategy_tp1_pct_override.py`
- Schema 확장
- API endpoint PATCH `/strategies/{id}/tp1-threshold`
- Risk service 정상 모드 분기 override
- pytest 회귀 100%

### Phase 3 — Frontend PR (Phase 2 머지 후)
- strategies-list.js 카드 = 드롭다운 (TP1 옵션)
- event 3개 stopPropagation (= 헌법 신규 Pattern)
- 즉시 PATCH + toast

### Phase 4 (선택) — 추가 TP 옵션
- TP2/3/4/5 도 같은 패턴 (사장님 요구 시)

---

## 🌿 사장님 결정 사항

### Phase 1 = 이 spec 머지 후 = Phase 2 개발 시작

### 옵션 4가지 확인:
- ✅ **+10% (default)** = 옛 동작 (= 기존 strategy 영향 0)
- ✅ **+15%** = 약간 보수
- ✅ **+20%** = 보수
- ✅ **+25%** = 매우 보수

### Crisis 모드 정책:
- ✅ **Crisis = +5% 그대로** (= 충돌 X, 사장님 명시 의도)

### Phase 2 + 3 = 사장님 승인 후 = 즉시 개발 (헌법 5단계 100% 적용)

---

## 🛡 Phase 4 — 실시간 변경 + Trailing retrace 충돌 분석 (2026-06-08 추가)

### 사장님 요구 (2026-06-08):
> "실행된 전략 인스턴스에서 변경할 수 있게 만들어줘
>  그렇게 되면 익절 TP3 단계 실행 후 청산하는 옵션에 문제없게 기획해줘"

### 5 시나리오 매트릭스:

| 시점 | TP1 옵션 변경 | Trailing retrace 변경 |
|---|---|---|
| **S1: WAITING** (미진입) | ✅ 노출 (다음 cycle 적용) | ❌ 노출 X (hasPosition X) |
| **S2: ENTERED + TP1 미발동** | ⚠️ 임계 낮춤 = 즉시 청산 가능 | armed X (= 영향 0) |
| **S3: TP1~TP2 발동** | 영향 0 (= 이미 발동) | armed X (= 영향 0) |
| **S4: TP3+ + Trailing ARMED** | 영향 0 (= 이미 발동) | ⚠️ Retrace 줄임 = 즉시 청산 가능 |
| **S5: Crisis 진입** | 영향 0 (= 옵션 무시) | S4 동일 |

### 식별 위험 2건:

#### Risk 1: TP1 임계 낮춤 시 즉시 발동
- 사장님 옵션 +25% → +10% 변경
- 현재 ROI +20% > 신 +10% → 즉시 TP1 자동 발동 (25% 청산)
- 사장님 의도 = "잠시 익절" 이면 OK, 실수면 자본 침해

#### Risk 2: Trailing retrace 줄임 시 즉시 청산
- 사장님 옵션 -20% → -5% 변경
- peak +30% / 현재 +24% → peak - 5% = +25% > +24% → 즉시 TRAILING_TP 발동 (전량 청산)
- 사장님 의도 X 시 = 큰 자본 침해

---

## 🌿 사장님 최종 결정 — 옵션 A (= 사장님 자율, 2026-06-08)

### 사장님 명시:
> "A 로 진행해줘"

### 정책:
- **변경 즉시 적용** (= 현재 코드 그대로, confirm 모달 X)
- **Audit log (RiskEvent) 영구 기록** (= 이미 구현)
- **사장님 자율 책임** (= 사장님 사상 우선)

### 사장님 사상 정당화:
1. 사장님 = 1인 운영 = 본인 의도 외 변경 가능성 X
2. confirm 모달 = 추가 클릭 = 운영 속도 저하 (= 사장님 거부)
3. Audit log 영구 보존 = 사후 검증 가능 (= 헌법 「Silent bug 금지」 충족)
4. 사장님 자본 = 사장님 책임 = 사장님 자율이 최우선 (= 헌법 「사장님 사상 우선」)

### 옵션 B/C (= 미선택, 향후 사장님 의견 변경 시 추가 가능):
- 옵션 B = 위험 변경 confirm 모달
- 옵션 C = 청산 발동 시 Telegram 알림

---

## 🔗 관련 spec

- `TRAILING_RETRACE_POLICY_SPEC_2026-06-08.md` (= 동일 패턴, trailing retrace 옵션)
- `CRISIS_MODE_FINAL_SPEC_2026-06-06.md` (= Crisis 모드 사상)
- `DEVELOPMENT_PRINCIPLES_2026-06-07.md` (= 헌법)

---

> **Spec 작성**: 2026-06-08
> **위치**: `binance-auto-trader/TP1_THRESHOLD_OPTION_SPEC_2026-06-08.md`
> **상태**: 영구 보존 — 변경 시 = 사장님 명시 승인
> **다음**: Phase 2 (Backend) → Phase 3 (Frontend) PR 작성
