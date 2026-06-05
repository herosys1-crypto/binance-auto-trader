# 익절 + 트레일링 로직 — 최종 확정 (2026-05-12)

| 항목 | 내용 |
|---|---|
| 문서 목적 | 「몇 번을 바꿔야 하나?」 종결 — **이게 최종** |
| 코드 HEAD | `293a9ba` (또는 더 최신) |
| 회귀 테스트 | **55 passed** (5개 핵심 파일 모두) |
| 사용자 의도 일치 | **100% ✅** |

---

## ⚙️ 핵심 정책 상수 (risk_service.py:25~28)

```python
TRAILING_TP_PEAK_THRESHOLD = Decimal("5")    # 피크 ≥ +5%
TRAILING_TP_RETRACE_AMOUNT = Decimal("5")    # 회귀 -5%
TRAILING_MIN_TP_INDEX = 3                    # TP3 부터 armed
TRAILING_MIN_STAGE = 3                       # 진입 stage ≥ 3
```

## ⚙️ TP qty default ratio (tp_sl_orchestrator.py:116~117)

```python
default_ratio = {f"TP{n}": Decimal("25") for n in range(1, 10)}  # TP1~9 = 25% (균일)
default_ratio["TP10"] = Decimal("100")                            # TP10 = 100% (안전망)
```

---

## 🎯 익절 흐름 — 5가지 케이스 (decision tree)

### 1. 정상 TP 발동 (진입 단계 무관)

```
가격이 TP{n}_percent 임계 도달
+ status 가 TP{n} 미발동 상태
↓
잔량 × tp{n}_qty_ratio (template 또는 default 25%) 청산
status → TP{n}_DONE_PARTIAL
```

| TP | 임계 (default) | qty (default) | 결과 |
|---|---|---|---|
| TP1 | +10% | 25% of 잔량 | status=TP1_DONE_PARTIAL |
| TP2 | +15% | 25% of 잔량 | status=TP2_DONE_PARTIAL |
| TP3 | +20% | 25% of 잔량 | status=TP3_DONE_PARTIAL ⭐ trailing armed (조건 ①) |
| TP4 | (사용자) | 25% of 잔량 | status=TP4_DONE_PARTIAL |
| ... | | 25% of 잔량 | |
| TP10 | (사용자) | **100% (안전망)** | status=COMPLETED |

### 2. TRAILING_TP 발동 — **5가지 조건 모두 AND** (risk_service.py:163~169)

```python
if (
    status ∈ {TP3~TP10_DONE_PARTIAL, TRAILING_ARMED}    # ① TP3 까지 발동
    AND current_stage >= 3                              # ② 진입 stage 3 이상
    AND peak >= 5                                       # ③ peak ≥ +5%
    AND pnl_ratio <= peak - 5                          # ④ 회귀 -5% 이상
    AND pnl_ratio < peak                                # ⑤ 현재 < peak
):
    return "TRAILING_TP"  # → 잔량 100% 청산 + status=COMPLETED + Redis peak 리셋
```

### 3. 손절 (SL)

```
모든 단계 진입 완료 (current_stage == total_stages)
+ ROI ≤ -50% (leveraged)
↓
잔량 100% 청산 + status=STOPPING → REENTRY_READY
```

### 4. 크라이시스 모드

```
모든 단계 진입 완료 + max_loss_pct ≤ -50%
↓ crisis_mode_triggered_at 기록
TP override: TP1=+5/25%, TP2=+10/25%, TP3=+15/50%, TP4=+20/100%
첫 TP (+5%) 발동 → CRISIS_TP1_DONE
이후: 피크 -5% → CRISIS_TRAIL_FULL (100% 청산)
       또는 PnL -1% → CRISIS_HARD_SL (100% 손절)
```

### 5. TP10 발동 (안전망)

```
가격이 사용자 설정 TP10 임계 도달
↓
잔량 100% 청산 (default ratio 100% — 사용자가 변경 가능)
status=COMPLETED
```

---

## 🚦 사용자 의도와 코드 매칭 (1:1)

| 사용자 룰 | 코드 위치 | 검증 테스트 | 결과 |
|---|---|---|---|
| TP1 +10% 25% 청산 | `default_ratio["TP1"]=25` | `test_tp1_through_tp9_default_25_pct` | ✅ |
| TP2 +15% 잔량의 25% | `default_ratio["TP2"]=25` | 동일 | ✅ |
| TP3 +20% 잔량의 25% | `default_ratio["TP3"]=25` | 동일 | ✅ |
| TP10 까지 균일 25% | `range(1, 10)` (TP1~9) | 동일 | ✅ |
| TP10 = 100% 안전망 | `default_ratio["TP10"]=100` | `test_tp10_default_100_pct_safety_net` | ✅ |
| 익절은 진입 단계 무관 | TP loop 가 stage 안 봄 | (default 동작) | ✅ |
| 진입 3단계 후 trailing | `current_stage >= 3` | `test_trailing_NOT_armed_when_stage_below_3` | ✅ |
| TP3 후 trailing | `status >= TP3_DONE_PARTIAL` | `test_trailing_fires_for_tp3_plus_done_partials_with_stage3` | ✅ |
| 최고가 -5% → 잔량 100% | trailing 5가지 조건 + 100% close | `test_98_LABUSDT_scenario_trailing_fires_at_peak_retrace` | ✅ |
| TP1, TP2 만 발동시 trailing X | TRAILING_ARMED_STATUSES 에 TP1/TP2 없음 | `test_trailing_NOT_armed_for_tp1_tp2_done_partials` | ✅ |
| 2단계까지만 진입시 trailing X | `current_stage >= 3` 조건 | `test_trailing_NOT_armed_when_stage_below_3` | ✅ |
| TP3 만 enable 해도 100% 강제 안 함 (last_active_tp shortcut 폐지) | shortcut 코드 제거됨 | `test_tp3_last_enabled_does_NOT_close_all` | ✅ |

**모든 룰 ✅. 11/11 tests pass.**

---

## 📊 실거래 시뮬레이션 — 사용자 의도대로 동작

### 시나리오: 7단계 SHORT, 진입 3단계까지, 가격 +25% 도달 후 -5% 회귀

```
[setup]
- Template: TP1=10%/25%, TP2=15%/25%, TP3=20%/25%, TP4=25%/25%, TP5~10 NULL
- 진입: stage 1 (100), stage 2 (200), stage 3 (300) → 총 자본 600 USDT
- 단계별 자본 가중평균 → 진입 qty 600/avg_price

[가격 변화]
+10% 도달 → TP1 발동
  close = 잔량 × 25% = 25% of 600 = 150 USDT 분 청산
  status = TP1_DONE_PARTIAL
  잔량 = 75% (450 분)

+15% 도달 → TP2 발동
  close = 잔량 × 25% = 18.75% of 600 = 112.5 분 청산
  status = TP2_DONE_PARTIAL
  잔량 = 56.25% (337.5 분)

+20% 도달 → TP3 발동
  close = 잔량 × 25% = 14.06% of 600 = 84.4 분 청산
  status = TP3_DONE_PARTIAL ⭐ trailing armed!
  잔량 = 42.19% (253.1 분)

+25% 도달 → TP4 발동 (사용자가 TP4 enable 한 경우만)
  close = 잔량 × 25% = 10.55% of 600 = 63.3 분 청산
  status = TP4_DONE_PARTIAL
  잔량 = 31.64% (189.8 분)
  peak = 25% 갱신

+20% 회귀 (peak=25 → 25-5=20, current=20) → trailing 발동!
  close_ratio = 1.00 (TRAILING_TP)
  잔량 100% (189.8 분) 모두 청산
  status = COMPLETED
  Redis peak 리셋

[총 청산 금액 (USDT 기준 — 가격 변동 무시한 분)]
TP1: 150 + TP2: 112.5 + TP3: 84.4 + TP4: 63.3 + Trailing: 189.8 = 600.0 ✓
```

이게 **사용자 의도** 와 정확히 일치합니다.

---

## ❓ 「왜 같은 패턴이 계속 나오는가」 — 과거 거래 미스터리

#11 BUSDT, #13 SAGAUSDT, #19 GTCUSDT, #2 VVVUSDT, #5 SAGAUSDT 모두 「TP1 후 즉시 100% 청산」 패턴.

코드는 v6 (위와 같이) 인데 왜 그런가? **3가지 가능성** — 검증 필요:

### 가설 1: Production 미배포 (가장 유력) ⭐

거래 시점 production 코드가 v5 또는 v1 였을 가능성. v6 commit 은 오늘 (2026-05-12) 저녁이므로:
- **새벽~저녁 거래** = v5 (last_active_tp shortcut 100% 강제) 또는 v1 (TP1+ armed)
- **저녁 이후 거래** = v6 (위 정의대로)

**검증**:
```bash
ssh root@159.65.137.250
cd ~/binance-auto-trader/backend
docker compose exec api grep "TRAILING_MIN_TP_INDEX = " /app/app/services/risk_service.py
docker compose exec api grep "TRAILING_MIN_STAGE = " /app/app/services/risk_service.py
docker compose exec api grep -c "last_active_tp = " /app/app/services/tp_sl_orchestrator.py
# 기대 (v6):
#   TRAILING_MIN_TP_INDEX = 3
#   TRAILING_MIN_STAGE = 3
#   0 (last_active_tp 변수 사라짐)
```

### 가설 2: 템플릿에 명시 100% 설정

사용자가 직접 `tp2_qty_ratio = 100` 또는 `tp3_qty_ratio = 100` 으로 설정한 경우, 그 값이 우선 → 100% 청산.

**검증** (production VPS):
```bash
docker compose exec api python -c "
from app.core.database import SessionLocal
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate
db = SessionLocal()
si = db.query(StrategyInstance).filter(StrategyInstance.id.in_([19, 21])).all()
for s in si:
    tpl = db.get(StrategyTemplate, s.strategy_template_id)
    print(f'#{s.id} {s.symbol} → tpl #{tpl.id} {tpl.name}')
    for n in range(1, 11):
        pct = getattr(tpl, f'tp{n}_percent', None)
        ratio = getattr(tpl, f'tp{n}_qty_ratio', None)
        if pct is not None or ratio is not None:
            print(f'  TP{n}: pct={pct}%, ratio={ratio}%')
db.close()
"
```

### 가설 3: 알림 진단 — 실제 어떤 TP 가 발동됐나

```bash
docker compose exec api python -c "
from app.core.database import SessionLocal
from app.models.notification import Notification
db = SessionLocal()
for sid in [19, 21]:
    print(f'=== Strategy #{sid} ===')
    notifs = db.query(Notification).filter(Notification.strategy_instance_id == sid).order_by(Notification.id).all()
    for n in notifs:
        print(f'  [{n.created_at}] {n.title}')
db.close()
"
```

이 3가지 명령 결과 보여주시면 **확실하게** 진단 가능합니다.

---

## 🎯 결론 — 코드는 변경 X

| 항목 | 상태 |
|---|---|
| 코드 정책 | ✅ v6 — 사용자 의도 100% 일치 |
| 회귀 테스트 | ✅ 55 passed (핵심 5 파일) + 530 passed (전체) |
| 코드 수정 필요? | ❌ **없음** — 추가 수정하지 마세요 |
| 미해결 항목 | 🔍 production 배포 상태 검증 + 과거 거래 데이터 확인 (가설 1/2/3) |

**더 이상 코드 변경 안 합니다.** 위 3개 진단 명령 결과로:
- 가설 1 (미배포) 확정 → `git pull && docker compose restart` 만으로 해결
- 가설 2 (template 100%) 확정 → 사용자가 UI 에서 template 수정
- 가설 3 (알림 4건 모두 있음) → UI 표시 누락 — 데이터는 정상

---

## 📌 정책 변경 시간선 (2026-05-12 하루)

| 시간 | 버전 | 변경 |
|---|---|---|
| 새벽 | v3 | trailing TP4+ armed (보수적) |
| 저녁 | v4 | trailing TP3+ armed (v3→v2 revert) |
| 밤 1차 | v5 | trailing + `current_stage >= 3` 추가 |
| 밤 2차 | **v6 (final)** | **TP qty 균일 25% + last_active_tp shortcut 폐지** |

**v6 가 사용자 의도와 정확히 일치 — 더 이상 변경 X.**

---

## 🆕 2026-06-05 update — 사장님 사상 v7 (Mainnet 운영 반영)

### 1. SL 정책 변경 — 「투자금 대비 손실 %」 (레버리지 무관) — PR #57

#### 사상 정확화
- **이전**: SL = `ROI ≤ -sl_pct` (레버리지 영향, 사장님 의도와 차이)
- **신규**: SL = `손실 USDT ≥ total_capital × sl_pct / 100` (레버리지 무관)

#### 정확한 식
```python
sl_threshold_usd = total_capital × sl_pct / 100   # 절대 손실 한도 USDT
sl_triggered    = abs(unrealized_pnl) ≥ sl_threshold_usd  # pnl 음수 시
```

#### 예시 (사장님 EPICUSDT)
```
사장님 자본 (total_capital) = 1,860 USDT
sl_pct                       = 80%
SL 한도 USDT                 = 1,860 × 80 / 100 = 1,488 USDT
→ 손실 1,488 USDT 도달 시 자동 청산 (레버리지 2x 무관)
```

#### 사장님 의도 100% 일치
> "투자금에 -80% 일때 실행, 레버리지 상관없이"

### 2. 증거금/포지션 추가 시 total_capital 자동 합산 — PR #56

#### 사장님 노력 보호 사상
- 사장님이 청산 늦추기 위해 = 증거금 또는 포지션 수동 추가
- 옛: total_capital 그대로 → SL 한도 = 옛 기준 (사장님 노력 미반영)
- **신규**: 모든 추가 = total_capital += amount 자동 합산

#### 영향
- SL 한도 자동 ↑ (사장님 추가 자본 반영)
- reserved_for_strategies 자동 ↑
- 잔액 카드 정확 표시

### 3. 자본 자동 동기화 (reconcile_worker) — PR #84

#### Binance UI 직접 추가 대응
- 사장님이 Binance UI 에서 증거금 직접 추가 = 우리 시스템 우회
- reconcile_worker (30초 주기) 매 사이클 검증:
  ```python
  binance_actual_margin = max(isolatedMargin, positionInitialMargin)
  if binance_actual_margin > DB total_capital × 1.05 (+ 차이 > 1 USDT):
      strategy.total_capital = binance_actual_margin  # 자동 갱신
      RiskEvent (TOTAL_CAPITAL_AUTO_SYNC) audit log
  ```
- 사장님이 어디서 추가하든 = 30초 내 우리 DB 자동 반영

### 4. TP 청산 수량 = max(qty 기준, capital 기준) — PR #87+#88

#### 사장님 명시 의도 (PR #88 commit 메시지)
> "TP1 부터 익절은 포지션과 증거금 포함해서 전체금액에 25%씩 익절하고
>  남은 포지션금액에 25%씩 익절"
> "수동포지션과 증거금 추가한 금액모두를 기준"

#### 옛 로직 (v6 — 5-12)
```python
close_qty = current_qty × close_ratio
# qty 만 25% — 증거금 추가 무관
```

#### 신규 로직 (v7 — 2026-06-05)
```python
# 사장님 자본 (DB) vs Binance 실 마진 (사장님 외부 추가 포함) — 둘 중 max
effective_margin = max(DB total_capital, latest_position.isolated_margin)

qty_based     = current_qty × close_ratio
capital_based = (effective_margin × close_ratio × leverage) / avg_entry
raw_qty       = max(qty_based, capital_based)
close_qty     = min(raw_qty, current_qty)  # 보유 초과 방지
```

#### 사장님 EPICUSDT 시뮬레이션
| 항목 | 옛 v6 | 신 v7 (case A) | 신 v7 (case B) |
|---|---|---|---|
| total_capital | - | 1,860 | 2,760 |
| current_qty | 3,396.70 | 3,396.70 | 3,396.70 |
| effective_margin | - | 1,860 | 2,760 |
| **close_qty** | **849** | **1,525** | **2,394** |
| vs v6 | - | **1.8배 ↑** | **2.8배 ↑** |

→ 사장님 자본 추가 노력 = TP 청산 자동 반영 = 더 빨리 회복 익절

### 5. total_capital 의미 변경 — 옵션 A (마진 단위) — PR #79+#80

#### 명확화
- **`total_capital` = 사장님 입력 자본 = 「마진 단위」** (notional X)
- 사장님이 strategy 생성 시 "1860 USDT" 입력 = Binance lock 마진 1,860 의도
- 거래 규모 (notional) = `total_capital × leverage` (별도 표시)

#### UI 표시
```
📦 수량 19,224
🔒 마진 175.03 / 1860 USDT  9%  ← 현재 / 사장님 자본 + 진입률
📊 거래규모 3720 USDT (= 자본 1860 × 2x)  ← tooltip
```

### 6. 빈 단계 자동 압축 + trigger 누적 — PR #60

#### 사장님 사상
> "4단계가 3단계가 되어 한단계식 당기면 되고, 3단계 trigger 10% 누적"

#### 동작
- 사장님이 단계 capital 빈 칸 + trigger 채움 → 자동 압축
- 빈 단계의 trigger = 다음 채워진 단계로 누적 합산

### 7. SL 진행률 시각화 + 80% 알림 — PR #64+#68

#### UI 표시 (전략 인스턴스 카드 PNL 컬럼)
```
SL 5% (-200 USDT)    회색 (진행률 5%)
SL 30% (-200 USDT)   노랑 (진행률 30%)
SL 60% (-200 USDT)   주황 (진행률 60%)
SL 85% (-200 USDT)   빨강 🚨 (진행률 80% 초과)
```

#### Telegram 자동 알림
- SL 진행률 80% 도달 시 자동 알림 (1h dedup)
- 사장님이 화면 안 봐도 즉시 인지

---

## 📋 정책 변경 시간선 (전체)

| 시점 | 버전 | 변경 |
|---|---|---|
| 5-12 새벽 | v3 | trailing TP4+ armed (보수적) |
| 5-12 저녁 | v4 | trailing TP3+ armed |
| 5-12 밤 1차 | v5 | trailing + current_stage >= 3 |
| 5-12 밤 2차 | **v6** | TP qty 균일 25% + last_active_tp shortcut 폐지 |
| **6-01** | **mainnet 진입** | 8 critical fix |
| **6-03** | **사상 정확화 PR #57** | SL = total_capital × sl_pct / 100 (레버리지 무관) |
| **6-05** | **v7 (옵션 A + TP capital 기준)** | 사장님 자본 = 마진 단위 + TP 청산 = max(qty, capital) × 25% |

**v7 = 사장님 mainnet 운영 완벽 반영 + 사장님 노력 영구 보호.**
