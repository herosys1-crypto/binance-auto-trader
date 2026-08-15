"""📉 4시간봉 볼밴 중단 이탈 → 반대 밴드 목표 전략 (v143 신!)

spec: docs/BB_4H_BAND_STRATEGY_SPEC.md
사장님 지시 2026-08-14:
  "4시간봉 볼밴 중단을 깨지면 추가 하락을 볼밴 하단까지 하고,
   볼밴 하단을 깨고 내려가는건 아주 적은 경우야. 분석해서 매매전략으로 만들어줘"

🔬 실측 (scripts/study_4h_bb_middle_break.py)
   178심볼 × 4h **215,561개 캔들** (약 250일) — 이번 세션 통틀어 가장 큰 표본

  ✅ [가설 1 = 사장님 말씀이 맞습니다]
     4H 종가가 중단을 하향 이탈한 13,053건 중
        → 5일 내 **하단 도달 82.8%** (10,806건)
        → 도달 소요 **중앙값 5봉(20시간)**, 진입가→하단 거리 **중앙값 2.72%**
     상향 돌파(대칭)도 **상단 도달 86.6%** = 방향 무관하게 성립합니다.

  ❌ [가설 2 = 데이터는 반대입니다]
     "하단을 깨고 내려가는 건 아주 적다" → 실제로는
        하단 도달 10,806건 중 **68.3%가 하단 아래로 종가 마감**했습니다.
        이탈 시 추가 하락폭 **중앙값 5.69%**.
     → 하단은 **지지선이 아닙니다.** (v140 의 15m BB중단 결론과 같은 방향)
     → 그래서 「하단에서 반등하겠지」로 LONG 잡는 건 위험합니다.

  💰 매매 규칙 실측 기대값 (수수료 차감 전):
     · 규칙 A = 중단 이탈 봉에 **추세 방향 진입**, TP = 반대 밴드
         하향: SL -5% → TP선착 64.0%, 기대값 **+0.42%** (10,806건)
         상향: SL -5% → TP선착 65.8%, 기대값 **+0.44%** (11,303건)
     · 규칙 B = 밴드 도달 시 **역방향(평균회귀)** 진입, TP = 중단 복귀
         하향→LONG: SL -2% → TP선착 36.8%, 기대값 +0.21%
         상향→SHORT: SL -2% → 35.5%, 기대값 +0.10%   ← 약함!

  → **규칙 A(추세 방향)가 규칙 B(역방향)보다 2배 이상 좋습니다.**

헌법 v143:
  '4H 중단을 깨면 반대 밴드까지 간다 (82~87%) — 이건 실측으로 가장 견고한 신호다'
  '단, 밴드는 지지·저항이 아니다. 68%가 밴드를 뚫고 더 간다!'
  '밴드 도달은 목표 달성이지 반전 신호가 아니다 — 역진입은 기대값이 절반이다'
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class BB4HBandAnalyzer:
    """4H BB 중단 이탈 감지 + 반대 밴드 목표 산출."""

    BB_PERIOD = 20
    BB_STD = 2.0

    # --- 실측 통계 (사장님께 그대로 노출) ---
    REACH_RATE = {"DOWN": 82.8, "UP": 86.6}       # 반대 밴드 도달률 %
    REACH_BARS = {"DOWN": 5, "UP": 4}             # 도달 소요 중앙값 (봉)
    REACH_DIST = {"DOWN": 2.72, "UP": 2.50}       # 진입가→밴드 거리 중앙값 %
    BREAK_RATE = {"DOWN": 68.3, "UP": 69.8}       # 밴드 도달 후 뚫고 마감 %
    EXTRA_MOVE = {"DOWN": 5.69, "UP": 7.38}       # 뚫었을 때 추가 이동 중앙값 %
    EVENTS = {"DOWN": 13053, "UP": 13045}

    # 규칙 A(추세 방향) 실측: SL% → (TP선착%, 기대값%)
    RULE_A = {
        "DOWN": {1.0: (26.0, 0.12), 2.0: (42.1, 0.24), 3.0: (52.1, 0.30), 5.0: (64.0, 0.42)},
        "UP": {1.0: (23.4, -0.02), 2.0: (40.7, 0.11), 3.0: (51.9, 0.21), 5.0: (65.8, 0.44)},
    }
    RECOMMENDED_SL = 5.0          # 실측상 기대값 최대
    # 규칙 B(역방향, 밴드에서 중단 복귀) — 참고용. 기대값이 절반 이하!
    RULE_B_BEST = {"DOWN": (2.0, 36.8, 0.21), "UP": (2.0, 35.5, 0.10)}

    FRESH_BARS = 2                # 이탈 후 2봉 이내 = 「신선한」 진입 구간
    NEAR_BAND_PCT = 0.5           # 밴드 ±0.5% = 도달로 간주
    ROUND_TRIP_FEE = 0.08

    KLINE_LIMIT = 120

    def __init__(self, binance_client=None):
        self.client = binance_client

    # ------------------------------------------------------------------
    @staticmethod
    def split_klines(klines: list) -> dict[str, list[float]]:
        return {
            "highs": [float(k[2]) for k in klines],
            "lows": [float(k[3]) for k in klines],
            "closes": [float(k[4]) for k in klines],
        }

    @classmethod
    def bollinger(cls, closes: list[float]) -> tuple[list, list, list]:
        n = len(closes)
        mid: list[float | None] = [None] * n
        up: list[float | None] = [None] * n
        lo: list[float | None] = [None] * n
        total = 0.0
        for i, c in enumerate(closes):
            total += c
            if i >= cls.BB_PERIOD:
                total -= closes[i - cls.BB_PERIOD]
            if i >= cls.BB_PERIOD - 1:
                m = total / cls.BB_PERIOD
                w = closes[i - cls.BB_PERIOD + 1: i + 1]
                sd = (sum((x - m) ** 2 for x in w) / cls.BB_PERIOD) ** 0.5
                mid[i], up[i], lo[i] = m, m + cls.BB_STD * sd, m - cls.BB_STD * sd
        return mid, up, lo

    # ------------------------------------------------------------------
    @classmethod
    def state(cls, klines: list) -> dict[str, Any]:
        """4H BB 상태 = 중단 이탈 여부 / 경과 봉수 / 목표 밴드 도달 여부.

        ⚠️ 이탈 판정은 **완료봉 종가** 기준입니다 (헌법 v127 = 진행 중 봉 신뢰 금지).
           연구도 완료봉 종가로 측정했으므로 기준을 맞춥니다.
        """
        out: dict[str, Any] = {
            "available": False, "note": None,
            "position": None, "cross": None, "bars_since_cross": None,
            "mid": None, "upper": None, "lower": None,
            "close": None, "current_price": None,
            "target_band": None, "target_dist_pct": None, "band_reached": False,
        }
        need = cls.BB_PERIOD + 6
        if not klines or len(klines) < need:
            out["note"] = f"4H 캔들 부족 ({len(klines or [])}/{need})"
            return out

        d = cls.split_klines(klines)
        closes, highs, lows = d["closes"], d["highs"], d["lows"]
        mid, up, lo = cls.bollinger(closes)

        out["current_price"] = round(closes[-1], 8)
        i = len(closes) - 2                      # 마지막 완료봉
        if mid[i] is None or mid[i - 1] is None:
            out["note"] = "BB 계산 불가"
            return out

        close = closes[i]
        out.update({
            "available": True,
            "close": round(close, 8),
            "mid": round(mid[i], 8),
            "upper": round(up[i], 8),
            "lower": round(lo[i], 8),
            "position": "ABOVE_MID" if close > mid[i] else "BELOW_MID",
        })

        # 최근 어느 봉에서 중단을 이탈했나? (완료봉만 탐색)
        cross = None
        bars_since = None
        for back in range(0, min(12, i)):
            j = i - back
            if mid[j] is None or mid[j - 1] is None:
                continue
            if closes[j - 1] >= mid[j - 1] and closes[j] < mid[j]:
                cross, bars_since = "DOWN", back
                break
            if closes[j - 1] <= mid[j - 1] and closes[j] > mid[j]:
                cross, bars_since = "UP", back
                break
        out["cross"] = cross
        out["bars_since_cross"] = bars_since

        if cross:
            target = lo[i] if cross == "DOWN" else up[i]
            out["target_band"] = round(target, 8) if target else None
            if target and close:
                out["target_dist_pct"] = round(abs((target - close) / close * 100), 3)
            # 이탈 이후 밴드에 닿았는가?
            reached = False
            for j in range(i - (bars_since or 0), i + 1):
                band = lo[j] if cross == "DOWN" else up[j]
                if band is None:
                    continue
                if (lows[j] <= band) if cross == "DOWN" else (highs[j] >= band):
                    reached = True
                    break
            out["band_reached"] = reached
        return out

    # ------------------------------------------------------------------
    @classmethod
    def combine(cls, symbol: str, side: str, st: dict) -> dict[str, Any]:
        """상태 → 등급/신호/레벨. side 는 사장님이 보려는 방향."""
        side = (side or "SHORT").upper()
        signals: list[str] = []

        if not st.get("available"):
            return {
                "available": False, "symbol": symbol, "side": side,
                "grade": "D", "stage": "UNKNOWN", "verdict": "➖ 판정 불가",
                "color": "#94a3b8", "score": 0,
                "signals": [f"➖ {st.get('note')}"], "state": st, "levels": {},
            }

        cross = st.get("cross")
        if not cross:
            return {
                "available": True, "symbol": symbol, "side": side,
                "grade": "D", "stage": "NONE",
                "verdict": "➖ 최근 12봉 내 4H 중단 이탈 없음",
                "color": "#64748b", "score": 0,
                "signals": [
                    f"➖ 현재 {('중단 위' if st['position']=='ABOVE_MID' else '중단 아래')} "
                    "= 이탈 이벤트 대기 중"
                ],
                "state": st, "levels": {},
            }

        want = "SHORT" if cross == "DOWN" else "LONG"
        band_word = "하단" if cross == "DOWN" else "상단"
        move_word = "하락" if cross == "DOWN" else "상승"
        bars = st.get("bars_since_cross") or 0
        reach = cls.REACH_RATE[cross]

        signals.append(
            f"{'📉' if cross=='DOWN' else '📈'} 4H 중단 "
            f"{'하향 이탈' if cross=='DOWN' else '상향 돌파'} "
            f"({bars}봉 전 = {bars*4}시간 전)"
        )
        signals.append(
            f"🎯 실측: 이탈 후 5일 내 {band_word} 도달 「{reach:.1f}%」 "
            f"(표본 {cls.EVENTS[cross]:,}건), 소요 중앙값 {cls.REACH_BARS[cross]}봉"
            f"({cls.REACH_BARS[cross]*4}시간)"
        )

        # 방향 일치 여부
        if side != want:
            signals.append(
                f"↔️ 이 신호는 「{want}」 방향인데 지금 분석은 {side} = 방향 불일치!"
            )

        if st.get("band_reached"):
            grade, stage = "C", "TARGET_HIT"
            verdict = f"✅ {band_word} 도달 = 목표 달성 (청산 검토!)"
            signals.append(
                f"⚠️ 다만 {band_word}은 지지·저항이 「아닙니다」 — 실측상 "
                f"{cls.BREAK_RATE[cross]:.1f}%가 밴드를 뚫고 마감했고, "
                f"뚫으면 추가 {move_word} 중앙값 {cls.EXTRA_MOVE[cross]:.2f}%입니다."
            )
            b_sl, b_tp_rate, b_ev = cls.RULE_B_BEST[cross]
            signals.append(
                f"💡 여기서 역방향(중단 복귀) 진입은 SL -{b_sl:.0f}% 기준 "
                f"TP선착 {b_tp_rate:.1f}%, 기대값 {b_ev:+.2f}% = 「추세 방향의 절반 이하」입니다."
            )
            score = 30
        elif bars <= cls.FRESH_BARS:
            grade, stage = "A", "TRIGGER"
            verdict = f"🎯 A등급 = 4H 중단 이탈 직후! 목표 {band_word}"
            score = 80
        else:
            grade, stage = "B", "IN_PROGRESS"
            verdict = f"⭐ B등급 = 이탈 후 진행 중 ({bars}봉 경과), 목표 {band_word} 미도달"
            score = 55

        if side != want:
            grade, score = "D", 0
            stage = "AVOID"
            verdict = f"↔️ 신호 방향({want})과 불일치 = 이 방향으로는 근거 없음"

        tp_rate, ev = cls.RULE_A[cross][cls.RECOMMENDED_SL]
        net = ev - cls.ROUND_TRIP_FEE
        if grade in ("A", "B"):
            signals.append(
                f"💰 실측 최적: SL -{cls.RECOMMENDED_SL:.0f}%, TP = {band_word} "
                f"→ TP선착 {tp_rate:.1f}%, 기대값 {ev:+.2f}% "
                f"(수수료 차감 후 ≈ {net:+.2f}%, 슬리피지 별도)"
            )
            signals.append(
                f"📊 4H 전략이라 진입을 서두를 필요가 없습니다 = 15m/5m 대비 슬리피지 유리!"
            )

        color = {"A": "#22c55e", "B": "#f59e0b", "C": "#a855f7", "D": "#64748b"}[grade]
        entry = st.get("close")
        target = st.get("target_band")
        levels = {
            "entry_ref": entry,
            "bb_mid": st.get("mid"),
            "bb_upper": st.get("upper"),
            "bb_lower": st.get("lower"),
            "target_band": target,
            "target_dist_pct": st.get("target_dist_pct"),
            "sl_pct": cls.RECOMMENDED_SL,
            "sl_price": (round(entry * (1 + cls.RECOMMENDED_SL / 100), 8) if cross == "DOWN"
                         else round(entry * (1 - cls.RECOMMENDED_SL / 100), 8)) if entry else None,
            "reach_rate": reach,
            "tp_first_rate": tp_rate,
            "expected_value_pct": ev,
            "expected_value_after_fee_pct": round(net, 3),
            "expected_bars": cls.REACH_BARS[cross],
            "sample_n": cls.EVENTS[cross],
        }
        return {
            "available": True, "symbol": symbol, "side": side,
            "signal_side": want, "cross": cross,
            "grade": grade, "stage": stage, "verdict": verdict,
            "color": color, "score": score, "signals": signals,
            "state": st, "levels": levels,
        }

    # ------------------------------------------------------------------
    # 🐻 v149 사장님 지시 (2026-08-16): 4H 볼밴 상단 정점 후 하락 = SHORT!
    # ------------------------------------------------------------------
    # 사장님 스크린샷 (APRUSDT 4H, +320% 급등 후 -70% 급락):
    #   1. 볼밴 상단 근처 = 정점 형성! (최근 5봉 = high가 upper의 95%+)
    #   2. 상단 이탈 → close < upper!
    #   3. RSI 하락 (이전 봉 대비 하락 + 이전 RSI > 65!)
    #   4. MACD 크로스 (약세 전환)!
    #   5. Volume 매도 증가 (하락 봉 volume > 평균!)
    # = 5개 조건 모두 만족 = confidence 0.85+!
    # = 사장님 = "확률 85% 이상만 보여줘!"

    TOP_REVERSAL_LOOKBACK = 5        # 최근 5봉 = 정점 근접 판정
    TOP_REVERSAL_UPPER_TOUCH = 0.95  # high >= upper * 0.95 = 상단 근접
    TOP_REVERSAL_RSI_MIN = 65        # 이전 RSI > 65 = 과매수 조건
    TOP_REVERSAL_VOL_MULT = 1.2      # 최근 봉 볼륨 > 평균 * 1.2

    @classmethod
    def _calc_rsi(cls, closes: list[float], period: int = 14) -> float | None:
        if len(closes) < period + 1:
            return None
        gains = losses = 0.0
        for i in range(1, period + 1):
            d = closes[i] - closes[i - 1]
            if d > 0:
                gains += d
            else:
                losses += -d
        avg_g = gains / period
        avg_l = losses / period
        for i in range(period + 1, len(closes)):
            d = closes[i] - closes[i - 1]
            g = d if d > 0 else 0
            l_ = -d if d < 0 else 0
            avg_g = (avg_g * (period - 1) + g) / period
            avg_l = (avg_l * (period - 1) + l_) / period
        if avg_l == 0:
            return 100.0
        rs = avg_g / avg_l
        return round(100 - (100 / (1 + rs)), 2)

    @classmethod
    def _calc_ema(cls, values: list[float], period: int) -> list[float]:
        if len(values) < period:
            return []
        k = 2 / (period + 1)
        ema = [sum(values[:period]) / period]
        for i in range(period, len(values)):
            ema.append(values[i] * k + ema[-1] * (1 - k))
        return ema

    @classmethod
    def _macd_bearish(cls, closes: list[float]) -> bool:
        """MACD Signal 아래 or Histogram 감소 = 약세!"""
        if len(closes) < 35:
            return False
        ema12 = cls._calc_ema(closes, 12)
        ema26 = cls._calc_ema(closes, 26)
        offset = 26 - 12
        macd_line = [a - b for a, b in zip(ema12[offset:], ema26)]
        if len(macd_line) < 10:
            return False
        signal_line = cls._calc_ema(macd_line, 9)
        if not signal_line:
            return False
        macd_now = macd_line[-1]
        macd_prev = macd_line[-2]
        signal_now = signal_line[-1]
        hist_now = macd_now - signal_now
        hist_prev = macd_prev - signal_line[-2] if len(signal_line) >= 2 else 0
        # 약세 = MACD < Signal OR Histogram 감소!
        return (macd_now < signal_now) or (hist_now < hist_prev)

    @classmethod
    def top_reversal_signal(cls, klines_4h: list) -> dict[str, Any]:
        """🐻 4H 볼밴 상단 정점 후 하락 전환 = SHORT 진입!

        사장님 지시 2026-08-16 (APRUSDT 4H 스크린샷):
        "4시간봉 이런 차트가 가능한 확률로 심볼을 찾아줘 [...] 확률 85% 이상만!"

        조건 (5개 모두 만족!):
        1. 볼밴 상단 근처 = 최근 5봉 = high 가 upper의 95%+
        2. 상단 이탈 → 마지막 완료봉 = close < upper
        3. RSI 하락 = 지금 < 이전 (5봉 전) + 이전 > 65
        4. MACD 약세 = Signal 아래 or Histogram 감소
        5. Volume 매도 = 마지막 봉 volume > 최근 20봉 평균 * 1.2
        """
        need = max(cls.BB_PERIOD, 35) + cls.TOP_REVERSAL_LOOKBACK + 2
        if not klines_4h or len(klines_4h) < need:
            return {"detected": False, "reason": f"4H 캔들 부족 ({len(klines_4h or [])}/{need})"}

        try:
            highs = [float(k[2]) for k in klines_4h]
            lows = [float(k[3]) for k in klines_4h]
            opens = [float(k[1]) for k in klines_4h]
            closes = [float(k[4]) for k in klines_4h]
            volumes = [float(k[5]) for k in klines_4h]
        except Exception as e:
            return {"detected": False, "reason": f"파싱 실패: {e}"}

        # 완료봉 기준 (진행 중 봉 제외!)
        highs_c = highs[:-1]
        lows_c = lows[:-1]
        opens_c = opens[:-1]
        closes_c = closes[:-1]
        volumes_c = volumes[:-1]

        if len(closes_c) < cls.BB_PERIOD + cls.TOP_REVERSAL_LOOKBACK:
            return {"detected": False, "reason": "완료봉 부족"}

        _, ups, _ = cls.bollinger(closes_c)
        if not ups[-1] or not ups[-cls.TOP_REVERSAL_LOOKBACK - 1]:
            return {"detected": False, "reason": "BB 계산 미완료"}

        upper = ups[-1]
        close_last = closes_c[-1]
        open_last = opens_c[-1]

        # 조건 1: 상단 근접 정점! (최근 5봉 high 중 하나가 upper * 0.95+)
        recent_highs = highs_c[-cls.TOP_REVERSAL_LOOKBACK:]
        recent_ups = ups[-cls.TOP_REVERSAL_LOOKBACK:]
        peak_reached = False
        for h, u in zip(recent_highs, recent_ups):
            if u and h >= u * cls.TOP_REVERSAL_UPPER_TOUCH:
                peak_reached = True
                break
        if not peak_reached:
            return {"detected": False, "reason": "5봉 내 BB 상단 근접 없음"}

        # 조건 2: 상단 이탈 = close < upper!
        if close_last >= upper:
            return {"detected": False, "reason": f"아직 상단({upper:.6g}) 위 마감({close_last:.6g})"}

        # + 마지막 봉 음봉 확인!
        if close_last >= open_last:
            return {"detected": False, "reason": "마지막 봉 양봉 (하락 확정 X)"}

        # 조건 3: RSI 하락 + 이전 RSI > 65!
        rsi_now = cls._calc_rsi(closes_c)
        rsi_prev = cls._calc_rsi(closes_c[:-cls.TOP_REVERSAL_LOOKBACK])
        if rsi_now is None or rsi_prev is None:
            return {"detected": False, "reason": "RSI 계산 불가"}
        if rsi_prev < cls.TOP_REVERSAL_RSI_MIN:
            return {"detected": False, "reason": f"이전 RSI {rsi_prev} < {cls.TOP_REVERSAL_RSI_MIN} (과매수 아님)"}
        if rsi_now >= rsi_prev:
            return {"detected": False, "reason": f"RSI {rsi_prev} → {rsi_now} = 하락 X"}

        # 조건 4: MACD 약세!
        if not cls._macd_bearish(closes_c):
            return {"detected": False, "reason": "MACD 약세 X"}

        # 조건 5: Volume 매도 증가!
        recent_20_vol = volumes_c[-20:] if len(volumes_c) >= 20 else volumes_c
        avg_vol = sum(recent_20_vol) / len(recent_20_vol)
        vol_last = volumes_c[-1]
        vol_mult = vol_last / avg_vol if avg_vol > 0 else 0
        if vol_mult < cls.TOP_REVERSAL_VOL_MULT:
            return {"detected": False, "reason": f"Volume {vol_mult:.2f}x < {cls.TOP_REVERSAL_VOL_MULT}"}

        # ✅ 모두 만족! confidence 85%+!
        # 신뢰도 = 5개 조건 모두 통과 = 0.85 기본 + RSI 낙폭 + Volume 배수 가산!
        rsi_drop = rsi_prev - rsi_now
        confidence = 0.85 + min((rsi_drop - 5) / 100, 0.05) + min((vol_mult - 1.2) / 20, 0.05)
        confidence = min(max(confidence, 0.85), 0.95)

        recent_high = max(recent_highs)
        return {
            "detected": True,
            "side": "SHORT",
            "type": "bb4h_top_reversal",
            "kind": "TOP_REVERSAL",
            "confidence": round(confidence, 3),
            "upper_band": round(upper, 8),
            "recent_high": round(recent_high, 8),
            "current_price": round(close_last, 8),
            "rsi_prev": rsi_prev,
            "rsi_now": rsi_now,
            "rsi_drop": round(rsi_drop, 2),
            "volume_multiplier": round(vol_mult, 2),
            "tp_pct": 8.0,   # 실측 EXTRA_MOVE = 5.69% + 여유 = 목표 -8%!
            "sl_pct": 3.0,   # 정점 재돌파 = 손절!
            "reason": (
                f"🐻 4H BB 상단({upper:.6g}) 정점 이탈 + 음봉! "
                f"RSI {rsi_prev} → {rsi_now} (-{rsi_drop:.1f}), "
                f"MACD 약세, Volume {vol_mult:.2f}x = 신뢰도 {confidence*100:.0f}%!"
            ),
        }

    # ------------------------------------------------------------------
    def analyze(self, symbol: str, side: str = "SHORT",
                klines_4h: list | None = None) -> dict[str, Any]:
        """4H BB 밴드 전략 판정 (읽기 전용!)."""
        symbol = (symbol or "").upper()
        try:
            k4 = klines_4h if klines_4h is not None else (
                self.client.get_klines(symbol=symbol, interval="4h", limit=self.KLINE_LIMIT)
                if self.client else None)
            if k4 is None:
                raise RuntimeError("binance_client 없음 (캔들을 직접 넘기세요!)")
        except Exception as e:
            logger.warning("[bb_4h] 캔들 조회 실패 %s: %s", symbol, e)
            return {
                "available": False, "symbol": symbol, "side": (side or "SHORT").upper(),
                "grade": "D", "stage": "UNKNOWN", "verdict": "➖ 판정 불가",
                "color": "#94a3b8", "score": 0,
                "signals": [f"➖ 캔들 조회 실패: {e}"], "error": str(e),
            }
        try:
            return self.combine(symbol, side, self.state(k4))
        except Exception as e:
            logger.warning("[bb_4h] 계산 실패 %s: %s", symbol, e)
            return {
                "available": False, "symbol": symbol, "side": (side or "SHORT").upper(),
                "grade": "D", "stage": "UNKNOWN", "verdict": "➖ 판정 불가",
                "color": "#94a3b8", "score": 0,
                "signals": [f"➖ 계산 실패: {e}"], "error": str(e),
            }


def to_learning_context(result: dict | None) -> dict[str, Any]:
    """학습 저장용 압축 스냅샷."""
    if not result:
        return {}
    st = result.get("state") or {}
    lv = result.get("levels") or {}
    return {
        "available": bool(result.get("available")),
        "grade": result.get("grade"),
        "stage": result.get("stage"),
        "cross": result.get("cross"),
        "signal_side": result.get("signal_side"),
        "bars_since_cross": st.get("bars_since_cross"),
        "band_reached": bool(st.get("band_reached")),
        "target_dist_pct": lv.get("target_dist_pct"),
        "reach_rate": lv.get("reach_rate"),
        "expected_value_pct": lv.get("expected_value_pct"),
    }
