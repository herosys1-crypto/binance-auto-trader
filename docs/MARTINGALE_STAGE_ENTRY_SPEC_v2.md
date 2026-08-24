# 📊 MARTINGALE_STAGE_ENTRY_SPEC v2 — 마틴게일 단계 진입 통합 사양서

> **Fix 56 통합 spec 문서 · 2026-08-24 · v219+ 계열 확정**
> 사장님 사상 100% 반영 · 다중 시간대(15m·1h·4h) 지표 검증 강제 · PENGUUSDT -93 USDT 재발 방지

---

## 🎯 사장님 verbatim (사상의 원천)

사장님께서 직접 지시하신 verbatim 문장을 spec 최상단에 박제합니다.
아래 3문장은 이 spec 전체를 지배하는 **불변의 헌법**입니다.

> **"충분히 상승/하락 반복 후 조정 시점에 2단계 진입 → 3단계까지 실패는 말이 안돼!"**

> **"OBV MACD RSI 등등 특히 OBV와 MACD 보조차트를 분석해서 진입시점"**

> **"15분 차트 기준과 1시간 4시간을 참고해서 진입시점"**

**해석 (헌법 확정):**
1. **2단계·3단계 실패는 사장님 사상에서 "말이 안 되는 일"** → 지표 검증 없이 하락률만 보고 진입하면 안 됨
2. **OBV·MACD는 필수 보조지표** → RSI 단독 진입 금지
3. **15m = 기본 판단**, **1h = 2·3단계 재확인**, **4h = 4단계 최종 관문**

---

## 1. 개요

### 1.1 목적
- 사장님 사상 "정점 SHORT / 저점 LONG + 조정 시 마틴게일 추가" 를 **모든 단계 진입 경로에 강제**
- 특정 워커(auto_short_at_top / auto_long_at_bottom) 뿐 아니라 **stage_trigger_worker / peak_break_reversal_worker / realtime_reentry_worker / success_pyramiding_worker** 등 모든 마틴게일 진입 게이트에 동일 규칙 적용
- Fix 55 이전에 발생한 **PENGUUSDT -93 USDT 사고**의 근본 원인(하락률만 보고 진입) 재발 방지

### 1.2 적용 범위
| 워커 | 마틴게일 성격 | spec 적용 여부 |
| --- | --- | :---: |
| `stage_trigger_worker` | 원 진입 후 반대 방향 하락 시 다음 단계 매수 | ✅ 필수 |
| `peak_break_reversal_worker` (Fix 41) | 저항 돌파 실패 시 SHORT 재진입 | ✅ 필수 |
| `realtime_reentry_worker` | 청산 후 재진입 (v202 Martingale) | ✅ 필수 |
| `success_pyramiding_worker` (Fix v218) | 익절 구간 추가 매수 | ✅ 필수 |
| `auto_short_at_top_worker` (v219) | 1단계 원 진입 (SHORT) | ❌ 원 진입 규칙 별도(SAJANGNIM_PROVEN_STRATEGY_v219) |
| `auto_long_at_bottom_worker` | 1단계 원 진입 (LONG) | ❌ 원 진입 규칙 별도 |

---

## 2. 단계별 진입 조건 매트릭스

### 2.1 자본 스케줄 (사장님 마틴게일 최종 확정)

| 단계 | 자본 (USDT) | 배수 | 누적 | 비고 |
| :---: | :---: | :---: | :---: | --- |
| 1단계 | **300** | 1.0× | 300 | default (사장님 지시) |
| 2단계 | **600** | 2.0× | 900 | 이전 × 2 |
| 3단계 | **1800** | 6.0× | 2700 | 투자금 전체 × 2 (매우 신중!) |
| 4단계 (라스트) | **1800** | 6.0× | 4500 | **최종 관문**, 4h 확인 필수 |
| 5단계+ | **금지** | — | — | `None` 반환 (헌법 v219 최종) |

> **사장님 verbatim (v219):** "3단계까지 갈 수 있다야 가능하면 가지 않는 관리가 필요"

### 2.2 진입 조건 매트릭스 (단계별 강제 검증)

| 단계 | 트리거 조건 (가격) | 필수 지표 검증 (15m) | 추가 시간대 확인 | 자본 |
| :---: | --- | --- | --- | :---: |
| **1단계** | 원 진입 워커 (v219 7중 정점 / OBV 재매집 등) | 워커별 spec | — | 300 |
| **2단계** | 평단 대비 -5% ~ -8% 조정 도달 | **3개 중 2개** 반전 필수:<br>① RSI (SHORT: <70 이탈 / LONG: >30 이탈)<br>② MACD Hist (SHORT: 최고 대비 -30% / LONG: 최저 대비 +30%)<br>③ OBV slope (SHORT: 하락 전환 / LONG: 상승 전환) | 15m 만 사용 | 600 |
| **3단계** | 평단 대비 -10% ~ -15% 조정 도달 | **3개 모두** 반전 필수 (RSI + MACD + OBV) | **1h 재확인 필수**<br>(1h RSI 동일 방향 반전 필요) | 1800 |
| **4단계 (라스트)** | 평단 대비 -18% 이상 조정 | 3개 모두 반전 + **다이버전스** 확인 (RSI/MACD hidden div 필수) | **4h 확인 필수**<br>(4h BB 반대 밴드 도달 or 4h OBV 반전) | 1800 |
| **5단계+** | 진입 불가 (`None` 반환) | — | — | — |

### 2.3 24h 변동 필터 (헌법 64 예외 규정)

| 단계 | 24h ±15% 필터 | 이유 |
| :---: | :---: | --- |
| 1단계 | ✅ 적용 (auto_short_at_top / auto_long_at_bottom 원 진입) | 급등락 반대매매 금지 (헌법 64) |
| 2단계 | ⚠️ 완화 (±20%까지 허용) | 이미 진입한 방향 유지 |
| 3단계 | ❌ 재적용 (±15% 초과 시 skip) | 폭발 위험 방지 |
| 4단계 | ❌ 재적용 + **다이버전스 필수** | 라스트 = 최종 안전장치 |

---

## 3. 다중 시간대 매트릭스 (사장님 verbatim 준수)

### 3.1 시간대별 역할 분담

| 시간대 | 역할 | 검증 항목 | 사용 단계 |
| :---: | --- | --- | :---: |
| **15m** | 기본 판단 (사장님 지시: "15분 차트 기준") | RSI, MACD Hist, OBV slope | 2단계 이상 전체 |
| **1h** | 2·3단계 재확인 (사장님 지시: "1시간 참고") | 1h RSI 방향, 1h MACD 크로스 | 3단계+ |
| **4h** | 4단계 최종 관문 (사장님 지시: "4시간 참고") | 4h BB, 4h OBV 반전, 다이버전스 | 4단계 |

### 3.2 지표 산정 함수 (구현 매핑)

| 지표 | 함수 | 파일 | 반환 |
| --- | --- | --- | --- |
| RSI (14) | `calculate_rsi(candles, period=14)` | `services/indicators.py` | float (0~100) |
| MACD Hist | `calculate_macd(candles, 12, 26, 9)` | `services/indicators.py` | (macd, signal, hist) |
| OBV slope | `calculate_obv_slope(candles, window=10)` | `services/indicators.py` | float |
| BB (20, 2σ) | `calculate_bollinger(candles, 20, 2)` | `services/indicators.py` | (upper, mid, lower) |
| 다이버전스 | `detect_divergence(candles, indicator)` | `services/chart_analyzer.py` | Enum |

### 3.3 시간대별 캔들 조회 (Redis 캐시 우선 — 헌법 6 단일 진실)

```python
# 우선순위: Redis → DB → Binance Public API
candles_15m = await get_candles(symbol, interval="15m", limit=100)  # 신선도 60s
candles_1h  = await get_candles(symbol, interval="1h",  limit=100)  # 신선도 300s
candles_4h  = await get_candles(symbol, interval="4h",  limit=100)  # 신선도 900s
```

---

## 4. 구현 파일 매핑 (Fix 56 통합)

### 4.1 워커 파일 → 검증 함수

| 워커 파일 | 마틴게일 진입 함수 | 지표 검증 함수 | 상태 |
| --- | --- | --- | :---: |
| `workers/stage_trigger_worker.py` | `_trigger_next_stage` | **`_check_stage_indicator_reversal`** | Fix 55 배포 |
| `workers/peak_break_reversal_worker.py` | `_open_reversal_short` | **`_check_reversal_signals`** | Fix 41 배포 |
| `workers/realtime_reentry_worker.py` | `_open_reentry_position` | **`_check_indicator_reversal_for_reentry`** | v202 배포 |
| `workers/success_pyramiding_worker.py` | `_add_pyramiding_stage` | **`_check_pyramiding_gate`** | Fix v218 배포 |

### 4.2 공용 게이트 함수 (신설 — Fix 56)

Fix 56에서 아래 공용 함수를 `services/martingale_gate.py`로 신설하여
4개 워커 모두 **단일 진입점**을 통과하도록 통합합니다. (헌법 6: 단일 진실)

```python
# services/martingale_gate.py (Fix 56 신설)
async def validate_stage_entry(
    *,
    symbol: str,
    side: Side,               # SHORT / LONG
    stage: int,               # 2, 3, 4
    entry_avg_price: Decimal, # 현재 평단
    current_price: Decimal,
) -> tuple[bool, str]:
    """
    마틴게일 단계 진입 게이트.
    True = 진입 허용, False = 차단 + 사유.

    호출자: stage_trigger / peak_break_reversal / realtime_reentry / success_pyramiding
    """
    # 1. 가격 조정 확인 (2단계 -5%, 3단계 -10%, 4단계 -18%)
    # 2. 15m 지표 반전 확인 (2단계: 2/3, 3·4단계: 3/3)
    # 3. 3단계 이상: 1h 재확인
    # 4. 4단계: 4h + 다이버전스
    # 5. 24h 변동 필터 (2단계 완화, 3·4단계 재적용)
    ...
```

---

## 5. 검증 함수 상세 사양

### 5.1 `_check_stage_indicator_reversal` (stage_trigger_worker)

```python
async def _check_stage_indicator_reversal(
    symbol: str, side: Side, stage: int
) -> tuple[bool, dict]:
    """
    stage_trigger_worker 전용 지표 반전 검증.

    Return:
      (allow: bool, detail: dict)
      detail = {
        "rsi": float, "rsi_reversed": bool,
        "macd_hist": float, "macd_reversed": bool,
        "obv_slope": float, "obv_reversed": bool,
        "reversed_count": int,  # 0~3
        "required_count": int,  # 2단계=2, 3·4단계=3
        "reason": str,
      }
    """
```

### 5.2 `_check_reversal_signals` (peak_break_reversal_worker)

```python
async def _check_reversal_signals(
    symbol: str, side: Side, stage: int
) -> tuple[bool, dict]:
    """
    저항 돌파 실패 후 재진입용 반전 신호 검증.
    peak_break_reversal_worker (Fix 41) 전용.
    """
```

### 5.3 `_check_indicator_reversal_for_reentry` (realtime_reentry_worker)

```python
async def _check_indicator_reversal_for_reentry(
    symbol: str, side: Side, stage: int, prev_close_reason: str
) -> tuple[bool, dict]:
    """
    청산 후 재진입 게이트 (v202 Martingale).
    prev_close_reason (TP1 / SL / MANUAL) 별로 조건 차등.
    """
```

### 5.4 `_check_pyramiding_gate` (success_pyramiding_worker)

```python
async def _check_pyramiding_gate(
    symbol: str, side: Side, stage: int, unrealized_pnl_pct: float
) -> tuple[bool, dict]:
    """
    익절 중 추가 매수 게이트 (Fix v218).
    unrealized_pnl_pct >= +5% 이면서 지표 지속 신호 필요.
    """
```

---

## 6. 자동 검증 시스템 (spec drift 방지)

Fix 56 이후 사양이 코드와 어긋나는 것을 **자동으로** 잡기 위해 3중 방어선을 둡니다.

### 6.1 `spec_audit_worker` (v48 기존) — FORBIDDEN / REQUIRED 등록

```python
# workers/spec_audit_worker.py
SPEC_RULES_MARTINGALE = {
    "MARTINGALE_STAGE_ENTRY_SPEC_v2": {
        "REQUIRED_CALLS": [
            # 이 함수들은 반드시 각 워커의 진입 경로에 존재해야 함
            ("workers/stage_trigger_worker.py", "_check_stage_indicator_reversal"),
            ("workers/peak_break_reversal_worker.py", "_check_reversal_signals"),
            ("workers/realtime_reentry_worker.py", "_check_indicator_reversal_for_reentry"),
            ("workers/success_pyramiding_worker.py", "_check_pyramiding_gate"),
        ],
        "FORBIDDEN_PATTERNS": [
            # 지표 검증 없이 가격만 보고 stage 진행하는 안티패턴
            (r"PRICE_DOWN_PCT.*_trigger_next_stage(?!.*_check_)", "지표 검증 누락"),
        ],
        "REQUIRED_TIMEFRAMES": {
            "stage>=3": ["15m", "1h"],
            "stage>=4": ["15m", "1h", "4h"],
        },
    }
}
```

### 6.2 `martingale_gate_validator_worker` (신 워커 — Fix 56 신설)

매 10분마다 실행하며 다음을 감사합니다.

| 감사 항목 | 실패 시 조치 |
| --- | --- |
| 최근 1시간 내 마틴게일 진입 로그에 `indicator_check` 필드 존재 | 텔레그램 CRITICAL 알림 + Sentry |
| stage=3 진입 시 `timeframe_1h_confirmed=True` 존재 | 진입 차단 롤백 트리거 |
| stage=4 진입 시 `timeframe_4h_confirmed=True` + `divergence_detected=True` 존재 | 진입 차단 롤백 트리거 |
| `martingale_gate.validate_stage_entry` 호출 카운트 vs 실제 진입 카운트 일치 | 불일치 시 관리자 알림 |

### 6.3 단위 테스트 (`tests/unit/test_martingale_stage_entry.py`)

```python
# 필수 케이스
def test_stage2_needs_2of3_reversal(): ...
def test_stage3_needs_3of3_plus_1h(): ...
def test_stage4_needs_4h_plus_divergence(): ...
def test_stage5_returns_none(): ...              # 5단계+ 금지
def test_pengu_incident_replay_blocks_entry(): ...  # PENGU 재현 → 차단 확인
def test_24h_pct_filter_stage3_blocks_over_15(): ...
def test_all_workers_use_shared_gate(): ...      # 4개 워커 모두 shared gate 통과
```

CI는 `test_martingale_stage_entry` 실패 시 배포 차단.

---

## 7. 자본 관리 (사장님 사상 재확인)

### 7.1 총 노출 한도

| 단계 | 자본 (USDT) | 누적 (USDT) | 총 자산 대비 (5% 룰) |
| :---: | :---: | :---: | :---: |
| 1 | 300 | 300 | 정상 |
| 2 | 600 | 900 | 정상 |
| 3 | 1800 | 2700 | ⚠️ 신중 |
| 4 (라스트) | 1800 | **4500** | 🚨 최대 노출 |

### 7.2 최대 손실 시나리오 계산

- 총 노출: **4500 USDT** (평단 기준)
- 4단계 라스트 손절 라인: -5% (평단 대비 소액 손절)
- **최대 손실: 4500 × 5% = -225 USDT** (안전 구간)

> 사장님 사상: **"짧은 손절 후 재진입"** — 4단계까지 갔더라도 -5% 손절 후 학습, 재진입 사이클로 전환

### 7.3 계정 자산 무관 원칙 (v219 헌법)

- **전체 자산이 5000 USDT든 500,000 USDT든 초기 300 USDT 고정**
- 계정 총액에 비례한 스케일링 금지 (헌법 v219 확정)
- 사장님 verbatim: **"자본 관리: 전체 자산 무관! 초기 금액만!"**

---

## 8. PENGUUSDT -93 USDT 사고 학습 (재발 방지)

### 8.1 사고 개요

| 항목 | 값 |
| --- | --- |
| 발생일 | 2026-08-24 |
| 심볼 | PENGUUSDT |
| 손실 | **-93 USDT** |
| 진입 방향 | SHORT (v219 정점) |
| 사고 단계 | 2·3단계 마틴게일 |
| 원 진입 worker | auto_short_at_top (정상) |
| 문제 워커 | **stage_trigger_worker** |

### 8.2 근본 원인 (Root Cause)

`stage_trigger_worker.py`의 `PRICE_DOWN_PCT` 모드에서:

- **가격 하락률(%)만 감지**하여 다음 단계 진입 트리거
- **지표(RSI/MACD/OBV) 반전 확인 함수 호출이 누락**
- 결과: 사장님 사상 "조정 후 진입"이 아니라 **"하락 중 물타기"**가 되어 손실 확대
- PENGU는 4H 볼밴 중단 이탈 후 지속 하락 국면 → 마틴게일 진입 = **추세 역행**

### 8.3 해결 (Fix 55 배포 완료)

- `stage_trigger_worker.py`의 `_trigger_next_stage` 함수에 **`_check_stage_indicator_reversal` 호출 강제 삽입**
- 지표 반전 미확인 시 `STAGE_PENDING` 상태로 대기 (진입 X)
- 배포 완료: 2026-08-24

### 8.4 재발 방지 (Fix 56~60 시스템)

| Fix | 조치 | 상태 |
| :---: | --- | :---: |
| **Fix 55** | stage_trigger_worker 지표 검증 강제 | ✅ 배포 완료 |
| **Fix 56** | 통합 spec (본 문서) + `services/martingale_gate.py` 공용 게이트 | 🟡 문서화 완료, 코드 통합 예정 |
| **Fix 57** | `martingale_gate_validator_worker` 신설 (매 10분 감사) | ⏳ 예정 |
| **Fix 58** | 단위 테스트 `test_martingale_stage_entry.py` 필수 케이스 12건 | ⏳ 예정 |
| **Fix 59** | `spec_audit_worker`에 `SPEC_RULES_MARTINGALE` 등록 (FORBIDDEN/REQUIRED) | ⏳ 예정 |
| **Fix 60** | 텔레그램 CRITICAL 알림 + Sentry 태그 `martingale_gate_bypass` | ⏳ 예정 |

---

## 9. 로그 스키마 (감사·학습용)

마틴게일 진입 시 아래 필드를 **강제 저장** (learning_records + 로그 파일).

```json
{
  "event": "martingale_stage_entry",
  "symbol": "PENGUUSDT",
  "side": "SHORT",
  "stage": 2,
  "entry_avg_price": "0.02451",
  "current_price": "0.02328",
  "price_drop_pct": -5.02,
  "capital_usdt": 600,
  "indicator_check": {
    "rsi_15m": 62.3,
    "rsi_reversed": true,
    "macd_hist_15m": -0.00012,
    "macd_reversed": true,
    "obv_slope_15m": -1234.5,
    "obv_reversed": false,
    "reversed_count": 2,
    "required_count": 2
  },
  "timeframe_1h_confirmed": null,
  "timeframe_4h_confirmed": null,
  "divergence_detected": null,
  "gate_result": "ALLOWED",
  "gate_reason": "2/3 reversed (RSI+MACD) meets stage=2 threshold",
  "worker": "stage_trigger_worker",
  "spec_version": "MARTINGALE_STAGE_ENTRY_SPEC_v2"
}
```

---

## 10. 롤아웃·롤백 절차

### 10.1 배포 순서 (Fix 56)

1. `services/martingale_gate.py` 신설 (공용 게이트 함수)
2. `workers/stage_trigger_worker.py` → 공용 게이트 호출로 리팩터
3. `workers/peak_break_reversal_worker.py` → 공용 게이트 호출로 리팩터
4. `workers/realtime_reentry_worker.py` → 공용 게이트 호출로 리팩터
5. `workers/success_pyramiding_worker.py` → 공용 게이트 호출로 리팩터
6. 단위 테스트 12건 통과 확인
7. `martingale_gate_validator_worker` 배포 (감사 워커)
8. VPS 배포: `git pull && docker compose restart api scheduler`
9. 24h 관찰 (마틴게일 진입 로그 감사 카운트 일치 확인)

### 10.2 롤백 트리거

- 24h 내 `gate_bypass` 이벤트 1건 이상 발견 시 즉시 롤백
- `martingale_gate.py` 호출 실패로 원 진입 워커(1단계)까지 영향 시 즉시 롤백
- 사장님 UI에서 "정상 진입인데 차단됨" 검증 실패 3건 이상 시 롤백

---

## 11. 사장님 검증 체크리스트 (Fix 56 배포 후)

- [ ] 배포 후 24h 내 마틴게일 2단계 진입 발생 시 로그에 `indicator_check` 필드 존재 확인
- [ ] 3단계 진입 발생 시 `timeframe_1h_confirmed=true` 확인
- [ ] 4단계 진입 발생 시 `timeframe_4h_confirmed=true` + `divergence_detected=true` 확인
- [ ] PENGUUSDT 유사 케이스(하락 지속 국면) 발생 시 **진입 차단** 확인
- [ ] 텔레그램 알림에 `[Martingale Gate]` 태그 정상 수신 확인
- [ ] `martingale_gate_validator_worker` 매 10분 실행 로그 확인

---

## 12. 관련 문서 (교차 참조)

| 문서 | 관계 |
| --- | --- |
| `SAJANGNIM_PROVEN_STRATEGY_v219.md` | 1단계 원 진입 전략 (본 spec 범위 밖) |
| `SAJANGNIM_TRADING_PHILOSOPHY_v219.md` | 사장님 6대 사상 (본 spec의 상위 헌법) |
| `UNIFIED_15M_ENTRY_SPEC_v224.md` | 15m 진입 사양 (본 spec 시간대와 정합) |
| `MULTI_TIMEFRAME_ENTRY_SPEC_v222.md` | 다중 시간대 사양 (본 spec 3.1과 정합) |
| `AUTO_RETRY_AFTER_LIQUIDATION_SPEC_v131.md` | 청산 후 재진입 (realtime_reentry_worker 관련) |
| `CHART_REENTRY_STRATEGY_SPEC.md` | OBV 재매집 (본 spec 지표 검증과 정합) |

---

## 13. 변경 이력

| 버전 | 날짜 | 작성자 | 변경 사항 |
| :---: | :---: | --- | --- |
| v1 | 2026-08-24 (오전) | Fix 55 대응 | stage_trigger_worker 지표 검증 강제 (단일 워커) |
| **v2** | **2026-08-24 (오후)** | **Fix 56 통합** | **4개 워커 공용 게이트 통합 + 다중 시간대 매트릭스 + PENGUUSDT 사고 반영** |

---

## 부록 A. 사장님 verbatim 원문 재수록

```
사장님 verbatim #1:
"충분히 상승/하락 반복 후 조정 시점에 2단계 진입 → 3단계까지 실패는 말이 안돼!"

사장님 verbatim #2:
"OBV MACD RSI 등등 특히 OBV와 MACD 보조차트를 분석해서 진입시점"

사장님 verbatim #3:
"15분 차트 기준과 1시간 4시간을 참고해서 진입시점"

사장님 verbatim #4 (v219):
"3단계까지 갈 수 있다야 가능하면 가지 않는 관리가 필요"

사장님 verbatim #5 (v219):
"자본 관리: 전체 자산 무관! 초기 금액만!"
```

---

**본 spec의 위반은 사장님 사상 위반과 동치이며,
`spec_audit_worker` + `martingale_gate_validator_worker` + CI 단위 테스트 3중 방어선으로 자동 차단됩니다.**

**End of MARTINGALE_STAGE_ENTRY_SPEC v2**
