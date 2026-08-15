"""⚖ BB Middle ±5% Scan API (v159 사장님 신!)

배경 (사장님 요청 2026-08-16):
"급등락 실시간 진입에 15분 4시간봉 볼밴 중단 5% 아래위 종목을
 당일 최고 상승이 높은 순으로 볼수 있게 하나 추가해줘"

= 4H (or 15m) 볼밴 중단선 = middle 값!
= 현재가가 middle ±5% 근처 심볼 찾기!
= 당일 최고 상승 순 정렬!

= 사장님 사상: middle 이탈 시점 = 매매 기회!
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.crypto import decrypt_text
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.services.bb_4h_band_analyzer import BB4HBandAnalyzer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bb-middle-scan", tags=["bb-middle-scan"])


@router.get("/scan")
def scan_bb_middle(
    interval: str = Query(default="4h", pattern="^(4h|15m|1h|1d)$",
                          description="타임프레임"),
    proximity_pct: float = Query(default=5.0, ge=0.1, le=20.0,
                                 description="middle ±% 범위"),
    max_symbols: int = Query(default=100, ge=10, le=200,
                             description="상위 몇 심볼 스캔"),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    """⚖ 볼밴 중단선 ±X% 근처 심볼 = 당일 최고 상승 순!

    사장님 사상 (2026-08-16):
    - middle 이탈 시점 = 매매 기회!
    - middle 위 → 하락 시 = 지지 or 이탈?
    - middle 아래 → 상승 시 = 저항 or 돌파?
    - 24h 변동이 큰 심볼 = 움직임 활발!
    """
    account = db.execute(
        select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
    ).scalar_one_or_none()
    if not account:
        return {"symbols": [], "error": "no mainnet account"}

    bc = BinanceClient(
        api_key=decrypt_text(account.api_key_enc),
        api_secret=decrypt_text(account.api_secret_enc),
        is_testnet=False,
    )

    try:
        tickers = bc.get_24hr_ticker()
        if not isinstance(tickers, list):
            return {"symbols": [], "error": "ticker 실패"}
    except Exception as e:
        return {"symbols": [], "error": str(e)}

    # 상위 = 24h 상승 큰 순!
    usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
    try:
        usdt.sort(
            key=lambda x: float(x.get("priceChangePercent", 0) or 0),
            reverse=True,
        )
    except Exception:
        pass
    candidates = usdt[:max_symbols]

    matched: list[dict[str, Any]] = []
    for t in candidates:
        symbol = str(t.get("symbol", ""))
        if not symbol.endswith("USDT"):
            continue
        try:
            kl = bc.get_klines(
                symbol=symbol, interval=interval,
                limit=BB4HBandAnalyzer.KLINE_LIMIT,
            )
            if not isinstance(kl, list) or len(kl) < BB4HBandAnalyzer.BB_PERIOD + 5:
                continue

            closes = [float(k[4]) for k in kl]
            mid, up, lo = BB4HBandAnalyzer.bollinger(closes)
            if not mid or mid[-1] is None:
                continue

            middle = mid[-1]
            current = float(t.get("lastPrice", 0) or 0)
            if current <= 0 or middle <= 0:
                continue

            # middle 대비 현재가 %!
            dist_pct = (current - middle) / middle * 100

            # ±proximity_pct 안!
            if abs(dist_pct) > proximity_pct:
                continue

            change_24h = float(t.get("priceChangePercent", 0) or 0)
            high_24h = float(t.get("highPrice", 0) or 0)
            low_24h = float(t.get("lowPrice", 0) or 0)
            volume_24h = float(t.get("quoteVolume", 0) or 0)

            # 당일 최고 상승 = 저점 대비 고점!
            max_rise_pct = 0.0
            if low_24h > 0:
                max_rise_pct = round((high_24h - low_24h) / low_24h * 100, 2)

            matched.append({
                "symbol": symbol,
                "current_price": round(current, 8),
                "middle": round(middle, 8),
                "upper": round(up[-1] or 0, 8),
                "lower": round(lo[-1] or 0, 8),
                "dist_pct_from_middle": round(dist_pct, 2),
                "position": "ABOVE" if dist_pct > 0 else "BELOW",
                "change_24h": round(change_24h, 2),
                "max_rise_pct_24h": max_rise_pct,
                "high_24h": high_24h,
                "low_24h": low_24h,
                "volume_24h": round(volume_24h, 0),
            })
        except Exception as e:
            logger.debug("[bb_middle_scan] %s 실패: %s", symbol, e)
            continue

    # 정렬 = 당일 최고 상승 큰 순!
    matched.sort(key=lambda x: -x["max_rise_pct_24h"])

    return {
        "interval": interval,
        "proximity_pct": proximity_pct,
        "symbols": matched,
        "total": len(matched),
        "scanned": len(candidates),
        "note": (
            f"{interval} BB 중단선(middle) ±{proximity_pct:g}% 근처 심볼! "
            f"당일 최고 상승 (저점→고점) 큰 순 정렬! "
            f"(사장님 지시 2026-08-16)"
        ),
    }
