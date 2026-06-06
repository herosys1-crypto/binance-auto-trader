# 🚨 크라이시스 모드 최종 사상 (2026-06-06 사장님 명확화)

> **문서 목적**: 사장님 EPICUSDT (#23) 사건 (TP3 후 -5% 하락 = 미청산) 의 원인 분석 +
> 사장님 크라이시스 모드 사상 영구 보존 (코드 변경 시 항상 이 문서를 우선 참고).
>
> **사장님 명시 (2026-06-06)**:
> > "크라이시스는 손실이 큰 상태에서 단계별 포지션이 너무 많이 실행되어 큰 투자로 인해서
> > 수익이 발생했을때 빠른 익절을 시작하는거야. 다른건 없어. 큰 손실에서 작은 이익 5% 에서
> > 익절을 시작하고 tp1 tp2 tp3 일 실행되고 최고가 대비 -5% 가 되면 모든 포지션을 청산하는거야."

---

## 📜 사장님 사상 정확 (단순 + 완결)

### 핵심 단일 정책

```
1️⃣ 진입 조건
   = 큰 손실 발생 (max_loss ≤ template 임계, default -50%)
   + 단계별 포지션 너무 많이 실행 (모든 단계 진입 or ad-hoc 추가)
   = 「큰 투자」 상태

2️⃣ 회복 시 = 빠른 익절 시작
   - TP1 = ROI +5% (정상 모드 +10% 보다 빠름)
   - TP2 = ROI +10%
   - TP3 = ROI +15%
   - (TP4 = ROI +20%, 사용 시)

3️⃣ TP3 발동 후 = 최고가 (peak ROI) 대비 -5% 회귀 = 전량 청산
   = 「수익 보호」 (남은 수익을 잃지 않게)

4️⃣ 「다른 건 없어」
   = 추가 정책 X (Hard SL -1% 등 = 사장님 의도 X)
   = 정상 모드 SL 룰 (-50% 또는 사장님 설정값) = 별도 작동
```

### 의도 = 단 두 가지

| 단계 | 의도 |
|---|---|
| 회복 익절 | 큰 손실 → 작은 회복 = 빠르게 일부 정리 (TP1/2/3 단계적) |
| Trailing 보호 | TP3 후 peak 도달 = 남은 수익을 -5% 회귀로 잃지 않게 전량 청산 |

---

## 🔧 시스템 코드 분석 — 사장님 사상과 비교

### 정상 모드 TRAILING_TP (risk_service.py L195-202)

```python
TRAILING_ARMED_STATUSES = (
    {f"TP{n}_DONE_PARTIAL" for n in range(TRAILING_MIN_TP_INDEX, 11)}  # TP3+
    | {"TRAILING_ARMED"}
)
if (
    (strategy.status or "").upper() in TRAILING_ARMED_STATUSES  # TP3+ 발동
    and (strategy.current_stage or 0) >= TRAILING_MIN_STAGE     # stage >= 3
    and peak >= TRAILING_TP_PEAK_THRESHOLD                       # peak >= 5%
    and pnl_ratio <= (peak - TRAILING_TP_RETRACE_AMOUNT)         # retrace 5%p
    and pnl_ratio < peak
):
    return "TRAILING_TP"  # 전량 청산
```

**= 사장님 사상과 100% 일치!**
- ✅ TP3 발동 후부터 armed
- ✅ peak >= 5%
- ✅ peak - 5%p 회귀 시 청산

### Crisis 모드 차이

Crisis 모드는 TP threshold 만 override (5/10/15/20%) — 나머지 정책은 동일:

```python
# risk_service.py L173-179
if strategy.crisis_mode_triggered_at:
    CRISIS_OVERRIDE = {
        "TP1": Decimal("5"), "TP2": Decimal("10"),
        "TP3": Decimal("15"), "TP4": Decimal("20"),
    }
```

= **TRAILING_TP 평가는 정상 모드와 동일하게 작동해야 함!**

---

## 🐛 EPICUSDT (#23) 미청산 원인 분석

### 캡쳐 (사장님 보고 2026-06-06)
- 6/8 단계, 3/10 익절 (TP1/TP2/TP3 발동 추정)
- 「🚨 크라이시스 Stage 1 (TP 임계↓)」 표시
- PNL: -77.27 USDT (-7.28% ROI)
- SHORT, qty -2,547.6

### 코드 path 검증 결과

| 검사 항목 | 코드 동작 | EPICUSDT 추정 | 결과 |
|---|---|---|---|
| `evaluate_stop_loss` | stage < total_stages 면 SL skip | 6 < 8 = skip ✅ | SL 미발동 OK |
| `evaluate_take_profit_level` 호출 | SL skip 후 호출 | 호출됨 ✅ | OK |
| TRAILING_TP 조건 1 (status) | TP3_DONE_PARTIAL+ | **❓ 진단 필요** | 미확인 |
| TRAILING_TP 조건 2 (stage) | >= 3 | 6 ✅ | OK |
| TRAILING_TP 조건 3 (peak >= 5%) | TP3 발동 = ROI 15% 도달 = peak >= 15% | **❓ 진단 필요** | 미확인 |
| TRAILING_TP 조건 4 (retrace 5%p) | peak 15% - current -7.28% = 22.28%p | ✅ 22.28 > 5 | OK |

### 가장 의심 원인 (남은 가능성)

**A. `strategy.status` 가 TP3_DONE_PARTIAL 가 아님**:
- TP3 실제 발동 안 했을 수도 (UI "3/10" 의 의미 별도 확인 필요)
- 또는 status update 실패 (다른 worker 가 덮어씀)

**B. `peak` Redis 휘발 + `max_profit_pct` 미갱신**:
- Redis `strategy:23:peak_pnl_pct` 키 = TTL 만료 또는 evict
- fallback `max_profit_pct` 도 None 또는 < 5%
- 다만 = TP3 발동 시점 = max_profit_pct >= 15% 갱신됐어야 (`_update_pnl_extremes`)

**C. `process_action` 호출 자체 안 됨**:
- stream_service ACCOUNT_UPDATE / mark-price stream 시 호출
- 특정 path 에서 skip 됐을 수도

### Silent bug 별도 발견 (사장님 사상과 무관, 단지 UI 영향)

**`crisis_first_tp_done_at`**:
- grep `crisis_first_tp_done_at = ` = backend 전체 0건!
- = TP1 발동해도 영원히 None
- = Frontend UI 영원히 「Stage 1」 표시 (Stage 2 진입 X)
- 다만 = **사장님 사상에는 무관** ("Stage 2 보호" = 사장님 의도 X, DEAD CODE 의도)
- = UI 만 정확화 fix 필요 (Trailing TP 와 무관)

**`_execute_crisis_action` DEAD CODE (tp_sl_orchestrator.py L393-421)**:
- CRISIS_TP1 / CRISIS_TRAIL_FULL / CRISIS_HARD_SL = 호출처 0건
- 다만 = 사장님 사상 = 정상 TRAILING_TP 와 동일 = **wire-up 불필요**
- = 영구 제거 권장 (혼란 방지)

---

## 🎯 다음 진행 계획

### Step 1 — 진단 (사장님 협조 필요)

VPS 에서 EPICUSDT (#23) 실제 DB 값 확인:

```bash
docker compose exec api python -u -c "
import sys
from app.core.database import SessionLocal
from app.models.strategy_instance import StrategyInstance
db = SessionLocal()
s = db.get(StrategyInstance, 23)
sys.stdout.write(f'status={s.status}\n')
sys.stdout.write(f'crisis_mode={s.crisis_mode_triggered_at}\n')
sys.stdout.write(f'crisis_tp1={s.crisis_first_tp_done_at}\n')
sys.stdout.write(f'max_profit={s.max_profit_pct}\n')
sys.stdout.write(f'max_loss={s.max_loss_pct}\n')
sys.stdout.write(f'unrealized_pnl={s.unrealized_pnl}\n')
sys.stdout.write(f'current_stage={s.current_stage}\n')
sys.stdout.flush()
db.close()
"
```

`-u` flag + `sys.stdout.write()` + `flush()` = Docker stdout buffering 회피.

추가 = Redis peak 키 확인:
```bash
docker compose exec api python -u -c "
import sys
from app.core.redis_client import get_redis_client
r = get_redis_client()
val = r.get('strategy:23:peak_pnl_pct')
sys.stdout.write(f'redis_peak={val}\n')
sys.stdout.flush()
"
```

### Step 2 — 분석

진단 결과로 미청산 원인 확정:
- `status` 가 TP3_DONE_PARTIAL 가 아니면 = status update bug
- `max_profit_pct` 가 < 5% 면 = peak 갱신 bug
- 둘 다 정상이면 = `process_action` 호출 안 된 worker bug

### Step 3 — PR 계획 (다음 세션)

| PR | 변경 |
|---|---|
| **PR-A** | `crisis_first_tp_done_at` set 추가 (TP1 발동 시) → Frontend UI Stage 2 정확 표시 |
| **PR-B** | `_execute_crisis_action` DEAD CODE 영구 제거 + `_eval_crisis_mode_tp_sl` 도 제거 (사장님 사상 X) |
| **PR-C** | 진단 결과 따른 bug fix (status / peak / worker 중 하나) |
| **PR-D** | Trailing TP 발동 시 Telegram 알림 (사장님 즉시 인지) |

---

## 📋 사장님 사상 보존 — 향후 개발 시 절대 변경 금지

1. **크라이시스 = TP threshold override 만** (5/10/15/20%)
2. **TRAILING_TP = 정상 모드 코드 그대로** (TP3+ + stage>=3 + peak>=5% + retrace 5%p)
3. **「다른 정책 없음」** — Hard SL -1% 등 추가 X (사장님 명시 거부)
4. **「수익 보호」 = 사장님 핵심 의도** — peak 도달 후 회귀 시 잃지 않게 전량 정리

---

## 🔗 관련 문서

- `TP_TRAILING_LOGIC_FINAL.md` v7 — 사장님 사상 trailing 정책 (정상 모드)
- `CRISIS_RECOVERY_MODE_PLAN.md` — 옛 크라이시스 계획 (Phase D 미완성 = DEAD CODE 의 원인)
- `SPEC_UPDATE_2026-06-05.md` — 6-01~6-05 통합 정리
- `risk_service.py` L115-224 — `evaluate_take_profit_level` (사장님 사상 핵심 코드)
- `tp_sl_orchestrator.py` L107-305 — `_execute_take_profit` (TP 실행 + status update)

---

> **결론**: 사장님 사상 = 단순 + 정상 모드 TRAILING_TP 와 동일 정책.
> Crisis 모드는 TP threshold override 만 + DEAD CODE (Stage 2 보호) = 사장님 의도 X.
> EPICUSDT 미청산 = 진단 필요 (3가지 가능 원인 중 하나).
> 다음 세션 = 진단 결과 → PR 4건 진행.
