"""🚀 Live Pump/Dump API (v133d 신!) - 급등락 중 실시간 진입!

사장님 요구 (2026-08-13):
"급등 급락 중 진입 별도 메뉴!"

= 별도 카드 = 5분마다 자동 감지!
= 즉시 진입 가능!
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.crypto import decrypt_text
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/live-pump-dump", tags=["live-pump-dump"])


@router.get("/scan")
def scan_live_pump_dump(
    threshold_5m: float = 1.5,
    threshold_1h: float = 3.0,
    max_symbols: int = 40,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    """🚀 실시간 급등락 심볼 스캔!

    - 5분봉 변동 >= threshold_5m% (기본 1.5%!)
    - 1시간봉 변동 >= threshold_1h% (기본 3.0%!)
    - LONG (급등 중!) + SHORT (급락 중!)
    """
    account = db.execute(
        select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
    ).scalar_one_or_none()
    if not account:
        return {"alerts": [], "error": "no mainnet account"}

    bc = BinanceClient(
        api_key=decrypt_text(account.api_key_enc),
        api_secret=decrypt_text(account.api_secret_enc),
        is_testnet=False,
    )

    try:
        tickers = bc.get_24hr_ticker()
        if not isinstance(tickers, list):
            return {"alerts": [], "error": "invalid ticker response"}
    except Exception as e:
        return {"alerts": [], "error": str(e)}

    # USDT 심볼만 + volume 큰 순!
    usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
    try:
        usdt.sort(key=lambda x: float(x.get("quoteVolume", 0) or 0), reverse=True)
    except Exception:
        pass

    # 상위 max_symbols 심볼만 = rate limit!
    candidates = usdt[:max_symbols]

    alerts = []
    for t in candidates:
        symbol = str(t.get("symbol"))
        if not symbol.endswith("USDT"):
            continue

        # 5분봉!
        change_5m = None
        try:
            k5 = bc.get_klines(symbol=symbol, interval="5m", limit=3)
            if isinstance(k5, list) and len(k5) >= 2:
                last = k5[-2]
                o = float(last[1])
                c = float(last[4])
                if o > 0:
                    change_5m = round(((c - o) / o) * 100, 2)
        except Exception:
            continue

        # 1시간봉!
        change_1h = None
        try:
            k1h = bc.get_klines(symbol=symbol, interval="1h", limit=3)
            if isinstance(k1h, list) and len(k1h) >= 2:
                last = k1h[-2]
                o = float(last[1])
                c = float(last[4])
                if o > 0:
                    change_1h = round(((c - o) / o) * 100, 2)
        except Exception:
            pass

        # 감지 조건!
        detected = False
        alert_type = None
        side = None
        reason_parts = []
        change_display = 0.0

        # 5분 급등 (LONG!)
        if change_5m is not None and change_5m >= threshold_5m:
            detected = True
            alert_type = "pump_live"
            side = "LONG"
            reason_parts.append(f"🚀 5분 +{change_5m}%")
            change_display = change_5m
        # 5분 급락 (SHORT!)
        elif change_5m is not None and change_5m <= -threshold_5m:
            detected = True
            alert_type = "dump_live"
            side = "SHORT"
            reason_parts.append(f"📉 5분 {change_5m}%")
            change_display = change_5m
        # 1시간 급등 (LONG!)
        elif change_1h is not None and change_1h >= threshold_1h:
            detected = True
            alert_type = "pump_1h"
            side = "LONG"
            reason_parts.append(f"🚀 1시간 +{change_1h}%")
            change_display = change_1h
        # 1시간 급락 (SHORT!)
        elif change_1h is not None and change_1h <= -threshold_1h:
            detected = True
            alert_type = "dump_1h"
            side = "SHORT"
            reason_parts.append(f"📉 1시간 {change_1h}%")
            change_display = change_1h

        if not detected:
            continue

        # 부가 정보!
        if change_5m is not None and change_1h is not None:
            reason_parts.append(f"1h: {change_1h}%")

        volume_24h = float(t.get("quoteVolume", 0) or 0)
        price = float(t.get("lastPrice", 0) or 0)

        # 신뢰도!
        confidence = min(0.60 + abs(change_display) / 20, 0.90)

        alerts.append({
            "symbol": symbol,
            "side": side,
            "type": alert_type,
            "change_5m": change_5m,
            "change_1h": change_1h,
            "change_display": change_display,
            "confidence": round(confidence, 3),
            "reason": " | ".join(reason_parts),
            "price": price,
            "volume_24h": volume_24h,
        })

    # 정렬 = 신뢰도 순!
    alerts.sort(key=lambda a: a.get("confidence", 0), reverse=True)

    return {
        "alerts": alerts,
        "total": len(alerts),
        "scanned": len(candidates),
        "threshold_5m": threshold_5m,
        "threshold_1h": threshold_1h,
    }
