"""🎯 v189 사장님 Multi-Timeframe 지표 반전 감지! (2026-08-20)

사장님 사상:
"4시간 OBV/RSI/MACD가 하락/상승할 때가 급락/급등!
 이것을 미리 파악하고 = 1시간과 15분 차트의 OBV/RSI/MACD가
 먼저 큰 하락/상승 = 4시간이 하락/상승할 때 포지션 진입 = 큰 수익!
 틀리면 = 짧은 손절 = 다시 시점 잡기!"

= Multi-Timeframe Analysis (MTA)!
- 4H = 큰 추세 (방향!)
- 1H = 확인!
- 15m = 진입 시점! (선행!)

= 15m/1H 반전 감지 = 4H 반전 예상!
= 큰 수익 + 짧은 손절!
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
from app.api.v1.bb_middle_scan import (
    _calc_rsi, _calc_macd, _calc_obv_slope, _calc_cci, _calc_bb_slope,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/multi-timeframe-scan", tags=["multi-timeframe-scan"])


def _analyze_timeframe(bc: BinanceClient, symbol: str, interval: str) -> dict | None:
    """한 타임프레임의 지표 분석!"""
    try:
        kl = bc.get_klines(symbol=symbol, interval=interval, limit=BB4HBandAnalyzer.KLINE_LIMIT)
        if not isinstance(kl, list) or len(kl) < 30:
            return None
        closes = [float(k[4]) for k in kl]
        highs = [float(k[2]) for k in kl]
        lows = [float(k[3]) for k in kl]
        volumes = [float(k[5]) for k in kl]

        rsi_now = _calc_rsi(closes[-30:])
        rsi_prev = _calc_rsi(closes[-31:-1]) if len(closes) >= 31 else None
        macd = _calc_macd(closes[-60:] if len(closes) >= 60 else closes)
        obv_slope = _calc_obv_slope(closes[-30:], volumes[-30:])
        cci = _calc_cci(highs[-20:], lows[-20:], closes[-20:], period=9)
        # 🌟 v192 사장님 (2026-08-20): BB 기울기 (방향!)
        mid, up, lo = BB4HBandAnalyzer.bollinger(closes)
        bb_slope = _calc_bb_slope(mid, lookback=5)

        # 반전 감지!
        rsi_delta = (rsi_now - rsi_prev) if (rsi_now is not None and rsi_prev is not None) else 0
        macd_hist = macd["hist"] if macd else 0
        macd_signal_cross = (
            macd and macd["macd"] > macd["signal"] and macd_hist > 0
        )
        macd_bear_cross = (
            macd and macd["macd"] < macd["signal"] and macd_hist < 0
        )

        # LONG 반전 시그널: RSI 상승 + OBV 상승 + MACD 골든 or CCI 반전!
        long_score = 0
        long_reasons = []
        if rsi_delta > 2:
            long_score += 1
            long_reasons.append(f"RSI +{rsi_delta:.1f}")
        if obv_slope is not None and obv_slope > 0.02:
            long_score += 1
            long_reasons.append(f"OBV +{obv_slope*100:.0f}%")
        if macd_signal_cross:
            long_score += 1
            long_reasons.append("MACD ↑")
        if cci is not None and cci > 0 and cci > -50:
            long_score += 1
            long_reasons.append(f"CCI {cci:.0f}")

        # SHORT 반전 시그널: RSI 하락 + OBV 하락 + MACD 데드 or CCI 반전!
        short_score = 0
        short_reasons = []
        if rsi_delta < -2:
            short_score += 1
            short_reasons.append(f"RSI {rsi_delta:.1f}")
        if obv_slope is not None and obv_slope < -0.02:
            short_score += 1
            short_reasons.append(f"OBV {obv_slope*100:.0f}%")
        if macd_bear_cross:
            short_score += 1
            short_reasons.append("MACD ↓")
        if cci is not None and cci < 0 and cci < 50:
            short_score += 1
            short_reasons.append(f"CCI {cci:.0f}")

        # 🌟 v192 사장님: BB 기울기 = 큰 흐름 반영!
        # 상승 방향 = LONG 가산 / SHORT 감점!
        # 하락 방향 = SHORT 가산 / LONG 감점!
        if bb_slope is not None:
            if bb_slope > 0.5:  # 강한 상승!
                long_score += 1
                long_reasons.append(f"🌟 BB↑+{bb_slope:.1f}%")
                short_score = max(0, short_score - 1)
            elif bb_slope > 0.1:
                long_score += 1
                long_reasons.append(f"BB↑+{bb_slope:.1f}%")
            elif bb_slope < -0.5:  # 강한 하락!
                short_score += 1
                short_reasons.append(f"🌟 BB↓{bb_slope:.1f}%")
                long_score = max(0, long_score - 1)
            elif bb_slope < -0.1:
                short_score += 1
                short_reasons.append(f"BB↓{bb_slope:.1f}%")

        return {
            "interval": interval,
            "rsi": round(rsi_now, 1) if rsi_now is not None else None,
            "rsi_delta": round(rsi_delta, 1),
            "macd_hist": round(macd_hist, 6) if macd else None,
            "obv_slope_pct": round(obv_slope * 100, 1) if obv_slope is not None else None,
            "cci": round(cci, 1) if cci is not None else None,
            "bb_slope_pct": round(bb_slope, 2) if bb_slope is not None else None,
            "long_score": long_score,
            "long_reasons": long_reasons,
            "short_score": short_score,
            "short_reasons": short_reasons,
        }
    except Exception as e:
        logger.debug("[mta] %s %s 실패: %s", symbol, interval, e)
        return None


@router.get("/scan")
def scan_multi_timeframe(
    max_symbols: int = Query(default=100, ge=10, le=200),
    min_score: int = Query(default=6, ge=3, le=12,
                           description="최소 종합 점수 (15m + 1h + 4h 각 최대 4점 = 12!)"),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    """🎯 v189 사장님 Multi-Timeframe 지표 반전!

    사장님 사상:
    - 15m/1H OBV/RSI/MACD 반전 = 4H 반전 선행!
    - 낮은 프레임 반전 감지 = 큰 수익 조기 진입!

    로직:
    1. 4H = 큰 추세 (long_score / short_score!)
    2. 1H = 확인!
    3. 15m = 진입 시점!
    4. 종합 점수 = 15m*3 + 1h*2 + 4h*1 (15m 우선!)
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

    usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
    try:
        usdt.sort(key=lambda x: float(x.get("quoteVolume", 0) or 0), reverse=True)
    except Exception:
        pass
    candidates = usdt[:max_symbols]

    long_signals: list[dict] = []
    short_signals: list[dict] = []

    for t in candidates:
        symbol = str(t.get("symbol", ""))
        if not symbol.endswith("USDT"):
            continue
        try:
            # 3개 타임프레임 동시 분석!
            tf_15m = _analyze_timeframe(bc, symbol, "15m")
            tf_1h = _analyze_timeframe(bc, symbol, "1h")
            tf_4h = _analyze_timeframe(bc, symbol, "4h")
            if not tf_15m or not tf_1h or not tf_4h:
                continue

            change_24h = float(t.get("priceChangePercent", 0) or 0)
            current = float(t.get("lastPrice", 0) or 0)
            volume_24h = float(t.get("quoteVolume", 0) or 0)

            # 🌟 v192 사장님: 4H BB 방향 = 필터! (사장님 ACEUSDT 지적!)
            # 4H BB 상승 방향인데 SHORT 시그널 = 위험!
            # 4H BB 하락 방향인데 LONG 시그널 = 위험!
            tf_4h_slope = tf_4h.get("bb_slope_pct", 0) or 0
            long_penalty = 0
            short_penalty = 0
            if tf_4h_slope > 0.3:  # 4H 확실 상승!
                short_penalty = 4  # SHORT = 대폭 감점! (사장님 ACEUSDT 케이스!)
            elif tf_4h_slope < -0.3:  # 4H 확실 하락!
                long_penalty = 4  # LONG = 대폭 감점!

            # 사장님 가중치: 15m 우선! (진입!) + 1h 확인 + 4h 방향!
            long_total = (
                tf_15m["long_score"] * 3   # 15m 최우선!
                + tf_1h["long_score"] * 2  # 1h 확인!
                + tf_4h["long_score"] * 1  # 4h 방향!
                - long_penalty  # 🌟 v192: 4H BB 반대 = 감점!
            )
            short_total = (
                tf_15m["short_score"] * 3
                + tf_1h["short_score"] * 2
                + tf_4h["short_score"] * 1
                - short_penalty  # 🌟 v192: 4H BB 반대 = 감점!
            )
            long_total = max(0, long_total)
            short_total = max(0, short_total)
            # 최대 = 3*4 + 2*4 + 1*4 = 24! (v192 반대 방향 -4!)

            common = {
                "symbol": symbol,
                "current_price": current,
                "change_24h": round(change_24h, 2),
                "volume_24h": round(volume_24h, 0),
                "tf_15m": tf_15m,
                "tf_1h": tf_1h,
                "tf_4h": tf_4h,
            }

            if long_total >= min_score:
                long_signals.append({
                    **common,
                    "side": "LONG",
                    "total_score": long_total,
                    "reason": (
                        f"15m: {'+'.join(tf_15m['long_reasons']) or '-'} | "
                        f"1h: {'+'.join(tf_1h['long_reasons']) or '-'} | "
                        f"4h: {'+'.join(tf_4h['long_reasons']) or '-'}"
                    ),
                })

            if short_total >= min_score:
                short_signals.append({
                    **common,
                    "side": "SHORT",
                    "total_score": short_total,
                    "reason": (
                        f"15m: {'+'.join(tf_15m['short_reasons']) or '-'} | "
                        f"1h: {'+'.join(tf_1h['short_reasons']) or '-'} | "
                        f"4h: {'+'.join(tf_4h['short_reasons']) or '-'}"
                    ),
                })
        except Exception as e:
            logger.debug("[mta] %s 실패: %s", symbol, e)
            continue

    long_signals.sort(key=lambda x: -x["total_score"])
    short_signals.sort(key=lambda x: -x["total_score"])

    return {
        "long_signals": long_signals[:20],
        "short_signals": short_signals[:20],
        "counts": {
            "long": len(long_signals),
            "short": len(short_signals),
            "total": len(long_signals) + len(short_signals),
        },
        "scanned": len(candidates),
        "min_score": min_score,
        "note": (
            "🎯 v189 사장님 Multi-Timeframe! "
            "15m/1H/4H OBV/RSI/MACD/CCI 반전 종합! "
            "가중치: 15m*3 + 1h*2 + 4h*1 (최대 24!)"
        ),
    }
