"""Fix 47 (2026-08-24 사장님!): LONG 자동 진입 (v219 방식!)"""
from __future__ import annotations
import json, logging
from datetime import datetime, timezone
from decimal import Decimal
from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance

logger = logging.getLogger(__name__)
SPEC_VERSION = "auto_long_at_bottom_v1_2026-08-24"


def _redis():
    try:
        from app.core.redis_client import get_redis_client
        return get_redis_client()
    except Exception: return None


def _get_daily_limit(db):
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, "sajangnim_top_short_daily_limit")
        if row and row.value: return max(0, int(row.value))
    except Exception: pass
    return 20


def _count_used():
    """v219와 daily_limit 공유!"""
    try:
        from app.workers.auto_short_at_top_worker import _count_v219_used_slots
        db = SessionLocal()
        try: return _count_v219_used_slots(db)
        finally: db.close()
    except Exception: return 0


def run_auto_long_at_bottom_once():
    """scheduler_runner 진입점 (매 30초!)"""
    result = {"note": "", "scanned": 0, "entered": 0, "spec": SPEC_VERSION}
    r = _redis()
    if r is None:
        result["note"] = "no redis"
        return result
    
    db = SessionLocal()
    try:
        # daily_limit 체크!
        daily_limit = _get_daily_limit(db)
        if daily_limit <= 0:
            result["note"] = "daily_limit=0"
            return result
        
        used = _count_used()
        remaining = daily_limit - used
        if remaining <= 0:
            result["note"] = f"daily {used}/{daily_limit}"
            return result
        
        # Redis에서 LONG 알람 조회!
        alerts = []
        try:
            for k in r.scan_iter(match="long_bottom:alert:*:LONG", count=100):
                key = k.decode() if isinstance(k, bytes) else k
                v = r.get(k)
                if v:
                    raw = v.decode() if isinstance(v, bytes) else v
                    alerts.append(json.loads(raw))
        except Exception as e:
            logger.warning(f"[auto_long] redis: {e}")
        
        result["scanned"] = len(alerts)
        if not alerts:
            result["note"] = "no LONG alerts"
            return result
        
        # 활성 심볼 skip!
        active_syms = set()
        try:
            active = db.query(StrategyInstance).filter(
                StrategyInstance.status.in_(list(ACTIVE_LIKE))
            ).all()
            active_syms = {s.symbol for s in active}
        except Exception: pass
        
        # 각 알람 진입 시도!
        for a in alerts[:remaining]:
            symbol = a.get("symbol")
            if not symbol or symbol in active_syms: continue
            try:
                # v219 방식 = auto_bb_breakdown _create_auto_bb_strategy 재사용!
                from app.workers.auto_bb_breakdown_worker import _create_auto_bb_strategy
                new_strategy = _create_auto_bb_strategy(
                    db, symbol, "LONG",
                    {"symbol": symbol, "side": "LONG",
                     "entry_snapshot": {"confidence": a.get("confidence"),
                                       "change_24h": a.get("change_24h"),
                                       "close": a.get("close"),
                                       "spec_version": SPEC_VERSION},
                     "source": "sajangnim_long_bottom"},
                    strategy_type_suffix="_SAJANGNIM_LONG"
                )
                if new_strategy:
                    result["entered"] += 1
                    # Fix 49: 신 사상 = -5% 짧은 손절!
                    try:
                        new_strategy.force_sl_enabled_override = True
                        new_strategy.force_sl_roi_override = Decimal("5")
                        db.commit()
                        logger.warning(f"[Fix49] {symbol} SL -5% 세팅! (신 LONG!)")
                    except Exception as _e:
                        logger.warning(f"[Fix49] SL 세팅 실패: {_e}")
                        db.rollback()
                    active_syms.add(symbol)
                    
                    # StrategySuggestion 저장!
                    try:
                        from app.models.strategy_suggestion import StrategySuggestion
                        sugg = StrategySuggestion(
                            symbol=symbol, side="LONG",
                            suggestion_type="sajangnim_long_bottom",
                            strategy_config={"symbol": symbol, "side": "LONG",
                                           "entry_snapshot": a},
                            confidence_score=Decimal(str(a.get("confidence", 0.85))),
                            reason=f"LONG 저점/급등 초기! conf={a.get('confidence')} chg24={a.get('change_24h')}",
                            status="EXECUTED", execution_mode="AUTO",
                            executed_at=datetime.now(timezone.utc),
                            executed_strategy_id=new_strategy.id,
                            outcome_status="PENDING"
                        )
                        db.add(sugg)
                        db.commit()
                    except Exception as e:
                        logger.warning(f"[auto_long] suggestion: {e}")
                    
                    # 텔레그램 알림!
                    try:
                        from app.services.notification_service import NotificationService
                        db2 = SessionLocal()
                        try:
                            NotificationService(db2).send_system_alert(
                                title=f"[Fix 47 LONG] {symbol} 자동 진입!",
                                body=f"{symbol} LONG #{new_strategy.id}\nconf={a.get('confidence')}\n"
                                     f"24h={a.get('change_24h')}%\nspec={SPEC_VERSION}"
                            )
                        finally: db2.close()
                    except Exception: pass
                    
                    logger.warning(f"[auto_long] ✅ ENTERED #{new_strategy.id} {symbol} LONG")
                    
                    # Redis 알람 삭제 (중복 방지!)
                    try:
                        r.delete(f"long_bottom:alert:{symbol}:LONG")
                    except Exception: pass
            except Exception as e:
                logger.error(f"[auto_long] {symbol}: {e}", exc_info=True)
        
        logger.warning(f"[auto_long] DONE: {result}")
        return result
    finally:
        db.close()
