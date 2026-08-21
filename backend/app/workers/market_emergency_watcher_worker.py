"""🚨 v216 사장님 (2026-08-21): 시장 이상 감지 = 자동 진입 전체 중단!

사장님 실 자금 = 시장 급락에서 절대 보호!

= BTC/ETH 급락 감지 시 = 신규 자동 진입 = 즉시 중단!
= 회복 시 = 자동 재개!

로직 (매 5분!):
1. BTC/ETH 30분 변동 조회!
2. 급락 판단:
   - BTC 30분 -3% 이하 = WARN (진입 중단!)
   - BTC 30분 -5% 이하 = CRITICAL (모든 신 진입 즉시 중단!)
   - ETH 30분 -5% 이하 = 유사 처리!
3. Redis emergency flag ON (TTL 1시간!)
4. 텔레그램 알림!
5. 회복 시 (30분 변동 -2% 이내) = flag 해제!

효과:
- 시장 크래시 = 자동 방어!
- BTC 급락 → altcoin도 급락 = 진입 회피!
- 회복 시 = 자동 재개 (수동 개입 X!)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.crypto import decrypt_text
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount

logger = logging.getLogger(__name__)

# 임계값!
CRITICAL_DROP_PCT = -5.0   # 30분 -5% = CRITICAL!
WARN_DROP_PCT = -3.0        # 30분 -3% = WARN!
RECOVERY_THRESHOLD_PCT = -2.0  # 30분 -2% 이내 = 회복!

REDIS_KEY = "v216:market_emergency"
REDIS_TTL_SEC = 3600  # 1시간!

MONITORED_SYMBOLS = ["BTCUSDT", "ETHUSDT"]

_LAST_ALERT_AT: datetime | None = None


def run_market_emergency_watcher() -> dict:
    """매 5분 = BTC/ETH 급락 감지!"""
    db: Session = SessionLocal()
    try:
        # Binance client!
        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            return {"error": "no mainnet account"}

        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )

        # 각 심볼 30분 변동 조회 (1m×30개!)
        results = []
        max_drop = 0.0
        worst_symbol = None

        for symbol in MONITORED_SYMBOLS:
            try:
                klines = bc.get_klines(symbol=symbol, interval="1m", limit=30)
                if not klines or len(klines) < 30:
                    continue
                open_30m = float(klines[0][1])
                close_now = float(klines[-1][4])
                change_pct = ((close_now - open_30m) / open_30m) * 100
                results.append({
                    "symbol": symbol,
                    "change_30m_pct": round(change_pct, 2),
                })
                if change_pct < max_drop:
                    max_drop = change_pct
                    worst_symbol = symbol
            except Exception as e:
                logger.warning("[v216] %s 조회 실패: %s", symbol, e)
                continue

        if not results:
            return {"error": "no data"}

        # 판단!
        level = None
        if max_drop <= CRITICAL_DROP_PCT:
            level = "CRITICAL"
        elif max_drop <= WARN_DROP_PCT:
            level = "WARN"

        # Emergency flag!
        active = level is not None
        _set_emergency_flag(active, level, max_drop, worst_symbol)

        # 알림!
        if level:
            _alert_if_needed(db, level, max_drop, worst_symbol, results)
        elif max_drop >= RECOVERY_THRESHOLD_PCT:
            # 회복 = flag 해제 (이미 없으면 무영향!)
            _set_emergency_flag(False, None, max_drop, worst_symbol)

        result = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "max_drop_pct": round(max_drop, 2),
            "worst_symbol": worst_symbol,
            "level": level,
            "emergency_active": active,
            "symbols": results,
        }
        logger.info(
            "[v216 market_emergency] max_drop=%.2f%% (%s) level=%s",
            max_drop, worst_symbol, level,
        )
        return result
    except Exception as e:
        logger.warning("[v216 market_emergency] 실패: %s", e)
        return {"error": str(e)}
    finally:
        db.close()


def _set_emergency_flag(active: bool, level: str | None, drop: float, symbol: str | None) -> None:
    """Redis emergency flag!"""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        if active:
            r.setex(REDIS_KEY, REDIS_TTL_SEC, f"{level}:{symbol}={drop:.2f}%")
        else:
            r.delete(REDIS_KEY)
    except Exception as e:
        logger.warning("[v216] Redis flag 실패: %s", e)


def is_market_emergency() -> tuple[bool, str | None]:
    """auto_bb_breakdown_worker에서 호출! = emergency 상태 체크!"""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        val = r.get(REDIS_KEY)
        if val:
            if isinstance(val, bytes):
                val = val.decode()
            return True, val
        return False, None
    except Exception:
        return False, None


def _alert_if_needed(db: Session, level: str, max_drop: float, symbol: str, results: list) -> None:
    """알림 (30분 dedup!)"""
    global _LAST_ALERT_AT
    now = datetime.now(timezone.utc)
    if _LAST_ALERT_AT and (now - _LAST_ALERT_AT).total_seconds() < 1800:
        return

    emoji = "🚨🚨" if level == "CRITICAL" else "🚨"
    title = f"{emoji} [v216] 시장 이상 감지 = {level}!"

    lines = [f"{it['symbol']}: {it['change_30m_pct']:+.2f}%" for it in results]

    body = (
        f"{emoji} 시장 급락 감지!\n"
        f"\n"
        f"🔻 최대 하락 = {symbol}: {max_drop:.2f}% (30분)\n"
        f"\n"
        f"📊 모니터 심볼:\n"
        + "\n".join(f"  {l}" for l in lines)
        + f"\n\n🛡️ 신규 자동 진입 = 중단!\n"
        f"⏰ 회복 시 = 자동 재개!\n"
        f"\n"
        f"⚠️ 수동 진입은 정상 가능!"
    )
    try:
        from app.services.notification_service import NotificationService
        NotificationService(db).send_system_alert(title=title, body=body)
        _LAST_ALERT_AT = now
    except Exception as e:
        logger.warning("[v216] 알림 실패: %s", e)
