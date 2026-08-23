"""🌟 v224 (2026-08-23 사장님 통합 요구!): 모든 자동매매 = 15m 급등/급락 심볼 통합!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 verbatim (2026-08-23):
  "지금까지 모든 자동매매는 오늘 15분 차트 급등과 급락한 심볼만
   자동매매를 하는걸로 통합해서 운영할수 있게 하나도 통합정리해줘"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

= 15분 차트 급등/급락 = 유일한 진입 유니버스!
= 모든 자동매매 진입 소스 (BB SUSTAINED / PENDING_HC / OBV_REVERSE /
  pump_top / pending_hc_fast) = 이 워커 하나로 통합!

로직 (매 30초 실행!):
  1. 상위 거래대금 심볼 (top ~40) + 24h |변동| ≥ 3% 후보!
  2. 각 심볼 15m 캔들 조회 (analyze_timeframe → Redis 캐시!)
  3. 오늘 15m 급등/급락 = A OR B 트리거!
     A. 4봉 (1시간) 변동 ≥ ±unified_15m_1h_pct (default 5%!)
     B. 12봉 (3시간) 변동 ≥ ±unified_15m_3h_pct (default 10%!)
  4. 방향 = 급등→SHORT (정점 반전!) / 급락→LONG (저점 반등!)
  5. v223 = 15m score ≥3/5 + 1h/4h 반대 방향 <3/5!
  6. 필터: 활성 심볼 / 최근 48h 손실 / 학습된 실패 조건!
  7. 통과 = _create_auto_bb_strategy = 실 주문!
  8. suggestion_type="unified_15m_entry" 저장!

daily_limit = SystemSetting "auto_bb_break_daily_limit" 공유!
(v219 통합 사상 유지 = _count_used_slots가 이미 unified_15m_entry 포함!)

이 워커가 켜지면 (unified_entry_enabled=1) 아래 워커는 disable!
  - auto_bb_breakdown (BB 4H!)
  - pump_top_detector (v219/v222/v223!)
  - auto_short_at_top (정점 SHORT!)
  - pending_hc_fast (PENDING_HC 85%+!)

후속 대응 워커는 유지 (통합 아님!):
  - realtime_reentry (마틴게일 재진입!)
  - success_pyramiding (익절중 추가!)
  - auto_add_margin (증거금 추가!)
  - reentry_alert_watcher (OBV 알람 저장 = 학습용!)

헌법 70 (2026-08-23): 15m 급등/급락 = 유일 진입 유니버스 (사장님 통합!)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_suggestion import StrategySuggestion
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

# ─── 상수 (SystemSetting 없을 시 default!) ─────────────────────────────
MAX_SYMBOLS = 40                    # 스캔 상한 (API Ban 방지!)
MIN_24H_CHANGE_PREFILTER = 3.0      # 24h |변동| ≥ 3% pre-filter!
DEFAULT_1H_PCT = 5.0                # 4봉 (1시간) 변동 ≥ ±5% (사장님 core!)
DEFAULT_3H_PCT = 10.0               # 12봉 (3시간) 변동 ≥ ±10%
DEFAULT_LEVERAGE = 2                # 사장님 default!
V223_MIN_SCORE = 3                  # 15m score 최소치
V223_OPP_SKIP = 3                   # 1h/4h 반대 score >= 이 값 = skip!
SUGGESTION_TYPE = "unified_15m_entry"  # 통합 마커!


# ─── SystemSetting 로더 ────────────────────────────────────────────────
def _get_setting_int(db: Session, key: str, default: int) -> int:
    try:
        row = db.get(SystemSetting, key)
        if row and row.value:
            return int(row.value)
    except Exception:
        pass
    return default


def _get_setting_float(db: Session, key: str, default: float) -> float:
    try:
        row = db.get(SystemSetting, key)
        if row and row.value:
            return float(row.value)
    except Exception:
        pass
    return default


# ─── 트리거 판정 ───────────────────────────────────────────────────────
def _detect_15m_surge(
    closes: list[float],
    pct_1h: float,
    pct_3h: float,
) -> tuple[bool, str | None, dict[str, float]]:
    """오늘 15m 급등/급락 감지!

    Returns:
        (matched, side, meta)
        - matched=True: 15m 급등/급락!
        - side="SHORT" (급등!) or "LONG" (급락!)
        - meta = {change_1h_pct, change_3h_pct, matched_window}
    """
    if not closes or len(closes) < 13:
        return False, None, {}
    last = closes[-1]
    c1h = ((last / closes[-5]) - 1.0) * 100.0    # 4봉 이전 = 1시간!
    c3h = ((last / closes[-13]) - 1.0) * 100.0   # 12봉 이전 = 3시간!
    meta = {"change_1h_pct": round(c1h, 3), "change_3h_pct": round(c3h, 3)}

    # A. 4봉 트리거!
    if abs(c1h) >= pct_1h:
        side = "SHORT" if c1h > 0 else "LONG"
        meta["matched_window"] = "1h"
        meta["matched_pct"] = round(c1h, 3)
        return True, side, meta
    # B. 12봉 트리거!
    if abs(c3h) >= pct_3h:
        side = "SHORT" if c3h > 0 else "LONG"
        meta["matched_window"] = "3h"
        meta["matched_pct"] = round(c3h, 3)
        return True, side, meta
    meta["matched_window"] = None
    return False, None, meta


# ─── 메인 워커 ─────────────────────────────────────────────────────────
def run_unified_15m_entry() -> dict:
    """🌟 v224: 15m 급등/급락 통합 진입 워커! (매 30초!)"""
    db: Session = SessionLocal()
    entered = 0
    skipped = 0
    scanned = 0
    surges_found = 0
    results: list[dict] = []
    try:
        # 1. 활성화 여부!
        if not _get_setting_int(db, "unified_entry_enabled", 1):
            return {"note": "unified_entry_enabled=0 (OFF!)", "entered": 0}

        # 2. daily_limit = auto_bb_break_daily_limit 공유! (v219 통합!)
        daily_limit = _get_setting_int(db, "auto_bb_break_daily_limit", 0)
        if daily_limit <= 0:
            return {"note": "daily_limit=0 (OFF!)", "entered": 0}

        # 3. used slots = 통합 카운터 (v219 통합 유지!)
        from app.workers.auto_bb_breakdown_worker import (
            _count_used_slots,
            _get_active_symbol_keys,
            _get_recent_loss_symbol_keys,
            _matches_failure_condition,
            _create_auto_bb_strategy,
        )
        used = _count_used_slots(db)
        remaining = daily_limit - used
        if remaining <= 0:
            return {"note": f"오늘 {used}/{daily_limit} 소진!", "entered": 0}

        # 4. mainnet 계정 + API Ban!
        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            return {"error": "mainnet 계정 없음!", "entered": 0}
        from app.core.api_backoff import is_account_banned
        if is_account_banned(account.id):
            return {"note": "API Ban 중 = skip!", "entered": 0}

        # 5. BinanceClient!
        from app.integrations.binance.client import BinanceClient
        from app.core.crypto import decrypt_text
        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )

        # 6. 세팅 로드!
        pct_1h = _get_setting_float(db, "unified_15m_1h_pct", DEFAULT_1H_PCT)
        pct_3h = _get_setting_float(db, "unified_15m_3h_pct", DEFAULT_3H_PCT)

        # 7. 24h ticker → pre-filter!
        tickers = bc.get_24hr_ticker()
        if not isinstance(tickers, list):
            return {"error": "ticker 실패!", "entered": 0}
        usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
        try:
            usdt.sort(key=lambda x: float(x.get("quoteVolume", 0) or 0), reverse=True)
        except Exception:
            pass
        candidates = [
            t for t in usdt[:MAX_SYMBOLS * 2]
            if abs(float(t.get("priceChangePercent", 0) or 0)) >= MIN_24H_CHANGE_PREFILTER
        ][:MAX_SYMBOLS]
        if not candidates:
            return {"note": "24h 후보 없음!", "entered": 0}

        # 8. 활성 + 손실 심볼!
        active_keys = _get_active_symbol_keys(db)
        recent_loss_keys = _get_recent_loss_symbol_keys(db)

        # 9. default profile!
        from app.api.v1.suggestion_profiles import _load_profiles
        profiles, default_name = _load_profiles(db)
        default_profile = next(
            (p for p in profiles if p.get("name") == default_name), None,
        )
        if not default_profile:
            return {"error": "default profile 없음!", "entered": 0}
        cfg_base = default_profile.get("config", {})

        # 10. 자본 = 사장님 default (300 USDT!)
        from app.services.sajangnim_capital import compute_stage1_capital
        base_capital = float(compute_stage1_capital(bc, db))

        # 11. v223 검사기!
        from app.services.chart_analyzer import ChartAnalyzer
        from app.workers.pump_top_detector_worker import PumpTopDetector

        # 12. 심볼 순회!
        for t in candidates:
            if entered >= remaining:
                break
            symbol = str(t.get("symbol", ""))
            if not symbol:
                continue
            scanned += 1

            try:
                # 12a. 15m 분석! (Redis 캐시 재사용!)
                a15 = ChartAnalyzer.analyze_timeframe(bc, symbol, "15m", limit=60)
                if not a15:
                    continue
                closes = a15.get("closes") or []
                matched, side, surge_meta = _detect_15m_surge(closes, pct_1h, pct_3h)
                if not matched or side is None:
                    continue
                surges_found += 1

                key = f"{symbol}:{side}"

                # 12b. 활성 심볼 skip!
                if key in active_keys:
                    skipped += 1
                    continue

                # 12c. 최근 48h 손실 skip! (마틴게일은 realtime_reentry_worker 담당!)
                if key in recent_loss_keys:
                    skipped += 1
                    logger.info(
                        "[unified_15m_v224] skip %s (최근 48h 손실 = 재진입은 realtime_reentry!)",
                        key,
                    )
                    continue

                # 12d. v223 = 15m score + 1h/4h 역방향!
                v = PumpTopDetector.check_v223_15m_primary(bc, symbol, side)
                if not v.get("detected"):
                    logger.debug(
                        "[unified_15m_v224] v223 skip %s %s: %s",
                        symbol, side, v.get("reason"),
                    )
                    continue
                confidence = float(v.get("confidence", 0) or 0)

                # 12e. 학습된 실패 조건 skip! (BTC 방향 + WORST 시나리오 포함!)
                snap15 = (v.get("entry_snapshot") or {}).get("15m") or {}
                _filter_it = {
                    "symbol": symbol,
                    "rsi": snap15.get("rsi_now"),
                    "cci": snap15.get("cci_now"),
                    "obv_slope_pct": None,   # 15m OBV slope는 계산 X (필터만!)
                    "regime": "NEUTRAL",     # 15m 기반 = regime 판정 X → NEUTRAL로 fail-open!
                    "change_24h": float(t.get("priceChangePercent", 0) or 0),
                    "source": "UNIFIED_15M",
                    "suggestion_type": SUGGESTION_TYPE,
                }
                if _matches_failure_condition(_filter_it, side):
                    skipped += 1
                    logger.info(
                        "[unified_15m_v224] 학습 실패 조건 skip: %s %s",
                        symbol, side,
                    )
                    continue

                # 12f. 실 진입!
                entry_cfg = dict(cfg_base)
                entry_cfg["capitals"] = [base_capital]
                entry_cfg["leverage"] = int(cfg_base.get("leverage", DEFAULT_LEVERAGE))
                new_strategy = _create_auto_bb_strategy(
                    db, symbol, side, entry_cfg,
                    strategy_type_suffix="_UNIFIED_15M",
                )
                if not new_strategy:
                    skipped += 1
                    logger.info(
                        "[unified_15m_v224] ❌ %s %s 진입 실패 = skip (재시도!)",
                        symbol, side,
                    )
                    continue

                # 12g. StrategySuggestion 저장 (학습!)
                _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
                entry_snapshot = {
                    "rsi": snap15.get("rsi_now"),
                    "cci": snap15.get("cci_now"),
                    "obv_slope_pct": None,
                    "regime": "NEUTRAL",
                    "sustained_bars": 0,
                    "change_24h": float(t.get("priceChangePercent", 0) or 0),
                    "source": "UNIFIED_15M",
                    "kst_hour": _kst_hour,
                    "confidence": confidence,
                    "score_15m": v.get("score_15m"),
                    "opp_score_1h": v.get("opp_score_1h"),
                    "opp_score_4h": v.get("opp_score_4h"),
                    "surge_meta": surge_meta,
                    "spec_version": "v224",
                    "entered_at": datetime.now(timezone.utc).isoformat(),
                }
                sugg = StrategySuggestion(
                    symbol=symbol, side=side,
                    suggestion_type=SUGGESTION_TYPE,
                    strategy_config={
                        **entry_cfg,
                        "symbol": symbol, "side": side,
                        "unified_15m": True,
                        "entry_snapshot": entry_snapshot,
                    },
                    confidence_score=Decimal(str(round(confidence, 4))),
                    reason=(
                        f"🌟 통합 15m 진입 (v224)! "
                        f"급등/급락={surge_meta.get('matched_window')} "
                        f"({surge_meta.get('matched_pct', 0):+.2f}%) "
                        f"conf={confidence*100:.0f}% "
                        f"15m={v.get('score_15m')}/5 "
                        f"opp(1h={v.get('opp_score_1h')},4h={v.get('opp_score_4h')}) "
                        f"24h={float(t.get('priceChangePercent', 0) or 0):+.1f}% "
                        f"RSI={snap15.get('rsi_now')} CCI={snap15.get('cci_now')} "
                        f"KST={_kst_hour:02d}h"
                    ),
                    status="EXECUTED",
                    execution_mode="AUTO",
                    executed_at=datetime.now(timezone.utc),
                    executed_strategy_id=new_strategy.id,
                    outcome_status="PENDING",
                )
                db.add(sugg)
                db.commit()

                entered += 1
                results.append({
                    "symbol": symbol, "side": side,
                    "confidence": confidence,
                    "capital": base_capital,
                    "strategy_id": new_strategy.id,
                    "surge": surge_meta,
                })

                logger.warning(
                    "[unified_15m_v224] ✅ 통합 진입: #%d %s %s "
                    "conf=%.2f 급등/급락=%s(%+.2f%%) 15m=%d/5",
                    new_strategy.id, symbol, side, confidence,
                    surge_meta.get("matched_window"),
                    surge_meta.get("matched_pct", 0),
                    v.get("score_15m", 0),
                )

                # 12h. 텔레그램!
                try:
                    from app.services.notification_service import NotificationService
                    _db_n = SessionLocal()
                    try:
                        _ns = NotificationService(_db_n)
                        emoji = "🐻" if side == "SHORT" else "🐂"
                        _ns.send_system_alert(
                            title=(
                                f"🌟 [v224 통합] {symbol} {side} 진입! "
                                f"({confidence*100:.0f}%)"
                            ),
                            body=(
                                f"{emoji} 15m 급등/급락 통합 자동 진입!\n"
                                f"심볼: {symbol} {side}\n"
                                f"자본: {base_capital:.2f} USDT × {int(entry_cfg['leverage'])}x\n"
                                f"신뢰도: {confidence*100:.0f}% "
                                f"(15m={v.get('score_15m')}/5)\n"
                                f"트리거: {surge_meta.get('matched_window')} "
                                f"= {surge_meta.get('matched_pct', 0):+.2f}%\n"
                                f"24h: {float(t.get('priceChangePercent', 0) or 0):+.1f}%\n"
                                f"오늘 {used + entered}/{daily_limit}"
                            ),
                        )
                    finally:
                        try:
                            _db_n.close()
                        except Exception:
                            pass
                except Exception as _te:
                    logger.warning("[unified_15m_v224] telegram 실패: %s", _te)

                # 12i. 오케스트라 EventBus!
                try:
                    from app.agents.orchestrator.event_bus import get_event_bus
                    from app.agents.orchestrator.event_types import EventType
                    get_event_bus().publish(EventType.AUTO_ENTRY_TRIGGERED, {
                        "strategy_id": new_strategy.id,
                        "symbol": symbol, "side": side,
                        "prob": confidence,
                        "source": "UNIFIED_15M",
                        "surge": surge_meta,
                    })
                except Exception as _be:
                    logger.debug("[unified_15m_v224] EventBus 실패: %s", _be)

            except Exception as e:
                logger.warning(
                    "[unified_15m_v224] %s 처리 실패: %s", symbol, e,
                )
                skipped += 1
                db.rollback()
                continue

        logger.info(
            "[unified_15m_v224] 완료: scanned=%d surges=%d entered=%d skipped=%d "
            "(daily %d/%d)",
            scanned, surges_found, entered, skipped, used + entered, daily_limit,
        )
        return {
            "daily_limit": daily_limit,
            "used_before": used,
            "remaining_before": remaining,
            "scanned": scanned,
            "surges_found": surges_found,
            "entered": entered,
            "skipped": skipped,
            "results": results,
            "spec_version": "v224",
        }
    except Exception as e:
        logger.exception("[unified_15m_v224] 예외: %s", e)
        return {"error": str(e), "entered": entered}
    finally:
        try:
            db.close()
        except Exception:
            pass
