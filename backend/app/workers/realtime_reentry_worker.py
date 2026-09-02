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
# 🌟 Fix 301: 재진입 대기 목록 (화면용). API 가 이 키를 읽는다.
WATCHLIST_REDIS_KEY = "reentry:watchlist"
WATCHLIST_TTL_SEC = 300        # 주기 30초의 여유 배수 — 죽으면 조용히 비워진다

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


REENTRY_CONCURRENT_SLOTS_KEY = "sajangnim_reentry_concurrent_slots"
REENTRY_CONCURRENT_SLOTS_DEFAULT = 10   # 사장님 2026-09-01 「동시 포지션에서 10개」


def _get_reentry_concurrent_slots(db: Session) -> int:
    """재진입 전용 동시 슬롯 (Fix 263). 0 이하 = 재진입 OFF (명시 존중)."""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, REENTRY_CONCURRENT_SLOTS_KEY)
        if row is not None and row.value is not None and str(row.value).strip() != "":
            return int(str(row.value).strip())
    except Exception as e:
        logger.warning(
            "[RT_REENTRY] ⚠️ %s 조회 실패 = default %d: %s",
            REENTRY_CONCURRENT_SLOTS_KEY, REENTRY_CONCURRENT_SLOTS_DEFAULT, e,
        )
    return REENTRY_CONCURRENT_SLOTS_DEFAULT


def _count_active_reentry(db: Session) -> int:
    """지금 살아 있는 **재진입** 전략 수.

    템플릿 이름의 suffix(_reentry1 / _reentry2 / _lastchance / _success)로 센다 —
    재진입 전략을 만들 때 _create_auto_bb_strategy 에 넘기는 그 값이다.

    🚨 Fix 265: 반드시 **ilike**(대소문자 무시)여야 한다.
       실제 저장 형태는 **대문자**다:
           AUTO_BB_BROCCOLIF3BUSDT_LONG_20260901_001407_REENTRY1
       처음에 `.like("%_reentry%")` 로 짰더니 **항상 0** 을 돌려줬고,
       그 결과 전용 슬롯(10)이 사실상 **무제한**으로 열려 있었다.
       실측으로 갈렸다: LIKE 0건 / ILIKE 1건 (같은 시점, 같은 조건).
    """
    from app.core.strategy_status import ACTIVE_LIKE
    from app.models.strategy_template import StrategyTemplate
    try:
        rows = db.execute(
            select(StrategyInstance.id)
            .join(StrategyTemplate,
                  StrategyTemplate.id == StrategyInstance.strategy_template_id)
            .where(StrategyInstance.status.in_(tuple(ACTIVE_LIKE)))
            .where(
                StrategyTemplate.name.ilike("%_reentry%")
                | StrategyTemplate.name.ilike("%_lastchance%")
                | StrategyTemplate.name.ilike("%_success%")
            )
        ).scalars().all()
        return len(rows)
    except Exception as e:
        # 🚨 fail-closed — 셀 수 없으면 슬롯이 꽉 찬 것으로 본다 (자본이 나가는 판정).
        logger.warning("[RT_REENTRY] 활성 재진입 수 조회 실패 = 상한으로 간주: %s", e)
        return REENTRY_CONCURRENT_SLOTS_DEFAULT


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
        # 🚨 Fix 228: 위 obv_slope 는 **원 계약수량 델타**다(정규화 없음).
        #   아래 반전 판정(obv_rev)은 같은 단위끼리 비교하므로 그대로 두고,
        #   **기록용 % 필드에는 정규화된 값**을 따로 담는다.
        #   옛 코드는 이 원단위를 그대로 "obv_slope_pct" 로 저장해
        #   실측 최대 2,249,160 같은 값을 30초마다 새로 만들고 있었다.
        from app.services.obv_metrics import obv_direction_ratio
        snapshot["obv_dir"] = obv_direction_ratio(obv, vols)
        snapshot["obv_slope_raw_3bar"] = obv_slope_now
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


def _get_base_capital_from_instance(si: StrategyInstance) -> float | None:
    """v218 (2026-08-22): 청산된 원 전략의 base capital 조회!

    사장님 사상: 마틴게일 = 이전 포지션 대비 1.5배!
    → 이전 포지션의 원 자본 = 정확한 base 필요!

    조회 순서:
    1. template.stages_config['capitals'][0] (JSONB 구조!)
    2. template.stage1_capital (Decimal fallback!)
    3. template.total_capital (Decimal fallback!)
    4. None (Fix 237: 옛 500.0 리터럴 제거 — 모르면 재진입 안 함)
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
    # 🚨 Fix 237 (2026-08-31 사장님): 옛 코드는 여기서 500.0 을 돌려줬다.
    #   사다리가 무너졌을 때 10 이 아니라 **500 으로 진입**하는 fail-BIG 이었다.
    #   원 전략의 자본을 모르면 그 자본의 배수도 알 수 없다 → 재진입하지 않는다.
    return None


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


def _build_order_price_map(
    db: Session, instance_ids: list[int],
) -> dict[int, dict[str, float]]:
    """🚨 Fix 105 A: 체결 주문 avg_price 배치 조회 = stop_price 3/4순위 소스!

    사장님 사상: 재진입 = 「손절가 대비 +N% 반등 시 진입」
    → 손절가(last_liquidation_price)/평단(avg_entry_price) 이 둘 다 결손이어도
      **실제 체결가**가 orders 테이블에 남아있으면 반등% 계산 가능!

    - "exit"  = 마지막 EXIT 체결가 = 실 청산가 (= 손절가 그 자체!)
    - "entry" = 첫 ENTRY 체결가   = 1단계 실 진입 평단

    배치 1회 조회 = 후보 N건이어도 쿼리 1번 (Fix 104 배치 패턴 동일!).
    fail-safe = 실패 시 빈 dict = 아래 순위(start_price)로 자연 강등!
    """
    out: dict[int, dict[str, float]] = {}
    if not instance_ids:
        return out
    try:
        from app.models.order import Order

        rows = db.execute(
            select(Order.strategy_instance_id, Order.purpose, Order.avg_price)
            .where(Order.strategy_instance_id.in_(list(instance_ids)))
            .where(Order.status.in_(("FILLED", "PARTIALLY_FILLED")))
            .where(Order.avg_price.isnot(None))
            .order_by(Order.strategy_instance_id, Order.id)  # id asc = 시간순!
        ).all()
        for _sid, _purpose, _avg in rows:
            try:
                px = float(_avg or 0)
            except (TypeError, ValueError):
                continue
            if px <= 0:
                continue
            slot = out.setdefault(_sid, {})
            if str(_purpose or "").upper() == "EXIT":
                slot["exit"] = px      # 덮어쓰기 = 마지막 EXIT (= 최종 청산가!)
            elif "entry" not in slot:
                slot["entry"] = px     # 최초 1회만 = 첫 ENTRY (= 1단계 진입가!)
        logger.info(
            "[Fix105] 체결가 배치 조회: instance %d건 중 %d건 확보 (1 query!)",
            len(instance_ids), len(out),
        )
    except Exception as e:
        logger.warning(
            "[Fix105] 체결가 배치 조회 실패 (fallback 축소 = start_price 로 진행): %s", e,
        )
    return out


def _classify_entry_error(msg: str) -> str:
    """🚨 Fix 105 B: 진입 예외 메시지 → 원인 분류 (「entry_exception 5건」 정체 노출!).

    create_strategy_instance 는 12개 가드가 모두 bare ValueError → worker 가
    「어느 가드에 막혔는지」 구별 불가 = 사실상 silent bug (헌법 위반!).
    → 메시지 패턴으로 분류해 완료 로그/응답에 사유를 명시!
    """
    m = str(msg or "")
    # 🚨 Fix 169 (2026-08-26): kill-switch 분기가 없어 전부 "other" 로 뭉뚱그려졌다.
    # 2026-08-26 KS 사건 때 진입이 전부 막혔는데 진단 로그는 "other" 만 찍어서
    # 원인 파악이 늦어졌다. KS 메시지는 두 가지 형태로 온다:
    #   execution_service.py:192  "Account kill-switch is enabled; new orders are blocked"
    #   strategy_service.py:222   "🔒 거래소 계정 #N 의 Kill-Switch 가 활성화돼 신규 거래가 차단됐습니다."
    _low = m.lower()
    if "kill-switch" in _low or "kill switch" in _low or "killswitch" in _low:
        return "kill_switch"
    # 상한(동시보유) 차단 — position_limit.check_position_slot 사유 문자열
    if "동시보유 상한" in m or "자동 진입 완전 OFF" in m:
        return "concurrent_cap"
    if "동시 운영 한도" in m or "진행 중인 전략이" in m:
        return "concurrent_limit"
    if "포지션" in m and "이미 있습니다" in m:
        return "residual_exchange_position"
    if "잔액" in m or "availableBalance" in m or "부족" in m:
        return "insufficient_balance"
    if "마진" in m or "130" in m:
        return "margin_reserve_exceeded"
    if "허용되지 않습니다" in m or "화이트리스트" in m:
        return "symbol_not_allowed"
    if "현재가 조회 실패" in m:
        return "no_start_price"
    if "not in DB" in m:
        return "symbol_not_in_db"
    if "통신 실패" in m:
        return "binance_api_error"
    return "other"


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

    # 🚨 Fix 105 A (2026-08-26): stop_price 다단 fallback (no_stop_price 21건 → 0!)
    # ※ Fix 104 와 동일하게 함수 최상단 초기화 필수! (_finish 가 payload 에 싣는데
    #   조기 return 경로는 루프 시작 전에 _finish 호출 = 미초기화 시 NameError!)
    order_px_map: dict[int, dict[str, float]] | None = None  # lazy = 결손 0건이면 쿼리 X!
    stop_px_srcs: dict[str, int] = {}   # 어느 소스로 기준가를 잡았나 (추적!)
    # 🚨 Fix 105 B: 진입 예외 정체 노출 = 메시지/분류를 응답에도 실어 보냄!
    entry_error_kinds: dict[str, int] = {}
    entry_errors: list[str] = []

    # ═══════════════════════════════════════════════════════════════════
    # 🌟 Fix 301 (2026-09-03 사장님): **재진입 대기 목록을 화면에 남긴다.**
    #
    #   사장님: "재진입 모니터링을 첫진입과 두번째 진입에서 실패하면 지금은 모두
    #            청산인데 99% 청산하고 다음 포지션을 진입하는 로직은 어떤가?
    #            ... 대기 모니터링도 전략 인스턴스에 남겨두고 종료 숨김 처럼
    #            선택적으로 볼수 있게 하는것도 좋은것 같아"
    #
    #   🚨 **99% 잔량 방식은 재진입을 완전히 막는다.** 이 워커는 후보를
    #      `status ∈ TERMINAL_STATUSES` (= 청산 완료) 에서 고르고,
    #      그 다음 `if symbol in active_syms: continue` 로 **활성 심볼을 건너뛴다**.
    #      1% 를 남기면 상태가 STAGE*_OPEN 으로 살아 있어 두 관문에 다 걸린다.
    #      → 그 심볼은 재진입 후보에서 **영구 제외**된다. 의도와 정반대다.
    #
    #   추가로 거래소 제약도 있다 — MIN_NOTIONAL 5.00 USDT.
    #      1차 진입 10 USDT × 레버 2 = 명목 20, 그 1% 는 **0.20 USDT**.
    #      reduceOnly 주문이 거부되어 **영원히 못 파는 dust** 가 된다
    #      (이 저장소는 dust orphan 하나로 계정 전체가 막힌 적이 있다).
    #
    #   그래서 사장님이 2안으로 제시하신 「대기 모니터링을 남기고 선택적으로
    #   보기」를 택한다. 포지션은 지금처럼 100% 청산하고, **감시 중인 심볼과
    #   각각이 왜 아직 진입 안 했는지**를 심볼별로 남겨 화면에 띄운다.
    #
    #   지금까지 사유는 `skip_reasons` 집계 카운트뿐이라 「어느 심볼이 왜」를
    #   알 수 없었다 — 사장님이 나에게 물어야만 알 수 있었다 (Fix 200 과 같은 성격).
    # ═══════════════════════════════════════════════════════════════════
    _watch: list[dict] = []              # 심볼별 판정 기록 (화면용)
    # ⚠️ 홀더를 **리스트 1칸**으로 둔다. 클로저가 dict 객체 하나를 잡아 두면
    #    루프마다 그 객체를 재사용하게 되고, `_watch` 에 담긴 것들이 전부
    #    같은 dict 를 가리켜 마지막 심볼의 값으로 덮인다.
    _cur_ref: list[dict | None] = [None]

    def _note(**kv) -> None:
        """현재 심볼 카드에 판정 재료를 붙인다 (루프 밖 호출은 무시)."""
        _c = _cur_ref[0]
        if _c is not None:
            _c.update(kv)

    def _bump(reason: str) -> None:
        """🎯 Fix 103 A: skip 사유 집계 = 완료 로그 1줄로 원인 판정!"""
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
        # Fix 301: 집계와 **함께** 심볼별로도 남긴다 (마지막 사유 = 막힌 이유)
        _c = _cur_ref[0]
        if _c is not None:
            _c["reason"] = reason

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
            # 🚨 Fix 105 A: 기준가를 어느 소스로 잡았나 (liq/avg_entry/exit_fill/...)
            "stop_px_srcs": dict(stop_px_srcs),
            # 🚨 Fix 105 B: 진입 예외 정체 (분류 + 실 메시지 최대 5건!)
            "entry_error_kinds": dict(entry_error_kinds),
            "entry_errors": list(entry_errors),
            "note": note,
            "spec": _gate_spec(),
            "results": results,
        }
        payload.update(extra)

        # ═══════════════════════════════════════════════════════════════
        # 🌟 Fix 301: 재진입 대기 목록을 Redis 에 남긴다 (화면이 읽는다).
        #   ⚠️ 기록 실패가 재진입을 막으면 안 된다 — 전부 fail-open.
        #   TTL 은 주기(30초)의 여유 배수. 워커가 죽으면 화면도 조용히 비워져
        #   「낡은 목록을 최신인 척」 보여주지 않는다.
        # ═══════════════════════════════════════════════════════════════
        payload["watchlist"] = _watch
        try:
            import json as _json
            from app.core.redis_client import get_redis_client as _grc
            _grc().setex(
                WATCHLIST_REDIS_KEY, WATCHLIST_TTL_SEC,
                _json.dumps({
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "note": note,
                    "candidates": candidates,
                    "entered": entered_fail + entered_success,
                    "items": _watch,
                }, default=str),
            )
        except Exception as _we:
            logger.debug("[Fix301] watchlist 기록 실패 (계속): %s", _we)

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

        # 🎯 Fix 112 (2026-08-26 사장님 verbatim "일 20개 최대 20개"):
        #   재진입도 「새 포지션」을 만든다! (JASMYUSDT #1480 이 그 증거!)
        #   → 동시 보유 상한을 재진입에도 적용하지 않으면 활성이 계속 누적됨!
        #   (재진입 전용 일일 한도와 별개 = 둘 다 통과해야 진입!)
        from app.services.position_limit import check_position_slot
        _slot_ok, _slot_why, _act, _cap = check_position_slot(db, "RT_REENTRY")

        # ══════════════════════════════════════════════════════════════
        # 🎯 Fix 263 (2026-09-01 사장님): 재진입 **전용 동시 슬롯**
        #
        # 사장님 verbatim:
        #   "재진입은 일 10개로 해줘 **일 최대 동시 포지션에서 10개는 가능하게** 해줘"
        #
        # 옛 동작: 전체 동시보유 상한(50)이 차면 재진입도 **통째로** 막혔다.
        #   신규 진입이 슬롯을 다 먹으면 재진입은 영원히 차례가 오지 않는다.
        # 신 동작: 현재 활성인 **재진입 전략** 수가 전용 슬롯 미만이면
        #   전체 상한과 무관하게 진행한다.
        #
        # ⚠️ 최악의 경우 총 활성 = 전체상한 + 전용슬롯 이 될 수 있다.
        #    자본은 1건당 1단계 금액이므로 상한이 명확하고, 사장님이
        #    슬롯 수를 SystemSetting 으로 바로 줄일 수 있다.
        # ══════════════════════════════════════════════════════════════
        # 💰 Fix 264: 잔액이 바닥나면 후보를 훑어봐야 전부 실패한다.
        #   조기 종료해 캔들·지표 API 낭비를 멈춘다. 플래그는 TTL 로 저절로 풀린다.
        try:
            from app.core.redis_client import get_redis_client as _grc264
            from app.services.balance_guard import check_balance_block as _bal_block
            _blocked, _bal_d = _bal_block(_grc264())
            if _blocked:
                return _finish(
                    f"💰 가용 잔액 부족 — 필요 {_bal_d.get('required')} / "
                    f"가용 {_bal_d.get('available')} USDT "
                    f"(출처 {_bal_d.get('source')}) = 진입 시도 일시 중단"
                )
        except Exception as _bg_e:
            logger.debug("[RT_REENTRY+Fix264] 잔액 가드 조회 실패 (계속): %s", _bg_e)

        _re_slots = _get_reentry_concurrent_slots(db)
        _re_active = _count_active_reentry(db)
        _re_room = _re_slots - _re_active
        if _re_room <= 0:
            return _finish(
                f"재진입 전용 동시 슬롯 소진: {_re_active}/{_re_slots} "
                f"(전체 동시보유 {_act}/{_cap})"
            )
        if not _slot_ok:
            logger.info(
                "[RT_REENTRY+Fix263] 전체 동시보유 상한(%s) 이지만 재진입 전용 슬롯 "
                "%d/%d 남음 → 진행 (사장님 「동시 포지션에서 10개는 가능하게」)",
                _slot_why, _re_room, _re_slots,
            )

        # 🚨 Fix 112b: 위 체크는 「루프 시작 전 1회」 뿐!
        #   remaining 은 재진입 「일일」 예산이라 루프를 그것만으로 돌면
        #   한 번에 여러 건이 나가 상한을 넘는다.
        #   → 루프 예산을 **전용 슬롯 여유**로 묶는다 (Fix 263).
        _slot_room = _re_room
        if _slot_room < remaining:
            logger.info(
                "[RT_REENTRY+Fix112b] 루프 예산 축소: 재진입일일 %d → 동시보유여유 %d (%d/%d)",
                remaining, _slot_room, _act, _cap,
            )
            remaining = _slot_room

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
            # ═══════════════════════════════════════════════════════════
            # 🚨 Fix 297 (2026-09-02 사장님 「손실일때 청산하고 모니터링 대기하고
            #   진입이 없었어」): 화이트리스트가 **주력 전략을 통째로 빼고 있었다.**
            #
            #   최근 7일 strategy_type 별 (재진입 후보에 드는가):
            #     auto_bb_break_*   254건  ✅
            #     pump_split         68건  🚨 빠져 있었다  ← 사장님 주력(볼밴 분할)
            #     DYNAMIC_LONG/SHORT 42건  (수동 `_quick_`)
            #     bb_mid_line         7건  (오늘 신설)
            #
            #   오늘 손절된 25건 중 **13건이 후보에서 제외**됐다.
            #
            #   → `pump_split` 을 **추가**한다. 다단계 물타기 전략이라
            #     「짧은 손절 후 적당한 시점에 재진입」 사상과 맞고, 재진입 워커에는
            #     이미 반등 1% + 대기 3분 + 볼륨 1.3x + 지표 반전 게이트가 걸려 있다.
            #
            #   ⚠️ **일부러 넣지 않는 것들** (넣으면 안 되는 이유가 있다):
            #     · DYNAMIC_* (수동) — 오늘 수동이 -124.72 를 잃었다. 자동 재진입을
            #       붙이면 그 손실을 **자동화**한다. 사상 ⑦(욕심 제어) 정면 위반.
            #       수동 진입은 사장님 판단이고, 그 뒤처리도 사장님 판단이어야 한다.
            #     · bb_mid_line / surge_peak_ladder — **1회 진입 전략**이고 자기
            #       쿨다운(8시간)·자기 재도전 사다리를 이미 갖고 있다
            #       (services/single_entry_guard.py 참조). 남의 재진입을 얹으면
            #       그 설계가 깨진다 — Fix 213/214/282/283 과 같은 성격이다.
            # ═══════════════════════════════════════════════════════════
            .where(
                or_(
                    StrategyTemplate.strategy_type.like('auto_bb_break%'),
                    StrategyTemplate.strategy_type.like('sajangnim_top%'),
                    StrategyTemplate.strategy_type.like('realtime_reentry%'),
                    StrategyTemplate.strategy_type.like('chart_pattern%'),
                    StrategyTemplate.strategy_type.like('pump_split%'),   # Fix 297
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
            .where(
                StrategyInstance.status.in_(list(ACTIVE_LIKE)),
                StrategyInstance.is_archived.is_(False),  # Fix 171 (헌법 108): 보관된 전략이 심볼을 점유하지 않도록
            )
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
            # Fix 301: 이 심볼의 판정 카드를 만들고 `_watch` 에 **그 객체를** 넣는다.
            #          사본을 넣으면 이후 `_bump`/`_note` 갱신이 반영되지 않는다.
            _card = {
                "symbol": symbol, "side": side,
                "strategy_id": si.id,
                "stopped_at": si.stopped_at.isoformat() if si.stopped_at else None,
                "reason": None, "entered": False,
            }
            _watch.append(_card)
            _cur_ref[0] = _card
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
            # ═══════════════════════════════════════════════════════════════
            # 🎯 Fix 135 (2026-08-26 사장님 지시): 사다리 소진 → 「1단계로 리셋」
            #
            # 사장님 verbatim:
            #   "손실일때 -10%정도되면 청산하고 마틴게일 1단계 모니터링 대기하고
            #    조건에 맞으면 1단계 진입하게 해줘"
            #
            # 옛 동작: 사다리(10→300→600)를 다 쓰면 그 심볼은 「영구 종료」.
            #          카운터가 max 에 걸린 채 TTL(7일)이 지나야만 풀렸다.
            # 신 동작: 소진되면 카운터를 0 으로 되돌려 「1단계(10 USDT) 대기」로 복귀.
            #          10 USDT 탐색 진입이므로 재시작 리스크가 작다 (= 사장님 설계 의도).
            #
            # ⚠️ 즉시 재진입이 아니다. 카운터만 리셋하고 이번 사이클은 skip 하므로,
            #    다음 사이클에 「1단계 진입 조건」을 처음부터 다시 통과해야 한다.
            # ═══════════════════════════════════════════════════════════════
            if re_count >= _max_count_effective:
                try:
                    _reset_reentry_count(symbol, side)
                    logger.warning(
                        "[RT_REENTRY+Fix135] %s %s 사다리 소진(%d/%d) → 카운터 리셋 = "
                        "1단계(탐색 진입) 모니터링 대기로 복귀",
                        symbol, side, re_count, _max_count_effective,
                    )
                    _bump("ladder_exhausted_reset_to_stage1")
                except Exception as _re:
                    logger.warning("[Fix135] %s 카운터 리셋 실패: %s", symbol, _re)
                    _bump("max_reentry_count")
                skipped += 1
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
            # 🚨 Fix 105 A (2026-08-26): stop_price 다단 fallback (no_stop_price 21건 → 0!)
            # 사장님 사상 = 재진입 = 「손절가 대비 +N% 반등 시 진입」
            #   → 손절가가 없으면 평단/실 체결가/시작가로 대체 가능!
            #     (SL -5% 로 청산됐으면 손절가 ≈ 평단 × 0.95, SHORT 는 × 1.05)
            # ⚠️ 1/2순위는 기존과 100% 동일 = 지금 통과 중인 후보의 판정 불변!
            #    (exit_fill 이 의미상 손절가에 더 가깝지만, 기존 동작 보존을 위해 3순위!)
            # ※ 근본 원인 = stream_service ACCOUNT_UPDATE 의 ep="0.0" truthy 함정이
            #   avg_entry_price 를 0 으로 파괴 → Fix 105 C 에서 별도 fix!
            # ═══════════════════════════════════════════════════════════
            # 🚨 Fix 296 (2026-09-02): 위 주석이 적어 둔 것을 **코드가 안 하고 있었다.**
            #
            #   주석: "(SL -5% 로 청산됐으면 손절가 ≈ 평단 × 0.95, SHORT 는 × 1.05)"
            #   코드: `_stop_price = avg_entry_price` — 환산을 **안 한다**.
            #
            #   그래서 LONG 이 평단 -5% 에서 손절됐어도 기준가가 「평단」이 되고,
            #   재진입에 필요한 +1% 반등이 **평단보다 위**를 뜻하게 된다
            #   = 손절당한 가격보다 6% 비싸게 사야 재진입 = 사장님 사상의 정반대.
            #   실측: 재진입 후보 19건 전부 이 경로였고 16건이 rebound_too_small.
            #
            #   → ① 실 청산 체결가(exit_fill)를 **2순위로 올린다** — 그게 손절가 자체다.
            #     ② 평단으로 내려가면 **손절 ROI 로 역산**한다 (주석대로).
            #   ⚠️ Fix 295 로 앞으로는 1순위(liq)가 항상 채워지므로, 이 경로는
            #      **과거 데이터 구제용**이다.
            # ═══════════════════════════════════════════════════════════
            _stop_price = float(si.last_liquidation_price or 0)
            _px_src = "liq"
            if _stop_price <= 0:
                # 2순위 = 실 청산 체결가 (배치 1회 조회 = lazy)
                if order_px_map is None:
                    order_px_map = _build_order_price_map(db, [c.id for c in closed])
                _exit_px = float((order_px_map.get(si.id) or {}).get("exit") or 0)
                if _exit_px > 0:
                    _stop_price = _exit_px
                    _px_src = "exit_fill"
            if _stop_price <= 0:
                # 3순위 = 평단에서 **손절 ROI 를 역산**해 손절가를 추정한다
                _avg = float(si.avg_entry_price or 0)
                if _avg > 0:
                    try:
                        _lev = float(si.leverage or 1) or 1.0
                        _sl_roi = float(si.force_sl_roi_override or 0)
                        # ROI% = 가격변동% x 레버리지  →  가격변동% = ROI% / 레버
                        _pp = abs(_sl_roi) / _lev if _sl_roi else 5.0
                        _pp = min(max(_pp, 0.5), 50.0)      # 방어: 0.5~50%
                    except Exception:
                        _pp = 5.0
                    _stop_price = _avg * ((1 - _pp / 100) if side == "LONG"
                                          else (1 + _pp / 100))
                    _px_src = f"avg_entry-{_pp:.1f}%"
            if _stop_price <= 0:
                # 4순위 = orders 진입 체결가 / 시작가
                if order_px_map is None:
                    order_px_map = _build_order_price_map(
                        db, [c.id for c in closed],
                    )
                _slot = order_px_map.get(si.id) or {}
                _exit_px = float(_slot.get("exit") or 0)
                _entry_px = float(_slot.get("entry") or 0)
                if _exit_px > 0:
                    _stop_price = _exit_px
                    _px_src = "exit_fill"      # 실 청산 체결가 = 손절가 그 자체!
                elif _entry_px > 0:
                    _stop_price = _entry_px
                    _px_src = "entry_fill"     # 1단계 실 진입가 (평단 근사!)
            if _stop_price <= 0:
                # 5순위 = start_price (NOT NULL 컬럼 = 최후 보루!)
                _stop_price = float(si.start_price or 0)
                _px_src = "start_price"
            if _stop_price <= 0:
                # 🎯 Fix 103 A: 옛 = 무로그 continue! (전 소스 결손 = 데이터 결함!)
                # 🚨 Fix 105 A: 「최종 실패」 시에만 집계 = Fix 103 카운터 왜곡 방지!
                skipped += 1
                _bump("no_stop_price")
                logger.warning(
                    "[RT_REENTRY] skip: %s %s 기준가 전 소스 결손! "
                    "(liq=%s avg_entry=%s orders=%s start_price=%s instance_id=%s) "
                    "= 반등%% 계산 불가!",
                    symbol, side, si.last_liquidation_price, si.avg_entry_price,
                    (order_px_map or {}).get(si.id), si.start_price, si.id,
                )
                continue
            stop_px_srcs[_px_src] = stop_px_srcs.get(_px_src, 0) + 1
            if _px_src != "liq":
                logger.info(
                    "[RT_REENTRY] 🚨 Fix105 기준가 fallback: %s %s src=%s px=%s "
                    "(liq 결손 → 대체 소스 적중!)",
                    symbol, side, _px_src, _stop_price,
                )

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

            # Fix 301: 「얼마나 더 반등해야 들어가는가」를 화면에 보여준다
            _note(stop_price=float(_stop_price), mark=float(mp),
                  rebound_pct=round(float(_rebound_pct), 3),
                  rebound_need_pct=float(REBOUND_PCT_MIN_SAFETY))

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

                # 🎯 Fix 111 Part B (2026-08-26): 재진입에도 「새 정점」 확인!
                #
                # 사장님 JASMYUSDT 지적: "지금 진입이 첫진입을 해야 하는데
                #                        지금은 재진입으로 포지션에 진입한거야"
                #
                # 근본 결함: 옛 재진입은 「옛 손절가 대비 반등」 + 「범용 지표 반전」만 봄.
                #   → 새로 형성된 정점의 조건(반복 상승 + 지표 꺾임)은 한 번도 확인 X!
                #   → 첫 진입에는 Fix 111 게이트가 있는데 재진입엔 없었음 = 비대칭!
                #   → 결과: 첫 진입보다 재진입이 「더 느슨한」 기준으로 통과 (역전!)
                #
                # 신: 첫 진입과 똑같은 정점 게이트를 재진입에도 적용 = 대칭 (헌법 5!)
                if _ind_ok:
                    from app.services.peak_confirmation import confirm_peak
                    _rpk_ok, _rpk_why, _rpk_det = confirm_peak(_bc, symbol, side)
                    if not _rpk_ok:
                        _ind_ok = False
                        _ind_msg = f"{_ind_msg} | Fix111 정점 미확인: {_rpk_why}"
                        logger.warning(
                            "[RT_REENTRY+Fix111] %s %s 재진입 차단: %s | %s",
                            symbol, side, _rpk_why, _rpk_det,
                        )
                    else:
                        _ind_snap["fix111_peak"] = _rpk_det
                        _ind_msg = f"{_ind_msg} | Fix111 {_rpk_why}"
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

            # 🚨 Fix 105 B (2026-08-26): 동시 운영 한도 preflight!
            # create_strategy_instance 의 12개 가드는 전부 bare ValueError →
            # worker 에선 「entry_exception」 한 덩어리로만 보임 = 원인 불명 (silent!).
            # 그중 1순위 용의자(동시 한도)는 **미리** 판정 가능 → 전용 skip 사유로 승격!
            # (덤으로 한도 초과 시 Binance get_account() 왕복도 절약!)
            try:
                from app.core.config import settings as _cfg_settings
                _max_conc = max(1, int(_cfg_settings.max_concurrent_strategies_per_account))
                # strategy_service.create_strategy_instance 의 가드와 **완전 동일 조건**!
                # (_CLOSED_STATUSES = TERMINAL_STATUSES / exchange_account_id 별 집계)
                # _create_auto_bb_strategy 는 exchange_account_id=1 고정 진입!
                _live_cnt = len(
                    db.execute(
                        select(StrategyInstance.id)
                        .where(StrategyInstance.exchange_account_id == 1)
                        .where(StrategyInstance.status.notin_(list(TERMINAL_STATUSES)))
                    ).all()
                )
                if _live_cnt >= _max_conc:
                    skipped += 1
                    _bump("concurrent_limit_full")
                    logger.warning(
                        "[RT_REENTRY] 🚨 skip: %s %s 동시 운영 한도! (비종료 전략 %d개 "
                        ">= max_concurrent_strategies_per_account=%d) "
                        "= 재진입 전 활성 전략 정리 필요! (옛 entry_exception 의 정체!)",
                        symbol, side, _live_cnt, _max_conc,
                    )
                    continue
            except Exception as _pc_e:
                # fail-open = preflight 실패는 진입을 막지 않음 (기존 동작 유지!)
                logger.warning("[RT_REENTRY] 동시 한도 preflight 실패 (fail-open): %s", _pc_e)

            # 🚨 Fix 105 B: except 블록에서 반드시 참조 가능해야 함!
            # (미할당 NameError 방지 + 직전 iteration 값이 새는 stale 오진 방지!)
            _dbg_stage = 2 if _use_success_reentry else (re_count + 2)
            _entry_capital = None
            _suffix = None

            # 진입 실행!
            try:
                # 🎯 v219 사장님 최종 마틴게일 (2026-08-22!):
                # "300 600 1800" = 1단계 초기 / 2단계 이전×2 / 3단계 투자금전체×2
                # "3단계까지 갈수 있다야 가능하면 가지않는 관리가 필요"
                # 🎯 Fix 53 (2026-08-24): 4단계 = 라스트 챈스 (동일 자본!)
                _base_capital = _get_base_capital_from_instance(si)
                if _base_capital is None or float(_base_capital) <= 0:
                    # 🚨 Fix 237: 원 전략의 자본을 모르면 그 배수도 모른다 = 진입 안 함.
                    skipped += 1
                    logger.warning(
                        "[Fix237] #%s %s 원 전략 자본 불명 = 재진입 skip "
                        "(하드코딩 500 금지 — 사장님이 정한 값만 쓴다)",
                        si.id, si.symbol,
                    )
                    continue
                _is_last_chance = False  # Fix 53 라스트 챈스 여부!
                # ═══════════════════════════════════════════════════════
                # 🚨 Fix 298 (2026-09-02): **자체 물타기 전략에 마틴게일 배수를
                #   얹지 않는다** — Fix 297 이 만든 위험을 막는다.
                #
                #   compute_reentry_capital 은 `_base_capital` 을 **무시하고**
                #   사장님 사다리(10/300/600)를 그대로 쓴다. 그래서 Fix 297 로
                #   pump_split 을 재진입 대상에 넣은 순간:
                #
                #       볼밴 분할 100 손절 → 재진입 **300**(×3.00) → 또 손절 시 **600**(×6.00)
                #
                #   그런데 볼밴 분할은 **이미 자체 물타기**(1→2→3차 = 100→200→500)를 한다.
                #   그 위에 마틴게일 배수를 또 얹으면 **이중 마틴게일**이고,
                #   사장님이 설정한 자본(pump_split_capitals)을 시스템이 무시하는 것이다.
                #   사상 ⑦(「욕심을 제어 못했다 · 큰손실 후 무리한 투자」) 정면 위반.
                #
                #   → 자체 물타기 전략은 **원 자본 그대로** 재진입한다 (배수 없음).
                #     사장님 사다리 마틴게일은 auto_bb 계열 전용으로 둔다.
                # ═══════════════════════════════════════════════════════
                _own_ladder = False
                try:
                    _st_type = ""
                    _tpl_of = getattr(si, "strategy_template", None)
                    if _tpl_of is not None:
                        _st_type = str(getattr(_tpl_of, "strategy_type", "") or "")
                    _own_ladder = _st_type.startswith("pump_split")
                except Exception as _oe:
                    # 판정 실패 = **배수 없음**으로 (fail-closed: 자본이 커지는 판정)
                    logger.warning("[RT_REENTRY] Fix298 판정 실패 = 배수 없음: %s", _oe)
                    _own_ladder = True

                if _own_ladder:
                    _entry_capital = float(_base_capital)
                    _mult_label = " (자체 물타기 = 배수 없음)"
                    logger.info(
                        "[RT_REENTRY] Fix298 %s %s: 자체 물타기 전략 → 원 자본 %.0f 그대로 "
                        "(사장님 사다리 마틴게일 미적용)",
                        symbol, side, float(_base_capital),
                    )
                elif _use_success_reentry:
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
                    # Fix 228: 원단위(obv_slope) 대신 정규화된 obv_dir(-1~+1)
                    "obv_slope_pct": _ind_snap.get("obv_dir"),
                    "obv_slope_raw_3bar": _ind_snap.get("obv_slope_raw_3bar"),
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
                    # 🚨 Fix 105 A: 기준가를 어느 소스로 판정했나 = 학습/추적 필수!
                    "prev_stop_price_src": _px_src,
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
                        "prev_stop_price_src": _px_src,  # 🚨 Fix 105 A!
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
                _note(entered=True, reason=None,
                      new_strategy_id=new_strategy.id)      # Fix 301

                db.commit()
                remaining -= 1
                results.append({
                    "symbol": symbol, "side": side,
                    "reason": _reason_suffix,
                    "strategy_id": new_strategy.id,
                })
                logger.info(
                    "[RT_REENTRY] ✅ %s %s: %s (id=%d, 기준가 src=%s px=%s)",
                    symbol, side, _reason_suffix, new_strategy.id, _px_src, _stop_price,
                )
            except Exception as e:
                # 🚨 Fix 105 B (2026-08-26): 옛 = logger.warning(메시지만!) =
                #   「entry_exception 5건」의 정체 불명 = 사실상 silent bug (헌법 위반!)
                #   → logger.exception = 전체 스택트레이스 필수!
                #   → 분류(_classify_entry_error) + 실 메시지를 응답 payload 에도 적재!
                # ※ _err_kind = 위 _kind (RT_REENTRY 라벨) 와 별개 변수! (shadow 방지)
                _err_kind = _classify_entry_error(str(e))
                _err_msg = (
                    f"{symbol} {side} stage={_dbg_stage} "
                    f"[{_err_kind}] {type(e).__name__}: {e}"
                )
                logger.exception(
                    "[RT_REENTRY] 🚨 진입 예외: %s %s stage=%s capital=%s suffix=%s "
                    "kind=%s → %s",
                    symbol, side, _dbg_stage, _entry_capital, _suffix, _err_kind, e,
                )
                skipped += 1
                _bump("entry_exception")
                entry_error_kinds[_err_kind] = entry_error_kinds.get(_err_kind, 0) + 1
                if len(entry_errors) < 5:
                    entry_errors.append(_err_msg[:300])
                # fail-open = 1건 예외가 전체 루프 중단 X (다음 후보 계속!)
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
