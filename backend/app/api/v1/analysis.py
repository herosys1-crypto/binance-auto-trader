"""📊 Analysis API (v133c 신!) - 심볼/전략 상세 분석!

사장님 요구 (2026-08-13):
"종목을 클릭하면 새창으로 현재상태분석을 확인하고 조치할수 있게 해줘"

= 심볼 상세 분석 (즉시 진입 결정!)
= 활성 전략 상세 분석 (보유/청산/추가 결정!)
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.crypto import decrypt_text
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.integrations.binance.client import BinanceClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])


def _get_binance_client(db: Session) -> BinanceClient:
    """mainnet Binance client 로드!"""
    account = db.execute(
        select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
    ).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="mainnet account 없음!")
    return BinanceClient(
        api_key=decrypt_text(account.api_key_enc),
        api_secret=decrypt_text(account.api_secret_enc),
        is_testnet=account.is_testnet,
    )


def _calc_rsi(closes: list[float], period: int = 14) -> float | None:
    """RSI 계산!"""
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(-diff)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = diff if diff > 0 else 0
        loss = -diff if diff < 0 else 0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _calc_bb(closes: list[float], period: int = 20, std_mult: float = 2.0) -> dict:
    """Bollinger Bands 계산!"""
    if len(closes) < period:
        return {"upper": None, "middle": None, "lower": None}
    recent = closes[-period:]
    mid = sum(recent) / period
    variance = sum((c - mid) ** 2 for c in recent) / period
    std = variance ** 0.5
    return {
        "upper": round(mid + std_mult * std, 6),
        "middle": round(mid, 6),
        "lower": round(mid - std_mult * std, 6),
    }


def _calc_change_pct(open_p: float, close_p: float) -> float:
    """변동률!"""
    if open_p <= 0:
        return 0.0
    return round(((close_p - open_p) / open_p) * 100, 2)


@router.get("/symbol/{symbol}")
def analyze_symbol(
    symbol: str,
    side: str = Query("LONG", description="LONG or SHORT"),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    """🌟 심볼 상세 분석!

    - 현재가 + 다중 시간대 변동률
    - RSI, BB (기술 지표)
    - 판단 (진입 강도!)
    """
    bc = _get_binance_client(db)
    symbol = symbol.upper()
    side = side.upper()

    result: dict[str, Any] = {
        "symbol": symbol,
        "side": side,
    }

    # 1. 현재가 (24h ticker)!
    try:
        ticker = bc.get_24hr_ticker(symbol=symbol)
        if isinstance(ticker, dict):
            result["price"] = float(ticker.get("lastPrice", 0))
            result["change_24h"] = float(ticker.get("priceChangePercent", 0))
            result["volume_24h"] = float(ticker.get("quoteVolume", 0))
            result["high_24h"] = float(ticker.get("highPrice", 0))
            result["low_24h"] = float(ticker.get("lowPrice", 0))
    except Exception as e:
        logger.warning("[analyze_symbol] ticker 실패 %s: %s", symbol, e)
        result["price_error"] = str(e)

    # 2. 다중 시간대 변동!
    changes: dict[str, Any] = {}
    for interval, key, limit in [
        ("5m", "change_5m", 2),
        ("15m", "change_15m", 2),
        ("1h", "change_1h", 2),
        ("4h", "change_4h", 2),
    ]:
        try:
            klines = bc.get_klines(symbol=symbol, interval=interval, limit=limit)
            if isinstance(klines, list) and len(klines) >= 2:
                last = klines[-2]  # 완료 봉!
                open_p = float(last[1])
                close_p = float(last[4])
                changes[key] = _calc_change_pct(open_p, close_p)
        except Exception:
            changes[key] = None
    result["changes"] = changes

    # 3. RSI + BB (15분봉!)
    try:
        klines_15m = bc.get_klines(symbol=symbol, interval="15m", limit=50)
        if isinstance(klines_15m, list) and len(klines_15m) >= 20:
            closes = [float(k[4]) for k in klines_15m]
            result["rsi_15m"] = _calc_rsi(closes)
            result["bb_15m"] = _calc_bb(closes)
    except Exception as e:
        logger.warning("[analyze_symbol] 15m klines 실패 %s: %s", symbol, e)

    # 4. 판단!
    result["judgment"] = _judge_entry(result, side)
    return result


def _judge_entry(analysis: dict, side: str) -> dict:
    """진입 판단!

    - side에 따라 = 지표 반대로 해석!
    - RSI 30 미만 (과매도) → LONG 유리!
    - RSI 70 초과 (과매수) → SHORT 유리!
    - BB 하단 근접 → LONG 유리!
    - BB 상단 근접 → SHORT 유리!
    """
    score = 50  # 기본 = 중립!
    signals = []

    rsi = analysis.get("rsi_15m")
    bb = analysis.get("bb_15m") or {}
    price = analysis.get("price", 0)
    change_5m = (analysis.get("changes") or {}).get("change_5m", 0) or 0
    change_1h = (analysis.get("changes") or {}).get("change_1h", 0) or 0

    if side == "LONG":
        # 과매도 = LONG 유리!
        if rsi is not None:
            if rsi < 30:
                score += 20
                signals.append(f"✅ RSI {rsi} 과매도 = LONG 유리!")
            elif rsi > 70:
                score -= 15
                signals.append(f"⚠️ RSI {rsi} 과매수 = LONG 불리!")
            else:
                signals.append(f"➖ RSI {rsi} 중립")
        # BB 하단 근접 = 반등 기대!
        if bb.get("lower") and price > 0:
            dist_lower = ((price - bb["lower"]) / price) * 100
            if dist_lower < 1:
                score += 15
                signals.append(f"✅ BB 하단 근접 ({dist_lower:.1f}%) = 반등 기대!")
        # 5분 급락 = 지금 진입 = 반등 or 지속?
        if change_5m < -3:
            score -= 10
            signals.append(f"⚠️ 5분 {change_5m:.1f}% 급락 중 = LONG 신중!")
        elif change_5m > 3:
            score += 10
            signals.append(f"✅ 5분 +{change_5m:.1f}% 급등 중 = LONG 모멘텀!")
    else:  # SHORT
        # 과매수 = SHORT 유리!
        if rsi is not None:
            if rsi > 70:
                score += 20
                signals.append(f"✅ RSI {rsi} 과매수 = SHORT 유리!")
            elif rsi < 30:
                score -= 15
                signals.append(f"⚠️ RSI {rsi} 과매도 = SHORT 불리!")
            else:
                signals.append(f"➖ RSI {rsi} 중립")
        # BB 상단 근접 = 조정 기대!
        if bb.get("upper") and price > 0:
            dist_upper = ((bb["upper"] - price) / price) * 100
            if dist_upper < 1:
                score += 15
                signals.append(f"✅ BB 상단 근접 ({dist_upper:.1f}%) = 조정 기대!")
        # 5분 급등 = SHORT 즉시 = 반락?
        if change_5m > 3:
            score -= 10
            signals.append(f"⚠️ 5분 +{change_5m:.1f}% 급등 중 = SHORT 신중!")
        elif change_5m < -3:
            score += 10
            signals.append(f"✅ 5분 {change_5m:.1f}% 급락 중 = SHORT 모멘텀!")

    # 판단 결과!
    if score >= 75:
        verdict = "🔥 강력 추천!"
        color = "#ef4444" if side == "SHORT" else "#22c55e"
    elif score >= 60:
        verdict = "⭐ 추천!"
        color = "#f59e0b"
    elif score >= 45:
        verdict = "➖ 중립"
        color = "#94a3b8"
    else:
        verdict = "⚠️ 신중!"
        color = "#94a3b8"

    return {
        "score": score,
        "verdict": verdict,
        "color": color,
        "signals": signals,
    }


@router.get("/strategy/{strategy_id}")
def analyze_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    """🌟 활성 전략 상세 분석!

    - 현재 상태 (가격, ROI, 진입 단계, 트리거!)
    - 판단 (보유 유지 / 위험 청산 / 포지션 추가 / 강약!)
    """
    strategy = db.get(StrategyInstance, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="전략 없음!")

    result: dict[str, Any] = {
        "id": strategy.id,
        "symbol": strategy.symbol,
        "side": strategy.side,
        "status": strategy.status,
        "current_position_qty": str(strategy.current_position_qty or 0),
        "avg_entry_price": str(strategy.avg_entry_price or 0),
        "current_price": str(strategy.current_price or 0),
        "unrealized_pnl_pct": float(strategy.unrealized_pnl_pct or 0),
        "max_profit_pct": float(strategy.max_profit_pct) if strategy.max_profit_pct is not None else None,
        "max_loss_pct": float(strategy.max_loss_pct) if strategy.max_loss_pct is not None else None,
    }

    # 심볼 분석 = 재사용!
    try:
        symbol_analysis = analyze_symbol(
            symbol=strategy.symbol,
            side=strategy.side,
            db=db,
            user_id=user_id,
        )
        result["symbol_analysis"] = symbol_analysis
    except Exception as e:
        logger.warning("[analyze_strategy] symbol_analysis 실패: %s", e)

    # 판단 = 보유/청산/추가!
    result["position_judgment"] = _judge_position(strategy, result)
    return result


def _judge_position(strategy: StrategyInstance, analysis: dict) -> dict:
    """포지션 판단 = 보유/청산/추가!"""
    signals = []
    action = "HOLD"  # 기본 보유!
    color = "#22c55e"

    pnl = float(strategy.unrealized_pnl_pct or 0)
    max_profit = float(strategy.max_profit_pct or 0) if strategy.max_profit_pct is not None else 0

    # 손실 판단!
    if pnl <= -50:
        action = "URGENT_CLOSE"
        color = "#ef4444"
        signals.append(f"🚨 손실 {pnl:.1f}% = 위험! 청산 검토!")
    elif pnl <= -20:
        action = "REVIEW"
        color = "#f59e0b"
        signals.append(f"⚠️ 손실 {pnl:.1f}% = 주의! 지지선 확인!")
    elif pnl >= 30:
        action = "HOLD_STRONG"
        color = "#22c55e"
        signals.append(f"🎉 수익 +{pnl:.1f}% = 보유 유지! (트레일링 감시!)")
    elif pnl >= 10:
        signals.append(f"💰 수익 +{pnl:.1f}% = 보유 유지!")
    else:
        signals.append(f"➖ 손익 {pnl:.1f}% = 보유 (지켜보기!)")

    # 트레일링 = 피크 대비 하락!
    if max_profit >= 20 and pnl < max_profit - 5:
        signals.append(f"📉 피크 +{max_profit:.1f}%에서 하락 = 트레일링 감시!")

    # 심볼 분석 = 포지션 방향 반대면 청산!
    sym_analysis = analysis.get("symbol_analysis") or {}
    sym_judgment = sym_analysis.get("judgment") or {}
    if sym_judgment.get("verdict") and "강력" in sym_judgment.get("verdict", ""):
        signals.append(f"📊 심볼 분석: {sym_judgment['verdict']}")

    return {
        "action": action,
        "color": color,
        "signals": signals,
    }
