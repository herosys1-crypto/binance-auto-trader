# 📜 사장님 사상 — Trailing Retrace 옵션 정책 (2026-06-08)

> **사장님 명시 (2026-06-08)**:
> > "tp3단계 익절후 최고가 대비 -5% 하락할때 모두 청산하는 로직을 전략 인스턴스에
> >  추가로 -10% -15% -20% 세가지 선택박스를 만들어서 적용할수 있는 기획서와 개발을 추가해줘
> >  핵심은 tp3단계 익절후 -5%이상 하락해도 선택한 옵션까지는 청산하지 않고
> >  다시 익절되면 다음 익절단계를 계속이여 하고 tp4 이후도 같은 옵션이 적용되게 만들어줘
> >  운영중에 옵션을 선택하고 바로 적용할수 있는 기능으로 만들어줘"

이 문서 = 영구 보존. 향후 모든 trailing 관련 코드 변경 = 이 spec 100% 적용.

---

## 🌟 사장님 사상 핵심 (절대 변경 금지)

### 1. **Trailing Retrace = 사장님 선택 가능**
- 옛 (hardcoded): peak 대비 -5% 회귀 시 전량 청산
- 신 (사장님 선택): peak 대비 **-X% 회귀** 시 전량 청산
  - X 옵션: **5% (default) / 10% / 15% / 20%**

### 2. **운영 중 실시간 변경 + 즉시 적용**
- 전략 인스턴스 카드 = 드롭다운 (4 옵션)
- 변경 즉시 = PATCH API → DB 갱신 → 다음 risk evaluation cycle 부터 적용
- = 재시작 / strategy 종료 X (= 실시간)

### 3. **TP3 이후 모든 단계에 적용**
- TP3 발동 → trailing armed
- TP4, TP5, ..., TP10 = 정상 발동 가능 (= trailing buffer 안에서)
- trailing 발동 (peak - X% 회귀) = 모든 잔량 전량 청산
- = TP 단계 계속 진행 + trailing 보호 모두 작동

### 4. **사장님 자본 보호 의도**
- 변동 폭 큰 종목 = -5% 단순 노이즈 = 잔량 보호
- 사장님이 = "이 종목은 변동 큼" 인식 시 = -15% 또는 -20% 선택
- = 사장님 시장 판단 = 시스템에 반영

---

## 📐 정책 동작 시나리오

### Scenario A — Default (-5%):
```
TP3 발동 @ ROI +15% (= peak 시점)
peak = +15%
→ ROI 회귀 <= peak - 5% = +10% 도달 시 = 전량 청산
```

### Scenario B — 사장님 선택 -10%:
```
TP3 발동 @ ROI +15%
peak = +15%
→ ROI 회귀 <= peak - 10% = +5% 도달 시 = 전량 청산
→ 그 사이 = +20% 도달 시 = TP4 발동 (가능)
→ peak 갱신 = +20%
→ +10% 회귀 = +10% 도달 시 = 전량 청산
```

### Scenario C — 사장님 선택 -20% (= 매우 보수적):
```
TP3 발동 @ ROI +15%
peak = +15%
→ ROI 회귀 <= peak - 20% = -5% 도달 시 = 전량 청산
→ 매우 큰 변동 견딤
→ 단점: 손실 진입 가능 (= peak 시점 수익 못 회수)
→ 장점: 잔량 매우 오래 보호 = 가격 회복 시 큰 잠재 수익
```

---

## 🏗 기술 설계

### DB Migration
```sql
ALTER TABLE strategy_instances
ADD COLUMN trailing_retrace_pct DECIMAL(5,2) DEFAULT 5.00;
COMMENT ON COLUMN strategy_instances.trailing_retrace_pct
IS '사장님 trailing 옵션 (% peak 회귀 시 전량 청산). default 5, 옵션 5/10/15/20.';
```

### Schema
```python
# schemas/strategy.py StrategyDetailResponse 에 추가
trailing_retrace_pct: Decimal = Field(default=Decimal("5"), description="...")
```

### API Endpoint (신규)
```python
# 가장 단순 = 단일 필드 PATCH
@router.patch("/{strategy_id}/trailing-retrace")
def update_trailing_retrace(
    strategy_id: int,
    payload: TrailingRetracePctRequest,  # {pct: Decimal}
    db: Session, user_id: int,
) -> StrategyDetailResponse:
    # 검증: pct ∈ {5, 10, 15, 20}
    # 본인 소유 + 활성 strategy
    # 변경 즉시 DB commit
    # 다음 risk cycle 부터 자동 적용
```

### Risk Service
```python
# risk_service.py evaluate_take_profit_level
# 옛 (hardcoded):
TRAILING_RETRACE_AMOUNT = TRAILING_RETRACE_PCT  # =5

# 신 (strategy 별):
trailing_retrace = Decimal(str(strategy.trailing_retrace_pct or 5))
if (
    status TP3+_DONE_PARTIAL
    and stage >= 3
    and peak >= 5%  # 임계는 그대로
    and pnl_ratio <= (peak - trailing_retrace)  # 사장님 옵션 적용
):
    return "TRAILING_TP"
```

### Frontend (전략 인스턴스 카드)
```html
<select onchange="updateTrailingRetrace({id}, this.value)">
  <option value="5"  selected>📏 -5% (default)</option>
  <option value="10">📐 -10% (= buffer 큼)</option>
  <option value="15">📐 -15% (= 매우 보수)</option>
  <option value="20">📐 -20% (= 극도 보수)</option>
</select>
```

```javascript
async function updateTrailingRetrace(strategyId, pct) {
  try {
    await api(`/strategies/${strategyId}/trailing-retrace`, {
      method: 'PATCH',
      body: { pct: Number(pct) },
    });
    toast(`✅ Trailing -${pct}% 적용`, 'success');
    // 다음 polling cycle 에 자동 갱신 (= 별도 새로고침 X)
  } catch (e) {
    toast(`❌ 변경 실패: ${e.message}`, 'error');
  }
}
```

---

## 🛡 헌법 5단계 검정 (Phase 2 + 3 모두 적용)

### Phase 2 (Backend):
1. **사상 검증** ✅ — 이 spec
2. **기존 코드 분석** = risk_service.evaluate_take_profit_level + alembic migrations
3. **변경 영향 분석**:
   - HIGH 위험: 모든 활성 strategy 영향
   - silent fail 가능성: `strategy.trailing_retrace_pct` 가 null 시 = default 5 fallback (= 옛 동작 유지)
   - 대칭성: PATCH endpoint = 검증 + 기록 (RiskEvent)
4. **코드 작성**:
   - default = 5 (= 옛 동작 그대로)
   - PATCH endpoint = 사장님 본인 소유 검증 + 4 옵션 강제 (5/10/15/20)
   - RiskEvent 기록 (= 사장님 변경 이력 audit)
5. **grep 검증**:
   - TRAILING_RETRACE_PCT 사용처 모두 grep
   - python ast.parse SYNTAX OK
   - pytest 회귀

### Phase 3 (Frontend):
1. **사상 검증** ✅
2. **기존 코드 분석** = strategies-list.js 카드 + cm-* 모달
3. **변경 영향 분석**: UI 만
4. **코드 작성**: 드롭다운 + onchange PATCH
5. **grep 검증**: 변수 정의 + 호출 일관성

---

## 🌟 사장님 자본 보호 의도

### 옛 시스템 한계:
- TP3 발동 후 = peak 시점 한 번 도달 → -5% 빠른 trailing 발동 → 잔량 청산
- = 변동 폭 큰 종목 (예: 30% 일일 변동) = 단순 노이즈에도 청산

### 신 시스템 효과:
- 사장님 = 종목 변동 폭 파악 → 적절한 옵션 선택
- 예: BEATUSDT (변동 큼) = -15% 또는 -20%
- 예: BTCUSDT (변동 작음) = -5% 또는 -10%
- = **사장님 시장 판단 + 시스템 자동 보호 = 최적 운영**

---

## 📋 향후 fix 계획 (Phase 분리)

### Phase 1 ✅ (이 spec) — 사장님 사상 영구 보존
### Phase 2 — Backend PR
- alembic migration (DB)
- Schema 확장
- API endpoint
- Risk service 적용
- pytest 회귀 100%

### Phase 3 — Frontend PR (Phase 2 머지 후)
- strategies-list.js 카드 = 드롭다운 추가
- 즉시 PATCH + toast 알림
- Tooltip = 옵션별 의미 설명

### Phase 4 (선택) — 사장님 시각 가이드
- 종목별 권장 옵션 (24h 변동 폭 기반)
- 예: 변동 > 20% = 추천 -15% 이상

---

## 🌿 사장님 결정 사항

### Phase 1 = 이 spec 머지 후 = Phase 2 개발 시작

### 옵션 4가지 확인:
- ✅ **-5% (default)** = 옛 동작 (= 기존 strategy 영향 0)
- ✅ **-10%** = 변동 보통 종목
- ✅ **-15%** = 변동 큰 종목
- ✅ **-20%** = 매우 보수 (= 손실 가능성 있음)

### Phase 2 + 3 = 사장님 승인 후 = 즉시 개발 (헌법 5단계 100% 적용)

---

> **Spec 작성**: 2026-06-08
> **위치**: `binance-auto-trader/TRAILING_RETRACE_POLICY_SPEC_2026-06-08.md`
> **상태**: 영구 보존 — 변경 시 = 사장님 명시 승인
> **다음**: Phase 2 (Backend) → Phase 3 (Frontend) PR 작성
