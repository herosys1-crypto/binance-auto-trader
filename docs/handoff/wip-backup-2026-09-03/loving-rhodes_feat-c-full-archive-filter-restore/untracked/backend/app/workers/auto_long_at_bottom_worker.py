"""🎯 v219 신 대칭 (2026-08-24 사장님!): 저점 감지 자동 LONG 진입 워커!

사장님 사상 (auto_short_at_top 완전 대칭!):
"급락 후 저점 = 볼밴 최하단 밖 + obv 최저점 + macd rsi cci 모든 지표 최저점 =
 저점 매수 (LONG) 진입! 전체 자산에 1-2% 소액!"

로직 (SHORT 정점 워커의 완전 대칭!):
1. Redis `sajangnim:bottom_long:*` 스캔 (저점 감지 워커가 저장!)
2. daily_limit 체크 (SystemSetting `sajangnim_top_short_daily_limit` = SHORT와 공유!)
3. 활성 심볼 skip!
4. 자본 = compute_stage1_capital (전체 자산 × 1~2% = default 300 USDT!)
5. LONG 자동 진입 (레버리지 2x!)
6. Fix 49 신 사상: 진입 직후 -5% 짧은 손절 override!
7. entry_snapshot 저장 (학습!)
8. 헌법 64 예외 (사장님 실 성공 로직 대칭!)

안전:
- daily_limit SHORT + LONG 통합 (하루 총 진입 수 제한!)
- 소액 자본 (1~2%!)
- 7중 저점 확인 후만 (confidence >= 0.85)!
- API Ban 체크 (create 내부에서 처리)!
- 알람 삭제는 진입 성공 후에만 (실패 시 재시도 가능!)

헌법 6 (단일 진실):
- _count_used_slots = auto_bb_breakdown_worker에서 lazy import
  (해당 함수는 'bb4h_auto_entry' + 'sajangnim_top_short' + 'sajangnim_bottom_long'
   suggestion_type 모두 카운트 & _auto_bb_reset_at 기준 리셋 로직 그대로 사용!)
- _create_auto_bb_strategy = auto_bb_breakdown_worker에서 lazy import
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

DEFAULT_LEVERAGE = 2      # 사장님 default (SHORT와 동일!)
ALERT_PATTERN = "sajangnim:bottom_long:*"


def _get_daily_limit(db) -> int:
    """🎯 v219 통합 (2026-08-24 사장님!):
    SHORT와 같은 daily_limit 공유 = sajangnim_top_short_daily_limit!
    사장님 요구: "SHORT + LONG 통합 카운터 = 하루 총 진입 수 제한"
    헌법 6 (단일 진실): SHORT/LONG이 같은 SystemSetting key를 읽음.
    """
    try:
        row = db.get(SystemSetting, "sajangnim_top_short_daily_limit")
        if row and row.value:
            return max(0, int(row.value))
    except Exception:
        pass
    return 0


def run_auto_long_at_bottom() -> dict:
    """매 30초 = 저점 알람 확인 → 자동 LONG 진입! (SHORT 정점의 완전 대칭!)"""
    db = SessionLocal()
    entered = 0
    skipped = 0
    results: list[dict] = []
    try:
        # 1. daily_limit 체크! (SHORT + LONG 통합 = sajangnim_top_short_daily_limit 공유!)
        daily_limit = _get_daily_limit(db)
        if daily_limit <= 0:
            return {"note": "daily_limit=0 (OFF!)", "entered": 0}

        # 통합 카운트 = 모든 자동 진입 (BB + SHORT 정점 + LONG 저점!) 포함!
        # 헌법 6: auto_bb_breakdown_worker._count_used_slots를 재사용 (단일 진실!)
        from app.workers.auto_bb_breakdown_worker import _count_used_slots
        used = _count_used_slots(db)
        remaining = daily_limit - used
        if remaining <= 0:
            return {"note": f"daily {used}/{daily_limit} (통합!)", "entered": 0}

        # 2. Redis 알람 조회!
        from app.core.redis_client import get_redis_client
        r = get_redis_client()

        alert_keys = list(r.scan_iter(ALERT_PATTERN))
        if not alert_keys:
            return {"note": "저점 알람 없음!", "entered": 0}

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
        # 사장님 규정: 전체 자산 무관! 1단계 = 초기 금액! (SHORT와 동일!)
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
                side = alert.get("side", "LONG")
                if not symbol or side != "LONG":
                    continue
                if symbol in active_syms:
                    skipped += 1
                    continue

                confidence = float(alert.get("confidence", 0))
                if confidence < 0.85:
                    continue

                # 7. 자동 진입!
                cfg = {"capitals": [capital_float], "leverage": DEFAULT_LEVERAGE}
                new_strategy = _create_auto_bb_strategy(
                    db, symbol, side, cfg,
                    strategy_type_suffix="_SAJANGNIM_BOTTOM",
                )
                if not new_strategy:
                    skipped += 1
                    logger.info(
                        "[auto_long_at_bottom] ❌ %s 진입 실패 = 알람 유지 (재시도!)",
                        symbol,
                    )
                    continue

                # Fix 49 신 사상 (SHORT 대칭): 저점 LONG = -5% 짧은 손절!
                # 사장님 verbatim: "v219 단계별 진입후 -5% 손실이면 청산하고 대기 모니터링"
                # 기존 활성 전략은 그대로! 신 진입만 -5%!
                try:
                    new_strategy.force_sl_enabled_override = True
                    new_strategy.force_sl_roi_override = Decimal("5")
                    db.commit()
                    logger.info(
                        "[auto_long_at_bottom] 🛡️ %s SL override -5%% 적용 (strategy_id=%s)",
                        symbol, new_strategy.id,
                    )
                except Exception as _sl_exc:
                    logger.warning(
                        "[auto_long_at_bottom] ⚠️ %s SL override 실패: %s (진입은 유지)",
                        symbol, _sl_exc,
                    )
                    db.rollback()

                # 8. entry_snapshot 저장 (학습!)
                _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
                entry_snapshot = {
                    "rsi": alert.get("rsi"),
                    "cci": alert.get("cci_last"),
                    "obv_slope_pct": None,
                    "regime": "BOTTOM_REVERSAL",
                    "source": "SAJANGNIM_BOTTOM",
                    "sustained_bars": 0,
                    "change_24h": alert.get("change_24h"),
                    "kst_hour": _kst_hour,
                    "confidence": confidence,
                    "signals_passed": alert.get("signals"),
                    "entered_at": datetime.now(timezone.utc).isoformat(),
                }
                sugg = StrategySuggestion(
                    symbol=symbol, side=side,
                    suggestion_type="sajangnim_bottom_long",
                    strategy_config={
                        "capitals": cfg["capitals"],
                        "symbol": symbol, "side": side,
                        "sajangnim_bottom": True,
                        "confidence": confidence,
                        "signals": alert.get("signals"),
                        "entry_snapshot": entry_snapshot,
                    },
                    confidence_score=Decimal(str(round(confidence, 4))),
                    reason=(
                        f"📉 사장님 저점 LONG (v219 대칭)! "
                        f"7중 통과 (conf={confidence*100:.0f}%) "
                        f"24h={alert.get('change_24h', 0):.1f}% "
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

                # 알람 삭제 (중복 진입 방지!) — 진입 성공 후에만!
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
                    "[auto_long_at_bottom] ✅ 자동 LONG: %s cap=%.2f conf=%.2f (id=%d)",
                    symbol, capital_float, confidence, new_strategy.id,
                )

                # 텔레그램! (별도 세션 = finally close 패턴!)
                try:
                    from app.services.notification_service import NotificationService
                    _db_n = SessionLocal()
                    try:
                        _ns = NotificationService(_db_n)
                        _ns.send_system_alert(
                            title=f"📉 [v219 대칭] {symbol} LONG 진입! ({confidence*100:.0f}%)",
                            body=(
                                f"📉 7중 저점 LONG 자동 진입: {symbol}\n"
                                f"심볼: {symbol} LONG\n"
                                f"자본: {capital_float:.2f} USDT × 2x\n"
                                f"신뢰도: {confidence*100:.0f}%\n"
                                f"오늘 {daily_limit - remaining}/{daily_limit} (SHORT+LONG 통합!)"
                            ),
                        )
                    finally:
                        try:
                            _db_n.close()
                        except Exception:
                            pass
                except Exception as _te:
                    logger.warning("[auto_long_at_bottom] telegram 실패: %s", _te)

            except Exception as e:
                logger.warning("[auto_long_at_bottom] %s 처리 실패: %s", key_str, e)
                skipped += 1
                db.rollback()
                continue

        logger.info(
            "[auto_long_at_bottom] 완료: entered=%d skipped=%d",
            entered, skipped,
        )
        return {
            "entered": entered,
            "skipped": skipped,
            "results": results,
        }
    except Exception as e:
        logger.exception("[auto_long_at_bottom] 실행 실패: %s", e)
        return {"error": str(e), "entered": 0}
    finally:
        db.close()
