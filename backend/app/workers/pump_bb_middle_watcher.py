"""신 급등 + BB중단 알람 워처! (v131 사장님 요청 2026-08-09!)

사장님 요구:
"바이낸스 선물에서 당일 급등한 종목 1위에서 50위 까지 급등한 종목의
 4시간 차트 최고점에서 볼밴 중단까지 위아래 5% 까지 빠지는 종목을 알람으로 알려줘"

로직:
  1. 24h 상승률 top 50 심볼 조회 (Binance 선물 USDT!)
  2. 각 심볼 = 4H 봉 조회 (최근 50봉!)
  3. 최근 30봉 최고점 계산
  4. 볼밴 중단 (20MA!) 계산
  5. |최고점 - BB중단| / BB중단 × 100 ≤ 5%?
  6. YES → Redis 알람 + Telegram!

의미 (사장님 사고!):
  - 급등 종목 = 상승 추세!
  - 최고점 = 조정 시작!
  - BB 중단 (20MA!) = 지지선!
  - 근접 = 매수 기회 감지! (재상승 가능!)

⚠️ 2026-08-14 v147b — 실측이 이 전제와 **어긋납니다**:
    · 4H BB 중단/하단 (215,561 캔들): 밴드 도달 후 **68.3% 가 뚫고 마감**
      (docs/BB_4H_BAND_STRATEGY_SPEC.md)
    · 15m BB 중단 (478,435 캔들): 도달 후 **이탈 47.2% vs 반등 18.3%**
      (docs/BB_TOP_15M_STRATEGY_SPEC.md)
    → **BB 중단은 지지선이 아닙니다.** 「닿으면 반등」 전제로 매수하면 위험합니다.
    이 알람은 **관찰 신호로만** 쓰시고, 진입은 반등이 확인된 뒤에 판단하십시오.
    (기능 자체는 사장님 요청이므로 유지하되, 알람에 경고를 함께 실어 보냅니다.)

헌법 v131 (신!):
  '급등 후 지지선 도달 = 사장님 진입 기회 자동 알림!'
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

REDIS_KEY_ALERTS = "pump_bb_alerts:v1"  # sorted set
ALERT_TTL_SEC = 6 * 3600  # 6h (짧게 = 신선한 신호만!)


def get_top_pump_symbols(binance_client, top_n: int = 50) -> list[str]:
    """Binance 선물 24h 상승률 top N USDT 심볼!"""
    try:
        ticker_all = binance_client.get_24hr_ticker()
        if not isinstance(ticker_all, list):
            return []
        # USDT 선물만!
        filtered = [
            t for t in ticker_all
            if str(t.get("symbol", "")).endswith("USDT")
        ]
        # 24h 상승률 정렬!
        try:
            sorted_by_pump = sorted(
                filtered,
                key=lambda x: float(x.get("priceChangePercent", 0) or 0),
                reverse=True,
            )
        except Exception as e:
            logger.warning("[pump_bb] 정렬 실패: %s", e)
            return []
        return [str(t.get("symbol", "")) for t in sorted_by_pump[:top_n]]
    except Exception as e:
        logger.warning("[pump_bb] top pump 조회 실패: %s", e)
        return []


def check_pump_bb_middle_signal(
    binance_client,
    symbol: str,
    lookback_bars: int = 30,
    threshold_pct: Decimal = Decimal("5"),
) -> tuple[bool, dict]:
    """4H 봉 = 최고점 vs BB 중단 (20MA!) ±X%!

    Args:
        binance_client: Binance API client
        symbol: 심볼 (예 BTCUSDT)
        lookback_bars: 최고점 계산 기간 (default 30봉 = 5일)
        threshold_pct: 근접 임계 % (default 5%)

    Returns:
        (신호?, detail dict)
    """
    try:
        kl_4h = binance_client.get_klines(symbol=symbol, interval="4h", limit=50)
        if not kl_4h or len(kl_4h) < 20:
            return (False, {"error": "insufficient 4h klines"})

        # kline 구조: [openTime, open, high, low, close, volume, ...]
        closes = [Decimal(str(k[4])) for k in kl_4h]
        highs = [Decimal(str(k[2])) for k in kl_4h]

        # 최근 lookback_bars봉 최고점
        recent_highs = highs[-lookback_bars:] if len(highs) >= lookback_bars else highs
        peak = max(recent_highs)

        # 볼밴 중단 = 20MA (최근 20 종가 평균)
        if len(closes) < 20:
            return (False, {"error": "insufficient closes for 20MA"})
        bb_middle = sum(closes[-20:]) / Decimal("20")
        if bb_middle <= 0:
            return (False, {"error": "bb_middle <= 0"})

        # 차이율 (%!)
        diff_pct = abs(peak - bb_middle) / bb_middle * Decimal("100")
        signal = diff_pct <= threshold_pct

        current_price = closes[-1]
        # 사장님 참고: 현재가가 = peak 대비 얼마나 하락?
        drop_from_peak = ((peak - current_price) / peak * Decimal("100")) if peak > 0 else Decimal("0")

        detail = {
            "signal": signal,
            "peak": str(round(peak, 8)),
            "bb_middle": str(round(bb_middle, 8)),
            "current_price": str(round(current_price, 8)),
            "diff_pct": str(round(diff_pct, 2)),
            "drop_from_peak_pct": str(round(drop_from_peak, 2)),
            "threshold_pct": str(threshold_pct),
        }
        return (signal, detail)
    except Exception as e:
        logger.warning("[pump_bb] %s 검사 실패: %s", symbol, e)
        return (False, {"error": str(e)})


def run_pump_bb_watcher(db: Session, decrypt_text) -> dict:
    """실행! Top 50 급등 심볼 = 4H 최고점 vs BB중단 감시!"""
    from app.models.exchange_account import ExchangeAccount
    from app.integrations.binance.client import BinanceClient
    from app.core.redis_client import get_redis_client

    result: dict = {"checked": 0, "alerts": 0, "errors": []}

    # 임의 계정 사용 (public API만 필요하지만 client는 API key 필요)
    accounts = db.execute(
        select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
    ).scalars().all()
    if not accounts:
        return {"error": "no mainnet accounts"}
    account = accounts[0]

    try:
        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=account.is_testnet,
        )
    except Exception as e:
        return {"error": f"binance client init: {e}"}

    # Top 50 급등 심볼!
    symbols = get_top_pump_symbols(bc, top_n=50)
    if not symbols:
        return {"error": "no top pump symbols"}
    logger.info("[pump_bb] Top pump symbols: %s...(총 %d)", symbols[:5], len(symbols))

    _redis = None
    try:
        _redis = get_redis_client()
    except Exception:
        pass

    for symbol in symbols:
        try:
            signal, detail = check_pump_bb_middle_signal(bc, symbol)
            result["checked"] += 1
            if signal:
                # 알람 저장 = Redis!
                _alert = {
                    "symbol": symbol,
                    "detail": detail,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    # v147b: 실측 경고를 알람에 동봉 (UI 가 그대로 표시)
                    "caution": (
                        "⚠️ 실측: BB 중단은 지지선이 아닙니다 — 4H 밴드 도달 후 "
                        "68.3%가 뚫고 마감(추가 하락 중앙 5.69%). 반등 확인 후 판단!"
                    ),
                }
                if _redis:
                    import hashlib
                    _alert_key = "pump_bb_alert:" + hashlib.md5(symbol.encode()).hexdigest()[:16]
                    _redis.setex(_alert_key, ALERT_TTL_SEC, json.dumps(_alert))
                    _redis.zadd(
                        REDIS_KEY_ALERTS,
                        {_alert_key: datetime.now(timezone.utc).timestamp()}
                    )
                    # 옛 알람 정리 (6h+!)
                    _redis.zremrangebyscore(
                        REDIS_KEY_ALERTS,
                        0, (datetime.now(timezone.utc) - timedelta(hours=6)).timestamp()
                    )
                result["alerts"] += 1
                logger.info(
                    "[pump_bb] 🚨 알람! %s peak=%s bb_mid=%s diff=%s%%",
                    symbol, detail.get("peak"), detail.get("bb_middle"), detail.get("diff_pct"),
                )
                # Telegram (dedup 3h)
                try:
                    from app.services.notification_service import NotificationService
                    _dedup_key = f"pump_bb:sent:{symbol}"
                    if _redis and not _redis.get(_dedup_key):
                        NotificationService(db).send_system_alert(
                            title=f"🚨 [급등+BB중단!] {symbol}",
                            body=(
                                f"⚡ 「{symbol}」 = 4H 최고점 = BB중단 근접!\n"
                                f"  최고점: {detail.get('peak')}\n"
                                f"  BB중단(20MA): {detail.get('bb_middle')}\n"
                                f"  차이: {detail.get('diff_pct')}% (≤ 5%!)\n"
                                f"  현재가: {detail.get('current_price')}\n"
                                f"  피크 대비 하락: {detail.get('drop_from_peak_pct')}%\n\n"
                                f"= 급등 후 조정 = 지지선 근접!\n"
                                f"= 매수 기회 감지!"
                            ),
                        )
                        _redis.setex(_dedup_key, 3 * 3600, "1")
                except Exception as _te:
                    logger.warning("[pump_bb] Telegram 실패: %s", _te)
        except Exception as e:
            result["errors"].append(f"{symbol}: {e}")

    logger.info("[pump_bb] 완료: checked=%s alerts=%s", result["checked"], result["alerts"])
    return result


if __name__ == "__main__":
    from app.core.database import SessionLocal
    from app.core.crypto import decrypt_text
    with SessionLocal() as _db:
        print(run_pump_bb_watcher(_db, decrypt_text))
