"""🎯 사장님 사상 (2026-08-21): 실시간 재진입 시스템!

사장님 verbatim:
"포지션 실패한 심볼은 실시간 모니터링에 넣어서 짧은 시간 계속 모니터링하고
재진입을 하는 로직이야
그리고 익절도 마찬가지로 익절후 계속 모니터링하고 계속 수익이 가능하면
다시 포지션을 늘려서 수익을 극대화하고 다시 하락하면 -5% 상승후 하락시
진행하는 로직으로 청산하는거야"

= 매 15분 실행!
= 실패 심볼 + 익절 심볼 = 실시간 감지!
= 조건 만족 시 = 즉시 재진입!

로직:
1. daily_limit 체크 (auto_bb_break_daily_limit!)
2. 최근 24h 청산된 자동 진입 심볼 조회!
3. Redis mark_price로 현재가 조회!
4. 재진입 조건 판단:
   - 실패 심볼: SL 대비 +3% 반등 시 재진입 (1.5x)!
   - 익절 심볼: 익절가 대비 +3% 추가 상승 시 재진입 (원 자본)!
5. 조건 만족 = _create_auto_bb_strategy 호출 (즉시!)!
6. 재진입 카운터 갱신!

안전:
- max 2회 재진입 (v202!)
- 급등/급락 필터 (헌법 64!)
- daily_limit 체크!
- 이미 활성 심볼 skip!
- 24h 재진입 카운터 5회 초과 = skip!
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE, TERMINAL_STATUSES
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate

logger = logging.getLogger(__name__)

# 🎯 v221 사장님 재설계 (2026-08-23): 지표 반전 = MAIN gate!
# 사장님 verbatim: "차트와 보조지표가 다시 롱이나 숏으로 진행할수 있는 지표가 필요"
# = 반등 % 는 최소 안전선만! (0.5%!) → 지표 반전 = 진짜 조건!
#
# 🎯 Fix 99 정밀 강화 (2026-08-25!):
# 사장님 verbatim: "손절후 이익이 더 많은 이익이 가능해" = 재진입 시점만 정확하면 큰 수익!
# → 반등 % 상향 (0.5% → 1.5%!) = 노이즈 대신 진짜 반전!
#
# 🎯 Fix 102 완화 + 정밀 (2026-08-26!):
# 사장님 verbatim: "손절후 2단계 진입이 없는것 같이 이것도 보조지표를 최대한 활용해"
# → Fix 99 = 너무 엄격 = 진입 X! → 완화 + 다이버전스/BB 위치 정밀 활용!
REBOUND_PCT_MIN_SAFETY = 1.0    # 🎯 Fix 102 C: 1.5 → 1.0 (완화! 진입 가능성 확보!)
MAX_HOURLY_REENTRIES = 5        # 1h 최대 5건 (남발 방지!)
STAGE3_MIN_WAIT_HOURS = 4.0     # 3단계 = 충분히 대기!
MIN_LEARNING_SUCCESS_RATE = 0.30  # 학습 성공률 30%+ 심볼만!

# 🎯 Fix 99 E → Fix 102 C 완화 (2026-08-26): 손절 후 최소 대기 (whipsaw 방지!)
# 5분 → 3분 (완화!) = 급변동 whipsaw 방지 유지하되 실행 가능성 회복!
MIN_STOP_WAIT_MINUTES = 3.0     # 🎯 Fix 102 C: 5.0 → 3.0 (완화!)

# 🎯 Fix 99 C → Fix 102 C 완화 (2026-08-26): 볼륨 반전 확인 = 진짜 세력!
# 반등 볼륨 = 이전 3봉 평균 × 1.3+ → 이중 볼륨 확인 (OBV+VOL) 중복 완화!
VOLUME_REVERSAL_MULTIPLIER = 1.3  # 🎯 Fix 102 C: 1.5 → 1.3 (완화!)

# 🎯 Fix 53 사장님 신 사상 (2026-08-24!):
# 사장님 verbatim: "최종 단계까지 진행했는데 손실이면 -5%에서 다시 모니터링 대기하고
#                  최종단계 진입금액으로 한번더 하고 안되면 종료하는 로직으로 해줘"
# = 3단계 (1800 USDT) SL 발동 후 = 라스트 챈스 1회 (동일 자본 1800!)
# = 라스트 챈스도 SL = 완전 종료 (더 이상 재진입 X!)
# 최소 침습: 기존 v219 로직 유지 + stage 4 = 라스트 챈스만 추가!
ENABLE_LAST_CHANCE = True
MAX_REENTRY_STAGE_WITH_LAST = 4  # 3단계 + 라스트 챈스 1회!

# 🎯 Fix 99 A → Fix 102 A 완화 (2026-08-26): 5중 → 8중 (5 core + 3 bonus)
# 사장님 verbatim: "손절후 2단계 진입이 없는것 같이 이것도 보조지표를 최대한 활용해"
# → 5중 3/4/5 = 너무 엄격 = 실 진입 X! → 8중 통과 조건 확장 + 임계 완화!
#
# 5 core (15m): RSI, MACD, OBV, CCI, VOLUME (기존!)
# 3 bonus (Fix 102 B/D): 4H MACD 동조 (soft!) + 다이버전스 + BB 위치!
# → 2단계 = 2/8 (완화!) / 3단계 = 3/8 / 라스트 = 4/8 (라스트 챈스 실 작동!)
MIN_PASSED_STAGE2 = 2         # 🎯 Fix 102 A: 3 → 2 (완화! 첫 재진입 = 진입 가능성!)
MIN_PASSED_STAGE3 = 3         # 🎯 Fix 102 A: 4 → 3 (완화!)
MIN_PASSED_STAGE_LAST = 4     # 🎯 Fix 102 A: 5 → 4 (라스트 챈스 실 작동!)
STAGE3_24H_ABS_LIMIT_PCT = 15.0  # 3단계+ = 24h 변동 ±15% 초과 시 반대매매 skip!

# 🎯 Fix 102 D (2026-08-26): 다이버전스 + BB 위치 정밀 gate 파라미터!
DIVERGENCE_LOOKBACK = 10          # 최근 10봉 extreme 탐색!
DIVERGENCE_RSI_GAP = 3.0          # 다이버전스 인정 = RSI 3+ 차이!
DIVERGENCE_PRICE_TOL_PCT = 1.0    # extreme 대비 1% 이내 = "근접"!
BB_PERIOD = 20                    # BB(20, 2) 표준!
BB_STD = 2.0
BB_NEAR_BAND_PCT = 0.10           # 밴드 폭의 10% 이내 = "밴드 근접"!

# 🚨🚨 Fix 103 (2026-08-26): 재진입 = 「신규 진입」 아님! = 마틴게일 2단계!
# 사장님 verbatim: "손절후 2단계 진입이 없는것 같이 이것도 보조지표를 최대한 활용해"
#
# 근본 원인 (진단 결과):
#  (1) daily_limit = db.get("sajangnim_top_short_daily_limit") 직접 읽기
#      → row 없음/빈 값 = 0 = 무로그 즉시 return = 워커 전면 OFF! (미호출과 구별 불가!)
#      → auto_short_at_top/_auto_long_at_bottom 은 fallback 체인 사용 = 대칭 붕괴!
#  (2) remaining = daily_limit - _count_used_slots(db)
#      → _count_used_slots = 신규 진입 워커 3종 공유 카운터 (bb4h/top_short/bottom_long)
#      → 신규 진입이 하루 한도(20)를 채우면 = 재진입(마틴게일 2단계) 도 동반 차단!
#      → auto_bb_breakdown_worker.py:827 주석은 이미 "손절 재진입 = 별도 카운트!" 라고
#        선언했으나 코드는 공유 카운터를 그대로 사용 = 선언 ↔ 구현 불일치!
#
# Fix 103 C: 재진입 전용 한도 + 전용 카운터 (신규 진입 슬롯 완전 면제!)
#  - 카운터 = 오늘 RT_REENTRY suggestion 건수만! (신규 진입 무관!)
#  - 한도 = sajangnim_reentry_daily_limit (전용, 0 = 명시적 OFF 존중!)
#           → 없으면 sajangnim_top_short_daily_limit / auto_bb_break_daily_limit 값 참조
#           → 모두 없으면 DEFAULT (20) = row 누락으로 인한 silent OFF 영구 차단!
REENTRY_DAILY_LIMIT_DEFAULT = 20
REENTRY_DAILY_LIMIT_KEY = "sajangnim_reentry_daily_limit"   # 전용 키 (0 = 명시 OFF!)
REENTRY_DAILY_LIMIT_FALLBACK_KEYS = (
    "sajangnim_top_short_daily_limit",
    "auto_bb_break_daily_limit",
)


def _gate_spec() -> str:
    """🎯 Fix 103 B (2026-08-26): 완료 로그에 gate 파라미터 박제!

    매 실행 로그에 현재 임계값을 남겨야 "왜 진입 안 됐나"를 로그만으로 판정 가능!
    (Fix 99 ↔ Fix 102 완화 이력이 실 운영에 반영됐는지도 즉시 확인!)
    """
    return (
        f"rebound>={REBOUND_PCT_MIN_SAFETY}% wait>={MIN_STOP_WAIT_MINUTES}min "
        f"vol>={VOLUME_REVERSAL_MULTIPLIER}x pass=2:{MIN_PASSED_STAGE2}/3:{MIN_PASSED_STAGE3}/"
        f"last:{MIN_PASSED_STAGE_LAST} of8 hourly_max={MAX_HOURLY_REENTRIES} "
        f"stage3_wait={STAGE3_MIN_WAIT_HOURS}h last_chance={ENABLE_LAST_CHANCE}"
    )


def _get_reentry_daily_limit(db: Session) -> tuple[int, str]:
    """🚨 Fix 103 C (2026-08-26): 재진입 전용 일일 한도 (silent OFF 영구 차단!)

    옛 (silent bug!):
        limit_row = db.get(SystemSetting, "sajangnim_top_short_daily_limit")
        daily_limit = int(limit_row.value) if limit_row and limit_row.value else 0
        if daily_limit <= 0: return {...}   # ← 무로그! row 누락 = 워커 전면 OFF!

    신 (Fix 103):
      1) sajangnim_reentry_daily_limit  = 재진입 전용! (0 = 사장님 명시 OFF = 존중!)
      2) sajangnim_top_short_daily_limit / auto_bb_break_daily_limit = 값만 참조 (>0)
      3) REENTRY_DAILY_LIMIT_DEFAULT (20) = row 누락 시 fallback!
         (auto_short_at_top_worker._get_daily_limit 와 동일 패턴 = 헌법 6 대칭!)

    Return: (limit, source_key)
    """
    from app.models.system_setting import SystemSetting

    # 1) 전용 키 = 명시값 우선 (0 도 존중 = 사장님 OFF 스위치!)
    row = None  # except 절에서 참조 = NameError 방지!
    try:
        row = db.get(SystemSetting, REENTRY_DAILY_LIMIT_KEY)
        if row is not None and str(row.value or "").strip():
            return int(str(row.value).strip()), REENTRY_DAILY_LIMIT_KEY
    except (TypeError, ValueError) as e:
        logger.warning(
            "[RT_REENTRY] ⚠️ %s 파싱 실패 (value=%r) = fallback 진행: %s",
            REENTRY_DAILY_LIMIT_KEY, getattr(row, "value", None), e,
        )
    except Exception as e:  # DB 접근 실패 = 절대 은폐 X!
        logger.warning("[RT_REENTRY] ⚠️ %s 조회 실패 = fallback 진행: %s", REENTRY_DAILY_LIMIT_KEY, e)

    # 2) 공유 세팅 = 값만 참조 (0 = 신규 진입 OFF 의미 → 재진입은 면제!)
    for key in REENTRY_DAILY_LIMIT_FALLBACK_KEYS:
        try:
            row = db.get(SystemSetting, key)
            if row and str(row.value or "").strip():
                v = int(str(row.value).strip())
                if v > 0:
                    return v, key
        except Exception as e:
            logger.warning("[RT_REENTRY] ⚠️ %s 조회 실패 = 다음 fallback: %s", key, e)
            continue

    # 3) 최종 fallback = row 누락으로 인한 silent OFF 영구 차단!
    return REENTRY_DAILY_LIMIT_DEFAULT, "default"


def _count_reentry_used_today(db: Session) -> int:
    """🚨 Fix 103 C (2026-08-26): 재진입 전용 카운터!

    옛: _count_used_slots(db) = 신규 진입 워커 3종 공유 (bb4h/top_short/bottom_long!)
        → 신규 진입이 하루 20건 채우면 = 마틴게일 2단계까지 동반 차단! (사장님 사상 위배!)
    신: 오늘 RT_REENTRY suggestion 건수만! (신규 진입 슬롯 완전 면제!)

    기준 시각 = _auto_bb_reset_at (사장님 리셋 존중 = 헌법 6 단일 진실!)
    """
    from app.models.strategy_suggestion import StrategySuggestion

    try:
        from app.api.v1.strategy_suggestions import _auto_bb_reset_at
        since = _auto_bb_reset_at(db)
    except Exception as e:
        # 🚨 절대 은폐 X = 로그 남기고 KST 자정 fallback!
        logger.warning("[RT_REENTRY] ⚠️ reset_at 조회 실패 = KST 자정 fallback: %s", e)
        _now = datetime.now(timezone.utc)
        since = (_now + timedelta(hours=9)).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(hours=9)

    rows = db.execute(
        select(StrategySuggestion)
        .where(StrategySuggestion.status == "EXECUTED")
        .where(StrategySuggestion.execution_mode == "AUTO")
        .where(StrategySuggestion.executed_at >= since)
        .where(StrategySuggestion.reason.like("%RT_REENTRY%"))
    ).scalars().all()
    return len(rows)


def _check_indicator_reversal_for_reentry(
    bc, symbol: str, side: str, use_4h: bool = True, min_passed: int = 2
) -> tuple[bool, str, dict]:
    """🎯 v221 사장님 재설계 (2026-08-23): 지표 반전 = 재진입 진짜 조건!
    🎯 Fix 55 P3 (2026-08-24): min_passed 인자 추가 = 단계별 계단식 강화!
    🎯 Fix 99 (2026-08-25): 3중 → 5중 강화 + 4H MACD Hist 필터 + 볼륨 gate!
    🎯 Fix 102 (2026-08-26): 5중 → 8중 (5 core + 3 bonus!) = 완화 + 정밀!

    사장님 verbatim (Fix 102): "손절후 2단계 진입이 없는것 같이 이것도 보조지표를 최대한 활용해"
    → Fix 99 = 너무 엄격 = 진입 X! → 완화 + 다이버전스/BB 정밀 활용!

    로직 (8중 통과 조건 = 최소 min_passed 통과!):
    Core 5 (15m):
    - RSI 반전 (LONG: 상승 반전 / SHORT: 하락 반전)
    - MACD hist 반전
    - OBV slope 반전 (지속!)
    - CCI 반전 (Fix 99 A!)
    - 볼륨 반등 확인 (Fix 99 A/C, Fix 102 C: 1.5x → 1.3x 완화!)
    Bonus 3 (Fix 102 B/D):
    - 4H MACD Hist 동조 (Fix 102 B: 하드 필터 → 소프트 = 강력 반전 시 4H 역방향 허용!)
    - 다이버전스 (Fix 102 D: SHORT=베어리시 / LONG=불리시 = 진짜 반전 신호!)
    - BB 위치 근접 (Fix 102 D: SHORT=상단 / LONG=하단 근접 = 반등/반락 자리!)

    하드 필터 (whipsaw 방지, 완화 후에도 유지!):
    - 4h RSI 급진행: 역방향 지속 시 차단!

    min_passed (Fix 102 A):
    - 2단계 = 2/8 (완화! 첫 재진입 실행 가능성 확보!)
    - 3단계 = 3/8
    - 라스트 챈스 = 4/8 (라스트 챈스 = 실 작동!)

    Return: (통과, 사유, 스냅샷)
    """
    from app.services.bb_4h_band_analyzer import BB4HBandAnalyzer as BB

    snapshot: dict = {"tf": "15m+4h" if use_4h else "15m"}
    try:
        kl = bc.get_klines(symbol=symbol, interval="15m", limit=60)
        if not isinstance(kl, list) or len(kl) < 35:
            return False, "kline 부족", snapshot
        closes = [float(k[4]) for k in kl]
        highs = [float(k[2]) for k in kl]
        lows = [float(k[3]) for k in kl]
        vols = [float(k[5]) for k in kl]

        # 1) RSI 반전 (직전 대비 방향 전환)
        rsi_now = BB._calc_rsi(closes)
        rsi_prev = BB._calc_rsi(closes[:-3])  # 3봉 전!
        if rsi_now is None or rsi_prev is None:
            return False, "RSI 계산 실패", snapshot
        snapshot["rsi"] = rsi_now
        snapshot["rsi_prev"] = rsi_prev
        rsi_rev = (rsi_now > rsi_prev + 1) if side == "LONG" else (rsi_now < rsi_prev - 1)

        # 2) MACD hist 반전
        ema12 = BB._calc_ema(closes, 12)
        ema26 = BB._calc_ema(closes, 26)
        if not ema12 or not ema26:
            return False, "EMA 계산 실패", snapshot
        macd_line = [a - b for a, b in zip(ema12[14:], ema26)]
        sig = BB._calc_ema(macd_line, 9)
        if not sig or len(sig) < 3:
            return False, "MACD 부족", snapshot
        hist = [m - s for m, s in zip(macd_line[-len(sig):], sig)]
        if len(hist) < 3:
            return False, "hist 부족", snapshot
        snapshot["macd_hist"] = hist[-1]
        macd_rev = (hist[-1] > hist[-2]) if side == "LONG" else (hist[-1] < hist[-2])

        # 3) OBV slope (2봉 지속 반전)
        obv = [0.0]
        for i in range(1, len(closes)):
            v = vols[i]
            if closes[i] > closes[i - 1]:
                obv.append(obv[-1] + v)
            elif closes[i] < closes[i - 1]:
                obv.append(obv[-1] - v)
            else:
                obv.append(obv[-1])
        obv_slope_now = obv[-1] - obv[-4] if len(obv) >= 4 else 0
        obv_slope_prev = obv[-4] - obv[-7] if len(obv) >= 7 else 0
        snapshot["obv_slope"] = obv_slope_now
        obv_rev = (
            (obv_slope_now > 0 and obv_slope_now > obv_slope_prev)
            if side == "LONG"
            else (obv_slope_now < 0 and obv_slope_now < obv_slope_prev)
        )

        # 4) 🎯 Fix 99 A (2026-08-25): CCI 반전 (14 period, 4번째 지표!)
        cci_period = 14
        cci_rev = False
        if len(closes) >= cci_period + 3:
            tps = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(len(closes))]

            def _calc_cci_at(end_idx: int):
                """end_idx 시점 (exclusive) 기준 CCI = 마지막 end_idx-1 지점의 CCI!"""
                if end_idx < cci_period:
                    return None
                window = tps[end_idx - cci_period:end_idx]
                sma = sum(window) / cci_period
                mean_dev = sum(abs(x - sma) for x in window) / cci_period
                if mean_dev <= 0:
                    return 0.0
                return (tps[end_idx - 1] - sma) / (0.015 * mean_dev)

            cci_now = _calc_cci_at(len(tps))
            cci_prev = _calc_cci_at(len(tps) - 3)
            if cci_now is not None and cci_prev is not None:
                snapshot["cci"] = cci_now
                snapshot["cci_prev"] = cci_prev
                # CCI 반전 임계 = ±5 (RSI 대비 스케일 큼!)
                cci_rev = (cci_now > cci_prev + 5) if side == "LONG" else (cci_now < cci_prev - 5)

        # 5) 🎯 Fix 99 A/C (2026-08-25): 볼륨 반전 확인 (5번째 지표!)
        # 최근 3봉 평균 볼륨 >= 이전 3봉 평균 × 1.5 → 진짜 세력 진입!
        # 저볼륨 반등 = fake bounce (dead cat bounce!) = 차단!
        vol_rev = False
        if len(vols) >= 6:
            vol_recent3 = sum(vols[-3:]) / 3.0
            vol_prev3 = sum(vols[-6:-3]) / 3.0
            vol_ratio = (vol_recent3 / vol_prev3) if vol_prev3 > 0 else 0.0
            snapshot["vol_ratio"] = round(vol_ratio, 2)
            snapshot["vol_recent3"] = round(vol_recent3, 4)
            snapshot["vol_prev3"] = round(vol_prev3, 4)
            vol_rev = vol_ratio >= VOLUME_REVERSAL_MULTIPLIER

        # 🎯 Fix 102 D (2026-08-26): 다이버전스 감지 (진짜 반전 신호!)
        # SHORT 재진입 = 베어리시 다이버전스 (가격 신 고점 but RSI 하락)
        # LONG 재진입 = 불리시 다이버전스 (가격 신 저점 but RSI 반등)
        divergence_ok = False
        try:
            _lb = min(DIVERGENCE_LOOKBACK, len(closes) - 5)
            if _lb >= 5:
                _recent = closes[-_lb:]
                if side == "LONG":
                    # 불리시 다이버전스: 최근 저점 대비 RSI 개선!
                    _extreme_val = min(_recent)
                    _extreme_local_idx = _recent.index(_extreme_val)
                    _extreme_full_idx = len(closes) - _lb + _extreme_local_idx
                    if _extreme_full_idx >= 15:  # RSI 최소 14봉 필요!
                        _rsi_at_extreme = BB._calc_rsi(closes[:_extreme_full_idx + 1])
                        _price_tol = _extreme_val * (1 + DIVERGENCE_PRICE_TOL_PCT / 100.0)
                        _price_near = closes[-1] <= _price_tol
                        if _rsi_at_extreme is not None:
                            _rsi_higher = rsi_now > _rsi_at_extreme + DIVERGENCE_RSI_GAP
                            divergence_ok = _price_near and _rsi_higher
                            snapshot["rsi_at_extreme"] = round(_rsi_at_extreme, 2)
                else:  # SHORT
                    # 베어리시 다이버전스: 최근 고점 대비 RSI 하락!
                    _extreme_val = max(_recent)
                    _extreme_local_idx = _recent.index(_extreme_val)
                    _extreme_full_idx = len(closes) - _lb + _extreme_local_idx
                    if _extreme_full_idx >= 15:
                        _rsi_at_extreme = BB._calc_rsi(closes[:_extreme_full_idx + 1])
                        _price_tol = _extreme_val * (1 - DIVERGENCE_PRICE_TOL_PCT / 100.0)
                        _price_near = closes[-1] >= _price_tol
                        if _rsi_at_extreme is not None:
                            _rsi_lower = rsi_now < _rsi_at_extreme - DIVERGENCE_RSI_GAP
                            divergence_ok = _price_near and _rsi_lower
                            snapshot["rsi_at_extreme"] = round(_rsi_at_extreme, 2)
        except Exception:
            divergence_ok = False
        snapshot["divergence"] = divergence_ok

        # 🎯 Fix 102 D (2026-08-26): BB 위치 확인 (반등/반락 자리!)
        # SHORT 재진입 = BB 상단 근접 (반락 자리!)
        # LONG 재진입 = BB 하단 근접 (반등 자리!)
        bb_position_ok = False
        try:
            if len(closes) >= BB_PERIOD:
                _bb_window = closes[-BB_PERIOD:]
                _bb_mid = sum(_bb_window) / BB_PERIOD
                _bb_var = sum((x - _bb_mid) ** 2 for x in _bb_window) / BB_PERIOD
                _bb_std_val = _bb_var ** 0.5
                _bb_upper = _bb_mid + BB_STD * _bb_std_val
                _bb_lower = _bb_mid - BB_STD * _bb_std_val
                _bb_width = _bb_upper - _bb_lower
                _cur_px = closes[-1]
                snapshot["bb_upper"] = round(_bb_upper, 6)
                snapshot["bb_lower"] = round(_bb_lower, 6)
                snapshot["bb_mid"] = round(_bb_mid, 6)
                if _bb_width > 0:
                    if side == "LONG":
                        # 하단 근처 or 이탈 = LONG 반등 자리!
                        _threshold = _bb_lower + _bb_width * BB_NEAR_BAND_PCT
                        bb_position_ok = _cur_px <= _threshold
                    else:  # SHORT
                        # 상단 근처 or 이탈 = SHORT 반락 자리!
                        _threshold = _bb_upper - _bb_width * BB_NEAR_BAND_PCT
                        bb_position_ok = _cur_px >= _threshold
        except Exception:
            bb_position_ok = False
        snapshot["bb_position_ok"] = bb_position_ok

        # 6) 4h 방향 확인 = 하드 필터 (whipsaw 방지!) + 4H MACD 소프트 (Fix 102 B!)
        macd_4h_agree = False  # 🎯 Fix 102 B: 4H MACD = 소프트 bonus!
        if use_4h:
            try:
                kl4 = bc.get_klines(symbol=symbol, interval="4h", limit=40)
                if isinstance(kl4, list) and len(kl4) >= 30:
                    c4 = [float(k[4]) for k in kl4]

                    # 6a) 4h RSI 역방향 급진행 = 기존 하드 필터 (whipsaw 방지 유지!)
                    rsi4_now = BB._calc_rsi(c4)
                    rsi4_prev = BB._calc_rsi(c4[:-2])
                    if rsi4_now is not None and rsi4_prev is not None:
                        snapshot["rsi_4h"] = rsi4_now
                        contradicts_4h_rsi = (
                            (side == "LONG" and rsi4_now < rsi4_prev - 3 and rsi4_now < 40)
                            or (side == "SHORT" and rsi4_now > rsi4_prev + 3 and rsi4_now > 60)
                        )
                        if contradicts_4h_rsi:
                            return False, f"4h RSI 역방향 지속 (RSI4={rsi4_now:.1f})", snapshot

                    # 6b) 🎯 Fix 102 B (2026-08-26): 4h MACD Hist = 하드 → 소프트!
                    # 옛(Fix 99 B): 4H 역방향 = 무조건 skip = 진입 X 자주!
                    # 신(Fix 102 B): 4H 동조 시 = bonus score 1점! 역방향이어도 = 통과 가능!
                    # → 강력 반전 (다이버전스 + BB 위치 등) 시 = 4H 역방향 허용!
                    ema12_4h = BB._calc_ema(c4, 12)
                    ema26_4h = BB._calc_ema(c4, 26)
                    if ema12_4h and ema26_4h:
                        macd_line_4h = [a - b for a, b in zip(ema12_4h[14:], ema26_4h)]
                        sig_4h = BB._calc_ema(macd_line_4h, 9)
                        if sig_4h and len(sig_4h) >= 1:
                            hist_4h = [m - s for m, s in zip(macd_line_4h[-len(sig_4h):], sig_4h)]
                            if hist_4h:
                                _h4 = hist_4h[-1]
                                snapshot["macd_hist_4h"] = _h4
                                macd_4h_agree = (
                                    (side == "SHORT" and _h4 < 0)
                                    or (side == "LONG" and _h4 > 0)
                                )
            except Exception:
                pass  # 4h 실패 시 = 15m만 신뢰!
        snapshot["macd_4h_agree"] = macd_4h_agree

        # 🎯 Fix 102 A (2026-08-26): 8중 = core 5 + bonus 3 (완화 + 정밀!)
        passes_core = (
            int(rsi_rev) + int(macd_rev) + int(obv_rev)
            + int(cci_rev) + int(vol_rev)
        )
        passes_bonus = (
            int(divergence_ok) + int(bb_position_ok) + int(macd_4h_agree)
        )
        passes = passes_core + passes_bonus
        snapshot["passes_15m"] = f"{passes_core}/5"
        snapshot["passes_bonus"] = f"{passes_bonus}/3"
        snapshot["passes_total"] = f"{passes}/8"
        snapshot["min_passed_required"] = min_passed
        snapshot["rsi_rev"] = rsi_rev
        snapshot["macd_rev"] = macd_rev
        snapshot["obv_rev"] = obv_rev
        snapshot["cci_rev"] = cci_rev
        snapshot["vol_rev"] = vol_rev

        ok = passes >= min_passed
        return (
            ok,
            (
                f"total {passes}/8 (need {min_passed}/8, core={passes_core}/5 bonus={passes_bonus}/3 | "
                f"RSI={rsi_rev} MACD={macd_rev} OBV={obv_rev} "
                f"CCI={cci_rev} VOL={vol_rev} | "
                f"DIV={divergence_ok} BB={bb_position_ok} 4HMACD={macd_4h_agree})"
            ),
            snapshot,
        )
    except Exception as e:
        return False, f"err={e}", snapshot


def _is_symbol_learning_ok(db: Session, symbol: str, side: str) -> tuple[bool, str]:
    """🎓 v221 (2026-08-23): 학습 인사이트 활용 = 심볼 성공률 gate!

    🚨 Fix 71 (2026-08-25 사장님 verbatim!):
    "제한 심볼들 모두 해제해줘 제한 심볼을 만들지 않도록해"
    → 심볼 이름 기반 worst gate = 완전 해제! (재진입 항상 허용!)
    → 항상 (True, "disabled_by_sajangnim") 반환!

    ※ 지표 기반 재진입 판단 (OBV/RSI/BB 반전) 은 상위 로직에서 유지!
    """
    return True, "disabled_by_sajangnim_2026-08-25"


def _get_base_capital_from_instance(si: StrategyInstance) -> float:
    """v218 (2026-08-22): 청산된 원 전략의 base capital 조회!

    사장님 사상: 마틴게일 = 이전 포지션 대비 1.5배!
    → 이전 포지션의 원 자본 = 정확한 base 필요!

    조회 순서:
    1. template.stages_config['capitals'][0] (JSONB 구조!)
    2. template.stage1_capital (Decimal fallback!)
    3. template.total_capital (Decimal fallback!)
    4. 500.0 (최종 fallback!)
    """
    try:
        tmpl = si.strategy_template
        if tmpl and getattr(tmpl, "stages_config", None):
            caps = tmpl.stages_config.get("capitals", []) if isinstance(tmpl.stages_config, dict) else []
            if caps and len(caps) > 0:
                return float(caps[0])
        if tmpl and getattr(tmpl, "stage1_capital", None):
            return float(tmpl.stage1_capital)
        if tmpl and getattr(tmpl, "total_capital", None):
            return float(tmpl.total_capital)
    except Exception:
        pass
    return 500.0


# 🚨🚨 Fix 104 (2026-08-26): mark_price 결손 = 재진입 구조적 전멸! → 배치 ticker fallback!
#
# 사장님 VPS 실측 (Fix 103 로그):
#   reasons={'no_mark_price': 43, 'already_active': 22}
#   = 재진입 후보 66%가 mark_price Redis 키 없어서 탈락!
#   = 지표 조건 판정까지 도달한 심볼 0건!
#
# 근본 원인 (mark_price_stream_consumer.py):
#   ACTIVE_STATUS_NOT_IN 이 STOPPED/CLOSED_BY_SL/REENTRY_READY 등을 제외
#   → _refresh_loop 이 30초마다 UNSUBSCRIBE → set_mark_price 중단 → TTL 60초 만료
#   → 청산된 심볼(= 정확히 재진입 후보!) = Redis 키 영구 소멸!
#   → 재진입이 「구조적으로」 영원히 불가능한 상태였음!
#
# 해결: 전 심볼 ticker 1회 배치 조회 (43 calls → 1 call = rate limit 안전!)
FIX104_PRICE_FIELDS = ("lastPrice", "markPrice", "price")


def _build_price_fallback_map(bc) -> dict[str, float]:
    """🚨 Fix 104: 전 심볼 현재가 1회 배치 조회 = mark_price 결손 대비!

    bc.get_24hr_ticker() 를 **심볼 인자 없이** 호출 = 전 심볼 한 번에!
    (후보 43개를 개별 조회하면 43 calls / 배치는 1 call = rate limit 안전!)

    실패 시 = 빈 dict = fallback 없이 기존 동작 유지 (fail-safe!).
    """
    if bc is None:
        return {}
    try:
        rows = bc.get_24hr_ticker()   # symbol 인자 없음 = 전 심볼!
        if not isinstance(rows, list):
            logger.warning(
                "[Fix104] ticker 배치 응답이 list 아님 (%s) = fallback 없이 진행!",
                type(rows).__name__,
            )
            return {}
        out: dict[str, float] = {}
        for r in rows:
            try:
                if not isinstance(r, dict):
                    continue
                sym = str(r.get("symbol") or "").strip().upper()
                if not sym:
                    continue
                px = 0.0
                for _f in FIX104_PRICE_FIELDS:
                    _v = r.get(_f)
                    if _v not in (None, "", "0"):
                        px = float(_v)
                        if px > 0:
                            break
                if px > 0:
                    out[sym] = px
            except Exception:
                continue
        logger.info(
            "[Fix104] ticker 배치 조회 성공: %d 심볼 가격 확보 (1 API call!)", len(out),
        )
        return out
    except Exception as e:
        logger.warning("[Fix104] ticker 배치 조회 실패 (fallback 없이 진행): %s", e)
        return {}


def _make_mainnet_client(db: Session):
    """🚨 Fix 104: mainnet BinanceClient 생성 (배치 ticker 전용, 없으면 None).

    fail-safe = 계정 없음/복호화 실패 = None 반환 = fallback 없이 기존 동작 유지!
    """
    try:
        from app.core.crypto import decrypt_text
        from app.integrations.binance.client import BinanceClient
        from app.models.exchange_account import ExchangeAccount

        acc = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not acc:
            logger.warning(
                "[Fix104] mainnet ExchangeAccount 없음 = ticker fallback 불가!",
            )
            return None
        return BinanceClient(
            api_key=decrypt_text(acc.api_key_enc),
            api_secret=decrypt_text(acc.api_secret_enc),
            is_testnet=False,
        )
    except Exception as e:
        logger.warning("[Fix104] mainnet client 생성 실패 = fallback 불가: %s", e)
        return None


def run_realtime_reentry() -> dict:
    """매 30초 = 실시간 재진입 감지!

    🚨 Fix 103 (2026-08-26 사장님 verbatim):
    "손절후 2단계 진입이 없는것 같이 이것도 보조지표를 최대한 활용해"

    Fix A: 모든 조기 return = logger.warning 필수! (silent return 금지 = 헌법!)
    Fix B: 함수 끝 = 항상 완료 로그! (매 30초 = 로그 1건 = 살아있음 증명!)
    Fix C: 재진입 = 신규 진입 daily slot 완전 면제 (마틴게일 2단계 = 신 진입 X!)
    """
    db: Session = SessionLocal()
    entered_fail = 0
    entered_success = 0
    skipped = 0
    scanned = 0
    candidates = 0
    results: list[dict] = []
    skip_reasons: dict[str, int] = {}

    # 🚨 Fix 104 (2026-08-26): mark_price 결손 대비 배치 ticker fallback!
    # ※ 반드시 함수 최상단 초기화! (_finish 가 이 값을 읽는데, 조기 return 경로가
    #   루프 시작 전에 _finish 를 호출 = 미초기화 시 NameError!)
    price_fallback: dict[str, float] | None = None  # lazy = 결손 없으면 API 호출 0회!
    fallback_bc = None                               # lazy = 결손 없으면 client 생성 X!
    fallback_used = 0                                # fallback 적중 건수 (완료 로그!)

    def _bump(reason: str) -> None:
        """🎯 Fix 103 A: skip 사유 집계 = 완료 로그 1줄로 원인 판정!"""
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    def _finish(note: str, level: str = "warning", **extra) -> dict:
        """🚨 Fix 103 A+B: 모든 종료 경로 = 반드시 여기로! (silent return 0건!)"""
        payload: dict = {
            "scanned": scanned,
            "candidates": candidates,
            "entered_fail_reentry": entered_fail,
            "entered_success_reentry": entered_success,
            "entered": entered_fail + entered_success,
            "skipped": skipped,
            "skip_reasons": dict(skip_reasons),
            # 🚨 Fix 104: fallback 작동 여부 = 로그/응답 1줄로 확인!
            "fallback_px": fallback_used,
            "note": note,
            "spec": _gate_spec(),
            "results": results,
        }
        payload.update(extra)
        _log = getattr(logger, level, logger.warning)
        _log(
            "[RT_REENTRY] 완료: scanned=%d candidates=%d reentered=%d "
            "(fail=%d success=%d) skipped=%d fallback_px=%d note=%s reasons=%s spec=%s",
            scanned, candidates, entered_fail + entered_success,
            entered_fail, entered_success, skipped, fallback_used,
            note, (skip_reasons or "-"), _gate_spec(),
        )
        return payload

    try:
        # 1. 🚨 Fix 103 C: 재진입 전용 daily_limit (신규 진입 슬롯 면제!)
        daily_limit, _limit_src = _get_reentry_daily_limit(db)
        if daily_limit <= 0:
            # 🚨 Fix 103 A: 옛 = 무로그 return (미호출과 구별 불가!) → 이제 반드시 로그!
            return _finish(
                f"재진입 OFF: reentry_daily_limit={daily_limit} (src={_limit_src}) "
                f"= 사장님 명시 OFF! (켜려면 SystemSetting '{REENTRY_DAILY_LIMIT_KEY}' > 0)"
            )

        from app.workers.auto_bb_breakdown_worker import (
            _create_auto_bb_strategy,
            _get_reentry_count, _increment_reentry_count,
            _reset_reentry_count, MAX_REENTRY_COUNT,
        )
        # 🚨 Fix 103 C 근본 fix: _count_used_slots(신규 진입 공유 카운터) 사용 중단!
        # 재진입 = 이미 손절된 심볼의 마틴게일 2단계 = 「신규 진입」 아님!
        # → 신규 진입이 하루 한도를 채워도 재진입은 계속 가능해야 함! (사장님 사상!)
        used = _count_reentry_used_today(db)
        remaining = daily_limit - used
        if remaining <= 0:
            return _finish(
                f"재진입 일일 한도 소진: {used}/{daily_limit} (src={_limit_src}) "
                f"= 재진입 전용 카운터 (신규 진입 무관!)"
            )

        # 2. 1h 재진입 남발 체크!
        cutoff_1h = datetime.now(timezone.utc) - timedelta(hours=1)
        from app.models.strategy_suggestion import StrategySuggestion
        recent_re = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.created_at >= cutoff_1h)
            .where(StrategySuggestion.reason.like("%RT_REENTRY%"))
        ).scalars().all()
        if len(recent_re) >= MAX_HOURLY_REENTRIES:
            return _finish(
                f"1h 재진입 남발 차단: {len(recent_re)}건 >= max {MAX_HOURLY_REENTRIES}"
            )

        # 3. 최근 24h 청산된 자동 진입 심볼 조회!
        # 🚨 v221 Fix 25 (2026-08-23 사장님 지적!): strategy_type 필터 확장!
        # 이전: 'auto_bb_break%'만! → sajangnim_top_short 등 = 모두 skip!
        # 신: 모든 자동 진입 소스 = 재진입 대상!
        # 사장님 확인: 24h 청산 20건 중 = 이전 필터 = 1건만 통과!
        from sqlalchemy import or_
        cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        closed = db.execute(
            select(StrategyInstance)
            .join(StrategyTemplate,
                  StrategyInstance.strategy_template_id == StrategyTemplate.id)
            .where(StrategyInstance.stopped_at >= cutoff_24h)
            .where(StrategyInstance.status.in_(list(TERMINAL_STATUSES)))
            .where(
                or_(
                    StrategyTemplate.strategy_type.like('auto_bb_break%'),
                    StrategyTemplate.strategy_type.like('sajangnim_top%'),
                    StrategyTemplate.strategy_type.like('realtime_reentry%'),
                    StrategyTemplate.strategy_type.like('chart_pattern%'),
                )
            )
        ).scalars().all()
        logger.info(
            "[RT_REENTRY] 24h 청산 자동 진입 = %d건 (필터 확장!) | 재진입 슬롯 %d/%d (src=%s)",
            len(closed), used, daily_limit, _limit_src,
        )
        if not closed:
            # 🎯 Fix 103 A: 후보 0건도 반드시 기록! (미호출과 구별!)
            return _finish("24h 청산 후보 0건 (재진입 대상 없음)")

        # 4. 활성 심볼 skip!
        active = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.status.in_(list(ACTIVE_LIKE)))
        ).scalars().all()
        active_syms = {r.symbol for r in active}

        # 5. Redis mark_price!
        from app.core.redis_client import get_redis_client
        redis = get_redis_client()

        # 6. 심볼별 = 최신 청산 1건씩만!
        latest_by_sym: dict[tuple[str, str], StrategyInstance] = {}
        for si in closed:
            key = (si.symbol, si.side)
            if key not in latest_by_sym or (
                si.stopped_at and latest_by_sym[key].stopped_at
                and si.stopped_at > latest_by_sym[key].stopped_at
            ):
                latest_by_sym[key] = si
        candidates = len(latest_by_sym)

        for (symbol, side), si in latest_by_sym.items():
            scanned += 1
            if remaining <= 0:
                # 🎯 Fix 103 A: 루프 중단도 무로그 금지!
                logger.warning(
                    "[RT_REENTRY] 루프 중단: 재진입 슬롯 소진 (scanned=%d/%d)",
                    scanned, candidates,
                )
                _bump("slot_exhausted_midloop")
                break
            if symbol in active_syms:
                skipped += 1
                _bump("already_active")
                logger.info("[RT_REENTRY] skip: %s %s 이미 활성 심볼!", symbol, side)
                continue

            # 재진입 카운터 max 2 (기존) or 3 (Fix 53 라스트 챈스!)
            re_count = _get_reentry_count(symbol, side)
            _max_count_effective = (
                MAX_REENTRY_COUNT + 1 if ENABLE_LAST_CHANCE else MAX_REENTRY_COUNT
            )
            if re_count >= _max_count_effective:
                skipped += 1
                _bump("max_reentry_count")
                logger.info(
                    "[RT_REENTRY] skip: %s %s MAX 재진입 %d회 도달! (max=%d, last_chance=%s)",
                    symbol, side, re_count, _max_count_effective, ENABLE_LAST_CHANCE,
                )
                continue

            # mark_price 조회!
            # 🎯 Fix 103 A: 옛 = 3개 경로 모두 무로그 continue = 「후보인데 왜 사라졌나」 불명!
            # 🚨 Fix 104 (2026-08-26): Redis 결손 = 청산 심볼 = 재진입 후보 66% 전멸!
            #    → 실패 시 즉시 continue 하지 않고 배치 ticker fallback 을 먼저 시도!
            #    (skip 사유는 「최종 실패」 시에만 1회 집계 = Fix 103 카운터 왜곡 방지!)
            mark_price: float | None = None
            _mp_issue = "no_mark_price"
            try:
                mp_raw = redis.get(f"mark_price:{symbol}")
                if mp_raw:
                    _mp_val = float(mp_raw.decode() if isinstance(mp_raw, bytes) else mp_raw)
                    if _mp_val > 0:
                        mark_price = _mp_val
                    else:
                        _mp_issue = "mark_price_nonpositive"
                        logger.warning(
                            "[RT_REENTRY] %s %s Redis mark_price<=0 (%s) → Fix104 fallback 시도!",
                            symbol, side, _mp_val,
                        )
            except Exception as _mpe:
                _mp_issue = "mark_price_error"
                logger.warning(
                    "[RT_REENTRY] %s %s mark_price 파싱 실패 (→ Fix104 fallback 시도): %s",
                    symbol, side, _mpe,
                )

            if mark_price is None or mark_price <= 0:
                # 🚨 Fix 104: Redis 결손 → 전 심볼 ticker 배치 조회 (43 calls → 1 call!)
                if price_fallback is None:
                    # lazy 초기화 = 결손 0건이면 API 호출 0회 = rate limit 부담 X!
                    if fallback_bc is None:
                        fallback_bc = _make_mainnet_client(db)
                    price_fallback = _build_price_fallback_map(fallback_bc)
                # map key = 대문자 정규화 → DB 심볼 표기 흔들려도 적중!
                _fb_px = price_fallback.get(symbol) or price_fallback.get(
                    str(symbol).strip().upper()
                )
                if _fb_px and _fb_px > 0:
                    mark_price = float(_fb_px)
                    fallback_used += 1
                    logger.info(
                        "[RT_REENTRY] 🚨 Fix104 fallback 적중: %s %s px=%s "
                        "(Redis %s → ticker 배치!)",
                        symbol, side, mark_price, _mp_issue,
                    )

            if not mark_price or mark_price <= 0:
                skipped += 1
                _bump(_mp_issue)
                logger.info(
                    "[RT_REENTRY] skip: %s %s 현재가 확보 실패! "
                    "(Redis mark_price:%s = %s + Fix104 ticker fallback 미적중)",
                    symbol, side, symbol, _mp_issue,
                )
                continue

            # 이후 기존 로직 = mp 변수 그대로 사용! (반등%% 계산 등)
            mp = mark_price

            # 🎯 v218 fix (2026-08-22): 청산가 우선 = 평단 fallback!
            # 이전 = 평단 = 실 청산가와 다름 = 3% 반등 판정 부정확!
            # last_liquidation_price = SL 발동가! = 반등 시작점 정확!
            _stop_price = float(si.last_liquidation_price or si.avg_entry_price or 0)
            if _stop_price <= 0:
                # 🎯 Fix 103 A: 옛 = 무로그 continue! (청산가/평단 둘 다 없음 = 데이터 결함!)
                skipped += 1
                _bump("no_stop_price")
                logger.warning(
                    "[RT_REENTRY] skip: %s %s 기준가 없음! (last_liquidation_price=%s "
                    "avg_entry_price=%s instance_id=%s) = 반등%% 계산 불가!",
                    symbol, side, si.last_liquidation_price, si.avg_entry_price, si.id,
                )
                continue

            pnl = float(si.realized_pnl or 0)
            _is_fail = pnl < 0
            _is_success = pnl > 0

            # 🎯 Fix 99 E (2026-08-25): 손절/익절 후 최소 대기 시간 (whipsaw 방지!)
            # 사장님 사상 = 정밀 재진입! → SL 직후 급변동 = skip 필수!
            # (기존 STAGE3_MIN_WAIT_HOURS 는 3단계+만 적용 = 2단계에서 무대기 whipsaw!)
            if si.stopped_at:
                _elapsed_min = (datetime.now(timezone.utc) - si.stopped_at).total_seconds() / 60.0
                if _elapsed_min < MIN_STOP_WAIT_MINUTES:
                    skipped += 1
                    _bump("stop_wait_too_short")
                    logger.info(
                        "[RT_REENTRY] skip: %s %s 손절/익절 후 대기 부족 (%.1fmin < %.1fmin) = whipsaw 방지!",
                        symbol, side, _elapsed_min, MIN_STOP_WAIT_MINUTES,
                    )
                    continue

            # 급등/급락 필터 = 24h 변동 조회 (안전!)
            # 여기선 skip 판정만 = 근사치!

            # 🎯 v221 사장님 재설계 (2026-08-23): 지표 반전 = MAIN gate!
            # 반등 % 는 최소 안전선(0.5%) — 진짜 진입 조건 = 지표 3중 반전!
            _use_success_reentry = _is_success
            if side == "LONG":
                _rebound_pct = (mp - _stop_price) / _stop_price * 100
            else:
                _rebound_pct = (_stop_price - mp) / _stop_price * 100

            # (a) 최소 안전선 = 역방향 폭주 방지 (0.5% 만!)
            if _rebound_pct < REBOUND_PCT_MIN_SAFETY:
                skipped += 1
                _bump("rebound_too_small")
                logger.info(
                    "[RT_REENTRY] skip: %s %s 역방향 진행 중 (%.2f%% < %.1f%%)",
                    symbol, side, _rebound_pct, REBOUND_PCT_MIN_SAFETY,
                )
                continue

            # (b) 학습 인사이트 = worst 심볼 gate
            _learn_ok, _learn_msg = _is_symbol_learning_ok(db, symbol, side)
            if not _learn_ok:
                skipped += 1
                _bump("learning_gate")
                logger.info(
                    "[RT_REENTRY] skip: %s %s 학습 실패 심볼 (%s)",
                    symbol, side, _learn_msg,
                )
                continue

            # 🎯 Fix 55 P3 (2026-08-24): 단계별 min_passed 결정!
            # 익절 후 재진입 = 초기 stage 취급 (loose 2/3)
            # 실패 재진입 = re_count + 2 stage
            if _use_success_reentry:
                _stage_no_for_gate = 2  # 익절 재진입 = loose
            else:
                _stage_no_for_gate = re_count + 2
            if _stage_no_for_gate == 2:
                _min_passed = MIN_PASSED_STAGE2
            elif _stage_no_for_gate == 3:
                _min_passed = MIN_PASSED_STAGE3
            elif _stage_no_for_gate >= 4:
                _min_passed = MIN_PASSED_STAGE_LAST
            else:
                _min_passed = MIN_PASSED_STAGE2

            # (c) 지표 반전 확인 = 핵심 gate! (실패/익절 모두!)
            try:
                from app.integrations.binance.client import BinanceClient
                from app.core.crypto import decrypt_text
                from app.models.exchange_account import ExchangeAccount
                _acc = db.execute(
                    select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
                ).scalar_one_or_none()
                if not _acc:
                    # 🎯 Fix 103 A: 옛 = 무로그! (mainnet 계정 없음 = 전 심볼 조용히 전멸!)
                    skipped += 1
                    _bump("no_exchange_account")
                    logger.warning(
                        "[RT_REENTRY] skip: %s %s mainnet ExchangeAccount 없음 = 지표 조회 불가!",
                        symbol, side,
                    )
                    continue
                _bc = BinanceClient(
                    api_key=decrypt_text(_acc.api_key_enc),
                    api_secret=decrypt_text(_acc.api_secret_enc),
                    is_testnet=False,
                )
                _ind_ok, _ind_msg, _ind_snap = _check_indicator_reversal_for_reentry(
                    _bc, symbol, side, use_4h=True, min_passed=_min_passed,
                )
            except Exception as _ve:
                logger.warning(
                    "[RT_REENTRY] skip: %s %s 지표 조회 실패 = skip 안전: %s", symbol, side, _ve,
                )
                skipped += 1
                _bump("indicator_fetch_error")
                continue

            if not _ind_ok:
                skipped += 1
                _bump(f"indicator_gate_need{_min_passed}")
                logger.info(
                    "[RT_REENTRY] skip: %s %s 지표 반전 미확인 (%s) [rebound=%.2f%% stage=%d need=%d/8]",
                    symbol, side, _ind_msg, _rebound_pct, _stage_no_for_gate, _min_passed,
                )
                continue

            # 🎯 Fix 55 P3 (2026-08-24): 3단계+ = 24h 변동 필터 = 급등/급락 반대매매 skip!
            # (2단계는 기존 유지 = loose)
            # 사장님 헌법 64: 급등 SHORT / 급락 LONG = 물타기 폭발 방지!
            if (not _use_success_reentry) and _stage_no_for_gate >= 3:
                try:
                    _ticker = _bc.get_24hr_ticker(symbol=symbol)
                    _chg_pct = None
                    if isinstance(_ticker, dict):
                        _chg_pct = float(_ticker.get("priceChangePercent") or 0)
                    elif isinstance(_ticker, list) and _ticker:
                        _chg_pct = float(_ticker[0].get("priceChangePercent") or 0)
                    if _chg_pct is not None:
                        _skip_24h = (
                            (side == "SHORT" and _chg_pct >= STAGE3_24H_ABS_LIMIT_PCT)
                            or (side == "LONG" and _chg_pct <= -STAGE3_24H_ABS_LIMIT_PCT)
                        )
                        if _skip_24h:
                            skipped += 1
                            _bump("24h_change_limit")
                            logger.warning(
                                "[RT_REENTRY] 🚨 stage %d skip: %s %s 24h=%.2f%% (한도 ±%.1f%% 초과 = 헌법 64!)",
                                _stage_no_for_gate, symbol, side, _chg_pct, STAGE3_24H_ABS_LIMIT_PCT,
                            )
                            continue
                except Exception as _te:
                    logger.warning("[RT_REENTRY] 24h ticker 조회 실패 = 진행: %s", _te)

            # 통과 → 진입!
            _kind = "RT_REENTRY_SUCCESS" if _use_success_reentry else "RT_REENTRY"
            _reason_suffix = (
                f"{_kind}: {side} {'익절' if _is_success else '실패'} 후 "
                f"지표 반전 [{_ind_msg}] rebound={_rebound_pct:.2f}% [{_learn_msg}]"
            )

            # 3단계 + Fix 53 4단계 (라스트 챈스) = "충분히 대기" = 최소 4h!
            if not _use_success_reentry:
                _stage_no = re_count + 2
                if _stage_no >= 3 and si.stopped_at:
                    _elapsed_h = (datetime.now(timezone.utc) - si.stopped_at).total_seconds() / 3600
                    if _elapsed_h < STAGE3_MIN_WAIT_HOURS:
                        skipped += 1
                        _bump("stage3_wait_too_short")
                        logger.info(
                            "[RT_REENTRY] stage %d skip: %s 대기 부족 (%.1fh < %.1fh)",
                            _stage_no, symbol, _elapsed_h, STAGE3_MIN_WAIT_HOURS,
                        )
                        continue

            # 진입 실행!
            try:
                # 🎯 v219 사장님 최종 마틴게일 (2026-08-22!):
                # "300 600 1800" = 1단계 초기 / 2단계 이전×2 / 3단계 투자금전체×2
                # "3단계까지 갈수 있다야 가능하면 가지않는 관리가 필요"
                # 🎯 Fix 53 (2026-08-24): 4단계 = 라스트 챈스 (동일 자본!)
                _base_capital = _get_base_capital_from_instance(si)
                _is_last_chance = False  # Fix 53 라스트 챈스 여부!
                if _use_success_reentry:
                    # 사장님: 익절 후 재진입 = 초기 시작금액!
                    _entry_capital = float(_base_capital)
                    _mult_label = ""
                else:
                    # 🎯 v219 사장님 신 마틴게일 (300/600/1800!) + Fix 53 라스트 챈스!
                    from decimal import Decimal as _D
                    from app.services.sajangnim_capital import compute_reentry_capital, MAX_REENTRY_STAGE
                    _stage = re_count + 2  # count=0 → 2단계, count=1 → 3단계, count=2 → 4단계(라스트!)
                    _is_last_chance = (
                        ENABLE_LAST_CHANCE
                        and _stage == MAX_REENTRY_STAGE_WITH_LAST
                    )
                    if _stage > MAX_REENTRY_STAGE and not _is_last_chance:
                        skipped += 1
                        _bump("stage_over_max")
                        logger.info(
                            "[RT_REENTRY] v219 STOP: %s %s stage=%d > MAX=%d (3단계까지!)",
                            symbol, side, _stage, MAX_REENTRY_STAGE,
                        )
                        continue

                    if _is_last_chance:
                        # 🎯 Fix 53 라스트 챈스 = 3단계 동일 자본 (base × 6 = 1800!)
                        # compute_reentry_capital(3, ...)와 동일 결과 재사용!
                        _prev_caps = [
                            _D(str(_base_capital)),
                            _D(str(_base_capital)) * _D("2"),
                        ]
                        _entry_capital_dec = compute_reentry_capital(3, _prev_caps)
                        if _entry_capital_dec is None:
                            # 🎯 Fix 103 A: 옛 = 무로그!
                            skipped += 1
                            _bump("capital_none_lastchance")
                            logger.warning(
                                "[RT_REENTRY] skip: %s %s 라스트 챈스 자본 계산 None "
                                "(base=%.2f prev=%s)",
                                symbol, side, float(_base_capital), _prev_caps,
                            )
                            continue
                        _entry_capital = float(_entry_capital_dec)
                        _mult = _entry_capital / float(_base_capital)
                        _mult_label = f" ×{_mult:.2f} ({_stage}단계 🚨라스트 챈스!)"
                        logger.warning(
                            "[RT_REENTRY] 🚨 Fix 53 라스트 챈스: %s %s base=%.0f → %.0f USDT (마지막 1회!)",
                            symbol, side, float(_base_capital), _entry_capital,
                        )
                    else:
                        # 이전 진입 자본 리스트 구성!
                        _prev_caps = [_D(str(_base_capital))]
                        if _stage == 3:
                            # 2단계 자본 = base × 2 (실 이력 없이 규정 기반 재구성!)
                            _prev_caps.append(_D(str(_base_capital)) * _D("2"))
                        _entry_capital_dec = compute_reentry_capital(_stage, _prev_caps)
                        if _entry_capital_dec is None:
                            # 🎯 Fix 103 A: 옛 = 무로그! (stage 상한 초과 = 조용히 사라짐!)
                            skipped += 1
                            _bump(f"capital_none_stage{_stage}")
                            logger.warning(
                                "[RT_REENTRY] skip: %s %s stage=%d 자본 계산 None "
                                "(base=%.2f prev=%s) = compute_reentry_capital 상한!",
                                symbol, side, _stage, float(_base_capital), _prev_caps,
                            )
                            continue
                        _entry_capital = float(_entry_capital_dec)
                        _mult = _entry_capital / float(_base_capital)
                        _mult_label = f" ×{_mult:.2f} ({_stage}단계)"
                        logger.info(
                            "[RT_REENTRY] 🎯 v219 마틴게일 %d단계: %s %s base=%.0f → %.0f USDT (×%.2f)",
                            _stage, symbol, side, float(_base_capital), _entry_capital, _mult,
                        )
                cfg = {"capitals": [_entry_capital], "leverage": 2}
                _reason_suffix += _mult_label  # UI 배지에 ×1.50 표시!
                if _use_success_reentry:
                    _suffix = "_success"
                elif _is_last_chance:
                    _suffix = "_lastchance"  # Fix 53 = 라스트 챈스 마킹!
                else:
                    _suffix = f"_reentry{re_count + 1}"
                new_strategy = _create_auto_bb_strategy(
                    db, symbol, side, cfg,
                    strategy_type_suffix=_suffix,
                )
                if not new_strategy:
                    # 🚨 Fix 103 A: 옛 = 무로그! = 「gate 전부 통과했는데 진입 0건」 미궁!
                    skipped += 1
                    _bump("create_strategy_failed")
                    logger.warning(
                        "[RT_REENTRY] 🚨 skip: %s %s _create_auto_bb_strategy None 반환! "
                        "(capital=%.2f suffix=%s) = 전략 생성 단계 차단!",
                        symbol, side, _entry_capital, _suffix,
                    )
                    continue

                # 🎓 v218 fix (2026-08-22 사장님!): entry_snapshot 저장 = 학습 데이터!
                _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
                # 🎯 v221: 실제 지표 값 저장 = 학습 사이클 완성!
                # 🎯 Fix 99 (2026-08-25): CCI + 볼륨 + 4h MACD 추가 = 5중 지표 학습!
                # 🎯 Fix 102 (2026-08-26): 다이버전스 + BB 위치 + 4H MACD 소프트 = 8중 학습!
                _rt_entry_snapshot = {
                    "rsi": _ind_snap.get("rsi"),
                    "cci": _ind_snap.get("cci"),  # 🎯 Fix 99 A: CCI 실 측정값!
                    "obv_slope_pct": _ind_snap.get("obv_slope"),
                    "macd_hist": _ind_snap.get("macd_hist"),
                    "rsi_4h": _ind_snap.get("rsi_4h"),
                    "macd_hist_4h": _ind_snap.get("macd_hist_4h"),  # 🎯 Fix 99 B!
                    "macd_4h_agree": _ind_snap.get("macd_4h_agree"),  # 🎯 Fix 102 B: 소프트!
                    "vol_ratio": _ind_snap.get("vol_ratio"),        # 🎯 Fix 99 C!
                    "passes_15m": _ind_snap.get("passes_15m"),      # core 5중!
                    "passes_bonus": _ind_snap.get("passes_bonus"),  # 🎯 Fix 102: bonus 3!
                    "passes_total": _ind_snap.get("passes_total"),  # 🎯 Fix 102: total 8!
                    # 🎯 Fix 102 D: 다이버전스 + BB 위치 (정밀 반전 신호!)
                    "divergence": _ind_snap.get("divergence"),
                    "rsi_at_extreme": _ind_snap.get("rsi_at_extreme"),
                    "bb_position_ok": _ind_snap.get("bb_position_ok"),
                    "bb_upper": _ind_snap.get("bb_upper"),
                    "bb_lower": _ind_snap.get("bb_lower"),
                    "bb_mid": _ind_snap.get("bb_mid"),
                    "regime": "REVERSAL_LONG" if side == "LONG" else "REVERSAL_SHORT",
                    "source": "RT_REENTRY_SUCCESS" if _use_success_reentry else "RT_REENTRY_FAIL",
                    "kst_hour": _kst_hour,
                    "rt_reentry_price": mp,
                    "prev_stop_price": _stop_price,
                    "rebound_pct": round(_rebound_pct, 4),
                    "indicator_msg": _ind_msg,
                    "learning_msg": _learn_msg,
                    "reentry_count": re_count + 1 if not _use_success_reentry else 0,
                    "is_last_chance": _is_last_chance,  # 🎯 Fix 53 마킹!
                    "fix99_applied": True,  # 🎯 Fix 99 마킹 (학습 데이터 필터링 용!)
                    "fix102_applied": True,  # 🎯 Fix 102 마킹 (완화 + 다이버전스/BB!)
                    "entered_at": datetime.now(timezone.utc).isoformat(),
                }
                # StrategySuggestion 기록!
                sugg = StrategySuggestion(
                    symbol=symbol, side=side,
                    suggestion_type="bb4h_auto_entry",
                    strategy_config={
                        "capitals": cfg["capitals"],
                        "symbol": symbol, "side": side,
                        "rt_reentry": True,
                        "rt_reentry_price": mp,
                        "prev_stop_price": _stop_price,
                        "entry_snapshot": _rt_entry_snapshot,  # 🎓 v218!
                    },
                    confidence_score=Decimal("0.65"),
                    reason=_reason_suffix,
                    status="EXECUTED",
                    execution_mode="AUTO",
                    executed_at=datetime.now(timezone.utc),
                    executed_strategy_id=new_strategy.id,
                    outcome_status="PENDING",
                )
                db.add(sugg)

                if _use_success_reentry:
                    _reset_reentry_count(symbol, side)
                    entered_success += 1
                else:
                    _increment_reentry_count(symbol, side)
                    entered_fail += 1

                db.commit()
                remaining -= 1
                results.append({
                    "symbol": symbol, "side": side,
                    "reason": _reason_suffix,
                    "strategy_id": new_strategy.id,
                })
                logger.info(
                    "[RT_REENTRY] ✅ %s %s: %s (id=%d)",
                    symbol, side, _reason_suffix, new_strategy.id,
                )
            except Exception as e:
                logger.warning("[RT_REENTRY] %s %s 진입 실패: %s", symbol, side, e)
                skipped += 1
                _bump("entry_exception")
                db.rollback()

        # 🚨 Fix 103 B: 정상 완료 = 반드시 완료 로그! (매 30초 = 살아있음 증명!)
        # level=warning 고정 = 「재진입 0건」이 warning 필터에서도 반드시 보여야 함!
        # (사장님 지적 "손절후 2단계 진입이 없는것 같이" = 이 줄 1개로 즉시 판정!)
        return _finish(
            f"정상 스캔 완료 (재진입 슬롯 {used}/{daily_limit} src={_limit_src})"
        )
    except Exception as e:
        logger.exception("[RT_REENTRY] 실행 실패: %s", e)
        return _finish(f"실행 예외: {e}", level="error", error=str(e))
    finally:
        db.close()
