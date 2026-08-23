"""🤖 AutoBBBreakdownWorker = BB 이탈 SUSTAINED 자동 진입! (v174 사장님 완성!)

사장님 지시 (2026-08-18):
- 1일 5개 (조절 옵션!)
- 손실난 것 = 진입 수량에서 빼기 (카운트!)
- 익절 = 다시 수량 회복! (카운트 X!)
- BB 이탈 SUSTAINED 심볼 = 성공률 85%+ = 자동 진입!

로직 (매 4시간!):
- system_settings 「auto_bb_break_daily_limit」 확인!
- 0 = OFF (수동만!)
- 1+ = 하루 최대 N개 = 자동 진입!
- 카운터 = 활성+손절 (익절 제외!) = v163 로직!
- SUSTAINED (3봉+ 지속 이탈!) + 성공률 85%+ 만!
- 이미 활성 심볼 = 제외!
- 사장님 default profile = template + strategy 자동 생성!
- StrategySuggestion 저장 (자동 진입 표시!)
- 텔레그램 알림!
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_suggestion import StrategySuggestion
from app.models.strategy_template import StrategyTemplate
from app.models.symbol import Symbol
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

# 🎯 v179 사장님 (2026-08-19): 실패 확률 낮추기 = 다중 필터 강화!
# 사장님 지시: "실패확율을 더 낮춰야 해!"
# 이력:
#   v174 (2026-08-18): MIN_SUCCESS_PROBABILITY = 0.85 (BB 자동 진입 시작!)
#   v176 (2026-08-19): 손실 심볼 24h 블록 + 심볼 성공률 30% 필터!
#   v179 (2026-08-19): 모든 필터 강화! (사장님 「더 낮춰야」!)
MIN_SUCCESS_PROBABILITY = 0.60  # v179: 0.85→0.90 / v194: 0.90→0.80 / v201: 0.80→0.70 / 사장님 (2026-08-21): 0.70→0.60 (짧은 손절 + 재도전 = 공격적!)
MIN_SYMBOL_SUCCESS_RATE = 0.40  # 0.30 → 0.40 (10%p 상향!)
LOSS_BLOCKLIST_HOURS = 48  # 24 → 48 (2배 확대!)
MIN_SUSTAINED_BARS = 5  # 3 → 5 (지속 확실!)
# 🚨 v220 사장님 (2026-08-22): 손실 -400 USDT 사고!
# 사장님 지적: "손절이 너무 많이 문제를 찾아서 분석하고 학습해 이런 경우는 없게 해줘"
# 원인: LONG "NEUTRAL" 허용 → 애매장 LONG 진입 → 39건 손실!
# fix: LONG = UPTREND만! (NEUTRAL 제거!) SHORT도 좁힘!
REQUIRED_REGIMES = {
    "SHORT": {"DOWNTREND_STRONG", "DOWNTREND"},  # SHORT = 하락 계열!
    "LONG": {"UPTREND"},  # 🚨 v220 사장님: NEUTRAL 제거! (하락장 LONG 방지!)
}
# 🚨 v220: WORST 시나리오 blocklist! (성공률 <20% + 표본 8+!)
WORST_SCENARIO_MIN_TOTAL = 8      # 표본 8건+!
WORST_SCENARIO_MAX_RATE = 0.20   # 성공률 20% 미만!
# 🚨 v220: BTC 방향 필터! (하락 3%+ = LONG 금지, 상승 3%+ = SHORT 금지!)
BTC_DIRECTION_THRESHOLD = 3.0    # BTC 24h ±3% 이상 = 반대 방향 skip!
# v179 신: RSI 안전 범위!
RSI_SAFE_RANGE = {
    "SHORT": (30, 70),  # SHORT: RSI 30~70 (과매도 반등 X, 과매수는 진입 시점!)
    "LONG": (30, 70),  # LONG: RSI 30~70 (과매수 조정 X, 과매도는 진입 시점!)
}


def _is_risky_time_kst() -> tuple[bool, str]:
    """🚨 v197 사장님 실적 분석 (2026-08-21):
    KST 20:00/00:00/02:00 = 큰 손실 시간대!
    - KST 02:00: 8건 -494 USDT (승률 12%!)
    - KST 20:00: 5건 -461 USDT (승률 0%!)
    - KST 00:00: 7건 -288 USDT (승률 0%!)
    - KST 18:00: 2건 -197 USDT (승률 0%!)
    = 미국 새벽 시장 = 변동성 극대 = 위험!
    """
    kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
    # KST 18:00 ~ KST 03:00 = 위험!
    if kst_hour >= 18 or kst_hour < 3:
        return True, f"KST {kst_hour:02d}:00 = 위험 시간대 (미국 시장 변동성!)"
    return False, ""


def run_auto_bb_breakdown() -> dict:
    # Fix 33 (2026-08-23 사장님!): v219만 유지! auto_bb_breakdown OFF!
    try:
        from app.core.database import SessionLocal as _SL
        from app.models.system_setting import SystemSetting as _SS
        _db = _SL()
        try:
            _s = _db.get(_SS, "auto_bb_breakdown_enabled")
            if _s and str(_s.value) in ("0", "false", "False"):
                import logging
                logging.getLogger(__name__).warning("[auto_bb_breakdown] DISABLED = skip")
                return {"disabled": True}
        finally: _db.close()
    except Exception: pass
    """매 4시간 = SUSTAINED 심볼 자동 진입! (v174 완성 + v197 시간대 필터!)"""
    db: Session = SessionLocal()
    entered = 0
    skipped = 0
    results: list[dict] = []
    try:
        # 🚀 사장님 (2026-08-21): v197 위험 시간대 필터 = 완전 제거!
        # = 사장님 사상 = 24시간 진입 = 공격적 매매!
        # (기존 v197: KST 18-03 skip → 지금 X!)
        # _is_risky_time_kst() = 함수 유지 (다른 곳에서 참조할 수 있음!) but 호출 X!

        # 1. daily_limit 확인!
        limit_row = db.get(SystemSetting, "auto_bb_break_daily_limit")
        daily_limit = int(limit_row.value) if limit_row and limit_row.value else 0
        if daily_limit <= 0:
            return {"note": "auto_bb_break_daily_limit=0 (OFF!)", "entered": 0}

        # 2. 카운터 (v163: 활성 + 손절 = 카운트, 익절 = 제외!)
        used = _count_used_slots(db)
        remaining = daily_limit - used
        if remaining <= 0:
            return {
                "note": f"오늘 사용 {used}/{daily_limit} (활성+손절, 익절 제외!)",
                "entered": 0,
            }

        # 3. SUSTAINED 스캔 (SHORT + LONG!)
        from app.api.v1.bb_middle_scan import scan_bb_breakdown
        try:
            scan_short = scan_bb_breakdown(
                interval="4h", direction="down", max_symbols=100,
                db=db, user_id=1,
            )
            scan_long = scan_bb_breakdown(
                interval="4h", direction="up", max_symbols=100,
                db=db, user_id=1,
            )
        except Exception as e:
            logger.warning("[auto_bb_breakdown] BB 스캔 실패: %s", e)
            scan_short = {"sustained": []}
            scan_long = {"sustained": []}

        all_sustained: list[dict] = []
        for it in (scan_short.get("sustained") or []):
            all_sustained.append({**it, "side": "SHORT", "source": "BB_SUSTAINED"})
        for it in (scan_long.get("sustained") or []):
            all_sustained.append({**it, "side": "LONG", "source": "BB_SUSTAINED"})

        # 🎯 v190 사장님: MTA (Multi-Timeframe) 소스 추가!
        # 🚨 v196 (API Ban 사고!): max_symbols 100 → 30 (호출 축소!)
        # 사장님 지시: "MTA 잘 활용해서 자동매매 많이 + 수익 많이 + 포지션 늘리기!"
        try:
            from app.api.v1.multi_timeframe_scan import scan_multi_timeframe
            mta_result = scan_multi_timeframe(
                max_symbols=30, min_score=18,  # v196: 100→30 (API Ban 방지!)
                db=db, user_id=1,
            )
            for it in (mta_result.get("long_signals") or []):
                # MTA 형식 → BB 형식 변환!
                all_sustained.append({
                    "symbol": it["symbol"],
                    "side": "LONG",
                    "source": "MTA",
                    "success_probability": min(0.99, it["total_score"] / 24.0 + 0.05),
                    "sustained_bars": 5,
                    "regime": "UPTREND",  # MTA LONG = 상승 반전!
                    "rsi": it["tf_15m"].get("rsi"),
                    "cci": it["tf_15m"].get("cci"),
                    "obv_slope_pct": it["tf_15m"].get("obv_slope_pct"),
                    "change_24h": it["change_24h"],
                    "mta_total": it["total_score"],
                    "mta_reason": it["reason"],
                })
            for it in (mta_result.get("short_signals") or []):
                all_sustained.append({
                    "symbol": it["symbol"],
                    "side": "SHORT",
                    "source": "MTA",
                    "success_probability": min(0.99, it["total_score"] / 24.0 + 0.05),
                    "sustained_bars": 5,
                    "regime": "DOWNTREND_STRONG",
                    "rsi": it["tf_15m"].get("rsi"),
                    "cci": it["tf_15m"].get("cci"),
                    "obv_slope_pct": it["tf_15m"].get("obv_slope_pct"),
                    "change_24h": it["change_24h"],
                    "mta_total": it["total_score"],
                    "mta_reason": it["reason"],
                })
            logger.info(
                "[auto_bb_breakdown] v190 MTA 소스: LONG %d + SHORT %d 추가!",
                len(mta_result.get("long_signals") or []),
                len(mta_result.get("short_signals") or []),
            )
        except Exception as e:
            logger.warning("[auto_bb_breakdown] v190 MTA 스캔 실패: %s", e)

        # 🎯 사장님 요구 (2026-08-21): PENDING suggestion 85%+ = 자동 진입 통합!
        # "실시간 모니터링 진입예정 신뢰도 85%/90%+ = 자동 진입!"
        # = bb 이탈 자동진입 로직으로 같이 처리!
        try:
            # 🚨 Agent 검증 fix 1 (2026-08-22): 0.75 → 0.85 복원!
            # Agent 진단: 0.75 = 손익분기 미달 = 구조적 마이너스!
            # 사장님 (2026-08-21): 공격적 조정 = 0.85 → 0.75! (실패!)
            pending_hc = db.execute(
                select(StrategySuggestion)
                .where(StrategySuggestion.status == "PENDING")
                .where(StrategySuggestion.confidence_score >= Decimal("0.85"))
                .order_by(StrategySuggestion.confidence_score.desc())
                .limit(20)
            ).scalars().all()
            for ps in pending_hc:
                _pcfg = ps.strategy_config if isinstance(ps.strategy_config, dict) else {}
                # 🎓 v218 Fix 13 (2026-08-22 사장님 C!): entry_snapshot 재사용 = 학습 필터 반영!
                # Fix 12 (strategy_suggestion_generator.py!) 이후 = 모든 신 suggestion = 지표 저장!
                # PENDING_HC = 원본 suggestion → entry_snapshot 재사용 = 학습 필터 100% 활용!
                # 옛 suggestion (Fix 12 이전) = snapshot 없음 = _pcfg.get() fallback = 안전!
                # 주의: None vs 0.0 구분 = `is not None` 사용! (rsi=0.0 유효값!)
                _snap = _pcfg.get("entry_snapshot") or {}
                if not isinstance(_snap, dict):
                    _snap = {}
                all_sustained.append({
                    "symbol": ps.symbol,
                    "side": ps.side,
                    "source": "PENDING_HC",  # High Confidence!
                    "success_probability": float(ps.confidence_score or 0),
                    "sustained_bars": _snap.get("sustained_bars") or _pcfg.get("sustained_bars", 5),
                    "regime": _snap.get("regime") or _pcfg.get("regime") or "NEUTRAL",
                    "rsi": _snap.get("rsi") if _snap.get("rsi") is not None else _pcfg.get("rsi"),
                    "cci": _snap.get("cci") if _snap.get("cci") is not None else _pcfg.get("cci"),
                    "obv_slope_pct": _snap.get("obv_slope_pct") if _snap.get("obv_slope_pct") is not None else _pcfg.get("obv_slope_pct"),
                    "change_24h": _snap.get("change_24h") if _snap.get("change_24h") is not None else _pcfg.get("change_24h"),
                    "_pending_suggestion_id": ps.id,  # 진입 후 EXECUTED 갱신용!
                })
            if pending_hc:
                logger.info(
                    "[auto_bb_breakdown] 🎯 PENDING_HC 통합: %d건 (85%%+!)",
                    len(pending_hc),
                )
        except Exception as e:
            logger.warning("[auto_bb_breakdown] PENDING_HC 통합 실패: %s", e)

        # 🎯 사장님 요구 (2026-08-21): 청산된 자동 진입 심볼 = 즉시 재진입 스캔!
        # 사장님 지적: "다시 진입하는 조건은 바로 나올것 같은데 로직 점검!"
        # = BB SUSTAINED 재감지 (20h!) 대기 X = 청산 즉시 재진입 후보!
        # 조건:
        # - _is_reentry_candidate = True (실패 있음 + 재진입 카운터 <2!)
        # - 급등/급락 필터 등 = 그대로 적용!
        try:
            from datetime import timedelta as _td_r
            from app.core.strategy_status import TERMINAL_STATUSES as _TS_r
            cutoff_r = datetime.now(timezone.utc) - _td_r(hours=24)
            _closed_auto = db.execute(
                select(StrategyInstance)
                .join(StrategyTemplate,
                      StrategyInstance.strategy_template_id == StrategyTemplate.id)
                .where(StrategyInstance.stopped_at >= cutoff_r)
                .where(StrategyInstance.status.in_(list(_TS_r)))
                .where(StrategyTemplate.strategy_type.like('auto_bb_break%'))
            ).scalars().all()

            _reentry_added = 0
            _reentry_seen = set()  # (symbol, side) 중복 방지!
            for _si in _closed_auto:
                _pnl = float(_si.realized_pnl or 0)
                if _pnl >= 0:
                    continue  # 익절 = skip (성공!)
                _key_r = (_si.symbol, _si.side)
                if _key_r in _reentry_seen:
                    continue
                _reentry_seen.add(_key_r)
                # 재진입 카운터 확인!
                if _get_reentry_count(_si.symbol, _si.side) >= MAX_REENTRY_COUNT:
                    continue
                # 🎯 Agent 검증 fix (2026-08-22): REENTRY_QUEUE PnL 게이트!
                # 사장님 지적: "실패 5건 = 마틴게일 폭발 위험!"
                # = 같은 심볼+방향 = 24h 누적 손실 -50 USDT+ = 재진입 STOP!
                # = BOMEUSDT -417 / ONGUSDT -411 사고 재발 방지!
                _recent_pnl = sum(
                    float(x.realized_pnl or 0) for x in _closed_auto
                    if x.symbol == _si.symbol and x.side == _si.side
                )
                # 🚨 Agent 검증 fix 2 (2026-08-22): PnL 게이트 강화 -50 → -30!
                # Agent 진단: -50까지 통과 = 첫 -30 손실 후 재진입 → 두 번째 -70 = -100 폭탄!
                if _recent_pnl <= -30.0:
                    logger.info(
                        "[auto_bb_breakdown] 🚨 REENTRY_QUEUE PnL 게이트: %s %s 24h 누적 %.2f USDT ≤ -30 = skip!",
                        _si.symbol, _si.side, _recent_pnl,
                    )
                    continue
                # 🎯 v219 REENTRY_QUEUE 부활! (2026-08-22 사장님 지적!)
                # 사장님: "GALAUSDT -21.37 손실인데 재진입로직은 없는건가?"
                # 이전: 실 지표 없음 = 완전 skip = REENTRY_QUEUE 사장(死藏)!
                # 신: entry_snapshot 없이도 = 신 마틴게일 스캔 리스트에 추가!
                # = 학습 필터는 skip (rsi=None → _matches_failure_condition = skip 안전!)
                # = 사장님 신 마틴게일 (300/600/1800) = _create_auto_bb_strategy에서 적용!
                all_sustained.append({
                    "symbol": _si.symbol,
                    "side": _si.side,
                    "source": "REENTRY_QUEUE",
                    "success_probability": 0.70,  # 재진입 = 신뢰도 중간!
                    "sustained_bars": MIN_SUSTAINED_BARS,
                    "regime": "NEUTRAL",
                    "rsi": None, "cci": None, "obv_slope_pct": None,
                    "change_24h": None,
                    "mta_total": None,
                    "_reentry_stage": _get_reentry_count(_si.symbol, _si.side) + 2,  # 2단계 or 3단계!
                    "_base_capital": float(_si.total_capital or 300),
                    "_prev_pnl": _pnl,
                })
                _reentry_added += 1
                logger.info(
                    "[auto_bb_breakdown] 🎯 v219 REENTRY_QUEUE: %s %s (stage=%d, pnl=%.2f, base=%.0f)",
                    _si.symbol, _si.side,
                    _get_reentry_count(_si.symbol, _si.side) + 2,
                    _pnl, float(_si.total_capital or 300),
                )
            if _reentry_added:
                logger.info(
                    "[auto_bb_breakdown] 🎯 REENTRY_QUEUE: %d건 청산 실패 심볼 재진입 스캔 추가!",
                    _reentry_added,
                )
        except Exception as e:
            logger.warning("[auto_bb_breakdown] REENTRY_QUEUE 실패: %s", e)

        # 🎯 사장님 요구 (2026-08-21): OBV 신호 = 자동 진입 소스 통합!
        # 사장님 verbatim: "B: auto_bb_breakdown에 = OBV 소스 통합!"
        # + "OBV 전략 = 신중해야 하니까 신뢰도 높은 심볼로!"
        # = reentry_alert_watcher(매 5분!)가 저장한 OBV+RSI+10% 신호 = 즉시 자동 진입!
        # = Redis에서 조회 = API 부담 X!
        # 🎯 사장님 신 설정 3개 (system_settings!):
        #   - auto_obv_enabled (0/1, default 0 = OFF!)
        #   - auto_obv_daily_limit (default 3 = 신중!)
        #   - auto_obv_min_confidence (default 0.95 = 매우 높은!)
        try:
            # OBV enabled 체크!
            _obv_enabled_row = db.get(SystemSetting, "auto_obv_enabled")
            _obv_enabled = int(_obv_enabled_row.value) if _obv_enabled_row and _obv_enabled_row.value else 0
            if not _obv_enabled:
                logger.debug("[auto_bb_breakdown] OBV_REVERSE OFF (auto_obv_enabled=0!)")
                raise StopIteration  # skip OBV block!

            # OBV daily_limit 체크!
            _obv_limit_row = db.get(SystemSetting, "auto_obv_daily_limit")
            _obv_daily_limit = int(_obv_limit_row.value) if _obv_limit_row and _obv_limit_row.value else 3
            # 오늘 OBV 진입 카운트! (단순 = reason LIKE 만!)
            _obv_used = db.execute(
                select(func.count(StrategySuggestion.id))
                .where(StrategySuggestion.created_at >= (datetime.now(timezone.utc).replace(hour=15, minute=0, second=0, microsecond=0) - timedelta(days=1)))
                .where(StrategySuggestion.reason.like("%OBV%"))
            ).scalar() or 0
            if _obv_used >= _obv_daily_limit:
                logger.info("[auto_bb_breakdown] OBV daily {%d/%d} skip!", _obv_used, _obv_daily_limit)
                raise StopIteration

            # OBV 최소 신뢰도!
            _obv_min_conf_row = db.get(SystemSetting, "auto_obv_min_confidence")
            _obv_min_confidence = float(_obv_min_conf_row.value) if _obv_min_conf_row and _obv_min_conf_row.value else 0.95

            from app.core.redis_client import get_redis_client
            import json as _json
            _r = get_redis_client()
            _alert_ids = _r.zrange("reentry_alerts:v1", 0, -1)
            _obv_added = 0
            for _aid in _alert_ids:
                _aid_str = _aid.decode() if isinstance(_aid, bytes) else _aid
                _alert_raw = _r.get(_aid_str)
                if not _alert_raw:
                    continue
                try:
                    _alert = _json.loads(
                        _alert_raw.decode() if isinstance(_alert_raw, bytes) else _alert_raw
                    )
                    _sym = _alert.get("symbol")
                    _side = _alert.get("side")
                    if not _sym or not _side:
                        continue
                    # 중복 방지! (같은 symbol:side 이미 있으면 skip!)
                    _dup = any(
                        it["symbol"] == _sym and it["side"] == _side
                        for it in all_sustained
                    )
                    if _dup:
                        continue
                    # 🎓 v218 Fix 13-B (2026-08-22 사장님 C!): 알람 저장 지표 재사용!
                    # reentry_alert_watcher가 이미 detail.rsi_last 저장!
                    # 학습 RSI 필터 반영 = 0% → ~25%!
                    _det = _alert.get("detail") or {}
                    if not isinstance(_det, dict):
                        _det = {}
                    try:
                        _rsi_v = float(_det.get("rsi_last")) if _det.get("rsi_last") is not None else None
                    except Exception:
                        _rsi_v = None
                    all_sustained.append({
                        "symbol": _sym,
                        "side": _side,
                        "source": "OBV_REVERSE",  # v130 OBV+RSI+10% 신호!
                        "success_probability": _obv_min_confidence,  # 사장님 세팅!
                        "sustained_bars": MIN_SUSTAINED_BARS,
                        "regime": "NEUTRAL",  # 4H OBV 반전 = 방향 판정 신뢰 X = NEUTRAL 유지!
                        "rsi": _rsi_v,  # 🎓 Fix 13: 알람 저장 값 재사용!
                        "cci": None,  # 알람 미저장 = None (학습 필터 skip)
                        "obv_slope_pct": None,  # 반전만 확인 = slope% 아님 = None
                        "change_24h": None,
                        "mta_total": None,
                    })
                    _obv_added += 1
                except Exception:
                    continue
            if _obv_added:
                logger.info(
                    "[auto_bb_breakdown] 🎯 OBV_REVERSE: %d건 알람 소스 추가! (신중=신뢰도 %.2f+, 일 %d건 max!)",
                    _obv_added, _obv_min_confidence, _obv_daily_limit,
                )
        except StopIteration:
            pass  # OBV OFF or daily 초과 = skip 정상!
        except Exception as e:
            logger.warning("[auto_bb_breakdown] OBV_REVERSE 통합 실패: %s", e)

        # 중복 제거 (같은 symbol:side!)
        seen_keys = set()
        deduped = []
        for it in all_sustained:
            k = f"{it['symbol']}:{it['side']}"
            if k not in seen_keys:
                seen_keys.add(k)
                deduped.append(it)
        all_sustained = deduped
        # 성공률 큰 순!
        all_sustained.sort(key=lambda x: -(x.get("success_probability") or 0))

        # 4. 이미 활성 심볼 = 제외!
        active_keys = _get_active_symbol_keys(db)
        # 🚨 v176: 최근 24h 손실 심볼 = 제외!
        recent_loss_keys = _get_recent_loss_symbol_keys(db)
        # 🎓 v188 사장님: 학습 인사이트 = WORST 심볼 자동 제외!
        worst_learning_keys = _get_worst_learning_keys(db)
        top_learning_keys = _get_top_learning_keys(db)

        # 5. 사장님 default profile 로드!
        from app.api.v1.suggestion_profiles import _load_profiles
        profiles, default_name = _load_profiles(db)
        default_profile = next(
            (p for p in profiles if p.get("name") == default_name), None,
        )
        if not default_profile:
            return {"error": "default profile 없음!", "entered": 0}
        cfg = default_profile.get("config", {})

        # 6. 각 SUSTAINED = 실 진입!
        for it in all_sustained:
            if entered >= remaining:
                break
            symbol = it["symbol"]
            side = it["side"]
            key = f"{symbol}:{side}"

            # 6a. 이미 활성 = skip!
            if key in active_keys:
                skipped += 1
                continue

            # 🎓 v188 사장님 (2026-08-20): 학습 인사이트 = WORST 심볼 자동 제외!
            # 🎯 v202 예외: 재진입 후보 (마틴게일!)면 = 진입 허용!
            _is_reentry = _is_reentry_candidate(db, symbol, side)
            if key in worst_learning_keys and not _is_reentry:
                skipped += 1
                logger.info(
                    "[auto_bb_breakdown] 🎓 v188 skip: %s (학습 실패 심볼 = 0%%!)", key,
                )
                continue

            # 🚨 v179: 최근 48h 손실 심볼 = skip! (24h → 48h!)
            # 🎯 v202 예외: 재진입 후보면 진입 허용!
            if key in recent_loss_keys and not _is_reentry:
                skipped += 1
                logger.info(
                    "[auto_bb_breakdown] 🚨 v179 skip: %s (최근 48h 손실 심볼!)", key,
                )
                continue

            # 🚨 v179: 심볼 30일 성공률 < 40% = skip! (30% → 40%!)
            try:
                from app.workers.prediction_outcome_worker import get_symbol_success_rate
                sr = get_symbol_success_rate(db, symbol, side, days=30)
                if sr < MIN_SYMBOL_SUCCESS_RATE:
                    skipped += 1
                    logger.info(
                        "[auto_bb_breakdown] 🚨 v179 skip: %s (심볼 30일 성공률 %.0f%% < %d%%)",
                        key, sr * 100, int(MIN_SYMBOL_SUCCESS_RATE * 100),
                    )
                    continue
            except Exception:
                pass  # sr 조회 실패 = 계속 진행 (fail-open)

            # 6b. 성공률 필터! (v201 사장님 「적극」!)
            # 🎓 v188: TOP 학습 심볼 = 완화 필터 (0.65!)
            # 🌟 v201: 학습 성공 조건 매치 시 = 대폭 완화 (0.55!)
            # 🚀 v204: 성공 재진입 후보 = 최대 완화 (0.50!)
            prob = float(it.get("success_probability") or 0)
            required_prob = MIN_SUCCESS_PROBABILITY  # 0.70 (v201!)
            reason_bonus = ""
            _is_success_reentry = _is_success_reentry_candidate(db, symbol, side)
            if _is_success_reentry:
                # 🚀 v204: 성공 후 재진입 = 강력 우선!
                required_prob = 0.50
                reason_bonus = " (🚀 성공 재진입! 최근 24h 익절 성공!)"
            elif key in top_learning_keys:
                required_prob = 0.65
                reason_bonus = " (TOP 심볼!)"
            elif _matches_success_condition(it, side):
                # v201: 학습 성공 조건 매치 = 필터 대폭 완화!
                required_prob = 0.55
                reason_bonus = " (성공 조건 매치!)"
            if prob < required_prob:
                continue
            if reason_bonus:
                logger.info(
                    "[auto_bb_breakdown] 🌟 우대: %s%s (%.0f%% >= %.0f%%)",
                    key, reason_bonus, prob*100, required_prob*100,
                )

            # 🌟 v179 신 필터 1: 지속 봉수 = 5봉+ 필수!
            sustained_bars = int(it.get("sustained_bars", 0) or 0)
            if sustained_bars < MIN_SUSTAINED_BARS:
                skipped += 1
                logger.info(
                    "[auto_bb_breakdown] 🌟 v179 skip: %s (지속 %d봉 < %d봉 필수!)",
                    key, sustained_bars, MIN_SUSTAINED_BARS,
                )
                continue

            # 🌟 v179 신 필터 2: regime 필수! (DOWNTREND_STRONG / UPTREND)
            regime = it.get("regime", "NEUTRAL")
            required_regimes = REQUIRED_REGIMES.get(side, set())
            if regime not in required_regimes:
                skipped += 1
                logger.info(
                    "[auto_bb_breakdown] 🌟 v179 skip: %s regime=%s (%s만 허용!)",
                    key, regime, "/".join(required_regimes),
                )
                continue

            # 🌟 v179 신 필터 3: RSI 안전 범위! (30~70)
            rsi = it.get("rsi")
            if rsi is not None:
                rsi_min, rsi_max = RSI_SAFE_RANGE.get(side, (0, 100))
                if rsi < rsi_min or rsi > rsi_max:
                    skipped += 1
                    logger.info(
                        "[auto_bb_breakdown] 🌟 v179 skip: %s RSI %.0f (안전 범위 %d~%d 밖!)",
                        key, rsi, rsi_min, rsi_max,
                    )
                    continue

            # 🚨 사장님 요구 (2026-08-21): 급등/급락 종목 = 반대 방향 진입 금지!
            # = BOMEUSDT +35% SHORT → -417 USDT 손실 사고!
            # = ONGUSDT +31% SHORT → -411 USDT 손실 사고!
            # = 급등 계속 = 물타기 3단계 = 큰 손실!
            # 로직: 24h 변동 > +15% = SHORT 금지! (급등 계속 위험!)
            #        24h 변동 < -15% = LONG 금지! (급락 계속 위험!)
            # 🐻 v219 사장님 C옵션 예외 (2026-08-22): sajangnim_top_short = bypass!
            #   = 급등이 곧 진입 근거 (정점 반전 SHORT!) = 사장님 명시 요구!
            _entry_reason = str(it.get("entry_reason") or "")
            _sugg_type = str(it.get("suggestion_type") or "")
            _bypass_pump_filter = (
                _sugg_type == "sajangnim_top_short"
                or _entry_reason == "pump_top_v219"
                or str(it.get("source") or "") == "SAJANGNIM_TOP"
            )
            change_24h = it.get("change_24h")
            if not _bypass_pump_filter and change_24h is not None:
                try:
                    _c = float(change_24h)
                    if side == "SHORT" and _c > 15.0:
                        skipped += 1
                        logger.info(
                            "[auto_bb_breakdown] 🚨 급등 skip: %s SHORT 24h=+%.2f%% (>15%%!)",
                            key, _c,
                        )
                        continue
                    if side == "LONG" and _c < -15.0:
                        skipped += 1
                        logger.info(
                            "[auto_bb_breakdown] 🚨 급락 skip: %s LONG 24h=%.2f%% (<-15%%!)",
                            key, _c,
                        )
                        continue
                except (ValueError, TypeError):
                    pass

            # 🎓 v198 사장님: 조건 매칭 = 실패 조건이면 skip!
            # RSI/CCI/OBV/regime/시간대 = 학습된 실패 조건 매치 시 = skip!
            if _matches_failure_condition(it, side):
                skipped += 1
                logger.info(
                    "[auto_bb_breakdown] 🎓 v198 skip: %s (실패 조건 매치!)", key,
                )
                continue

            # 6c. 실 진입!
            try:
                # 🎯 v202: 재진입 시 = 자본 1.5배! (마틴게일!)
                _entry_cfg = dict(cfg)
                _reentry_capital = None
                _reentry_count_now = 0  # 이번 진입의 재진입 번호! (0=첫, 1=1차재, 2=2차재!)
                if _is_reentry:
                    _prev_count = _get_reentry_count(symbol, side)
                    _reentry_count_now = _prev_count + 1  # 이번 진입 후 카운트!
                    _base = float(cfg.get("capitals", [500])[0])
                    _reentry_capital = _calc_reentry_capital(symbol, side, _base)
                    if _reentry_capital is None:
                        skipped += 1
                        logger.info(
                            "[auto_bb_breakdown] 🎯 v202 skip: %s (최대 재진입 %d회 도달!)",
                            key, MAX_REENTRY_COUNT,
                        )
                        continue
                    _entry_cfg["capitals"] = [_reentry_capital]
                    logger.info(
                        "[auto_bb_breakdown] 🎯 v202 재진입 %d차: %s 자본 %.0f → %.0f USDT (×%.2f)",
                        _reentry_count_now, key, _base, _reentry_capital,
                        _reentry_capital / _base,
                    )
                # 🎯 v203: strategy_type = 재진입 정보 포함!
                # 🚀 v204: 성공 재진입 표시 추가!
                #   - "auto_bb_break"          = 첫 진입!
                #   - "auto_bb_break_reentry1" = 1차 재진입 (실패 후 마틴게일!)
                #   - "auto_bb_break_reentry2" = 2차 재진입 (실패 후 마틴게일!)
                #   - "auto_bb_break_success"  = 성공 재진입 (초기 자본, 수익 누적!)
                _type_suffix = ""
                if _reentry_count_now > 0:
                    _type_suffix = f"_reentry{_reentry_count_now}"
                elif _is_success_reentry:
                    _type_suffix = "_success"  # 🚀 v204!
                # 🎯 사장님 사상 (2026-08-21): OBV 소스 = 오래 버티기 전략!
                # "OBV 전략은 실패하면 큰 손실이 나올꺼야 이전략은 청산될때까지 운영할수있게!"
                # = 강제 SL 비활성 + 수동 증거금/포지션 추가 가능!
                # (3단계 확장은 다음 세션 = 지금은 1단계 + 강제SL X!)
                _is_obv = it.get("source") == "OBV_REVERSE"
                _final_suffix = "_OBV_HOLD" if _is_obv else _type_suffix
                new_strategy = _create_auto_bb_strategy(
                    db, symbol, side, _entry_cfg,
                    strategy_type_suffix=_final_suffix,
                )
                # 🚨 v218 fix (2026-08-22): 진입 실패 = suggestion 저장 X + slot 보존!
                # 사장님 사상: "실패는 재시도!" = PENDING_HC/BB_SUSTAINED = 다음 사이클 자동 재시도!
                if not new_strategy:
                    skipped += 1
                    logger.info(
                        "[auto_bb_breakdown] ❌ v218 %s %s 진입 실패 = skip (slot 보존!)",
                        symbol, side,
                    )
                    _pid = it.get("_pending_suggestion_id")
                    if _pid:
                        logger.info("[PENDING_HC] 원본 %s PENDING 유지 (재시도!)", _pid)
                    continue
                # OBV 소스 = 강제 SL 비활성 = 오래 버티기!
                if _is_obv and new_strategy:
                    _apply_obv_hold_settings(db, new_strategy)
                # 🎯 v202: 재진입 카운터 증가!
                if _is_reentry:
                    _increment_reentry_count(symbol, side)
                # 🚀 v204: 성공 재진입 = 카운터 리셋! (사이클 갱신!)
                if _is_success_reentry:
                    _reset_reentry_count(symbol, side)
                # StrategySuggestion 저장 (자동 진입 표시!)
                # 🎓 v198 사장님 (2026-08-21): 진입 시점 지표 스냅샷 저장!
                # 사장님 지시: "실패한 차트 분석해서 다음에 대처하는 학습!"
                # = 조건 조합별 성공률 분석 = 실패 조건 자동 회피!
                _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
                entry_snapshot = {
                    "rsi": it.get("rsi"),
                    "cci": it.get("cci"),
                    "obv_slope_pct": it.get("obv_slope_pct"),
                    "regime": it.get("regime", "NEUTRAL"),
                    "sustained_bars": it.get("sustained_bars", 0),
                    "change_24h": it.get("change_24h"),
                    "source": it.get("source", "BB_SUSTAINED"),
                    "kst_hour": _kst_hour,
                    "mta_total": it.get("mta_total"),
                    "entered_at": datetime.now(timezone.utc).isoformat(),
                }
                sugg = StrategySuggestion(
                    symbol=symbol, side=side,
                    suggestion_type="bb4h_auto_entry",
                    strategy_config={
                        **cfg, "symbol": symbol, "side": side,
                        "entry_snapshot": entry_snapshot,  # 🎓 v198!
                    },
                    confidence_score=Decimal(str(round(prob, 4))),
                    reason=(
                        f"BB 4H SUSTAINED 자동 진입! "
                        f"성공률 {int(prob*100)}% / 지속 {it.get('sustained_bars', 0)}봉 / "
                        f"regime={it.get('regime', 'NEUTRAL')} / "
                        f"RSI={it.get('rsi')} CCI={it.get('cci')} OBV={it.get('obv_slope_pct')}% "
                        f"KST={_kst_hour:02d}h"
                    ),
                    status="EXECUTED",
                    execution_mode="AUTO",
                    executed_at=datetime.now(timezone.utc),
                    executed_strategy_id=new_strategy.id,
                    outcome_status="PENDING",
                )
                db.add(sugg)

                # 🎯 사장님 요구: PENDING_HC로 진입한 경우 = 원본 suggestion도 EXECUTED로 갱신!
                _pid = it.get("_pending_suggestion_id")
                if _pid:
                    try:
                        _orig = db.get(StrategySuggestion, _pid)
                        if _orig and _orig.status == "PENDING":
                            _orig.status = "EXECUTED"
                            _orig.execution_mode = "AUTO"
                            _orig.executed_at = datetime.now(timezone.utc)
                            _orig.executed_strategy_id = new_strategy.id
                            logger.info(
                                "[auto_bb_breakdown] 🎯 PENDING_HC 진입! %s %s (conf=%.0f%%)",
                                symbol, side, prob * 100,
                            )
                    except Exception as _pe:
                        logger.warning("[PENDING_HC] 원본 갱신 실패: %s", _pe)

                db.commit()

                results.append({
                    "symbol": symbol,
                    "side": side,
                    "success_probability": prob,
                    "sustained_bars": it.get("sustained_bars"),
                    "regime": it.get("regime"),
                    "source": it.get("source"),
                    "strategy_id": new_strategy.id,
                })
                entered += 1

                # 6d. 텔레그램 알림!
                _notify_auto_entry(new_strategy, prob, it)

                logger.info(
                    "[auto_bb_breakdown] ✅ 자동 진입: #%d %s %s (prob=%.0f%%)",
                    new_strategy.id, symbol, side, prob * 100,
                )
                # 🎼 v206 사장님: 오케스트라 통합 = EventBus 발신!
                try:
                    from app.agents.orchestrator.event_bus import get_event_bus
                    from app.agents.orchestrator.event_types import EventType
                    _bus = get_event_bus()
                    if _reentry_count_now > 0:
                        _bus.publish(EventType.REENTRY_TRIGGERED, {
                            "strategy_id": new_strategy.id,
                            "symbol": symbol, "side": side,
                            "count": _reentry_count_now,
                            "capital": float(_reentry_capital or 0),
                            "prob": prob,
                        })
                    elif _is_success_reentry:
                        _bus.publish(EventType.SUCCESS_REENTRY_TRIGGERED, {
                            "strategy_id": new_strategy.id,
                            "symbol": symbol, "side": side,
                            "prob": prob,
                        })
                    else:
                        _bus.publish(EventType.AUTO_ENTRY_TRIGGERED, {
                            "strategy_id": new_strategy.id,
                            "symbol": symbol, "side": side,
                            "prob": prob,
                            "regime": it.get("regime"),
                            "source": it.get("source", "BB_SUSTAINED"),
                        })
                except Exception as e:
                    logger.debug("[v206] EventBus 실패 (fail-open): %s", e)
            except Exception as e:
                logger.warning(
                    "[auto_bb_breakdown] ❌ %s %s 진입 실패: %s", symbol, side, e,
                )
                skipped += 1
                db.rollback()
                continue

        return {
            "daily_limit": daily_limit,
            "used_before": used,
            "remaining_before": remaining,
            "sustained_total": len(all_sustained),
            "entered_now": entered,
            "skipped": skipped,
            "results": results,
        }
    except Exception as e:
        logger.exception("[auto_bb_breakdown] 예외: %s", e)
        return {"error": str(e), "entered": entered}
    finally:
        db.close()


def _count_used_slots(db: Session) -> int:
    """v218 fix (2026-08-22): 사장님 리셋 존중 = 단일 진실 (헌법 6!)

    사장님 지적 (2026-08-22): "18/20 리셋했는데 왜 자꾸 이런걸 실수 하지"
    원인: 두 카운트 함수가 다른 로직!
    - _count_auto_bb_used (UI) = _auto_bb_reset_at 사용 = 리셋 반영!
    - _count_used_slots (worker) = KST 자정만 = 리셋 무시!
    = 사장님 리셋 → UI 0/20 → but worker 18/20 → 진입 안 됨!

    fix: API와 같은 _auto_bb_reset_at 재사용!
    보너스: realtime_reentry_worker.py:71도 자동 fix!

    오늘 EXECUTED (execution_mode='AUTO') + suggestion_type='bb4h_auto_entry'
    - 익절 (SUCCESS outcome) = 제외!
    - 활성 or 손절 (PENDING/FAIL outcome) = 카운트!
    """
    from app.api.v1.strategy_suggestions import _auto_bb_reset_at
    today_start_utc = _auto_bb_reset_at(db)

    # 🎯 v219 통합 (2026-08-22 사장님!): 사장님 정점 SHORT도 포함!
    # 사장님 요구: "일 진입수는 급등락 실시간과 같이 세팅"
    # 🎯 v220+ (2026-08-24): 사장님 저점 LONG도 통합! (헌법 6 단일 진실)
    # SHORT/LONG 대칭 = 하루 총 진입 수 = 통합 counter 공유!
    _auto_types = ["bb4h_auto_entry", "sajangnim_top_short", "sajangnim_bottom_long"]
    rows = db.execute(
        select(StrategySuggestion)
        .where(StrategySuggestion.status == "EXECUTED")
        .where(StrategySuggestion.execution_mode == "AUTO")
        .where(StrategySuggestion.suggestion_type.in_(_auto_types))
        .where(StrategySuggestion.executed_at >= today_start_utc)
    ).scalars().all()
    # 🎯 v220 Fix 22 (2026-08-23 사장님 지적!): 활성만 카운트!
    # 사장님 지적: "손실 18건인데 재진입 1건만!" = 손절이 slot 소진!
    # 사장님 사상: 손절 → 재진입 = 같은 심볼 재도전 = 신 slot 소비 X!
    # 신: 활성 (PENDING)만 카운트 = SUCCESS(익절) + FAIL(손절) 모두 제외!
    # → 재진입 = daily_limit 무관 = 자유롭게 진입!
    return sum(1 for r in rows if r.outcome_status == "PENDING")


def _get_active_symbol_keys(db: Session) -> set[str]:
    """현재 활성 심볼 keys = 'SYMBOL:SIDE' 집합!"""
    active_keys = set()
    from app.core.strategy_status import TERMINAL_STATUSES
    for a in db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.status.notin_(TERMINAL_STATUSES))
        .where(StrategyInstance.is_archived.is_(False))
    ).scalars().all():
        active_keys.add(f"{a.symbol}:{a.side}")
    return active_keys


# 🎓 v198 사장님: 학습된 실패 조건 캐시! (매 4h 갱신!)
_FAILURE_CONDITIONS_CACHE: dict = {"loaded_at": None, "conditions": {}}


def _load_failure_conditions(db: Session) -> dict:
    """🎓 v198: 학습 인사이트에서 = 실패 조건 로드!

    사장님 지시: "실패 차트 분석 → 다음에 대처!"
    - 성공률 <30% + 표본 5+ = 실패 조건!
    - RSI/CCI/OBV/regime/시간대별!
    """
    from datetime import timedelta as _td
    # 캐시 유효 = 30분!
    now = datetime.now(timezone.utc)
    if (_FAILURE_CONDITIONS_CACHE["loaded_at"] and
        (now - _FAILURE_CONDITIONS_CACHE["loaded_at"]) < _td(minutes=30)):
        return _FAILURE_CONDITIONS_CACHE["conditions"]

    failures = {
        "rsi_side": set(),      # {"low:LONG", ...}
        "cci_side": set(),
        "obv_side": set(),
        "regime_side": set(),
        "hour_side": set(),
    }
    try:
        from app.workers.pattern_learning_worker import get_learning_insights
        insights = get_learning_insights(db) or {}
        snap = insights.get("snapshot_conditions") or {}
        for key_name, out_key in [
            ("rsi_conditions", "rsi_side"),
            ("cci_conditions", "cci_side"),
            ("obv_conditions", "obv_side"),
            ("regime_conditions", "regime_side"),
            ("hour_conditions", "hour_side"),
        ]:
            for row in snap.get(key_name, []):
                if row.get("total", 0) >= 5 and row.get("success_rate", 0) < 0.30:
                    failures[out_key].add(row["key"])
    except Exception as e:
        logger.warning("[v198] 실패 조건 로드 실패: %s", e)

    _FAILURE_CONDITIONS_CACHE["loaded_at"] = now
    _FAILURE_CONDITIONS_CACHE["conditions"] = failures
    return failures


# 🌟 v201 사장님: 학습 성공 조건 캐시!
_SUCCESS_CONDITIONS_CACHE: dict = {"loaded_at": None, "conditions": {}}


def _load_success_conditions(db: Session) -> dict:
    """🌟 v201 사장님 「적극 매매」: 학습 인사이트에서 = 성공 조건 로드!

    - 성공률 60%+ + 표본 5+ = 성공 조건!
    - RSI/CCI/OBV/regime/시간대별!
    """
    from datetime import timedelta as _td
    now = datetime.now(timezone.utc)
    if (_SUCCESS_CONDITIONS_CACHE["loaded_at"] and
        (now - _SUCCESS_CONDITIONS_CACHE["loaded_at"]) < _td(minutes=30)):
        return _SUCCESS_CONDITIONS_CACHE["conditions"]

    successes = {"rsi_side": set(), "cci_side": set(), "obv_side": set(),
                 "regime_side": set(), "hour_side": set()}
    try:
        from app.workers.pattern_learning_worker import get_learning_insights
        insights = get_learning_insights(db) or {}
        snap = insights.get("snapshot_conditions") or {}
        for key_name, out_key in [
            ("rsi_conditions", "rsi_side"),
            ("cci_conditions", "cci_side"),
            ("obv_conditions", "obv_side"),
            ("regime_conditions", "regime_side"),
            ("hour_conditions", "hour_side"),
        ]:
            for row in snap.get(key_name, []):
                if row.get("total", 0) >= 5 and row.get("success_rate", 0) >= 0.60:
                    successes[out_key].add(row["key"])
    except Exception as e:
        logger.warning("[v201] 성공 조건 로드 실패: %s", e)

    _SUCCESS_CONDITIONS_CACHE["loaded_at"] = now
    _SUCCESS_CONDITIONS_CACHE["conditions"] = successes
    return successes


def _matches_success_condition(it: dict, side: str) -> bool:
    """🌟 v201: 진입 조건 = 학습된 성공 조건 매치?

    True 반환 = 성공 조건! = 필터 대폭 완화!
    """
    from app.core.database import SessionLocal as _SL
    _db = _SL()
    try:
        successes = _load_success_conditions(_db)
    finally:
        _db.close()

    match_count = 0

    rsi = it.get("rsi")
    if rsi is not None:
        rsi_bucket = _rsi_bucket_local(rsi)
        if f"{rsi_bucket}:{side}" in successes["rsi_side"]:
            match_count += 1

    cci = it.get("cci")
    if cci is not None:
        cci_bucket = _cci_bucket_local(cci)
        if f"{cci_bucket}:{side}" in successes["cci_side"]:
            match_count += 1

    obv = it.get("obv_slope_pct")
    if obv is not None:
        obv_bucket = _obv_bucket_local(obv)
        if f"{obv_bucket}:{side}" in successes["obv_side"]:
            match_count += 1

    regime = it.get("regime", "NEUTRAL")
    if f"{regime}:{side}" in successes["regime_side"]:
        match_count += 1

    kst_h = (datetime.now(timezone.utc).hour + 9) % 24
    if f"KST{kst_h:02d}:{side}" in successes["hour_side"]:
        match_count += 1

    # 5개 중 2개 이상 매치 = 성공 조건!
    return match_count >= 2


def _get_btc_change_24h() -> float | None:
    """🚨 v220 사장님 (2026-08-22): BTC 24h 변동 조회 = 시장 방향!"""
    try:
        from app.core.redis_client import get_redis_client
        import json as _j
        r = get_redis_client()
        _raw = r.get("ticker_24h:BTCUSDT")
        if _raw:
            _data = _j.loads(_raw.decode() if isinstance(_raw, bytes) else _raw)
            return float(_data.get("priceChangePercent", 0) or 0)
    except Exception:
        pass
    return None


def _matches_worst_scenario(it: dict, side: str) -> bool:
    """🚨 v220 사장님 (2026-08-22): WORST 시나리오 blocklist!
    사장님 지적: 손절 39건 -400 USDT = 학습된 최악 시나리오 진입!
    - suggestion_type:side 성공률 <20% + 표본 8건+ = blocklist!
    - bb4h_bottom_reversal:LONG (0%!), bb4h_top_reversal:SHORT (0%!) 자동 skip!
    """
    _stype = it.get("suggestion_type") or it.get("source", "")
    if not _stype:
        return False
    _key = f"{_stype}:{side}"
    try:
        from app.workers.pattern_learning_worker import get_learning_insights
        from app.core.database import SessionLocal as _SL
        _db2 = _SL()
        try:
            _insights = get_learning_insights(_db2) or {}
        finally:
            _db2.close()
        # type_side_rankings 조회!
        for r in _insights.get("type_side_rankings", []):
            if r.get("key") == _key and r.get("total", 0) >= WORST_SCENARIO_MIN_TOTAL:
                _rate = r.get("success_rate", 1.0)
                if _rate < WORST_SCENARIO_MAX_RATE:
                    return True  # WORST 시나리오 = skip!
    except Exception:
        pass
    return False


def _matches_btc_direction_conflict(side: str) -> bool:
    """🚨 v220 사장님 (2026-08-22): BTC 24h 방향 반대 = 진입 금지!
    - BTC 하락 3%+ = LONG 금지!
    - BTC 상승 3%+ = SHORT 금지!
    """
    _btc = _get_btc_change_24h()
    if _btc is None:
        return False  # BTC 데이터 없으면 = 통과!
    if side == "LONG" and _btc < -BTC_DIRECTION_THRESHOLD:
        return True  # BTC 하락 = LONG skip!
    if side == "SHORT" and _btc > BTC_DIRECTION_THRESHOLD:
        return True  # BTC 상승 = SHORT skip!
    return False


def _matches_failure_condition(it: dict, side: str) -> bool:
    """🎓 v198: 진입 조건 = 학습된 실패 조건 매치?

    True 반환 = 실패 조건! = 자동 진입 skip!

    🚨 v220 사장님 (2026-08-22): 손실 -400 USDT 방지 = 신 필터 통합!
    - WORST 시나리오 blocklist (성공률 <20%!)
    - BTC 방향 반대 (LONG 시 BTC 하락!)
    """
    # 🚨 v220 신 필터 우선! (사장님 자본 보호!)
    if _matches_worst_scenario(it, side):
        return True
    if _matches_btc_direction_conflict(side):
        return True

    from app.core.database import SessionLocal as _SL
    _db = _SL()
    try:
        failures = _load_failure_conditions(_db)
    finally:
        _db.close()

    # RSI 매치!
    rsi = it.get("rsi")
    if rsi is not None:
        rsi_bucket = _rsi_bucket_local(rsi)
        if f"{rsi_bucket}:{side}" in failures["rsi_side"]:
            return True

    # CCI 매치!
    cci = it.get("cci")
    if cci is not None:
        cci_bucket = _cci_bucket_local(cci)
        if f"{cci_bucket}:{side}" in failures["cci_side"]:
            return True

    # OBV 매치!
    obv = it.get("obv_slope_pct")
    if obv is not None:
        obv_bucket = _obv_bucket_local(obv)
        if f"{obv_bucket}:{side}" in failures["obv_side"]:
            return True

    # regime 매치!
    regime = it.get("regime", "NEUTRAL")
    if f"{regime}:{side}" in failures["regime_side"]:
        return True

    # 시간대 매치!
    kst_h = (datetime.now(timezone.utc).hour + 9) % 24
    if f"KST{kst_h:02d}:{side}" in failures["hour_side"]:
        return True

    return False


def _rsi_bucket_local(rsi: float) -> str:
    if rsi < 20: return "very_low (<20 극과매도)"
    if rsi < 30: return "low (20~30 과매도)"
    if rsi < 45: return "mid_low (30~45)"
    if rsi < 55: return "neutral (45~55)"
    if rsi < 70: return "mid_high (55~70)"
    if rsi < 80: return "high (70~80 과매수)"
    return "very_high (>80 극과매수)"


def _cci_bucket_local(cci: float) -> str:
    if cci < -200: return "extreme_low (<-200)"
    if cci < -100: return "low (-200~-100)"
    if cci < 0: return "mid_low (-100~0)"
    if cci < 100: return "mid_high (0~100)"
    if cci < 200: return "high (100~200)"
    return "extreme_high (>200)"


def _obv_bucket_local(obv: float) -> str:
    if obv < -10: return "strong_down (<-10%)"
    if obv < -3: return "down (-10~-3%)"
    if obv < 3: return "neutral (-3~+3%)"
    if obv < 10: return "up (+3~+10%)"
    return "strong_up (>+10%)"


def _get_worst_learning_keys(db: Session) -> set[str]:
    """🎓 v188+v194 사장님: 학습 인사이트 + 실제 손실 = WORST 심볼 자동 제외!

    v188: outcome_status 기반 (인사이트!)
    🚨 v194 (2026-08-20 사장님 실적 -798/24h 분석!):
    - 인사이트 outcome_status ≠ 실제 PnL! (CYSUSDT 88%인데 실제 -165!)
    - **실제 realized_pnl 기반 추가!**
    - 7일 -100 USDT+ 손실 심볼 = 자동 제외!
    """
    worst = set()
    # 1️⃣ v188: 학습 인사이트 기반!
    try:
        from app.workers.pattern_learning_worker import get_learning_insights
        insights = get_learning_insights(db) or {}
        for w in insights.get("worst_symbols_short", []):
            if w.get("total", 0) >= 5:
                worst.add(f"{w['symbol']}:SHORT")
        for w in insights.get("worst_symbols_long", []):
            if w.get("total", 0) >= 5:
                worst.add(f"{w['symbol']}:LONG")
    except Exception as e:
        logger.warning("[v188] worst 인사이트 로드 실패: %s", e)

    # 🚨 2️⃣ v194: 실제 realized_pnl 기반! (더 강력!)
    try:
        from datetime import timedelta as _td
        from app.core.strategy_status import TERMINAL_STATUSES as _TS
        cutoff = datetime.now(timezone.utc) - _td(days=7)
        rows = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.stopped_at >= cutoff)
            .where(StrategyInstance.status.in_(list(_TS)))
        ).scalars().all()
        sym_pnl: dict[str, dict] = {}
        for s in rows:
            key = f"{s.symbol}:{s.side}"
            pnl = float(s.realized_pnl or 0)
            if key not in sym_pnl:
                sym_pnl[key] = {"total": 0.0, "wins": 0, "losses": 0}
            sym_pnl[key]["total"] += pnl
            if pnl > 0:
                sym_pnl[key]["wins"] += 1
            elif pnl < 0:
                sym_pnl[key]["losses"] += 1
        # -100 USDT+ 손실 + 2건+ 손실 + 승률 <30% = worst!
        for key, s in sym_pnl.items():
            total_trades = s["wins"] + s["losses"]
            if total_trades < 2:
                continue
            win_rate = s["wins"] / total_trades if total_trades > 0 else 0
            if s["total"] <= -100 and win_rate < 0.30:
                worst.add(key)
                logger.info(
                    "[v194] worst 추가: %s (%.2f USDT, %d승/%d패)",
                    key, s["total"], s["wins"], s["losses"],
                )
    except Exception as e:
        logger.warning("[v194] realized_pnl worst 계산 실패: %s", e)
    return worst


def _get_top_learning_keys(db: Session) -> set[str]:
    """🎓 v188 + v195 사장님: TOP 심볼 (필터 완화!) + 실패 역이용!

    v188: 학습 인사이트 top 심볼!
    🌟 v195 (2026-08-20 사장님 지능!):
    "실패한 차트의 원인을 분석하고 학습해서 다음에 역으로 이용!"
    - CYSUSDT SHORT 실패 (-165!) → CYSUSDT LONG = **역 기회!**
    - USUSDT SHORT 실패 (-311!) → USUSDT LONG = **역 기회!**
    - 시장이 확실히 상승 → SHORT 실패 → LONG 진입!
    """
    top = set()
    # 1️⃣ v188: 학습 인사이트 top!
    try:
        from app.workers.pattern_learning_worker import get_learning_insights
        insights = get_learning_insights(db) or {}
        for t in insights.get("top_symbols_short", [])[:15]:
            if t.get("total", 0) >= 5 and t.get("success_rate", 0) >= 0.70:
                top.add(f"{t['symbol']}:SHORT")
        for t in insights.get("top_symbols_long", [])[:15]:
            if t.get("total", 0) >= 5 and t.get("success_rate", 0) >= 0.70:
                top.add(f"{t['symbol']}:LONG")
    except Exception as e:
        logger.warning("[v188] top 심볼 로드 실패: %s", e)

    # 🌟 2️⃣ v195: 실패 역이용! (반대 방향 = 기회!)
    try:
        inverse_opps = _get_inverse_opportunity_keys(db)
        top.update(inverse_opps)
        if inverse_opps:
            logger.info(
                "[v195] 실패 역이용 = %d개 (반대 방향 우대!): %s",
                len(inverse_opps), list(inverse_opps)[:5],
            )
    except Exception as e:
        logger.warning("[v195] 실패 역이용 실패: %s", e)
    return top


def _get_inverse_opportunity_keys(db: Session) -> set[str]:
    """🌟 v195 사장님 실패 역이용!

    사장님 사상 (2026-08-20):
    "실패한 차트의 원인을 분석하고 학습해서 다음에 역으로 이용할 수 있게!"

    로직:
    1. 7일 realized_pnl 심볼별 집계!
    2. SHORT 손실 심볼 → LONG 역기회!
    3. LONG 손실 심볼 → SHORT 역기회!
    4. -100 USDT+ 손실 + 2건+ 손실 + 승률 <30%
       = **반대 방향 = 시장이 확실히 그쪽으로 움직임 = 기회!**
    """
    inverse = set()
    try:
        from datetime import timedelta as _td
        from app.core.strategy_status import TERMINAL_STATUSES as _TS
        cutoff = datetime.now(timezone.utc) - _td(days=7)
        rows = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.stopped_at >= cutoff)
            .where(StrategyInstance.status.in_(list(_TS)))
        ).scalars().all()
        sym_pnl: dict[str, dict] = {}
        for s in rows:
            key = f"{s.symbol}:{s.side}"
            pnl = float(s.realized_pnl or 0)
            if key not in sym_pnl:
                sym_pnl[key] = {"total": 0.0, "wins": 0, "losses": 0}
            sym_pnl[key]["total"] += pnl
            if pnl > 0:
                sym_pnl[key]["wins"] += 1
            elif pnl < 0:
                sym_pnl[key]["losses"] += 1

        # 실패 심볼 = 반대 방향 = 역기회!
        for key, s in sym_pnl.items():
            total_trades = s["wins"] + s["losses"]
            if total_trades < 2:
                continue
            win_rate = s["wins"] / total_trades if total_trades > 0 else 0
            # -100 USDT+ 손실 + 승률 <30% = 확실한 실패!
            if s["total"] <= -100 and win_rate < 0.30:
                symbol, side = key.rsplit(":", 1)
                inverse_side = "LONG" if side == "SHORT" else "SHORT"
                inverse_key = f"{symbol}:{inverse_side}"
                # 반대 방향이 아직 손실 심볼이 아니면만 추가!
                inverse_stat = sym_pnl.get(inverse_key)
                if inverse_stat and inverse_stat["total"] < -50:
                    continue  # 반대도 이미 손실 = skip!
                inverse.add(inverse_key)
    except Exception as e:
        logger.warning("[v195] 역기회 계산 실패: %s", e)
    return inverse


# 🎯 v202 사장님 (2026-08-21): 재진입 마틴게일!
# 사장님 지시: "실패 심볼 재진입 시 = 옛 자본 × 1.5배! 최대 2번!"
REENTRY_MULTIPLIER = 1.5
MAX_REENTRY_COUNT = 2  # 🎯 v219 사장님 최종 (2026-08-22): 재진입 2번 = 3단계까지! (3단계 = 가급적 피해야!)
REENTRY_COUNT_TTL_DAYS = 7  # 7일 후 리셋!


def _get_reentry_count(symbol: str, side: str) -> int:
    """v202: 심볼:side의 재진입 카운터 (Redis!)"""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        val = r.get(f"reentry_count:{symbol}:{side}")
        return int(val) if val else 0
    except Exception:
        return 0


def _increment_reentry_count(symbol: str, side: str) -> int:
    """v202: 재진입 카운터 +1!"""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        new_count = _get_reentry_count(symbol, side) + 1
        r.setex(
            f"reentry_count:{symbol}:{side}",
            REENTRY_COUNT_TTL_DAYS * 86400,
            str(new_count),
        )
        return new_count
    except Exception:
        return 0


def _reset_reentry_count(symbol: str, side: str) -> None:
    """v202: 익절 성공 시 = 카운터 리셋!"""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        r.delete(f"reentry_count:{symbol}:{side}")
    except Exception:
        pass


def _calc_reentry_capital(symbol: str, side: str, base_capital: float) -> float | None:
    """v202+v204a: 재진입 자본!

    사장님 사상 (2026-08-21):
    "실패한 심볼은 모니터링 하다가 다시 진입할 시점에 이전 포지션의 1.5배!
     2번까지 할수 있는 로직!"

    - counter=0 (실패 후 1차 재진입!) = base × **1.5!** (예: 300 → 450!)
    - counter=1 (2차 재진입!) = base × **1.5² = 2.25!** (예: 300 → 675!)
    - counter=2 (최대 도달!) = None (진입 X!)

    🚨 v204a fix (agent 검증!): 옛 로직 = counter=0에서 1.0x 였음!
    = 사장님 「1.5배」 사상 미적용!
    = 신 로직: count + 1 = 항상 1.5배 이상!
    """
    count = _get_reentry_count(symbol, side)
    if count >= MAX_REENTRY_COUNT:
        return None  # 최대 도달!
    # v204a fix: 재진입은 무조건 1.5^(count+1)!
    multiplier = REENTRY_MULTIPLIER ** (count + 1)
    return base_capital * multiplier


def _is_reentry_candidate(db: Session, symbol: str, side: str) -> bool:
    """v202: 이 심볼:side가 = 재진입 후보?
    (최근 24h 손실 있고 = 카운터 <2)
    """
    if _get_reentry_count(symbol, side) >= MAX_REENTRY_COUNT:
        return False
    # 최근 24h 이 심볼 실패 있으면 = 재진입 후보!
    try:
        from app.core.strategy_status import TERMINAL_STATUSES as _TS
        from datetime import timedelta as _td
        cutoff = datetime.now(timezone.utc) - _td(hours=24)
        rows = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.symbol == symbol)
            .where(StrategyInstance.side == side)
            .where(StrategyInstance.stopped_at >= cutoff)
            .where(StrategyInstance.status.in_(list(_TS)))
        ).scalars().all()
        return any(float(s.realized_pnl or 0) < 0 for s in rows)
    except Exception:
        return False


def _apply_obv_hold_settings(db: Session, strategy: StrategyInstance) -> None:
    """🎯 사장님 사상 (2026-08-21): OBV 전용 = 오래 버티기 설정!

    사장님 verbatim:
    "OBV 전략은 실패하면 큰 손실이 나올꺼야 이전략은 청산될때까지 운영할수있게 해줘
    중간에 증거금이나 포지션 수동진입해서 최대한 오래 버티게 할수 있는 구조!"

    설정:
    - 강제 SL 비활성 (force_sl_enabled_override=False!)
    - 사장님 수동 증거금/포지션 추가 가능!
    - Liquidation까지 = 버티기!

    구성:
    - 3단계 진입! (각 400 USDT = 총 1200!)
    - 2단계 트리거 -5% (반대!)
    - 3단계 트리거 -10%
    - 강제 SL X = Liquidation까지 버티기!
    """
    try:
        strategy.force_sl_enabled_override = False
        db.commit()
        logger.info(
            "[auto_obv_hold] 🎯 OBV 전략 설정: strategy=%s force_sl=X (오래 버티기!)",
            strategy.id,
        )
    except Exception as e:
        logger.warning("[auto_obv_hold] 설정 실패: %s", e)


def _is_success_reentry_candidate(db: Session, symbol: str, side: str) -> bool:
    """🚀 v204 사장님 (2026-08-21): 성공 후 재진입 후보!

    사장님 사상: "익절 시작하고 우리 로직으로 강력한 포지션 진입일 경우
                초기 시작금액으로 즉시 포지션 진입해서 수익을 더해가고
                다시 하락하면 -5% 청산!"

    조건:
    - 최근 24h 이 심볼:side 익절 완료 있음! (realized_pnl > 0!)
    - 지금 활성 X! (진입 안 함!)
    - 자본 = 초기 (v202 마틴게일 X - 무제한 사이클!)
    """
    try:
        from app.core.strategy_status import TERMINAL_STATUSES as _TS
        from datetime import timedelta as _td
        cutoff = datetime.now(timezone.utc) - _td(hours=24)
        rows = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.symbol == symbol)
            .where(StrategyInstance.side == side)
            .where(StrategyInstance.stopped_at >= cutoff)
            .where(StrategyInstance.status.in_(list(_TS)))
        ).scalars().all()
        # 최근 24h = 이익 있으면 = 성공 재진입 후보!
        return any(float(s.realized_pnl or 0) > 0 for s in rows)
    except Exception:
        return False


def _get_recent_loss_symbol_keys(db: Session) -> set[str]:
    """🚨 v179: 최근 48h 손실 심볼 keys! (v176 24h → v179 48h!)

    사장님 CBRSUSDT #1013 = -10.97% 손실 → 3분 후 재진입 = 같은 심볼!
    = 손실 후 즉시 재진입 = 위험! 48h 쿨다운!
    """
    from datetime import timedelta
    loss_keys = set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOSS_BLOCKLIST_HOURS)
    # STOPPED 이면서 = realized_pnl < 0 = 손실 심볼!
    for s in db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.status.in_([
            "STOPPED", "CLOSED", "CLOSED_BY_SL", "STOPPED_CAPITAL_EXHAUSTED",
        ]))
        .where(StrategyInstance.stopped_at >= cutoff)
    ).scalars().all():
        try:
            pnl = float(s.realized_pnl or 0)
            if pnl < 0:  # 손실!
                loss_keys.add(f"{s.symbol}:{s.side}")
        except Exception:
            pass
    return loss_keys


def _create_auto_bb_strategy(
    db: Session, symbol: str, side: str, cfg: dict[str, Any],
    strategy_type_suffix: str = "",
) -> StrategyInstance:
    """사장님 default profile 기반 = template + strategy 자동 생성!

    🎯 v203: strategy_type_suffix (예: "_reentry1") = 재진입 번호!
    - "" = 첫 진입 (기본!)
    - "_reentry1" = 1차 재진입!
    - "_reentry2" = 2차 재진입!
    """
    # symbol 검증!
    symbol_row = db.execute(
        select(Symbol).where(Symbol.symbol == symbol)
    ).scalar_one_or_none()
    if not symbol_row:
        raise ValueError(f"symbol {symbol} not in DB")

    # 🌟 v177 사장님 (2026-08-19): 자동 진입 = 1단계만 강제!
    # 🎯 사장님 (2026-08-21): OBV_HOLD 예외! = 3단계 + 오래 버티기!
    capitals_full = cfg.get("capitals") or [500, 500, 500, 500]
    stage1_only = float(capitals_full[0]) if capitals_full else 500.0

    _is_obv_hold = strategy_type_suffix == "_OBV_HOLD"
    if _is_obv_hold:
        # 🎯 사장님 세팅! (system_settings에서 조회!)
        def _get_obv(k, default):
            row = db.get(SystemSetting, f"auto_obv_{k}")
            if row and row.value:
                try:
                    return float(row.value) if isinstance(default, float) else int(row.value)
                except (ValueError, TypeError):
                    return default
            return default
        _obv_base = float(_get_obv("capital_per_stage", 400))
        _obv_trig2 = _get_obv("stage2_trigger", -5.0)
        _obv_trig3 = _get_obv("stage3_trigger", -10.0)
        capitals = [_obv_base, _obv_base, _obv_base]
        total_capital = _obv_base * 3
        stages_config = {
            "capitals": capitals,
            "trigger_percents": [None, _obv_trig2, _obv_trig3],
            "stages_count": 3,
        }
    else:
        # v177: 1단계 강제!
        capitals = [stage1_only]
        total_capital = stage1_only
        stages_config = {
            "capitals": capitals,
            "trigger_percents": [None],
            "stages_count": 1,
        }

    # 신 template = 1단계만!
    now = datetime.now(timezone.utc)
    # v204a fix (agent 검증): _success suffix = "_REENTRY_success" (혼동!) → "_SUCCESS"
    if strategy_type_suffix == "_success":
        _tpl_name_suffix = "_SUCCESS"
    elif strategy_type_suffix and strategy_type_suffix.startswith("_reentry"):
        _tpl_name_suffix = f"_REENTRY{strategy_type_suffix.replace('_reentry', '')}"
    else:
        _tpl_name_suffix = ""
    # 🎯 OBV_HOLD = 3단계! 나머지 = 1단계!
    _stage1_cap = capitals[0]
    _stage2_cap = capitals[1] if _is_obv_hold else None
    _stage3_cap = capitals[2] if _is_obv_hold else None
    _stage2_trig = Decimal(str(_obv_trig2)) if _is_obv_hold else None
    _stage3_trig = Decimal(str(_obv_trig3)) if _is_obv_hold else None
    tpl = StrategyTemplate(
        name=f"AUTO_BB_{symbol}_{side}_{now.strftime('%Y%m%d_%H%M%S')}{_tpl_name_suffix}",
        strategy_type=f"auto_bb_break{strategy_type_suffix}",  # 🎯 v203: 재진입 정보!
        side=side,
        leverage=int(cfg.get("leverage", 2)),
        total_capital=Decimal(str(total_capital)),
        stages_config=stages_config,
        stage1_capital=Decimal(str(_stage1_cap)),
        stage2_capital=Decimal(str(_stage2_cap)) if _stage2_cap else None,
        stage3_capital=Decimal(str(_stage3_cap)) if _stage3_cap else None,
        stage4_capital=None,
        stage2_trigger_percent=_stage2_trig,
        stage3_trigger_percent=_stage3_trig,
        stage4_trigger_percent=None,
        tp1_percent=Decimal(str(cfg.get("tp1_percent", 10))),
        tp2_percent=Decimal(str(cfg.get("tp2_percent", 15))),
        tp3_percent=Decimal(str(cfg.get("tp3_percent", 20))),
        tp4_percent=Decimal(str(cfg.get("tp4_percent", 25))),
        tp1_qty_ratio=Decimal(str(cfg.get("tp1_qty_ratio", 10))),
        tp2_qty_ratio=Decimal(str(cfg.get("tp2_qty_ratio", 15))),
        tp3_qty_ratio=Decimal(str(cfg.get("tp3_qty_ratio", 20))),
        tp4_qty_ratio=Decimal(str(cfg.get("tp4_qty_ratio", 25))),
        stop_loss_percent_of_capital=Decimal(str(cfg.get("stop_loss_percent_of_capital", 90))),
        is_active=True,
    )
    db.add(tpl)
    db.flush()

    # 🎯 사장님 CRITICAL 요구 (2026-08-21): 자동 진입 = MARKET!
    # 롤백 (2026-08-22): start_price=None → planned_capital=None 오류!
    # = 현재가 필요 (preview 계산 위해!). MARKET 여부 = start_price로 판정!
    from app.services.strategy_service import StrategyService
    svc = StrategyService(db)

    # 현재가 조회 (preview 계산 필수!)
    start_price = _get_current_price(symbol)
    if not start_price or start_price <= 0:
        logger.warning("[auto_bb_breakdown] %s %s: 현재가 없음 = skip", symbol, side)
        return None

    strategy = svc.create_strategy_instance(
        user_id=1,
        exchange_account_id=1,
        strategy_template_id=tpl.id,
        symbol=symbol,
        side=side,
        start_price=start_price,  # 필수 (preview 계산!)
        leverage_override=int(cfg.get("leverage", 2)),
        retry_after_liquidation_enabled=bool(cfg.get("retry_after_liquidation_enabled", False)),
        retry_trigger_pct=(
            Decimal(str(cfg.get("retry_trigger_pct", 10)))
            if cfg.get("retry_trigger_pct") else None
        ),
    )

    # 🌟 v225 사장님 v219 사상 (2026-08-23): 신 자동 진입 = SL 강제 -80%!
    # 사장님 verbatim: "최종청산가는 -80%!"
    # = 전역 기본 (롱 -5%/숏 OFF) 무시 = 전략별 override로 -80% 강제!
    # SHORT도 강제 ON (전역 SHORT default=OFF 무시!)
    # ⚠️ OBV_HOLD 예외 = 오래 버티기 = 강제 SL 비활성 (기존 로직 존중!)
    if not _is_obv_hold:
        try:
            strategy.force_sl_enabled_override = True
            strategy.force_sl_roi_override = Decimal("80")  # ROI <= -80% 시 발동!
            db.commit()
            logger.info(
                "[auto_bb_breakdown] 🎯 v225 SL 강제 -80%%: strategy=%s %s %s",
                strategy.id, symbol, side,
            )
        except Exception as _sl_e:
            logger.warning("[auto_bb_breakdown] v225 SL -80%% 세팅 실패 (fail-open): %s", _sl_e)
            db.rollback()

    # 🎯 Agent 검증 fix v2 (2026-08-22): 자동 진입 = 실 주문 발송!
    # Agent 진단: v162부터 = create_strategy_instance는 DB row만 생성 = 실 주문 X!
    # = 모든 auto_bb_breakdown "진입"이 = 실은 미진입 상태로만 저장!
    # Fix (Option A 권장): auto_reentry_worker 패턴 그대로 복제!
    #   1. stage1.trigger_price=None (MARKET 경로 발동!)
    #   2. ExecutionService.start_stage1() 호출 (실 주문!)
    try:
        from app.models.strategy_stage_plan import StrategyStagePlan
        _stage1 = db.execute(
            select(StrategyStagePlan)
            .where(StrategyStagePlan.strategy_instance_id == strategy.id)
            .where(StrategyStagePlan.stage_no == 1)
        ).scalar_one_or_none()
        if _stage1:
            _stage1.trigger_price = None  # v130 MARKET 경로 강제!
            db.commit()
    except Exception as _mkt_e:
        logger.warning("[auto_bb_breakdown] trigger_price=None 실패 (fail-open): %s", _mkt_e)

    # 🎯 v218 fix (2026-08-22 사장님!): 실 진입 실패 시 = 좀비 정리 + None 반환!
    # 이전: fail-open = strategy 반환 + caller가 EXECUTED 마킹 = 가짜 진입 = slot 소모!
    # 사장님 사상: "실패는 재시도!" = suggestion PENDING 유지 = 다음 사이클 재도전!
    _entry_success = False
    try:
        from app.services.execution_service import ExecutionService
        from app.core.crypto import decrypt_text
        from app.models.exchange_account import ExchangeAccount
        _acc = db.get(ExchangeAccount, 1)
        if not _acc:
            logger.warning("[auto_bb_breakdown] ExchangeAccount id=1 없음!")
        else:
            _exec = ExecutionService(
                db,
                api_key=decrypt_text(_acc.api_key_enc),
                api_secret=decrypt_text(_acc.api_secret_enc),
                is_testnet=_acc.is_testnet,
            )
            _exec.start_stage1(strategy.id)
            _entry_success = True
            logger.info(
                "[auto_bb_breakdown] 🎯 실 진입 성공: %s %s strategy=%s (MARKET!)",
                symbol, side, strategy.id,
            )
    except Exception as _entry_e:
        logger.warning(
            "[auto_bb_breakdown] ❌ 실 진입 실패 (좀비 정리!): %s %s: %s",
            symbol, side, _entry_e,
        )

    if not _entry_success:
        # 🚨 v218: 좀비 방지 = strategy + template + stage_plans 삭제!
        try:
            db.rollback()
            _sid = strategy.id
            _tid = tpl.id
            db.delete(strategy)
            db.commit()
            _tpl_row = db.get(StrategyTemplate, _tid)
            if _tpl_row:
                db.delete(_tpl_row)
                db.commit()
            logger.info(
                "[auto_bb_breakdown] 🧹 v218 좀비 정리: strategy=%s template=%s 삭제!",
                _sid, _tid,
            )
        except Exception as _cleanup_e:
            logger.warning("[auto_bb_breakdown] 좀비 정리 실패: %s", _cleanup_e)
            db.rollback()
        return None  # caller가 skip 판단!

    return strategy


def _get_current_price(symbol: str) -> Decimal:
    """현재가 조회 = start_price!"""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        val = r.get(f"mark_price:{symbol}")
        if val:
            return Decimal(str(val.decode() if isinstance(val, bytes) else val))
    except Exception:
        pass
    # fallback = Binance API!
    try:
        from app.integrations.binance.client import BinanceClient
        from app.models.exchange_account import ExchangeAccount
        from app.core.crypto import decrypt_text
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            account = db.execute(
                select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
            ).scalar_one_or_none()
            if account:
                bc = BinanceClient(
                    api_key=decrypt_text(account.api_key_enc),
                    api_secret=decrypt_text(account.api_secret_enc),
                    is_testnet=False,
                )
                ticker = bc.get_24hr_ticker(symbol=symbol)
                if isinstance(ticker, dict):
                    return Decimal(str(ticker.get("lastPrice", 0)))
        finally:
            db.close()
    except Exception:
        pass
    raise ValueError(f"현재가 조회 실패: {symbol}")


def _notify_auto_entry(strategy: StrategyInstance, prob: float, scan_info: dict) -> None:
    """자동 진입 텔레그램 알림! (v193 fix: NotificationService(db) 직접 사용!)"""
    try:
        # 🌟 v193 fix: get_notification_service 함수 없음 → NotificationService(db) 직접!
        from app.services.notification_service import NotificationService
        db_notif = SessionLocal()
        ns = NotificationService(db_notif)
        emoji = "🐻" if strategy.side == "SHORT" else "🐂"
        source = scan_info.get("source", "BB_SUSTAINED")
        source_icon = "🎯" if source == "MTA" else "⚡"
        body_lines = [
            f"{source_icon} {source} 자동 진입!",
            f"📊 성공률: {int(prob * 100)}%",
            f"🎯 regime: {scan_info.get('regime', 'NEUTRAL')}",
            f"🔥 지속 봉수: {scan_info.get('sustained_bars', 0)}봉",
        ]
        # v190: MTA 정보!
        if source == "MTA" and scan_info.get("mta_total"):
            body_lines.append(f"🎯 MTA 종합점수: {scan_info['mta_total']}/24")
            body_lines.append(f"📈 {scan_info.get('mta_reason', '')}"[:100])
        body_lines.extend([
            f"💰 자본: {strategy.total_capital} USDT",
            f"⚖️ 레버리지: {strategy.leverage}x",
            "",
            f"= 사장님 default profile 자동 진입!",
            f"= 대시보드 확인!",
        ])
        ns.send_system_alert(
            title=f"🤖 [자동 진입] #{strategy.id} {strategy.symbol} {strategy.side} {emoji}",
            body="\n".join(body_lines),
        )
        try:
            db_notif.close()
        except Exception:
            pass
    except Exception as e:
        logger.warning("[auto_bb_breakdown] 알림 실패: %s", e)
