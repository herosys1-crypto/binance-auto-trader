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
REBOUND_PCT_MIN_SAFETY = 1.5    # 🎯 Fix 99 D: 0.5 → 1.5 (진짜 반전 = 노이즈 배제!)
MAX_HOURLY_REENTRIES = 5        # 1h 최대 5건 (남발 방지!)
STAGE3_MIN_WAIT_HOURS = 4.0     # 3단계 = 충분히 대기!
MIN_LEARNING_SUCCESS_RATE = 0.30  # 학습 성공률 30%+ 심볼만!

# 🎯 Fix 99 E (2026-08-25): 손절 후 최소 대기 시간 (whipsaw 방지!)
# 사장님 사상 = 정밀 재진입! → SL 직후 급변동 = skip 필수!
MIN_STOP_WAIT_MINUTES = 5.0     # 손절 후 최소 5분 대기 (whipsaw 방지!)

# 🎯 Fix 99 C (2026-08-25): 볼륨 반전 확인 = 진짜 세력!
# 반등 볼륨 = 이전 3봉 평균 × 1.5+ → 저볼륨 반등 (fake bounce!) 차단!
VOLUME_REVERSAL_MULTIPLIER = 1.5

# 🎯 Fix 53 사장님 신 사상 (2026-08-24!):
# 사장님 verbatim: "최종 단계까지 진행했는데 손실이면 -5%에서 다시 모니터링 대기하고
#                  최종단계 진입금액으로 한번더 하고 안되면 종료하는 로직으로 해줘"
# = 3단계 (1800 USDT) SL 발동 후 = 라스트 챈스 1회 (동일 자본 1800!)
# = 라스트 챈스도 SL = 완전 종료 (더 이상 재진입 X!)
# 최소 침습: 기존 v219 로직 유지 + stage 4 = 라스트 챈스만 추가!
ENABLE_LAST_CHANCE = True
MAX_REENTRY_STAGE_WITH_LAST = 4  # 3단계 + 라스트 챈스 1회!

# 🎯 Fix 99 A (2026-08-25): 3중 → 5중 반전 (계단식 강화!)
# 사장님 사상 = 정밀 재진입! → RSI/MACD/OBV/CCI/볼륨 = 5중 확인!
# 2단계 = 3/5 (loose) / 3단계 = 4/5 (엄격!) / 라스트 = 5/5 (완벽!)
MIN_PASSED_STAGE2 = 3         # 2단계 = 5중 반전 최소 3/5 (Fix 99!)
MIN_PASSED_STAGE3 = 4         # 3단계 = 5중 반전 4/5 (엄격!)
MIN_PASSED_STAGE_LAST = 5     # 라스트 챈스 = 5중 반전 5/5 (완벽!)
STAGE3_24H_ABS_LIMIT_PCT = 15.0  # 3단계+ = 24h 변동 ±15% 초과 시 반대매매 skip!


def _check_indicator_reversal_for_reentry(
    bc, symbol: str, side: str, use_4h: bool = True, min_passed: int = 3
) -> tuple[bool, str, dict]:
    """🎯 v221 사장님 재설계 (2026-08-23): 지표 반전 = 재진입 진짜 조건!
    🎯 Fix 55 P3 (2026-08-24): min_passed 인자 추가 = 단계별 계단식 강화!
    🎯 Fix 99 (2026-08-25): 3중 → 5중 강화 + 4H MACD Hist 필터 + 볼륨 gate!

    사장님 verbatim (Fix 99): "손절후 이익이 더 많은 이익이 가능해"
    = 재진입 시점만 정확하면 = 큰 수익! → 5중 반전 = 정밀 확인!

    로직 (5중 = 최소 min_passed/5 통과!):
    - 15m RSI 반전  (LONG: 상승 반전 / SHORT: 하락 반전)
    - 15m MACD hist 반전
    - 15m OBV slope 반전 (지속!)
    - 15m CCI 반전 (Fix 99 A: 4번째 = 정밀!)
    - 15m 볼륨 반등 확인 (Fix 99 A/C: 5번째 = 진짜 세력! 3봉 평균 × 1.5+)

    하드 필터 (whipsaw 방지!):
    - 4h MACD Hist 방향 (Fix 99 B): SHORT=음수 필수 / LONG=양수 필수!
    - 4h RSI 급진행 (기존): 역방향 지속 시 차단!

    min_passed (Fix 99 A):
    - 2단계 = 3/5 (loose)
    - 3단계 = 4/5 (엄격!)
    - 라스트 챈스 = 5/5 (완벽!)

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

        # 15m 5중 = 최소 min_passed/5 통과! (Fix 99 A: 계단식 강화!)
        passes = int(rsi_rev) + int(macd_rev) + int(obv_rev) + int(cci_rev) + int(vol_rev)
        snapshot["passes_15m"] = f"{passes}/5"
        snapshot["min_passed_required"] = min_passed
        snapshot["rsi_rev"] = rsi_rev
        snapshot["macd_rev"] = macd_rev
        snapshot["obv_rev"] = obv_rev
        snapshot["cci_rev"] = cci_rev
        snapshot["vol_rev"] = vol_rev

        # 6) 4h 방향 확인 = 하드 필터 (whipsaw 방지!)
        if use_4h:
            try:
                kl4 = bc.get_klines(symbol=symbol, interval="4h", limit=40)
                if isinstance(kl4, list) and len(kl4) >= 30:
                    c4 = [float(k[4]) for k in kl4]

                    # 6a) 4h RSI 역방향 급진행 = 기존 필터!
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

                    # 6b) 🎯 Fix 99 B (2026-08-25): 4h MACD Hist 방향 = 하드 필터!
                    # SHORT 재진입 = 4h 하락 지속 필요 (hist < 0)
                    # LONG 재진입 = 4h 상승 지속 필요 (hist > 0)
                    # → 4h 역방향이면 whipsaw 위험 = skip!
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
                                bad_4h_macd = (
                                    (side == "SHORT" and _h4 > 0)
                                    or (side == "LONG" and _h4 < 0)
                                )
                                if bad_4h_macd:
                                    _need = "음수" if side == "SHORT" else "양수"
                                    return False, (
                                        f"4h MACD 역방향 (hist4h={_h4:.6f}, "
                                        f"{side}는 {_need} 필요!)"
                                    ), snapshot
            except Exception:
                pass  # 4h 실패 시 = 15m만 신뢰!

        ok = passes >= min_passed
        return (
            ok,
            (
                f"15m {passes}/5 (need {min_passed}/5, "
                f"RSI={rsi_rev} MACD={macd_rev} OBV={obv_rev} "
                f"CCI={cci_rev} VOL={vol_rev})"
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


def run_realtime_reentry() -> dict:
    """매 15분 = 실시간 재진입 감지!"""
    db: Session = SessionLocal()
    entered_fail = 0
    entered_success = 0
    skipped = 0
    results: list[dict] = []
    try:
        # 1. daily_limit 체크!
        from app.models.system_setting import SystemSetting
        limit_row = db.get(SystemSetting, "sajangnim_top_short_daily_limit")
        daily_limit = int(limit_row.value) if limit_row and limit_row.value else 0
        if daily_limit <= 0:
            return {"note": "daily_limit=0 (OFF!)", "entered": 0}

        from app.workers.auto_bb_breakdown_worker import (
            _count_used_slots, _create_auto_bb_strategy,
            _get_reentry_count, _increment_reentry_count,
            _reset_reentry_count, MAX_REENTRY_COUNT,
        )
        used = _count_used_slots(db)
        remaining = daily_limit - used
        if remaining <= 0:
            return {"note": f"daily {used}/{daily_limit}", "entered": 0}

        # 2. 1h 재진입 남발 체크!
        cutoff_1h = datetime.now(timezone.utc) - timedelta(hours=1)
        from app.models.strategy_suggestion import StrategySuggestion
        recent_re = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.created_at >= cutoff_1h)
            .where(StrategySuggestion.reason.like("%RT_REENTRY%"))
        ).scalars().all()
        if len(recent_re) >= MAX_HOURLY_REENTRIES:
            return {"note": f"1h {len(recent_re)}건 (max {MAX_HOURLY_REENTRIES}!)", "entered": 0}

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
        logger.info("[RT_REENTRY] 24h 청산 자동 진입 = %d건 (필터 확장!)", len(closed))

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

        for (symbol, side), si in latest_by_sym.items():
            if remaining <= 0:
                break
            if symbol in active_syms:
                skipped += 1
                continue

            # 재진입 카운터 max 2 (기존) or 3 (Fix 53 라스트 챈스!)
            re_count = _get_reentry_count(symbol, side)
            _max_count_effective = (
                MAX_REENTRY_COUNT + 1 if ENABLE_LAST_CHANCE else MAX_REENTRY_COUNT
            )
            if re_count >= _max_count_effective:
                skipped += 1
                logger.info(
                    "[RT_REENTRY] skip: %s %s MAX 재진입 %d회 도달! (max=%d, last_chance=%s)",
                    symbol, side, re_count, _max_count_effective, ENABLE_LAST_CHANCE,
                )
                continue

            # mark_price 조회!
            try:
                mp_raw = redis.get(f"mark_price:{symbol}")
                if not mp_raw:
                    continue
                mp = float(mp_raw.decode() if isinstance(mp_raw, bytes) else mp_raw)
                if mp <= 0:
                    continue
            except Exception:
                continue

            # 🎯 v218 fix (2026-08-22): 청산가 우선 = 평단 fallback!
            # 이전 = 평단 = 실 청산가와 다름 = 3% 반등 판정 부정확!
            # last_liquidation_price = SL 발동가! = 반등 시작점 정확!
            _stop_price = float(si.last_liquidation_price or si.avg_entry_price or 0)
            if _stop_price <= 0:
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
                logger.info(
                    "[RT_REENTRY] skip: %s %s 역방향 진행 중 (%.2f%% < %.1f%%)",
                    symbol, side, _rebound_pct, REBOUND_PCT_MIN_SAFETY,
                )
                continue

            # (b) 학습 인사이트 = worst 심볼 gate
            _learn_ok, _learn_msg = _is_symbol_learning_ok(db, symbol, side)
            if not _learn_ok:
                skipped += 1
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
                    skipped += 1
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
                logger.warning("[RT_REENTRY] 지표 조회 실패 = skip 안전: %s", _ve)
                skipped += 1
                continue

            if not _ind_ok:
                skipped += 1
                logger.info(
                    "[RT_REENTRY] skip: %s %s 지표 반전 미확인 (%s) [rebound=%.2f%% stage=%d need=%d/3]",
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
                            skipped += 1
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
                            skipped += 1
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
                    skipped += 1
                    continue

                # 🎓 v218 fix (2026-08-22 사장님!): entry_snapshot 저장 = 학습 데이터!
                _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
                # 🎯 v221: 실제 지표 값 저장 = 학습 사이클 완성!
                # 🎯 Fix 99 (2026-08-25): CCI + 볼륨 + 4h MACD 추가 = 5중 지표 학습!
                _rt_entry_snapshot = {
                    "rsi": _ind_snap.get("rsi"),
                    "cci": _ind_snap.get("cci"),  # 🎯 Fix 99 A: CCI 실 측정값!
                    "obv_slope_pct": _ind_snap.get("obv_slope"),
                    "macd_hist": _ind_snap.get("macd_hist"),
                    "rsi_4h": _ind_snap.get("rsi_4h"),
                    "macd_hist_4h": _ind_snap.get("macd_hist_4h"),  # 🎯 Fix 99 B!
                    "vol_ratio": _ind_snap.get("vol_ratio"),        # 🎯 Fix 99 C!
                    "passes_15m": _ind_snap.get("passes_15m"),      # 🎯 Fix 99 A: 5중 통과!
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
                db.rollback()

        total_entered = entered_fail + entered_success
        logger.info(
            "[RT_REENTRY] 완료: fail=%d success=%d skipped=%d",
            entered_fail, entered_success, skipped,
        )
        return {
            "entered_fail_reentry": entered_fail,
            "entered_success_reentry": entered_success,
            "skipped": skipped,
            "results": results,
        }
    except Exception as e:
        logger.exception("[RT_REENTRY] 실행 실패: %s", e)
        return {"error": str(e), "entered": 0}
    finally:
        db.close()
