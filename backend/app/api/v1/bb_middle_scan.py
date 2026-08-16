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


@router.get("/breakdown")
def scan_bb_breakdown(
    interval: str = Query(default="4h", pattern="^(4h|1h|15m|1d)$"),
    direction: str = Query(default="down", pattern="^(down|up)$",
                           description="down=하락 이탈(SHORT), up=상승 돌파(LONG)"),
    max_symbols: int = Query(default=150, ge=10, le=250),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    """🐻 BB middle 이탈 3단계 분류! (v161 사장님!)

    사장님 지시 2026-08-16 (5개 스크린샷 = COW/ACE/BR/PROM/HOME!):
    "4시간봉이 볼밴 중단을 이탈할 것과 이탈을 시작한 것 그리고
     지속적으로 이탈하는 것 이렇게 찾아서 추천해줘!"

    3단계:
    1. **BREAK_PENDING** = 이탈 임박! (middle 근접 0~3%)
    2. **BREAK_STARTED** = 이탈 시작! (최근 1~3봉에 이탈!)
    3. **BREAK_SUSTAINED** = 이탈 지속! (3봉+ 이탈 유지!) ← ⭐ 제일 확실!

    direction:
    - down = middle 하향 이탈 (SHORT!)
    - up   = middle 상향 돌파 (LONG!)
    """
    is_down = direction == "down"
    recommend_side = "SHORT" if is_down else "LONG"

    # 🎯 v165 사장님 (2026-08-16): 학습 기반 성공 가능성!
    from app.workers.prediction_outcome_worker import get_symbol_success_rate

    def _calc_success_probability(
        symbol: str, stage: str, sustained_bars: int,
        change_24h: float, dist_pct: float,
    ) -> tuple[float, list[str]]:
        """🎯 학습 기반 성공 가능성 계산! (0.0 ~ 1.0)

        요소:
        1. 심볼 30일 성공률 (학습!)  = 최대 40%
        2. 이탈 단계 = SUSTAINED > STARTED > PENDING = 최대 30%
        3. 이탈 지속 봉수 (SUSTAINED만!) = 최대 15%
        4. 24h 변동 크기 = 최대 10%
        5. middle 이격 거리 = 최대 5%
        """
        reasons: list[str] = []
        # 1. 심볼 학습 성공률!
        try:
            sr = get_symbol_success_rate(db, symbol, recommend_side, days=30)
        except Exception:
            sr = 0.5
        symbol_score = sr * 0.40
        reasons.append(f"심볼 학습 {int(sr*100)}%")

        # 2. 단계 점수!
        stage_scores = {
            "BREAK_SUSTAINED": 0.30,
            "BREAK_STARTED": 0.20,
            "BREAK_PENDING": 0.05,
        }
        stage_score = stage_scores.get(stage, 0.0)
        reasons.append(f"단계 {stage.replace('BREAK_', '')}")

        # 3. 지속 봉수 (SUSTAINED만!)
        bars_score = 0.0
        if stage == "BREAK_SUSTAINED":
            # 3봉 = 0.05, 5봉 = 0.10, 7봉+ = 0.15!
            bars_score = min((sustained_bars - 2) * 0.025, 0.15)
            reasons.append(f"지속 {sustained_bars}봉")

        # 4. 24h 변동!
        # ±20% = 0.10 만점!
        change_score = min(abs(change_24h) / 200, 0.10)
        if abs(change_24h) >= 10:
            reasons.append(f"24h {change_24h:+.1f}%")

        # 5. middle 이격!
        # 이격 클수록 = 확실! (SUSTAINED에서!)
        # DOWN = 아래로 이격 큰 순 (음수!)
        # UP = 위로 이격 큰 순 (양수!)
        dist_score = 0.0
        if stage == "BREAK_SUSTAINED":
            wanted_dir_dist = -dist_pct if is_down else dist_pct
            if wanted_dir_dist > 0:
                dist_score = min(wanted_dir_dist / 200, 0.05)

        total = symbol_score + stage_score + bars_score + change_score + dist_score
        return round(min(max(total, 0.0), 1.0), 4), reasons

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

    pending: list[dict[str, Any]] = []   # 이탈 임박!
    started: list[dict[str, Any]] = []   # 이탈 시작!
    sustained: list[dict[str, Any]] = [] # 이탈 지속! ⭐

    for t in candidates:
        symbol = str(t.get("symbol", ""))
        if not symbol.endswith("USDT"):
            continue
        try:
            kl = bc.get_klines(symbol=symbol, interval=interval,
                               limit=BB4HBandAnalyzer.KLINE_LIMIT)
            if not isinstance(kl, list) or len(kl) < BB4HBandAnalyzer.BB_PERIOD + 5:
                continue

            closes = [float(k[4]) for k in kl]
            mid, up, lo = BB4HBandAnalyzer.bollinger(closes)
            if not mid or mid[-1] is None:
                continue

            middle_now = mid[-1]
            current = float(t.get("lastPrice", 0) or 0)
            if middle_now <= 0 or current <= 0:
                continue

            change_24h = float(t.get("priceChangePercent", 0) or 0)
            volume_24h = float(t.get("quoteVolume", 0) or 0)

            # 최근 5봉 (완료봉만!) middle 대비 close 위치!
            positions = []
            for i in range(-6, -1):  # -6~-2 (완료봉!)
                if i < -len(closes) or mid[i] is None:
                    continue
                c = closes[i]
                m = mid[i]
                # DOWN: close < middle = 이탈!
                # UP:   close > middle = 돌파!
                if is_down:
                    positions.append(c < m)
                else:
                    positions.append(c > m)

            if len(positions) < 3:
                continue

            # 현재 상태!
            close_last = closes[-1]  # 진행 중 봉!
            if is_down:
                current_broken = close_last < middle_now
                # 마지막 완료봉 = positions[-1]
            else:
                current_broken = close_last > middle_now

            dist_pct = (current - middle_now) / middle_now * 100  # + = 위, - = 아래

            common = {
                "symbol": symbol,
                "current_price": round(current, 8),
                "middle": round(middle_now, 8),
                "dist_pct": round(dist_pct, 2),
                "change_24h": round(change_24h, 2),
                "volume_24h": round(volume_24h, 0),
                "positions_recent": positions,  # 최근 5봉 이탈 여부
            }

            # 🎯 3단계 분류 + v165 성공 가능성 계산!

            # 3. SUSTAINED = 최근 3봉+ 지속 이탈! (⭐ 제일 확실!)
            if all(positions[-3:]) and current_broken:
                sustained_bars = 0
                for p in reversed(positions):
                    if p:
                        sustained_bars += 1
                    else:
                        break
                prob, reasons = _calc_success_probability(
                    symbol, "BREAK_SUSTAINED", sustained_bars, change_24h, dist_pct,
                )
                sustained.append({
                    **common,
                    "stage": "BREAK_SUSTAINED",
                    "sustained_bars": sustained_bars,
                    "success_probability": prob,
                    "probability_reasons": reasons,
                })
            # 2. STARTED = 최근 1~2봉 이탈 시작!
            elif current_broken and (
                positions[-1] or positions[-2] or positions[-3]
            ):
                prob, reasons = _calc_success_probability(
                    symbol, "BREAK_STARTED", 0, change_24h, dist_pct,
                )
                started.append({
                    **common,
                    "stage": "BREAK_STARTED",
                    "success_probability": prob,
                    "probability_reasons": reasons,
                })
            # 1. PENDING = 이탈 안 함 + middle 근접!
            elif not current_broken and abs(dist_pct) <= 3.0:
                if (is_down and 0 <= dist_pct <= 3.0) or (not is_down and -3.0 <= dist_pct <= 0):
                    prob, reasons = _calc_success_probability(
                        symbol, "BREAK_PENDING", 0, change_24h, dist_pct,
                    )
                    pending.append({
                        **common,
                        "stage": "BREAK_PENDING",
                        "success_probability": prob,
                        "probability_reasons": reasons,
                    })
        except Exception as e:
            logger.debug("[bb_breakdown] %s 실패: %s", symbol, e)
            continue

    # 🎯 v165 사장님: 성공 가능성 순 정렬!
    # SUSTAINED = 성공률 큰 순 → 지속 봉 → 24h 변동!
    sustained.sort(
        key=lambda x: (-x.get("success_probability", 0),
                       -x.get("sustained_bars", 0),
                       -abs(x["change_24h"]))
    )
    # STARTED = 성공률 큰 순 → 24h 변동!
    started.sort(key=lambda x: (-x.get("success_probability", 0), -abs(x["change_24h"])))
    # PENDING = 성공률 큰 순 → middle 근접!
    pending.sort(key=lambda x: (-x.get("success_probability", 0), abs(x["dist_pct"])))

    total = len(pending) + len(started) + len(sustained)
    return {
        "interval": interval,
        "direction": direction,
        "side_recommend": "SHORT" if is_down else "LONG",
        "sustained": sustained[:30],    # ⭐ 제일 확실!
        "started": started[:30],
        "pending": pending[:30],
        "counts": {
            "sustained": len(sustained),
            "started": len(started),
            "pending": len(pending),
            "total": total,
        },
        "scanned": len(candidates),
        "note": (
            f"{interval} BB middle 이탈 3단계 ({direction}) - "
            f"제일 확실 = 이탈 지속 (SUSTAINED)! 다음 = 이탈 시작 (STARTED)! "
            f"관찰 = 이탈 임박 (PENDING)! "
            f"(사장님 지시 2026-08-16)"
        ),
    }
