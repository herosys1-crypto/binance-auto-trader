# 🌟 사장님 매매 사상 v219 (2026-08-22)

> **목적**: 사장님이 말씀하신 6대 매매 사상을 코드·워커·spec 관점에서 명확히 문서화하고, 현재 시스템 반영 현황과 충돌 지점, 안전 필터, 구현 우선순위를 한 문서에 정리한다.
>
> **원칙**: 사장님 사상을 최우선으로 하되, 실측(과거 캔들 검증)과 충돌하는 지점은 숨기지 않고 그대로 노출한다. 사장님이 결정한다.

---

## 1. 사장님 6대 원칙 (사장님 verbatim)

| # | 원칙 | 핵심 매매 방향 |
|---|------|----------------|
| 1 | 급등 심볼 = 단기/중기/장기 반드시 하락 | **SHORT 기회** |
| 2 | 급등-조정-재급등 반복 = 결국 단/중/장기 하락 | **SHORT 재도전** |
| 3 | 급등 초기 LONG = 큰 수익 (예측은 어려움) | **초기 LONG** (조건부) |
| 4 | 급등 중 BB중단/하단 지지 → 재급등 = 결국 하락 | **SHORT 우대** |
| 5 | BB 상/중/하단 = 조정 or 돌파 = 큰 시세 | **양방향 (돌파)** |
| 6 | OBV = 세력 움직임 (상승/조정/하락 대부분 파악) | **OBV = 방향 판단 핵심** |

**핵심 요약**: SHORT 우선 사상 + BB/OBV 결합 = 급등 정점 SHORT + 급락 저점 LONG(짧게).

---

## 2. 현재 시스템 반영 현황

### ✅ 반영된 부분

| 원칙 | 반영 코드 | 반영 방식 |
|------|-----------|-----------|
| 5 (BB 3단) | `backend/app/services/bb_4h_band_analyzer.py` + `backend/app/agents/strategy_suggestion_team/bb_4h_scanner.py` | 4H BB 4트리거(중단↓SHORT / 중단↑LONG / 하단이탈SHORT / 상단돌파LONG) = **롱숏 대칭 실측 기반** (215,561 캔들, 헌법 v143) |
| 6 (OBV) | `backend/app/services/chart_analyzer.py::compute_obv` + `backend/app/workers/auto_bb_breakdown_worker.py::OBV_REVERSE` 통합 (라인 286~379, `_apply_obv_hold_settings` 라인 1241~1267) | 4H OBV 첫 하락 봉 + 15m/1h OBV 하락 = 「OBV 재진입 신호」 자동 진입 (v130 + v207) |
| 3 (급등 초기 LONG) | `backend/app/services/pump_dump_live_analyzer.py` (v141) | 5m/15m 20% 급등 = 추격 LONG (실측 EV+0.32~0.76%, 표본 185~782건) |
| 4 (지지 알람) | `backend/app/workers/pump_bb_middle_watcher.py` (v131) | 급등 top50 → BB중단 근접 알람 (⚠️ 실측상 BB중단은 지지선 X, 68% 뚫고 마감 — 파일 헤더에 명시) |

### ⚠️ 부분 반영 / 충돌 지점

| 원칙 | 충돌 대상 | 현황 |
|------|-----------|------|
| **1, 2 (급등 SHORT)** | 헌법 64 (2026-08-21) = 「24h ±15% = 반대매매 금지」 | `auto_bb_breakdown_worker`가 급등 심볼 SHORT를 **필터로 차단**. BOMEUSDT/ONGUSDT/HEMIUSDT -849 USDT 사고 반성. **사장님 사상 1과 정면 충돌.** |
| **1 (급등 SHORT)** | v141 실측 = 급등 → 추격 LONG이 유리 (양의 EV 54셀 중 37개가 LONG) | 「급등 초입」에서는 LONG이 유리, 「급등 정점 후」에서는 SHORT가 유리 = **타이밍 구분 필수** |
| **2 (조정 반복)** | 명시 코드 없음 | v144 실측 = 20%+ 급등 후 3% 되돌림 SHORT = EV+0.66~0.86% (373건, 2h 창) — 있으나 미배포 |
| **4 (BB중단 지지 반등)** | v143 실측 = BB 밴드 도달 후 68%가 뚫고 마감 (지지선 X) | 사장님 사상 4의 「지지 후 재급등」은 확률적으로 소수 케이스 (18%). 「결국 하락」 결론은 실측과 일치. |

### ❌ 미반영

- 원칙 2 (급등-조정-재급등 반복 SHORT 재도전) 전용 워커 없음
- OBV 다이버전스(가격↑ OBV↓) 감지 워커 없음 (`chart_analyzer`는 단순 방향만 판정)

---

## 3. 신 매매 spec (spec = single source of truth)

### A. SHORT 우선 진입 조건 (원칙 1 + 2 + 4 결합)

**타이밍 축**: 급등 지속 시간 + 지표 반전.

```
[전제 필터]
  - 24h 상승률 ≥ +15% (급등 심볼)
  - 15m 최근 3봉 = 상승 지속 후 조정 시작 (최고봉 대비 -3% 되돌림)
  - OR 4H BB 중단 하향 이탈 (BB4HScanner MID_DOWN 트리거)
  - OR 4H OBV 첫 하락 봉 (chart_analyzer.detect_4h_obv_first_bearish)

[SHORT 진입 조건 = ANY 2 이상 매치]
  1. 15m 20%+ 급등 후 2시간 창에서 3% 되돌림 (v144 실측 EV+0.66~0.86%)
  2. 4H BB 상단 도달 + 다음 봉 음봉 (반전)
  3. OBV 다이버전스 (가격 신고점, OBV 신고점 실패)
  4. RSI 15m 70+ 후 60 이탈 (과매수 회귀)

[SHORT SL/TP]
  - SL = -5% (v143 실측 최적)
  - TP = -10% (급등폭의 절반 회귀 목표)
  - 트레일링: -20% peak 도달 후 -15% 회귀 (사장님 default)
```

### B. LONG 진입 (원칙 3 = 급등 초기)

```
[전제 필터]
  - OBV 급상승 (최근 3봉 슬로프 +10%p 이상)
  - 거래량 최근 3봉 평균의 4배 이상 (v146 「지속」 시나리오)
  - BB 하단 근접 반등 (터치 후 종가 하단 위 마감)

[LONG SL/TP]
  - SL = -3% (짧게, v146 지침)
  - TP = +5% (짧게, 지속 LONG)
  - 최대 3단계 (사장님 지시, v146)
```

### C. BB 3단 대응 (원칙 5 = 기존 BB4HScanner 유지)

이미 완성된 4 트리거 시스템 유지 + confidence 실측값 그대로:

| 트리거 | 방향 | SL | TP | EV(실측) | 표본 |
|--------|------|-----|----|---------:|------:|
| 4H 중단 하향 이탈 | SHORT | -5% | 하단(동적) | +0.42% | 13,053 |
| 4H 중단 상향 돌파 | LONG | -5% | 상단(동적) | +0.44% | 13,045 |
| 4H 하단 이탈 | SHORT | -5% | +5% | +0.14% | 5,286 |
| 4H 상단 돌파 | LONG | -5% | +8% | +0.27% | 5,802 |

### D. OBV 활용 (원칙 6)

- **OBV 급상승 + 거래량 폭증** → LONG 우대 시그널 (원칙 3)
- **OBV 하락 지속** → SHORT 우대 시그널 (원칙 1)
- **OBV 다이버전스** → 반전 시그널 (급등 정점 SHORT, 급락 저점 LONG)
- 기존 `_apply_obv_hold_settings` = OBV 소스 = 강제 SL 비활성 + 3단계 물타기 = 「청산까지 버티기」 (사장님 2026-08-21 결정) 유지

---

## 4. 안전 필터: 급등 초입 vs 정점 구분

**핵심 문제**: 원칙 1 (급등 SHORT)과 원칙 3 (급등 초기 LONG)이 동시에 참일 수는 없다. **타이밍이 구분**한다.

| 국면 | 판정 조건 | 방향 |
|------|-----------|------|
| 급등 초입 (0~1시간) | 15m +3~10%, OBV 급상승, 거래량 4배+ | **LONG (짧게)** |
| 급등 정점 (지속 3시간+) | 4H 최고봉 대비 3% 이상 되돌림, OBV 반전, RSI 70→60 하락 | **SHORT (우세)** |
| 급락 국면 | 15m -15%+ | **관여 X** (v141 실측: 급락은 양방향 모두 EV≒0) |
| 24h ±15% 이내 정상장 | BB 4트리거만 사용 | 기존 유지 |

**헌법 64 재해석 제안**: 「24h ±15%에서 즉시 반대매매 금지」 → 「급등 초입 반대매매 금지, 정점 반전 확인 후 SHORT는 허용」. 사장님 최종 결정 사항.

---

## 5. 구현 우선순위

### 🔥 즉시 (사장님 승인 후, 이번 세션 or 다음 세션 초반)

1. **spec 문서 커밋** (이 문서!) → single source of truth 확립
2. **`auto_bb_breakdown_worker` 확장**: v144 실측 「20%+ 급등 후 3% 되돌림 SHORT」 소스를 OBV_REVERSE와 동일 방식으로 통합 (신 워커 X, 기존 강화)
   - `SystemSetting`: `auto_pump_short_enabled`, `auto_pump_short_daily_limit` (default 0 = OFF)
   - source="PUMP_REVERSAL_SHORT", success_probability 반영
3. **헌법 64 결정**: 사장님 최종 판단 = 급등 SHORT 완화 or 유지?

### ⏳ 다음 세션

4. **`obv_divergence_worker.py`** (신 워커): 가격 신고점 vs OBV 신고점 실패 감지 → 알람 (자동 진입 X, 수동 확인 소스)
5. **UI 배지**: 「🚀 급등 정점 SHORT 후보」 대시보드 카드 추가
6. **`pump_short_predictor.py`** (신 워커): 완전 자동 진입 (사장님 실 성과 확인 후)

### 🚫 지금 하지 않는 것 (v208~v216 롤백 교훈)

- 사장님 명시 요구 없는 신 워커 대량 생성 금지
- 헌법 64를 사장님 결정 없이 임의 변경 금지
- 신 default profile 변경 금지 (실 자금 영향)

---

## 6. 헌법 v219 (신)

- **v219-1**: 사장님 6대 원칙 = spec 우선. 실측과 충돌하면 사장님이 결정한다 (숨기지 않는다).
- **v219-2**: 급등 SHORT는 「초입 vs 정점」 타이밍 분리. 초입은 LONG(원칙 3), 정점은 SHORT(원칙 1).
- **v219-3**: OBV 다이버전스는 반전 시그널. 단일 지표 아닌 조합(BB + OBV + RSI)만 유효 (v146 실측 = 단일은 최대 1.18배, 조합은 8.7배).
- **v219-4**: 실측 EV는 왕복 수수료·슬리피지 전 값이다. UI에 반드시 함께 표시.
- **v219-5**: 자동 진입은 사장님 명시 승인 SystemSetting 값이 있을 때만 (default OFF).

---

## 부록: 코드 인덱스

- `backend/app/services/bb_4h_band_analyzer.py` — 4H BB 4트리거 실측
- `backend/app/services/pump_dump_live_analyzer.py` — 5m/15m 급등락 20%
- `backend/app/services/chart_analyzer.py` — OBV compute + 반전 신호
- `backend/app/agents/strategy_suggestion_team/bb_4h_scanner.py` — 자동 제안 소스
- `backend/app/workers/auto_bb_breakdown_worker.py` — 자동 진입 워커 + OBV_REVERSE 통합
- `backend/app/workers/pattern_learning_worker.py` — 성공/실패 학습
- `backend/app/workers/pump_bb_middle_watcher.py` — 급등+BB중단 알람
- `docs/BB_4H_BAND_STRATEGY_SPEC.md` — BB4H 실측 상세
- `docs/PUMP_DUMP_LIVE_STRATEGY_SPEC.md` — 급등락 실측 상세
