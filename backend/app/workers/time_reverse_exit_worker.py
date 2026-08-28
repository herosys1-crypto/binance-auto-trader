"""Fix 31 v230 (2026-08-23): 4h + 반대 신뢰도 청산 + 모니터링 전환 워커!

사장님 verbatim:
"포지션 진입 후 4시간 또는 행보 또는 포지션 진입 반대로 움직일 신뢰도 높으면 
 청산하고 모니터링으로 전환하고 다시 포지션 진입이 가능하면 다시 포지션에 진입해둬"

로직:
1. 활성 SHORT/LONG 조회 (STAGE1_OPEN + current_stage=1!)
2. 4시간 경과 or 반대 신뢰도 4+ = 전량 청산!
3. retry_after_liquidation_enabled=True = 모니터링 전환!
4. 텔레그램 알림!
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance

logger = logging.getLogger(__name__)

SPEC_VERSION = "time_reverse_exit_v1_2026-08-23"
TIME_EXIT_HOURS = 4
REVERSE_CONFIDENCE_MIN = 4  # 5점 만점 중!
MAX_STRATEGIES_PER_CYCLE = 50


def _redis():
    try:
        from app.core.redis_client import get_redis_client
        return get_redis_client()
    except Exception:
        return None


def _emergency_close(db, strategy, reason):
    """전량 청산 + 모니터링 전환!"""
    try:
        from app.services.execution_service import ExecutionService
        svc = ExecutionService(db)
        # 여러 함수 시도!
        result = None
        for fn_name in ('emergency_close_position', 'close_position', 'force_close_all'):
            fn = getattr(svc, fn_name, None)
            if fn is None: continue
            try:
                result = fn(strategy_id=strategy.id)
                if result: break
            except TypeError:
                try:
                    result = fn(strategy.id)
                    if result: break
                except Exception: continue
            except Exception as e:
                logger.warning(f"[Fix31] {fn_name} #{strategy.id}: {e}")
                continue
        
        if result:
            # 모니터링 전환!
            strategy.retry_after_liquidation_enabled = True
            strategy.last_error_message = f"[Fix31] {reason} ({SPEC_VERSION})"
            db.commit()
            logger.warning(f"[Fix31] CLOSED #{strategy.id} {strategy.symbol} reason={reason}")
            _notify(f"[{reason}] {strategy.symbol} 청산 + 모니터링",
                    f"{strategy.symbol} {strategy.side} #{strategy.id}\n사유: {reason}\n모니터링 전환!")
            return True
        else:
            logger.error(f"[Fix31] close failed #{strategy.id}")
            return False
    except Exception as e:
        logger.error(f"[Fix31] _emergency_close #{strategy.id}: {e}", exc_info=True)
        return False


def _notify(title, body):
    try:
        from app.services.notification_service import NotificationService
        db2 = SessionLocal()
        try: NotificationService(db2).send_system_alert(title=title, body=body)
        finally: db2.close()
    except Exception as e:
        logger.warning(f"[Fix31] notify: {e}")


def _check_reverse_confidence(bc, symbol, side):
    """반대 방향 신뢰도 계산 (5점 만점!)"""
    try:
        from app.services.chart_analyzer import ChartAnalyzer
        analysis = ChartAnalyzer.analyze_timeframe(bc, symbol=symbol, interval="15m", limit=60)
        opposite = 'LONG' if side == 'SHORT' else 'SHORT'
        score = ChartAnalyzer.compute_reversal_score(analysis, opposite)
        return score or 0
    except Exception as e:
        logger.warning(f"[Fix31] reverse_score {symbol}: {e}")
        return 0


def run_time_reverse_exit_once():
    """scheduler_runner 진입점 (매 5분!)"""
    result = {"scanned": 0, "time_exit": 0, "reverse_exit": 0, 
              "errors": 0, "spec": SPEC_VERSION}
    
    db = SessionLocal()
    try:
        acc = db.query(ExchangeAccount).filter(ExchangeAccount.is_testnet == False).first()
        if acc is None:
            logger.warning("[Fix31] mainnet 계정 없음 = skip")   # Fix 197: 헌법 80
            return result
        try:
            from app.core.api_backoff import is_account_banned
            if is_account_banned(acc.id):
                logger.warning("[Fix31] API ban 중 = skip")      # Fix 197: 헌법 80
                return result
        except Exception: pass
        try:
            from app.core.crypto import decrypt_text
            from app.integrations.binance.client import BinanceClient
            bc = BinanceClient(
                api_key=decrypt_text(acc.api_key_enc),
                api_secret=decrypt_text(acc.api_secret_enc),
            )
        except Exception as e:
            logger.error(f"[Fix31] BC: {e}")
            return result
        
        candidates = (db.query(StrategyInstance)
                      .filter(StrategyInstance.status.in_(list(ACTIVE_LIKE)),
                              StrategyInstance.is_archived == False,
                              StrategyInstance.current_stage == 1,
                              StrategyInstance.started_at.isnot(None))
                      .limit(MAX_STRATEGIES_PER_CYCLE).all())
        result["scanned"] = len(candidates)
        # 🚨 Fix 197: 옛 코드는 여기서 무로그 return 이라 **실행 흔적조차 없었다.**
        #   started_at 이 전 행 NULL 이라 위 필터가 항상 0건을 만들어,
        #   이 워커는 등록만 되고 2026-08-23 이후 한 번도 동작한 적이 없다.
        #   빈 리스트 for 는 no-op 이므로 그대로 아래 DONE 로그까지 흘려보낸다 (헌법 80).
        
        now = datetime.now(timezone.utc)
        threshold = timedelta(hours=TIME_EXIT_HOURS)
        
        for s in candidates:
            try:
                # 트레일링 활성 시 skip!
                if s.peak_pnl_pct_after_first_tp and float(s.peak_pnl_pct_after_first_tp) > 0:
                    continue
                
                # 1. 시간 경과 체크!
                elapsed = now - s.started_at
                if elapsed >= threshold:
                    if _emergency_close(db, s, "TIME_EXIT_4H"):
                        result["time_exit"] += 1
                    continue
                
                # 2. 반대 신뢰도 체크!
                score = _check_reverse_confidence(bc, s.symbol, s.side)
                if score >= REVERSE_CONFIDENCE_MIN:
                    if _emergency_close(db, s, f"REVERSE_CONFIDENCE_{score}"):
                        result["reverse_exit"] += 1
                
            except Exception as e:
                result["errors"] += 1
                logger.error(f"[Fix31] #{s.id}: {e}", exc_info=True)
        
        logger.warning(f"[Fix31] DONE: {result}")
        return result
    finally:
        db.close()
