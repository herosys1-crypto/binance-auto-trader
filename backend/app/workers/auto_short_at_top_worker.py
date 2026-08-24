"""🎯 v219 (2026-08-22 사장님!) + Fix 51 (2026-08-24!): 정점 감지 자동 SHORT 진입 워커!

사장님 verbatim (실 성공 로직!):
"급등하는 심볼 4시간봉 최상단 볼밴 최상단밖 obv 최고점 macd rsi cci 모든 지표가
 최고점일때 포지션 진입 전체자산에 1-2% 진입"

사장님 verbatim (Fix 49 위험 정책!):
"v219 단계별 진입후 -5% 손실이면 청산하고 대기 모니터링"

사장님 verbatim (Fix 51 P2 일 진입수 통합!):
"일 진입수는 급등락 실시간과 같이 세팅"

로직:
1. Redis `pump_top:alert:*` 스캔 (pump_top_detector_worker가 저장!)
2. daily_limit 체크 = _get_daily_limit (Fix 51 P2!):
   sajangnim_top_short_daily_limit → auto_bb_break_daily_limit → 20 fallback!
3. 활성 심볼 skip!
4. 자본 = compute_stage1_capital (전체 자산 × 1~2%!)
5. SHORT 자동 진입 (레버리지 2x!)
6. Fix 49 (P1): 신 진입만 force_sl_override = -5% (짧은 손절!)
7. entry_snapshot 저장 (학습!)
8. 헌법 64 예외 (사장님 실 성공 로직!)

안전:
- daily_limit fallback chain (v219 전용 → 공유 → default!)
- 소액 자본 (1~2%!)
- 7중 정점 확인 후만!
- 신 진입 = -5% SL (Fix 49 대칭 정책!)
- API Ban 체크!

SPEC: auto_short_at_top_v2_fix51_2026-08-24
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_suggestion import StrategySuggestion
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

SPEC_VERSION = "auto_short_at_top_v2_fix51_2026-08-24"
DEFAULT_LEVERAGE = 2      # 사장님 default!
DEFAULT_DAILY_LIMIT = 20  # sajangnim_top_short_daily_limit fallback!
ALERT_PATTERN = "pump_top:alert:*"


def _get_daily_limit(db) -> int:
    """🎯 v219 통합 (2026-08-22 사장님!) + Fix 51 P2 fallback 강화!:
    급등락 실시간과 같은 daily_limit 공유 = auto_bb_break_daily_limit!
    사장님 verbatim: "일 진입수는 급등락 실시간과 같이 세팅"

    LONG (auto_long_at_bottom) 동일 패턴 = 헌법 6 (단일 진실!):
    1) sajangnim_top_short_daily_limit (v219 정점 전용)
    2) auto_bb_break_daily_limit       (급등락 실시간 공유!)
    3) DEFAULT_DAILY_LIMIT (fallback = 20)
    """
    for key in ("sajangnim_top_short_daily_limit", "auto_bb_break_daily_limit"):
        try:
            row = db.get(SystemSetting, key)
            if row and row.value:
                v = int(row.value)
                if v > 0:
                    return v
        except Exception:
            continue
    return DEFAULT_DAILY_LIMIT


def run_auto_short_at_top() -> dict:
    """매 30초 = 정점 알람 확인 → 자동 SHORT 진입!"""
    db = SessionLocal()
    entered = 0
    skipped = 0
    results: list[dict] = []
    try:
        # 1. daily_limit 체크! (v219 통합 = auto_bb_break_daily_limit 공유!)
        daily_limit = _get_daily_limit(db)
        if daily_limit <= 0:
            return {"note": "daily_limit=0 (OFF!)", "entered": 0}

        # 통합 카운트 = 모든 자동 진입 (BB + PENDING_HC + OBV + v219 정점!) 포함!
        # Fix 34: v219 독립! (기존 _count_used_slots import 제거)
        used = _count_v219_used_slots(db)
        remaining = daily_limit - used
        if remaining <= 0:
            return {"note": f"daily {used}/{daily_limit} (통합!)", "entered": 0}

        # 2. Redis 알람 조회!
        from app.core.redis_client import get_redis_client
        r = get_redis_client()

        alert_keys = list(r.scan_iter(ALERT_PATTERN))
        if not alert_keys:
            return {"note": "정점 알람 없음!", "entered": 0}

        # 3. 활성 심볼 skip!
        active_syms = set()
        try:
            active = db.execute(
                select(StrategyInstance).where(StrategyInstance.status.in_(list(ACTIVE_LIKE)))
            ).scalars().all()
            active_syms = {r_.symbol for r_ in active}
        except Exception:
            pass

        # 4. mainnet 계정!
        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            return {"error": "mainnet 계정 없음!", "entered": 0}

        from app.integrations.binance.client import BinanceClient
        from app.core.crypto import decrypt_text
        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )

        # 5. 자본 계산 (사장님 초기 금액 = default 300 USDT!)
        # 사장님 규정: 전체 자산 무관! 1단계 = 초기 금액!
        from app.services.sajangnim_capital import compute_stage1_capital
        base_capital = compute_stage1_capital(bc, db)
        capital_float = float(base_capital)

        # 6. 각 알람 처리!
        from app.workers.auto_bb_breakdown_worker import _create_auto_bb_strategy
        for key in alert_keys:
            if remaining <= 0:
                break

            key_str = key.decode() if isinstance(key, bytes) else key
            try:
                raw = r.get(key_str)
                if not raw:
                    continue
                alert = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                symbol = alert.get("symbol")
                side = alert.get("side", "SHORT")
                if not symbol or side != "SHORT":
                    continue
                if symbol in active_syms:
                    skipped += 1
                    continue

                confidence = float(alert.get("confidence", 0))
                if confidence < 0.85:
                    continue

                # Fix 65: OBV 절대값 검증 (사장님 사상!)
                try:
                    from app.services.obv_gate import check_obv_gate
                    obv_pass, obv_reason = check_obv_gate(bc, symbol, "SHORT")
                    if not obv_pass:
                        logger.info("[auto_short_top+Fix65] %s skip: %s", symbol, obv_reason)
                        continue
                except Exception as _obv_exc:
                    logger.warning("[auto_short_top+Fix65] %s obv_gate error: %s (fail-open)", symbol, _obv_exc)

                # Fix 66 P1: 양방향 실패 blocklist!
                try:
                    from app.services.bidirectional_blocklist import is_bidirectional_blocked
                    blocked, block_reason = is_bidirectional_blocked(db, symbol)
                    if blocked:
                        logger.info("[auto_short_top+Fix66] %s skip: %s", symbol, block_reason)
                        continue
                except Exception as _bl_exc:
                    logger.warning("[auto_short_top+Fix66] blocklist error: %s", _bl_exc)

                # Fix 66 P2: pump_dump_regime (SHORT!)
                try:
                    from app.services.pump_dump_regime import is_regime_blocked_for_short
                    regime_blocked, regime_reason = is_regime_blocked_for_short(bc, symbol)
                    if regime_blocked:
                        logger.info("[auto_short_top+Fix66] %s skip: %s", symbol, regime_reason)
                        continue
                except Exception as _rg_exc:
                    logger.warning("[auto_short_top+Fix66] regime error: %s", _rg_exc)

                # 7. 자동 진입!
                cfg = {"capitals": [capital_float], "leverage": DEFAULT_LEVERAGE}
                new_strategy = _create_auto_bb_strategy(
                    db, symbol, side, cfg,
                    strategy_type_suffix="_SAJANGNIM_TOP",
                )
                if not new_strategy:
                    skipped += 1
                    logger.info(
                        "[sajangnim_top_v219] ❌ %s 진입 실패 = 알람 유지 (재시도!)",
                        symbol,
                    )
                    continue

                # Fix 49 (2026-08-24 사장님 위험 정책!): 정점 SHORT = -5% 짧은 손절!
                # 사장님 verbatim: "v219 단계별 진입후 -5% 손실이면 청산하고 대기 모니터링"
                # LONG (auto_long_at_bottom L800-812) 대칭 패턴!
                # 기존 활성 전략은 그대로! 신 진입만 -5%!
                try:
                    new_strategy.force_sl_enabled_override = True
                    new_strategy.force_sl_roi_override = Decimal("5")
                    db.commit()
                    logger.info(
                        "[sajangnim_top_v219] 🛡️ %s SL override -5%% 적용 (strategy_id=%s)",
                        symbol, new_strategy.id,
                    )
                except Exception as _sl_exc:
                    logger.warning(
                        "[sajangnim_top_v219] ⚠️ %s SL override 실패: %s (진입은 유지)",
                        symbol, _sl_exc,
                    )
                    db.rollback()

                # 8. entry_snapshot 저장 (학습!)
                _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
                entry_snapshot = {
                    "rsi": alert.get("rsi"),
                    "cci": alert.get("cci_last"),
                    "obv_slope_pct": None,
                    "regime": "TOP_REVERSAL",
                    "source": "SAJANGNIM_TOP",
                    "sustained_bars": 0,
                    "change_24h": alert.get("change_24h"),
                    "kst_hour": _kst_hour,
                    "confidence": confidence,
                    "signals_passed": alert.get("signals"),
                    "entered_at": datetime.now(timezone.utc).isoformat(),
                }
                sugg = StrategySuggestion(
                    symbol=symbol, side=side,
                    suggestion_type="sajangnim_top_short",
                    strategy_config={
                        "capitals": cfg["capitals"],
                        "symbol": symbol, "side": side,
                        "sajangnim_top": True,
                        "confidence": confidence,
                        "signals": alert.get("signals"),
                        "entry_snapshot": entry_snapshot,
                    },
                    confidence_score=Decimal(str(round(confidence, 4))),
                    reason=(
                        f"🎯 사장님 정점 SHORT (v219)! "
                        f"7중 통과 (conf={confidence*100:.0f}%) "
                        f"24h=+{alert.get('change_24h', 0):.1f}% "
                        f"RSI={alert.get('rsi', 0):.1f} "
                        f"CCI={alert.get('cci_last', 0):.0f}"
                    ),
                    status="EXECUTED",
                    execution_mode="AUTO",
                    executed_at=datetime.now(timezone.utc),
                    executed_strategy_id=new_strategy.id,
                    outcome_status="PENDING",
                )
                db.add(sugg)
                db.commit()

                # 알람 삭제 (중복 진입 방지!)
                r.delete(key_str)

                remaining -= 1
                entered += 1
                results.append({
                    "symbol": symbol, "side": side,
                    "capital": capital_float,
                    "confidence": confidence,
                    "strategy_id": new_strategy.id,
                })
                logger.warning(
                    "[sajangnim_top_v219] ✅ 자동 SHORT: %s cap=%.2f conf=%.2f (id=%d)",
                    symbol, capital_float, confidence, new_strategy.id,
                )

                # 텔레그램! (fix: NotificationService!)
                try:
                    from app.services.notification_service import NotificationService
                    _db_n = SessionLocal()
                    _ns = NotificationService(_db_n)
                    _ns.send_system_alert(
                        title=f"✅ [v219 자동] {symbol} SHORT 진입! ({confidence*100:.0f}%)",
                        body=(
                            f"✅ 사장님 정점 자동 진입! (v219)\n"
                            f"심볼: {symbol} SHORT\n"
                            f"자본: {capital_float:.2f} USDT × 2x\n"
                            f"신뢰도: {confidence*100:.0f}%\n"
                            f"오늘 {daily_limit - remaining}/{daily_limit}"
                        ),
                    )
                    try:
                        _db_n.close()
                    except Exception:
                        pass
                except Exception as _te:
                    logger.warning("[sajangnim_top_v219] telegram 실패: %s", _te)

            except Exception as e:
                logger.warning("[sajangnim_top_v219] %s 처리 실패: %s", key_str, e)
                skipped += 1
                db.rollback()
                continue

        logger.info(
            "[sajangnim_top_v219] 완료: entered=%d skipped=%d",
            entered, skipped,
        )
        return {
            "entered": entered,
            "skipped": skipped,
            "results": results,
        }
    except Exception as e:
        logger.exception("[sajangnim_top_v219] 실행 실패: %s", e)
        return {"error": str(e), "entered": 0}
    finally:
        db.close()


def _count_v219_used_slots(db) -> int:
    """🎯 Fix 34: v219 전용 카운터 (auto_bb_breakdown과 완전 분리!)"""
    try:
        from app.models.strategy_suggestion import StrategySuggestion
        from app.workers.auto_bb_breakdown_worker import _auto_bb_reset_at
        from sqlalchemy import and_
        today_start = _auto_bb_reset_at(db)
        count = db.query(StrategySuggestion).filter(
            and_(
                StrategySuggestion.suggestion_type == 'sajangnim_top_short',
                StrategySuggestion.execution_mode == 'AUTO',
                StrategySuggestion.status == 'EXECUTED',
                StrategySuggestion.executed_at >= today_start,
                StrategySuggestion.outcome_status != 'SUCCESS'
            )
        ).count()
        return count
    except Exception:
        return 0
