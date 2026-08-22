# 🌟 사장님 실 성공 로직 spec v219 (2026-08-22)

> **목적**: 사장님이 실제 수동 매매로 성공했던 「정점 SHORT + 마틴게일 자본」 로직을 시스템으로 완전 이식한다. 인간 한계(24/7 관찰 불가, 감정, 성급함)를 자동화로 방어한다.
>
> **범위**: `SAJANGNIM_TRADING_PHILOSOPHY_v219.md`(사상·현황 문서)와 짝. 이 문서는 **구현 spec**(진입 조건, 자본 룰, 워커 계약)만 다룬다.

---

## 1. 사장님 verbatim (2026-08-22)

> "정점 진입 = 4H BB 최상단 밖 + OBV/MACD/RSI/CCI 모두 최고점 = 7중 확인!
> 자본 = 전체 자산 1~2% (초기) → 하락 시작 신호 시 2배 → 계속 하락 시 증거금 유지 → OBV 강하게 하락 재확인 시 다시 2배!
> 분할 익절은 빠르게. 인간은 24/7 관찰 못 하고, 시점 못 기다리고, 청산 후 무리하게 늘려서 실패한다. 시스템으로 방어해!"

---

## 2. 7중 정점 감지 (SHORT 진입 조건)

**AND 조건 — 하나라도 실패 = 진입 X.**

| # | 지표 | 조건 | 근거 코드/파일 |
|---|------|------|----------------|
| 1 | 4H BB 최상단 밖 | `close > upper_band` (완료봉 종가) | `bb_4h_band_analyzer.py::state` (헌법 v127: 진행 중 봉 신뢰 X) |
| 2 | OBV 최고점 | `obv[-1] == max(obv[-N:])`, N=20 | `chart_analyzer.py::compute_obv` |
| 3 | MACD 최고점 | `macd_hist[-1] == max(hist[-N:])` AND 직전 봉 대비 감소 시작 | `bb_4h_band_analyzer._macd_bearish` 확장 필요 |
| 4 | RSI 최고점 | `rsi[-1] >= 70` AND `rsi[-1] < rsi[-2]` (꺾임 시작) | `bb_4h_band_analyzer._calc_rsi` |
| 5 | CCI 최고점 | `cci[-1] >= 200` AND `cci[-1] < cci[-2]` | **신규**: `chart_analyzer.compute_cci` 추가 필요 |
| 6 | 모든 지표 동시 = 최고점 | 위 2~5 모두 상위 5% 구간(직전 20봉 기준) | `pump_top_detector_worker` 판정 |
| 7 | 급등 후 정점 | 24h `priceChangePercent >= +15%` AND 최근 4h 봉 `high >= max(recent 20 highs)` | ticker + kline |

**신뢰도 = 7건 통과 = confidence 0.90+ (auto 진입 임계값 0.85 이상).**

---

## 3. 자본 관리 (마틴게일 사장님 룰)

**총자산 = Binance `/fapi/v2/account.totalWalletBalance` (모든 계정 합산).**

| 단계 | capital (margin) | 조건 | 수량 계산 |
|------|-----------------|------|-----------|
| 1 | 총자산 × 1~2% (시스템 설정) | 7중 정점 감지 즉시 | `qty = capital × leverage / mark_price` |
| 2 | 1단계 × 2 | 진입가 대비 -3% AND OBV 하락 신호 | 사장님 사상 v208 마틴게일과 동일(1.5x→2.0x로 조정) |
| 증거금 유지 | 추가 X | 계속 하락 중 (2단계~3단계 사이) | 청산가만 뒤로 밀기 (`add_position_margin`) |
| 3 | 2단계 × 2 | OBV 강하게 재하락(4H OBV 신저점) AND -8% 이상 | 최종 단계 |
| 분할 익절 | 5%/10%/15% | 각 도달 시 30% / 30% / 40% 청산 | 기존 `TP1_PCT_DEFAULT` + `TP2`/`TP3` 활용 |

**하드 리미트 (사장님 실패 방어)**:
- 최대 3단계 (**절대 4단계 금지** — v139 백테스트: 9단계+ 8건 손실 43%)
- 총 노출 = 총자산 × 7% (1 + 2 + 4 = 7% max)
- 평단 대비 -15% 도달 = 강제 SL (헌법 v147 `force_sl_loss_limit` 활용)

---

## 4. 헌법 64 재해석 (예외 명문화)

**기존 헌법 64 (2026-08-21)**: 24h ±15% = 반대매매 금지 (BOMEUSDT/ONGUSDT -849 USDT 사고 방지).

**신규 헌법 68 (제안, 예외)**:
> **「7중 정점 확인 SHORT」는 헌법 64의 예외다.** 급등 즉시 SHORT는 여전히 금지(급등 중 무한 물타기 위험). 단 4H BB 최상단 밖 + OBV/MACD/RSI/CCI 4개 지표 모두 꺾임 확인 = 「정점 확인」 = SHORT 허용.

**차이**:
| 케이스 | 헌법 64 | 헌법 68 |
|--------|---------|---------|
| BOMEUSDT +35% 급등 중 SHORT | 🚫 금지 (물타기 폭발) | 🚫 금지 (지표 꺾임 미확인) |
| 급등 후 4h BB 상단 벗어남 + OBV/MACD/RSI/CCI 모두 최고점 꺾임 | 🚫 금지 | ✅ 허용 (신뢰도 0.90+) |

**구현**: `auto_bb_breakdown_worker`의 급등 필터에 「7중 조건 통과 시 bypass」 예외 추가.

---

## 5. 신 워커 설계

### A. `pump_top_detector_worker.py` (신)
- 주기: **5분** (`scheduler_runner.py`에 등록)
- 대상: 24h 거래대금 상위 100 심볼 (`bb_4h_scanner._top_symbols` 재사용)
- 로직:
  1. 각 심볼 4H kline 120봉 로드
  2. `PumpTopDetector.check_7_signals(kl, ticker)` = 7중 판정
  3. 통과 시 Redis 저장: `pump_top:alert:{symbol}` (TTL 30분) + JSON 상세
  4. 텔레그램 알림 (신뢰도 0.90+ 만)

### B. `auto_short_at_top_worker.py` (신)
- 주기: **30초**
- 로직:
  1. Redis `pump_top:alert:*` 스캔
  2. 이미 활성 심볼 skip
  3. `daily_limit` 확인 (기존 `auto_bb_break_daily_limit` 재사용, **별도 카운터**: `auto_short_top_daily_count`)
  4. 자본 계산: `total_wallet × 0.01` (설정 값, 1~2%)
  5. 사장님 default template + strategy 자동 생성 (`_create_auto_bb_strategy` 재사용, `entry_reason="pump_top_v219"`)
  6. 진입 후 Redis 알람 삭제

### C. 마틴게일 자동화 = 기존 `realtime_reentry_worker.py` 확장
- 현행: 1.5x/2.25x (v202) → **옵션 추가**: `martingale_mode="sajangnim_v219"` 시 2.0x/2.0x
- 트리거 재정의: 진입가 대비 -3% AND `chart_analyzer.check_4h_first_bear_bar` (OBV 하락 재확인)

### D. 분할 익절 = 기존 TP1/TP2/TP3 시스템 그대로
- template: `tp1_pct=5, tp1_close_pct=30, tp2_pct=10, tp2_close_pct=30, tp3_pct=15, tp3_close_pct=40`

---

## 6. 자본 1~2% 계산 로직 (실 코드)

```python
# backend/app/services/sajangnim_capital.py (신)
from decimal import Decimal
from app.integrations.binance.client import BinanceClient

DEFAULT_ENTRY_PCT = Decimal("0.01")  # 사장님 default = 1%
MAX_ENTRY_PCT = Decimal("0.02")      # 상한 = 2%

def compute_stage1_capital(bc: BinanceClient, entry_pct: Decimal = DEFAULT_ENTRY_PCT) -> Decimal:
    """총자산 대비 1~2% 자본 계산 (마진 기준, USDT)."""
    if entry_pct > MAX_ENTRY_PCT:
        entry_pct = MAX_ENTRY_PCT
    acct = bc.get_account()
    total = Decimal(str(acct.get("totalWalletBalance") or "0"))
    avail = Decimal(str(acct.get("availableBalance") or "0"))
    # 안전: min(총자산%, 가용잔액×0.8)
    capital_by_total = total * entry_pct
    capital_by_avail = avail * Decimal("0.8")
    return min(capital_by_total, capital_by_avail).quantize(Decimal("0.01"))
```

**정확 vs 근사**: 정확 (Binance API 실시간). Multi-account = 계정별 합산은 `exchange_accounts.py::_wallet_total` 로직 재사용.

---

## 7. 구현 우선순위 (사장님 결정 요청)

| 옵션 | 범위 | 예상 세션 | 위험도 |
|------|------|-----------|--------|
| A | spec만 (본 문서) | 완료 | 0 |
| **B ⭐추천** | A + `pump_top_detector_worker` 만 (알람+텔레그램, 자동 진입 X) | 반나절 | 낮음 (알람만 = 사장님 눈으로 검증) |
| C | B + `auto_short_at_top_worker` (자동 진입, daily_limit=1로 시작) | 1일 | 중간 (실 자금, 소액 검증) |
| D | C + 마틴게일 확장 + 헌법 68 승격 | 2~3일 | 높음 (전체 자동화) |

**추천 근거**: 사장님 실 성공 로직 = 눈으로 정점 판단. 자동 감지 정확도를 **B 단계에서 알람만으로 최소 1주 관찰** → 실 매매 성공률 확인 → C로 승격. v186~v207 배포 사이클과 동일 패턴.

---

## 8. 검증 체크리스트 (배포 전)

- [ ] `PumpTopDetector` 단위 테스트 (BOMEUSDT 2026-08-21 데이터 = 정점 감지되어야)
- [ ] 백테스트: 최근 6개월 4H 캔들 × 178심볼 = 신호 개수 / 실 도달률 (`scripts/study_pump_top_v219.py` 신규)
- [ ] 헌법 68 문서 (`DEVELOPMENT_PRINCIPLES.md`)에 예외 명문화
- [ ] Redis key 스키마 등록 (`docs/REDIS_KEY_SCHEMA.md`)
- [ ] 텔레그램 알람 포맷 예시 사장님 확인
- [ ] daily_limit 설정 UI 추가 (system_settings)

---

**연관 문서**: `SAJANGNIM_TRADING_PHILOSOPHY_v219.md` (사상), `SAJANGNIM_CAPITAL_SPEC_2026-07-18.md` (자본), `BB_4H_BAND_STRATEGY_SPEC.md` (BB 실측), `DEVELOPMENT_PRINCIPLES.md` (헌법).
