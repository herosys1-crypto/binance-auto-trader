# MULTI-TIMEFRAME ENTRY SPEC v222

> **작성일**: 2026-08-23
> **작성자**: 오케스트라 에이전트 (사장님 사상 반영!)
> **헌법**: v222 = 다중 시간대 통합 진입 판정
> **선행 spec**: v219 (7중 정점 SHORT) / v220 (크기 무관 최고점 반전!)

---

## 1. 사장님 verbatim (2026-08-22 세션 요약!)

> "급등하는 심볼 4시간봉 최상단 볼밴 최상단밖 obv 최고점 macd rsi cci 모든 지표가 최고점일때 포지션 진입 전체자산에 1-2% 진입"
> "급등락이 10 20 30 40 등등 상관없어 차트가 하락으로 시작할수 있는 타이핑에!"
> "3단계까지 갈수 있다야 가능하면 가지않는 관리가 필요"

**핵심**: 4H는 큰 그림, 15m/1h는 정확한 타이밍! **크기가 아니라 반전 시점 (= 여러 시간대 합의)!**

---

## 2. 시간대별 지표 매트릭스

| TF   | 역할        | 필수 지표                              | limit | 캐시 TTL |
|------|-------------|---------------------------------------|-------|----------|
| 4h   | 큰 그림     | BB, OBV, MACD, RSI, CCI (5개 = v219)  | 120   | 300s     |
| 1h   | 중간 확인   | OBV, RSI, MACD (3개)                  | 80    | 180s     |
| 15m  | 진입 트리거 | OBV, RSI, MACD (3개)                  | 60    | 60s      |

**공식 (SHORT 예시!)**:
- **4H peak reversal** = v219 7중 정점 (BB상단 + OBV/MACD/RSI/CCI 최고점 꺾임)
- **1H confirm** = RSI ≥65 + 꺾임, OBV 최근 2봉 하락, MACD 히스토그램 축소
- **15m trigger** = RSI < RSI[-1] (꺾임!) + OBV 최근 3봉 하락 + MACD 히스토그램 음전환

**LONG 대칭** (사장님 「하락으로 시작할수 있는 타이핑」의 반대!):
- **4H bottom reversal** = BB 하단 밖 + OBV/MACD/RSI/CCI 최저점 꺾임 (v-bottom!)
- **1H confirm** = RSI ≤35 + 꺾임 상승, OBV 최근 2봉 상승
- **15m trigger** = RSI > RSI[-1] + OBV 최근 3봉 상승 + MACD 히스토그램 양전환

---

## 3. 통합 점수 방식 (multi_tf_entry_score!)

```
score_4h  = compute_reversal_score(kl_4h, side)   # 0~5 (v219 5지표)
score_1h  = compute_reversal_score(kl_1h, side)   # 0~3
score_15m = compute_reversal_score(kl_15m, side)  # 0~3

# 가중 평균 (4H가 대장!)
weighted = (score_4h/5)*0.5 + (score_1h/3)*0.3 + (score_15m/3)*0.2

# 진입 판정!
if weighted >= 0.75 and score_4h >= 4:  # 4H 대장 최소 4/5
    confidence = 0.80 + (weighted - 0.75) * 0.6   # 0.80 ~ 0.95
    return {enter: True, confidence, breakdown: {...}}
```

**임계값 근거**:
- `weighted >= 0.75` = **3 TF 모두 반전 신호 = 합의 확보!**
- `score_4h >= 4` = 4H 큰 그림 필수! (15m/1h만 반전 = 노이즈!)
- **7중 (v219) 통과 시 자동 승격** = 4H 5/5 + 1H/15m 각 2/3 = weighted 0.83 = confidence 0.85+!

---

## 4. 자동 매매 흐름 (v222)

```
[매 5분 pump_top_detector v222]
    │
    ├─ USDT 60→40 심볼 pre-filter (거래대금 정렬 = 헌법 API 부담!)
    │
    ├─ SHORT 후보: 24h ≥ +5% (v220 완화 유지)
    ├─ LONG  후보: 24h ≤ -5% (신! 사장님 "하락으로 시작할수 있는 타이밍"!)
    │
    ├─ for symbol in candidates:
    │     kl_4h  = get_klines(4h, 120)  ← 캐시!
    │     kl_1h  = get_klines(1h, 80)   ← 신!
    │     kl_15m = get_klines(15m, 60)  ← 신!
    │
    │     result_short = multi_tf_entry_score(bc, symbol, "SHORT")
    │     result_long  = multi_tf_entry_score(bc, symbol, "LONG")
    │
    │     if result_short.enter and result_short.confidence >= 0.85:
    │         Redis SETEX "pump_top:alert:{sym}:SHORT" 1800  → v219 자동 진입!
    │     if result_long.enter and result_long.confidence >= 0.85:
    │         Redis SETEX "pump_top:alert:{sym}:LONG"  1800  → v222 신 자동 진입!
    │
    └─ 텔레그램 알림 + trade_learning_records 저장!

[매 30초 auto_short_at_top_worker (v222 확장!)]
    ├─ pump_top:alert:*:SHORT 스캔 → 300 USDT SHORT 진입
    └─ pump_top:alert:*:LONG  스캔 → 300 USDT LONG 진입 (신!)
```

---

## 5. 학습 데이터 저장 (헌법 v134!)

**entry_context (dict)에 박제!**:
```json
{
  "spec_version": "v222",
  "detection_source": "multi_tf_entry",
  "side": "SHORT|LONG",
  "weighted_score": 0.83,
  "score_4h": 5, "score_1h": 3, "score_15m": 2,
  "signals_4h": {"bb": true, "obv": true, "macd": true, "rsi": true, "cci": true},
  "signals_1h": {"obv": true, "rsi": true, "macd": true},
  "signals_15m": {"obv": true, "rsi": true, "macd": false},
  "change_24h": -8.3,
  "confidence": 0.87
}
```

**분석 지표** (learning_sync_worker!):
- `score_by_confluence` = 합의 등급 (A: 3TF/B: 2TF/C: 1TF) 대비 실 수익률!
- `false_signal_rate` = 진입 후 SL 도달률
- `optimal_weight` = 가중치 자동 튜닝 후보 (0.5/0.3/0.2 → 데이터 기반 조정!)

**진입 시 CDN 저장**: `TradeLearningService.on_entry(strategy_id, entry_context)`

---

## 6. 위험 방어 (헌법 v127 API 부담!)

| 항목                | 이전 (v219)   | 신 (v222)         | 이유                                    |
|---------------------|---------------|-------------------|-----------------------------------------|
| MAX_SYMBOLS         | 60            | **40**            | 3배 API 호출 = 심볼당 3 kline!          |
| kline call/symbol   | 1 (4h)        | 3 (4h+1h+15m)     | -                                       |
| 총 API/실행         | ~60           | ~120 (40×3)       | Ban 여유 (분당 2400 weight의 5%!)      |
| 캐시 TTL            | 없음          | 4h:300s/1h:180s/15m:60s | 인접 실행 재사용                    |
| API Ban 체크        | 있음          | 유지 (is_account_banned!) | fail-safe                           |
| MIN_24H_CHANGE      | 5.0           | **abs(chg)≥5**    | SHORT: chg≥+5 / LONG: chg≤-5           |
| MIN_CONFIDENCE      | 0.85          | 0.85 (유지)       | 남발 차단!                              |

**캐시 구현**: Redis key = `kline_cache:{symbol}:{interval}` = json list. 신 함수 `_cached_klines()`로 가드!

**실행 주기 확인**: pump_top_detector = 5분 (변경 X!). 40 심볼 × 3 kline = ~120 call = 5분당 = **분당 24 call = Ban 안전!**

---

## 7. 롤백 계획

- **BREAKING X**: 신 v222는 기존 v219 SHORT 로직 유지 + LONG 추가 + 1h/15m 확인!
- 실패 시 `MULTI_TF_ENABLED = False` (env / config) → 즉시 v219 순수 로직 fallback.
- 신 워커/함수 = 완전 격리 (chart_analyzer 확장 = 기존 OBV 함수 무손상!).

---

## 8. 헌법 v222

> "4H는 큰 그림, 15m/1h는 정확한 타이밍! 3 시간대 합의 없이는 진입 X = silent bug 차단!"
