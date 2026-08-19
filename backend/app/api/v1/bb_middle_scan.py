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


# 🎯 v169 사장님 (2026-08-17): 보조지표 종합 분석!
# 사장님 CYSUSDT 4H 차트 = 4구간 (상승/정점/하락+반등/큰 하락 지지 반등)
# = 반등 구간은 피하고! 하락 구간에서 진입! + RSI/MACD/OBV/Vol 종합!

def _calc_rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder RSI = 0~100"""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = max(diff, 0)
        loss = max(-diff, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _calc_macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict | None:
    """MACD = macd/signal/hist"""
    if len(closes) < slow + signal:
        return None

    def _ema(data: list[float], period: int) -> list[float]:
        alpha = 2 / (period + 1)
        ema = [data[0]]
        for x in data[1:]:
            ema.append((x - ema[-1]) * alpha + ema[-1])
        return ema

    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, signal)
    return {
        "macd": macd_line[-1],
        "signal": signal_line[-1],
        "hist": macd_line[-1] - signal_line[-1],
    }


def _calc_obv_slope(closes: list[float], volumes: list[float], lookback: int = 10) -> float | None:
    """OBV 최근 lookback 봉 기울기 (%)"""
    if len(closes) < lookback + 1 or len(volumes) < lookback + 1:
        return None
    obv = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    recent = obv[-lookback:]
    base = abs(recent[0]) if recent[0] != 0 else 1.0
    return (recent[-1] - recent[0]) / base


def _calc_vol_trend(volumes: list[float], lookback: int = 10) -> float:
    """거래량 = 최근 vs 이전 평균 비율 (>1 = 증가!)"""
    if len(volumes) < lookback * 2:
        return 1.0
    recent = sum(volumes[-lookback:]) / lookback
    prev = sum(volumes[-lookback * 2:-lookback]) / lookback
    return recent / prev if prev > 0 else 1.0


def _calc_cci(highs: list[float], lows: list[float], closes: list[float], period: int = 9) -> float | None:
    """🌟 v184a 사장님: CCI(9) = Commodity Channel Index!

    사장님 사상 (2026-08-20): "RSI OBV CCI를 같이 보면 흐름 파악!"
    - CCI > +100 = 강한 상승 추세!
    - CCI < -100 = 강한 하락 추세!
    - -100 ~ +100 = 중립!
    - CCI 반전 = 매매 시점!
    """
    if len(closes) < period + 1 or len(highs) < period + 1 or len(lows) < period + 1:
        return None
    # Typical Price = (High + Low + Close) / 3
    tp = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    # SMA of Typical Price
    sma_tp = sum(tp[-period:]) / period
    # Mean Deviation
    mean_dev = sum(abs(t - sma_tp) for t in tp[-period:]) / period
    if mean_dev == 0:
        return 0.0
    # CCI = (TP - SMA) / (0.015 × Mean Deviation)
    return (tp[-1] - sma_tp) / (0.015 * mean_dev)


def _detect_regime(
    closes: list[float], highs: list[float], lows: list[float],
    up: list[float | None], lo: list[float | None],
) -> str:
    """🌟 v169 사장님 4구간 자동 감지!

    UPTREND / PEAK_VOLATILE / DOWNTREND_STRONG / BOTTOM_BOUNCE / NEUTRAL

    사장님 사상 (CYSUSDT 4H 예시):
    - 1️⃣ 상승 지지 = UPTREND (진입 X)
    - 2️⃣ 정점 = PEAK_VOLATILE (진입 X, 변동성!)
    - 3️⃣ 하락 + 반등 = DOWNTREND_STRONG (SHORT 시점!) ⭐
    - 4️⃣ 큰 하락 지지 반등 = BOTTOM_BOUNCE (진입 X, 반등 위험!)
    """
    n = min(30, len(closes))
    if n < 20:
        return "UNKNOWN"

    close_now = closes[-1]
    close_20 = closes[-20]
    close_10 = closes[-10]
    close_5 = closes[-5]
    change_20 = (close_now - close_20) / close_20 if close_20 > 0 else 0
    change_10 = (close_now - close_10) / close_10 if close_10 > 0 else 0
    change_5 = (close_now - close_5) / close_5 if close_5 > 0 else 0

    high_max = max(highs[-30:])
    low_min = min(lows[-30:])
    dist_from_top = (high_max - close_now) / high_max if high_max > 0 else 0
    dist_from_bottom = (close_now - low_min) / low_min if low_min > 0 else 0

    # BOLL 위치 (하단=0 / 중단=0.5 / 상단=1)
    bb_pos = 0.5
    if up and up[-1] and lo and lo[-1] and up[-1] != lo[-1]:
        bb_pos = (close_now - lo[-1]) / (up[-1] - lo[-1])

    # 1️⃣ UPTREND = 30% 이상 상승 + 최근 10봉 지지!
    if change_20 > 0.20 and change_10 > -0.05:
        return "UPTREND"
    # 2️⃣ PEAK_VOLATILE = 정점 10% 안 + 저점 30%+ 위!
    if dist_from_top < 0.10 and dist_from_bottom > 0.30:
        return "PEAK_VOLATILE"
    # 4️⃣ BOTTOM_BOUNCE = BOLL 하단 근처 + 최근 5봉 반등!
    if bb_pos < 0.25 and change_5 > -0.03:
        return "BOTTOM_BOUNCE"
    # 3️⃣ DOWNTREND_STRONG = 20봉 -10% 이상 하락 + 10봉도 하락!
    if change_20 < -0.10 and change_10 < 0:
        return "DOWNTREND_STRONG"
    return "NEUTRAL"


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
        recent_closes: list[float] | None = None,
        recent_opens: list[float] | None = None,
        current_price: float = 0,
        bb_upper: float = 0, bb_lower: float = 0,
        rsi: float | None = None,
        macd: dict | None = None,
        obv_slope: float | None = None,
        vol_trend: float = 1.0,
        regime: str = "NEUTRAL",
    ) -> tuple[float, list[str]]:
        """🎯 v168 사장님 사상 3 시나리오 + 학습 강화 성공 가능성 (0.0 ~ 1.0)

        사장님 사상 (2026-08-17):
        - 💎 최고 수익 = PENDING → 지속 하락 예상! (도전!)
        - 🥈 중간 = STARTED → 지속 하락! (수익+안전 중간!)
        - 🌟 최고 안전 = SUSTAINED (지속 하락) = 사장님 선호! (수익 적어도 확실!)

        학습 강화 요소 (신!):
        - 연속 음봉 스트릭! (SHORT 확실성!)
        - 저점 갱신 추세! (하락 지속성!)
        - 음봉/양봉 body 크기 비율! (모멘텀!)

        요소 (합계 + 패널티 - 사장님 SUSTAINED 우대!):
        1. 심볼 30일 학습 성공률 = 최대 25% (30 → 25!)
        2. 이탈 단계 = 최대 25%
        3. 이탈 지속 봉수 = 최대 12%
        4. 하락 지속 강도 (v167) = 최대 15%
        5. 🆕 연속 음봉 스트릭 = 최대 10%
        6. 🆕 저점 갱신 추세 = 최대 8%
        7. 🆕 body 비율 = 최대 5%
        8. 24h 변동 = 최대 5%
        9. middle 이격 = 최대 5%
        10. 🌟 사장님 선호 가산 = SUSTAINED = +10% (안전 우대!)
        패널티 (SUSTAINED = 완화!):
        - BB 반대 밴드 근접: SUSTAINED -10% / 기타 -20%
        - 최근 3봉 반대 방향: SUSTAINED -10% / 기타 -15%
        """
        reasons: list[str] = []
        # 1. 심볼 학습 성공률!
        try:
            sr = get_symbol_success_rate(db, symbol, recommend_side, days=30)
        except Exception:
            sr = 0.5
        symbol_score = sr * 0.25
        reasons.append(f"심볼 학습 {int(sr*100)}%")

        # 2. 단계 점수!
        stage_scores = {
            "BREAK_SUSTAINED": 0.25,
            "BREAK_STARTED": 0.15,
            "BREAK_PENDING": 0.05,
        }
        stage_score = stage_scores.get(stage, 0.0)
        reasons.append(f"단계 {stage.replace('BREAK_', '')}")

        # 3. 지속 봉수 (SUSTAINED만!)
        bars_score = 0.0
        if stage == "BREAK_SUSTAINED":
            bars_score = min((sustained_bars - 2) * 0.02, 0.12)
            reasons.append(f"지속 {sustained_bars}봉")

        # 4. v167 하락 지속 강도!
        continuity_score = 0.0
        if recent_closes and recent_opens and len(recent_closes) >= 10 and len(recent_opens) >= 10:
            recent20_c = recent_closes[-20:] if len(recent_closes) >= 20 else recent_closes
            recent20_o = recent_opens[-20:] if len(recent_opens) >= 20 else recent_opens
            wanted_bars = 0
            for o, c in zip(recent20_o, recent20_c):
                if is_down and c < o:
                    wanted_bars += 1
                elif not is_down and c > o:
                    wanted_bars += 1
            wanted_ratio = wanted_bars / len(recent20_c) if recent20_c else 0
            continuity_score = min(max((wanted_ratio - 0.4) * 2 * 0.15, 0), 0.15)
            direction_word = "음봉" if is_down else "양봉"
            reasons.append(f"지속성 {direction_word} {wanted_bars}/{len(recent20_c)}봉")

        # 🆕 5. v168: 연속 스트릭!
        streak_score = 0.0
        if recent_closes and recent_opens and len(recent_closes) >= 5:
            streak = 0
            for o, c in zip(reversed(recent_opens), reversed(recent_closes)):
                if is_down and c < o:
                    streak += 1
                elif not is_down and c > o:
                    streak += 1
                else:
                    break
            if streak >= 3:
                streak_score = min((streak - 2) * 0.025, 0.10)
                direction_word = "음봉" if is_down else "양봉"
                reasons.append(f"🔥 연속 {streak}봉 {direction_word}!")

        # 🆕 6. v168: 저점/고점 갱신 추세!
        trend_score = 0.0
        if recent_closes and len(recent_closes) >= 5:
            recent5_c = recent_closes[-5:]
            updates = 0
            if is_down:
                for i in range(1, len(recent5_c)):
                    if recent5_c[i] < recent5_c[i - 1]:
                        updates += 1
            else:
                for i in range(1, len(recent5_c)):
                    if recent5_c[i] > recent5_c[i - 1]:
                        updates += 1
            trend_score = (updates / 4) * 0.08
            if updates >= 3:
                direction_word = "저점" if is_down else "고점"
                reasons.append(f"📉 {direction_word} 갱신 {updates}/4봉")

        # 🆕 7. v168: body 크기 비율 (모멘텀!)
        body_score = 0.0
        if recent_closes and recent_opens and len(recent_closes) >= 10:
            wanted_bodies = []
            opposite_bodies = []
            for o, c in zip(recent_opens[-10:], recent_closes[-10:]):
                body = abs(c - o)
                if is_down and c < o:
                    wanted_bodies.append(body)
                elif not is_down and c > o:
                    wanted_bodies.append(body)
                elif is_down and c > o:
                    opposite_bodies.append(body)
                elif not is_down and c < o:
                    opposite_bodies.append(body)
            if wanted_bodies and opposite_bodies:
                avg_want = sum(wanted_bodies) / len(wanted_bodies)
                avg_opp = sum(opposite_bodies) / len(opposite_bodies)
                if avg_want > avg_opp and avg_opp > 0:
                    ratio = min(avg_want / avg_opp, 3.0)
                    body_score = min((ratio - 1.0) * 0.025, 0.05)
                    if ratio >= 1.5:
                        reasons.append(f"💪 body 비율 {ratio:.1f}x")
            elif wanted_bodies and not opposite_bodies:
                body_score = 0.05
                reasons.append("💪 반대 봉 0개!")

        # 8. 24h 변동!
        change_score = min(abs(change_24h) / 400, 0.05)
        if abs(change_24h) >= 10:
            reasons.append(f"24h {change_24h:+.1f}%")

        # 9. middle 이격!
        dist_score = 0.0
        if stage == "BREAK_SUSTAINED":
            wanted_dir_dist = -dist_pct if is_down else dist_pct
            if wanted_dir_dist > 0:
                dist_score = min(wanted_dir_dist / 200, 0.05)

        # 🌟 10. v168 사장님 선호: SUSTAINED = 안전 우대!
        preference_bonus = 0.0
        if stage == "BREAK_SUSTAINED":
            preference_bonus = 0.10
            reasons.append("🌟 사장님 선호 (안전!)")

        # ═══════════ 패널티 (SUSTAINED = 완화!) ═══════════
        penalty = 0.0
        is_sustained = stage == "BREAK_SUSTAINED"

        # 🚨 페널티 1: BB 반대 밴드 근접!
        if current_price > 0 and bb_lower > 0 and bb_upper > 0:
            band_width = bb_upper - bb_lower
            if band_width > 0:
                max_penalty = 0.10 if is_sustained else 0.20
                multiplier = 0.333 if is_sustained else 0.667
                if is_down:
                    dist_from_lower = (current_price - bb_lower) / band_width
                    if dist_from_lower < 0.30:
                        penalty_val = min((0.30 - dist_from_lower) * multiplier, max_penalty)
                        penalty += penalty_val
                        note = " (완화)" if is_sustained else ""
                        reasons.append(f"⚠️ BB 하단 근접 ({dist_from_lower*100:.0f}%){note}")
                else:
                    dist_to_upper = (bb_upper - current_price) / band_width
                    if dist_to_upper < 0.30:
                        penalty_val = min((0.30 - dist_to_upper) * multiplier, max_penalty)
                        penalty += penalty_val
                        note = " (완화)" if is_sustained else ""
                        reasons.append(f"⚠️ BB 상단 근접 ({dist_to_upper*100:.0f}%){note}")

        # 🚨 페널티 2: 최근 3봉 반대 방향!
        if recent_closes and recent_opens and len(recent_closes) >= 3:
            r_c = recent_closes[-3:]
            r_o = recent_opens[-3:]
            opposite_bars = 0
            for o, c in zip(r_o, r_c):
                if is_down and c > o:
                    opposite_bars += 1
                elif not is_down and c < o:
                    opposite_bars += 1
            if opposite_bars >= 2:
                pval = 0.10 if is_sustained else 0.15
                penalty += pval
                direction_word = "양봉" if is_down else "음봉"
                note = " (완화)" if is_sustained else ""
                reasons.append(f"⚠️ 최근 3봉 = {direction_word} {opposite_bars}봉 (반등 위험!{note})")

        # 🌟 v169 사장님 (2026-08-17): 보조지표 종합!
        # RSI/MACD/OBV/Vol 종합 분석 = ±10% 조정!
        tech_score = 0.0
        if is_down:
            # ═══ SHORT (하락 방향!) 지표 조합! ═══
            if rsi is not None:
                if 25 <= rsi < 45:
                    tech_score += 0.05
                    reasons.append(f"📊 RSI {rsi:.0f} (SHORT 여유!)")
                elif rsi < 25:
                    tech_score -= 0.05
                    reasons.append(f"⚠️ RSI {rsi:.0f} (과매도 반등 위험!)")
                elif rsi >= 60:
                    tech_score += 0.03
                    reasons.append(f"📊 RSI {rsi:.0f} (상승 → SHORT 진입!)")
            if macd is not None:
                if macd["macd"] < macd["signal"] and macd["hist"] < 0:
                    tech_score += 0.05
                    reasons.append("📉 MACD 하락!")
                elif macd["hist"] > 0 and macd["hist"] > macd["signal"] * 0.1:
                    tech_score -= 0.03
                    reasons.append("⚠️ MACD 상승 (반등!)")
            if obv_slope is not None:
                if obv_slope < -0.05:
                    tech_score += 0.03
                    reasons.append(f"📉 OBV -{abs(obv_slope)*100:.0f}%")
                elif obv_slope > 0.05:
                    tech_score -= 0.03
                    reasons.append(f"⚠️ OBV +{obv_slope*100:.0f}%")
            # 거래량 = 하락 매도 확인!
            if vol_trend > 1.3:
                tech_score += 0.02
                reasons.append(f"📊 거래량 +{(vol_trend-1)*100:.0f}%")
        else:
            # ═══ LONG (상승 방향!) 지표 조합! ═══
            if rsi is not None:
                if 55 <= rsi < 75:
                    tech_score += 0.05
                    reasons.append(f"📊 RSI {rsi:.0f} (LONG 여유!)")
                elif rsi > 75:
                    tech_score -= 0.05
                    reasons.append(f"⚠️ RSI {rsi:.0f} (과매수 조정 위험!)")
                elif rsi <= 40:
                    tech_score += 0.03
                    reasons.append(f"📊 RSI {rsi:.0f} (하락 → LONG 진입!)")
            if macd is not None:
                if macd["macd"] > macd["signal"] and macd["hist"] > 0:
                    tech_score += 0.05
                    reasons.append("📈 MACD 상승!")
                elif macd["hist"] < 0:
                    tech_score -= 0.03
                    reasons.append("⚠️ MACD 하락 (조정!)")
            if obv_slope is not None:
                if obv_slope > 0.05:
                    tech_score += 0.03
                    reasons.append(f"📈 OBV +{obv_slope*100:.0f}%")
                elif obv_slope < -0.05:
                    tech_score -= 0.03
                    reasons.append(f"⚠️ OBV -{abs(obv_slope)*100:.0f}%")
            if vol_trend > 1.3:
                tech_score += 0.02
                reasons.append(f"📊 거래량 +{(vol_trend-1)*100:.0f}%")

        # 🌟 v169: 4구간 (regime) 반영!
        # 사장님 사상 = 하락 지속 진입! / 반등/정점 피함!
        regime_score = 0.0
        if is_down:
            # SHORT!
            if regime == "DOWNTREND_STRONG":
                regime_score = 0.10  # ⭐ 최적!
                reasons.append("🎯 하락 지속 (사장님 최적!)")
            elif regime == "PEAK_VOLATILE":
                regime_score = 0.05
                reasons.append("🔺 정점 (하락 전환 가능!)")
            elif regime == "BOTTOM_BOUNCE":
                regime_score = -0.15  # 🚫 최악!
                reasons.append("🚫 저점 반등 (SHORT 위험!)")
            elif regime == "UPTREND":
                regime_score = -0.10
                reasons.append("⚠️ 상승 지지 (SHORT 반대!)")
        else:
            # LONG!
            if regime == "UPTREND":
                regime_score = 0.10
                reasons.append("🎯 상승 지지 (사장님 최적!)")
            elif regime == "BOTTOM_BOUNCE":
                regime_score = 0.05
                reasons.append("💡 저점 반등 (LONG 시점!)")
            elif regime == "PEAK_VOLATILE":
                regime_score = -0.15
                reasons.append("🚫 정점 (LONG 위험!)")
            elif regime == "DOWNTREND_STRONG":
                regime_score = -0.10
                reasons.append("⚠️ 하락 지속 (LONG 반대!)")

        total = (
            symbol_score + stage_score + bars_score
            + continuity_score + streak_score + trend_score + body_score
            + change_score + dist_score + preference_bonus
            + tech_score + regime_score
            - penalty
        )
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
            # v167: 반등 감지용 완료봉 = opens/closes 배열!
            recent_opens = [float(k[1]) for k in kl[:-1]]  # 완료봉만!
            recent_closes = closes[:-1]  # 완료봉만!
            upper_now = up[-1] if up[-1] is not None else 0
            lower_now = lo[-1] if lo[-1] is not None else 0

            # 🌟 v169 사장님: 보조지표 종합 + 4구간 감지!
            highs_all = [float(k[2]) for k in kl]
            lows_all = [float(k[3]) for k in kl]
            volumes_all = [float(k[5]) for k in kl]
            rsi_val = _calc_rsi(closes[-30:])
            macd_val = _calc_macd(closes[-60:] if len(closes) >= 60 else closes)
            obv_val = _calc_obv_slope(closes[-30:], volumes_all[-30:])
            vol_val = _calc_vol_trend(volumes_all[-30:])
            regime_val = _detect_regime(closes, highs_all, lows_all, up, lo)

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
                # 🌟 v169 사장님: UI 표시용 지표!
                "regime": regime_val,
                "rsi": round(rsi_val, 1) if rsi_val is not None else None,
                "macd_hist": round(macd_val["hist"], 6) if macd_val else None,
                "obv_slope_pct": round(obv_val * 100, 1) if obv_val is not None else None,
                "vol_trend_pct": round((vol_val - 1) * 100, 1),
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
                    recent_closes=recent_closes, recent_opens=recent_opens,
                    current_price=current, bb_upper=upper_now, bb_lower=lower_now,
                    rsi=rsi_val, macd=macd_val, obv_slope=obv_val,
                    vol_trend=vol_val, regime=regime_val,
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
                    recent_closes=recent_closes, recent_opens=recent_opens,
                    current_price=current, bb_upper=upper_now, bb_lower=lower_now,
                    rsi=rsi_val, macd=macd_val, obv_slope=obv_val,
                    vol_trend=vol_val, regime=regime_val,
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
                        recent_closes=recent_closes, recent_opens=recent_opens,
                        current_price=current, bb_upper=upper_now, bb_lower=lower_now,
                        rsi=rsi_val, macd=macd_val, obv_slope=obv_val,
                        vol_trend=vol_val, regime=regime_val,
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


# ═══════════════════════════════════════════════════════════════
# 🌟 v184 사장님 (2026-08-20): BB 볼밴 반전 매매!
# 사장님 VELVETUSDT 4H 관찰:
# "볼밴 중단 지지 + 볼밴 하단 지지 + 볼밴 상단 저항 + 볼밴 중단 저항!
#  롱과 숏을 왔다갔다!"
# = 범위 매매 = 지지/저항 반전!
# ═══════════════════════════════════════════════════════════════

@router.get("/reversal")
def scan_bb_reversal(
    interval: str = Query(default="4h", pattern="^(4h|1h|15m|1d)$"),
    max_symbols: int = Query(default=150, ge=10, le=250),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    """🌟 v184 사장님 BB 볼밴 반전 매매 (지지/저항 4시점!)

    사장님 사상 (VELVETUSDT 4H 분석):
    - 하단 지지 (LONG!) = 저점 반등 시작!
    - 중단 지지 (LONG!) = 조정 후 재상승!
    - 중단 저항 (SHORT!) = 반등 실패!
    - 상단 저항 (SHORT!) = 고점 도달!
    = 롱과 숏 왔다갔다 = 사이클 매매!
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

    # 4가지 반전 시나리오!
    lower_support: list[dict[str, Any]] = []  # 하단 지지 LONG
    middle_support: list[dict[str, Any]] = []  # 중단 지지 LONG
    middle_resistance: list[dict[str, Any]] = []  # 중단 저항 SHORT
    upper_resistance: list[dict[str, Any]] = []  # 상단 저항 SHORT

    for t in candidates:
        symbol = str(t.get("symbol", ""))
        if not symbol.endswith("USDT"):
            continue
        try:
            kl = bc.get_klines(symbol=symbol, interval=interval,
                               limit=BB4HBandAnalyzer.KLINE_LIMIT)
            if not isinstance(kl, list) or len(kl) < BB4HBandAnalyzer.BB_PERIOD + 10:
                continue

            closes = [float(k[4]) for k in kl]
            opens = [float(k[1]) for k in kl]
            highs = [float(k[2]) for k in kl]
            lows = [float(k[3]) for k in kl]
            volumes = [float(k[5]) for k in kl]
            mid, up, lo = BB4HBandAnalyzer.bollinger(closes)
            if not mid or mid[-1] is None or up[-1] is None or lo[-1] is None:
                continue

            middle_now = mid[-1]
            upper_now = up[-1]
            lower_now = lo[-1]
            current = float(t.get("lastPrice", 0) or 0)
            change_24h = float(t.get("priceChangePercent", 0) or 0)
            volume_24h = float(t.get("quoteVolume", 0) or 0)
            if middle_now <= 0 or current <= 0:
                continue

            # 🌟 v184a 사장님: RSI + OBV + CCI 종합 (사장님 지시!)!
            rsi_val = _calc_rsi(closes[-30:])
            macd_val = _calc_macd(closes[-60:] if len(closes) >= 60 else closes)
            obv_val = _calc_obv_slope(closes[-30:], volumes[-30:])
            cci_val = _calc_cci(highs[-20:], lows[-20:], closes[-20:], period=9)

            # 각 밴드 대비 위치!
            dist_lower_pct = (current - lower_now) / lower_now * 100 if lower_now > 0 else 0
            dist_middle_pct = (current - middle_now) / middle_now * 100
            dist_upper_pct = (current - upper_now) / upper_now * 100 if upper_now > 0 else 0

            # 최근 5봉 = 반전 감지용!
            recent5_o = opens[-5:] if len(opens) >= 5 else opens
            recent5_c = closes[-5:] if len(closes) >= 5 else closes
            recent5_l = lows[-5:] if len(lows) >= 5 else lows
            recent5_h = highs[-5:] if len(highs) >= 5 else highs
            bull_bars = sum(1 for o, c in zip(recent5_o, recent5_c) if c > o)
            bear_bars = sum(1 for o, c in zip(recent5_o, recent5_c) if c < o)

            common = {
                "symbol": symbol,
                "current_price": round(current, 8),
                "middle": round(middle_now, 8),
                "upper": round(upper_now, 8),
                "lower": round(lower_now, 8),
                "dist_lower_pct": round(dist_lower_pct, 2),
                "dist_middle_pct": round(dist_middle_pct, 2),
                "dist_upper_pct": round(dist_upper_pct, 2),
                "change_24h": round(change_24h, 2),
                "volume_24h": round(volume_24h, 0),
                "rsi": round(rsi_val, 1) if rsi_val is not None else None,
                "macd_hist": round(macd_val["hist"], 6) if macd_val else None,
                # 🌟 v184a 사장님: OBV + CCI 추가!
                "obv_slope_pct": round(obv_val * 100, 1) if obv_val is not None else None,
                "cci": round(cci_val, 1) if cci_val is not None else None,
                "bull_bars_5": bull_bars,
                "bear_bars_5": bear_bars,
            }

            # 1️⃣ 하단 지지 LONG! (사장님 3지표 종합!)
            # 조건: 하단 근접 + 반등 시작 + RSI 과매도 + OBV 반등 + CCI 반전!
            recent5_min_l = min(recent5_l) if recent5_l else current
            lower_touch_pct = (recent5_min_l - lower_now) / lower_now * 100 if lower_now > 0 else 0
            if (
                0 <= dist_lower_pct <= 5  # 현재가 = 하단 위 5% 이내
                and abs(lower_touch_pct) <= 3  # 최근 5봉 저점 = 하단 근접!
                and bull_bars >= 2  # 최근 5봉 중 2봉+ 양봉 (반등!)
                and (rsi_val is None or rsi_val < 40)  # RSI 과매도!
            ):
                score = 0.55
                reasons_l = [f"BB 하단 지지!"]
                if bull_bars >= 3:
                    score += 0.10
                    reasons_l.append(f"{bull_bars}봉 양봉")
                if rsi_val is not None and rsi_val < 30:
                    score += 0.10
                    reasons_l.append(f"RSI {rsi_val:.0f} 과매도")
                if macd_val and macd_val["hist"] > 0:
                    score += 0.08
                    reasons_l.append("MACD ↑")
                # 🌟 v184a: OBV 반등!
                if obv_val is not None and obv_val > 0:
                    score += 0.08
                    reasons_l.append(f"OBV +{obv_val*100:.0f}%")
                # 🌟 v184a: CCI 과매도 반전! (-100 이하에서 상승 = LONG!)
                if cci_val is not None:
                    if cci_val < -100:
                        score += 0.10
                        reasons_l.append(f"CCI {cci_val:.0f} 과매도 반전!")
                    elif cci_val < 0:
                        score += 0.05
                        reasons_l.append(f"CCI {cci_val:.0f}")
                lower_support.append({
                    **common,
                    "signal": "LOWER_SUPPORT_LONG",
                    "side": "LONG",
                    "score": round(min(score, 0.99), 4),
                    "reason": " + ".join(reasons_l),
                })

            # 2️⃣ 중단 지지 LONG!
            # 조건: 중단 근처 (|dist_middle| < 3%) + 아래에서 상승 중!
            if (
                -3 <= dist_middle_pct <= 3  # 중단 근접!
                and current > middle_now  # 중단 위!
                and bull_bars >= 3  # 강한 상승!
                and rsi_val is not None and 45 <= rsi_val <= 60  # 중립~약한 상승!
            ):
                score = 0.55
                if macd_val and macd_val["hist"] > 0 and macd_val["macd"] > macd_val["signal"]:
                    score += 0.15
                middle_support.append({
                    **common,
                    "signal": "MIDDLE_SUPPORT_LONG",
                    "side": "LONG",
                    "score": round(score, 4),
                    "reason": f"BB 중단 지지 재상승! RSI {rsi_val:.0f} MACD ↑",
                })

            # 3️⃣ 중단 저항 SHORT!
            # 조건: 중단 근처 + 위에서 하락 시작!
            if (
                -3 <= dist_middle_pct <= 3
                and current < middle_now  # 중단 아래!
                and bear_bars >= 3  # 강한 하락!
                and rsi_val is not None and 40 <= rsi_val <= 55
            ):
                score = 0.55
                if macd_val and macd_val["hist"] < 0 and macd_val["macd"] < macd_val["signal"]:
                    score += 0.15
                middle_resistance.append({
                    **common,
                    "signal": "MIDDLE_RESISTANCE_SHORT",
                    "side": "SHORT",
                    "score": round(score, 4),
                    "reason": f"BB 중단 저항 재하락! RSI {rsi_val:.0f} MACD ↓",
                })

            # 4️⃣ 상단 저항 SHORT! (사장님 3지표 종합!)
            # 조건: 상단 근접 + 반전 시작 + RSI 과매수 + OBV 하락 + CCI 반전!
            recent5_max_h = max(recent5_h) if recent5_h else current
            upper_touch_pct = (upper_now - recent5_max_h) / upper_now * 100 if upper_now > 0 else 0
            if (
                -5 <= dist_upper_pct <= 0  # 현재가 = 상단 아래 5% 이내
                and abs(upper_touch_pct) <= 3  # 최근 5봉 고점 = 상단 도달!
                and bear_bars >= 2
                and (rsi_val is None or rsi_val > 60)
            ):
                score = 0.55
                reasons_u = [f"BB 상단 저항!"]
                if bear_bars >= 3:
                    score += 0.10
                    reasons_u.append(f"{bear_bars}봉 음봉")
                if rsi_val is not None and rsi_val > 70:
                    score += 0.10
                    reasons_u.append(f"RSI {rsi_val:.0f} 과매수")
                if macd_val and macd_val["hist"] < 0:
                    score += 0.08
                    reasons_u.append("MACD ↓")
                # 🌟 v184a: OBV 하락!
                if obv_val is not None and obv_val < 0:
                    score += 0.08
                    reasons_u.append(f"OBV {obv_val*100:.0f}%")
                # 🌟 v184a: CCI 과매수 반전!
                if cci_val is not None:
                    if cci_val > 100:
                        score += 0.10
                        reasons_u.append(f"CCI {cci_val:.0f} 과매수 반전!")
                    elif cci_val > 0:
                        score += 0.05
                        reasons_u.append(f"CCI {cci_val:.0f}")
                upper_resistance.append({
                    **common,
                    "signal": "UPPER_RESISTANCE_SHORT",
                    "side": "SHORT",
                    "score": round(min(score, 0.99), 4),
                    "reason": " + ".join(reasons_u),
                })

        except Exception as e:
            logger.debug("[bb_reversal] %s 실패: %s", symbol, e)
            continue

    # 각 시나리오 = score 큰 순!
    lower_support.sort(key=lambda x: -x["score"])
    middle_support.sort(key=lambda x: -x["score"])
    middle_resistance.sort(key=lambda x: -x["score"])
    upper_resistance.sort(key=lambda x: -x["score"])

    return {
        "interval": interval,
        "lower_support": lower_support[:20],   # 🐂 하단 지지 LONG
        "middle_support": middle_support[:20], # 🐂 중단 지지 LONG
        "middle_resistance": middle_resistance[:20],  # 🐻 중단 저항 SHORT
        "upper_resistance": upper_resistance[:20],    # 🐻 상단 저항 SHORT
        "counts": {
            "lower_support": len(lower_support),
            "middle_support": len(middle_support),
            "middle_resistance": len(middle_resistance),
            "upper_resistance": len(upper_resistance),
            "total": (
                len(lower_support) + len(middle_support)
                + len(middle_resistance) + len(upper_resistance)
            ),
        },
        "scanned": len(candidates),
        "note": (
            f"🌟 v184 사장님 사상 = BB 볼밴 반전 매매!"
            f" 하단/중단 지지 = LONG! 중단/상단 저항 = SHORT!"
            f" 롱과 숏 왔다갔다! (사장님 VELVETUSDT 2026-08-20!)"
        ),
    }
