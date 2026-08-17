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
        recent_closes: list[float] | None = None,
        recent_opens: list[float] | None = None,
        current_price: float = 0,
        bb_upper: float = 0, bb_lower: float = 0,
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

        total = (
            symbol_score + stage_score + bars_score
            + continuity_score + streak_score + trend_score + body_score
            + change_score + dist_score + preference_bonus
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
                    recent_closes=recent_closes, recent_opens=recent_opens,
                    current_price=current, bb_upper=upper_now, bb_lower=lower_now,
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
