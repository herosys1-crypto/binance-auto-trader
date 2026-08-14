"""🔺 15분봉 「최상단(천장)」 예측 + 볼밴 중단 전략 (v140 신!)

spec: docs/BB_TOP_15M_STRATEGY_SPEC.md
사장님 지시 2026-08-14:
  "15분봉 최상단과 볼밴 중단을 기준으로 매매 / 1시간 4시간은 보조역할 /
   15분봉 최상단을 예측하는 시스템으로 학습 /
   macd obv rsi vol 이렇게 같이 분석하면 정확도가 가장높은것 같아 같이 사용해줘"

⚠️ v137/v138 과 근본적으로 다릅니다:
  - v137(EMA/VCP) / v138(SAR/구름대) = **4H가 최상위 거부권**을 가짐
  - v140(이 파일)                    = **15m이 주도**, 1H/4H는 **가중치만** (거부권 X!)

🔬 임계값은 추측이 아니라 실측입니다 (scripts/study_15m_top_bbmid.py):
  **181심볼 × 478,435개 15m 캔들**에서 「천장」을 라벨링하고 각 신호의 적중률을 측정.
  (천장 = 앞뒤 8봉 최고 AND 이후 8봉 내 -1.5% 이상 하락. 기저 발생률 3.23%)

  → 사장님 4대 지표(MACD/OBV/RSI/Vol) 가설은 **맞았지만 쓰는 법이 갈렸습니다**:
      · 단순 임계값 조합 (RSI≥70 + MACD꺾임 + OBV하락 + Vol감소)
          2개 이상 = 2.49% (**0.77배 = base보다 나쁨!**)
      · **다이버전스 조합** (가격은 신고가인데 지표는 못 따라옴)
          2개 이상 = 28.14% (**8.70배**)

  실측 단독 적중률 (base 3.23%):
      RSI 다이버전스   29.66%  (9.17배)   ← 최강
      OBV 다이버전스   28.46%  (8.80배)
      MACD 다이버전스  25.54%  (7.90배)
      BB 상단 고가터치 13.84%  (4.28배)
      윗꼬리 ≥50%      6.90%  (2.13배)
      RSI ≥ 70        10.32%  (3.19배)
      Volume 정점후감소 2.05%  (**0.63배 = 역효과**)
      OBV 5봉 하락      1.25%  (**0.39배 = 역효과**)

  최적 조합:
      다이버전스 3개 AND BB상단터치        = **38.54% (11.92배)** ← 최고
      다이버전스 2개+ AND BB터치 AND 윗꼬리 = 37.25% (11.52배)
      다이버전스 2개+ AND BB상단터치        = 32.19% ( 9.95배)
      ⚠️ 여기에 RSI≥70 을 더하면 21.62% 로 **떨어짐** (과매수 필터는 방해!)
      ⚠️ %B≥1.0(종가 돌파)도 21.63% 로 떨어짐 (고가 터치가 맞고 종가 돌파는 늦음!)

  1H·4H 보조 효과 = **거의 없음** (32.19% → 32~34%). 사장님이 「보조 역할」로 하라신 게
  데이터적으로도 정확했습니다. → 가중치 ±5점만.

✅ **구현 검증 완료** (scripts/validate_bb_top_analyzer.py, 표본 24,980 / 심볼 70):
      S등급 37.16% (11.28배)   ← 연구값 38.5% 재현
      A등급 34.23% (10.39배)   ← 연구값 32.2% 재현
      B등급 16.27% ( 4.94배)   (다이버전스 2개인데 BB 미터치 = 약한 하위집합)
      C등급 15.68% ( 4.76배)
      D등급  2.23% ( 0.68배)   ← 기저(3.29%) 이하 = 제대로 걸러냄!
  = 연구 스크립트와 서비스 코드가 따로 놀지 않음을 확인했습니다 (헌법 4번).

헌법 v140:
  '천장은 과매수가 아니라 **다이버전스**가 만든다. 지표 수치보다 가격과의 괴리를 봐라!'
  '볼밴 중단은 목표지 지지선이 아니다 (실측: 도달 후 이탈 47.2% vs 반등 18.3%)'
  '15m이 주도하고 1H/4H는 가중치만 준다 — 상위 추세에 거부권을 주지 마라!'
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class BBTopAnalyzer:
    """15m 천장 예측 + BB 중단 레벨 산출. 1H/4H는 보조 가중치."""

    # --- 볼린저밴드 ---
    BB_PERIOD = 20
    BB_STD = 2.0
    # --- RSI / MACD ---
    RSI_PERIOD = 14
    RSI_OVERBOUGHT = 70      # 참고 표시용 (점수에는 안 씀 — 실측상 방해!)
    MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
    # --- 다이버전스 탐색 구간 (직전 고점/저점을 찾는 범위) ---
    DIV_LOOKBACK = 20
    # --- 윗꼬리 / 아랫꼬리 ---
    WICK_RATIO = 0.5
    # --- 거래량 (참고용) ---
    VOL_MA = 20
    VOL_SPIKE = 1.5
    # --- 상위 타임프레임(보조) 추세 ---
    HTF_FAST, HTF_SLOW = 20, 50

    # --- 점수 배분 (실측 lift 비례 — 합계 100) ---
    W_DIV_RSI = 25       # 9.17배
    W_DIV_OBV = 24       # 8.80배
    W_DIV_MACD = 21      # 7.90배
    W_BB_TOUCH = 15      # 4.28배 (조합 시 +3%p)
    W_WICK = 10          # 2.13배 (조합 시 +5%p)
    W_HTF = 5            # 보조 = 실측상 효과 미미!

    # --- BB 중단 실측 통계 (사장님께 그대로 보여줍니다) ---
    MID_REACH_RATE = 99.7      # 천장 후 8시간 내 BB중단 도달률 %
    MID_MEDIAN_BARS = 2        # 도달까지 중앙값 봉수 (=30분)
    MID_MEDIAN_DROP = -1.84    # 천장→BB중단 하락폭 중앙값 %
    MID_BREAK_RATE = 47.2      # BB중단 도달 후 이탈 %
    MID_BOUNCE_RATE = 18.3     # BB중단 도달 후 반등 %
    MID_NEAR_PCT = 0.5         # 현재가가 BB중단 ±0.5% 이내 = 「도달」로 간주

    KLINE_LIMIT = 200   # 15m 200봉 = 50시간 (BB20 + MACD26 + 다이버전스 20 여유)

    def __init__(self, binance_client=None):
        self.client = binance_client

    # ------------------------------------------------------------------
    # 지표 (analysis.py 와 동일 계산식 = 헌법 6번 단일 진실)
    # ------------------------------------------------------------------
    @staticmethod
    def split_klines(klines: list) -> dict[str, list[float]]:
        return {
            "opens": [float(k[1]) for k in klines],
            "highs": [float(k[2]) for k in klines],
            "lows": [float(k[3]) for k in klines],
            "closes": [float(k[4]) for k in klines],
            "volumes": [float(k[5]) for k in klines],
        }

    @staticmethod
    def sma(values: list[float], period: int) -> list[float | None]:
        out: list[float | None] = [None] * len(values)
        total = 0.0
        for i, v in enumerate(values):
            total += v
            if i >= period:
                total -= values[i - period]
            if i >= period - 1:
                out[i] = total / period
        return out

    @staticmethod
    def ema(values: list[float], period: int) -> list[float | None]:
        out: list[float | None] = [None] * len(values)
        if len(values) < period or period <= 0:
            return out
        k = 2.0 / (period + 1)
        prev = sum(values[:period]) / period
        out[period - 1] = prev
        for i in range(period, len(values)):
            prev = values[i] * k + prev * (1 - k)
            out[i] = prev
        return out

    @classmethod
    def bollinger(cls, closes: list[float]) -> tuple[list, list, list]:
        """볼린저밴드 (20, 2σ) → (중단, 상단, 하단)."""
        mid = cls.sma(closes, cls.BB_PERIOD)
        upper: list[float | None] = [None] * len(closes)
        lower: list[float | None] = [None] * len(closes)
        for i in range(len(closes)):
            if mid[i] is None:
                continue
            window = closes[i - cls.BB_PERIOD + 1: i + 1]
            m = mid[i]
            sd = (sum((c - m) ** 2 for c in window) / cls.BB_PERIOD) ** 0.5
            upper[i] = m + cls.BB_STD * sd
            lower[i] = m - cls.BB_STD * sd
        return mid, upper, lower

    @classmethod
    def rsi(cls, closes: list[float]) -> list[float | None]:
        p = cls.RSI_PERIOD
        out: list[float | None] = [None] * len(closes)
        if len(closes) < p + 1:
            return out
        gain = loss = 0.0
        for i in range(1, p + 1):
            d = closes[i] - closes[i - 1]
            gain += max(d, 0.0)
            loss += max(-d, 0.0)
        ag, al = gain / p, loss / p
        out[p] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
        for i in range(p + 1, len(closes)):
            d = closes[i] - closes[i - 1]
            ag = (ag * (p - 1) + max(d, 0.0)) / p
            al = (al * (p - 1) + max(-d, 0.0)) / p
            out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
        return out

    @classmethod
    def macd_hist(cls, closes: list[float]) -> list[float | None]:
        """MACD 히스토그램 (12/26/9) — 입력과 길이 동일."""
        e_fast = cls.ema(closes, cls.MACD_FAST)
        e_slow = cls.ema(closes, cls.MACD_SLOW)
        line: list[float | None] = [None] * len(closes)
        for i in range(len(closes)):
            if e_fast[i] is not None and e_slow[i] is not None:
                line[i] = e_fast[i] - e_slow[i]
        idx = [i for i, v in enumerate(line) if v is not None]
        hist: list[float | None] = [None] * len(closes)
        if len(idx) < cls.MACD_SIGNAL:
            return hist
        signal = cls.ema([line[i] for i in idx], cls.MACD_SIGNAL)
        for j, i in enumerate(idx):
            if signal[j] is not None:
                hist[i] = line[i] - signal[j]
        return hist

    @staticmethod
    def obv(closes: list[float], volumes: list[float]) -> list[float]:
        out = [0.0] * len(closes)
        for i in range(1, len(closes)):
            if closes[i] > closes[i - 1]:
                out[i] = out[i - 1] + volumes[i]
            elif closes[i] < closes[i - 1]:
                out[i] = out[i - 1] - volumes[i]
            else:
                out[i] = out[i - 1]
        return out

    # ------------------------------------------------------------------
    # 상위 타임프레임 = 보조 (거부권 없음!)
    # ------------------------------------------------------------------
    @classmethod
    def htf_trend(cls, klines: list) -> dict[str, Any]:
        """1H/4H 추세 = EMA20 vs EMA50 (보조 가중치용)."""
        out: dict[str, Any] = {"available": False, "trend": None, "gap_pct": None}
        if not klines or len(klines) < cls.HTF_SLOW + 2:
            return out
        closes = cls.split_klines(klines)["closes"]
        fast = cls.ema(closes, cls.HTF_FAST)
        slow = cls.ema(closes, cls.HTF_SLOW)
        f, s = fast[-1], slow[-1]
        if f is None or s is None or s <= 0:
            return out
        gap = (f - s) / s * 100
        trend = "UP" if gap > 0.1 else ("DOWN" if gap < -0.1 else "FLAT")
        out.update({"available": True, "trend": trend, "gap_pct": round(gap, 3)})
        return out

    # ------------------------------------------------------------------
    # 15m 주 분석 = 천장(SHORT) / 바닥(LONG) 다이버전스
    # ------------------------------------------------------------------
    @classmethod
    def analyze_15m(cls, klines: list, side: str = "SHORT") -> dict[str, Any]:
        """15m 천장/바닥 판정 (**진행 중 봉 포함** = 실시간 포착).

        side="SHORT" → 천장 탐지 (가격 신고가 vs 지표 하락 = 약세 다이버전스)
        side="LONG"  → 바닥 탐지 (가격 신저가 vs 지표 상승 = 강세 다이버전스)

        ⚠️ 실측 검증은 **천장(SHORT) 쪽만** 되어 있습니다.
           바닥은 헌법 5번(대칭성)에 따라 같은 구조로 구현했지만 미검증입니다.
        """
        out: dict[str, Any] = {
            "available": False, "side": side, "note": None,
            "div_rsi": False, "div_macd": False, "div_obv": False, "div_count": 0,
            "bb_touch": False, "wick": False, "wick_ratio": None,
            "rsi": None, "macd_hist": None, "vol_ratio": None,
            "bb_mid": None, "bb_upper": None, "bb_lower": None,
            "price": None, "pct_b": None,
        }
        need = cls.BB_PERIOD + cls.MACD_SLOW + cls.MACD_SIGNAL + cls.DIV_LOOKBACK
        if not klines or len(klines) < need:
            out["note"] = f"15m 캔들 부족 ({len(klines or [])}/{need})"
            return out

        d = cls.split_klines(klines)
        opens, highs, lows = d["opens"], d["highs"], d["lows"]
        closes, vols = d["closes"], d["volumes"]
        i = len(closes) - 1

        mid, upper, lower = cls.bollinger(closes)
        rsi_s = cls.rsi(closes)
        hist_s = cls.macd_hist(closes)
        obv_s = cls.obv(closes, vols)
        vol_ma = cls.sma(vols, cls.VOL_MA)

        if mid[i] is None or upper[i] is None or rsi_s[i] is None or hist_s[i] is None:
            out["note"] = "15m 지표 계산 불가"
            return out

        is_top = side.upper() != "LONG"

        # --- 직전 극점 (다이버전스 비교 기준) ---
        lo_idx = max(0, i - cls.DIV_LOOKBACK)
        window = range(lo_idx, i)
        if is_top:
            ref = max(window, key=lambda x: highs[x])
            price_extreme = highs[i] > highs[ref]      # 가격 신고가
        else:
            ref = min(window, key=lambda x: lows[x])
            price_extreme = lows[i] < lows[ref]        # 가격 신저가

        def _div(series, ref_idx: int) -> bool:
            """가격은 신고(저)가인데 지표는 못 따라옴 = 다이버전스."""
            a, b = series[i], series[ref_idx]
            if a is None or b is None or not price_extreme:
                return False
            return a < b if is_top else a > b

        div_rsi = _div(rsi_s, ref)
        div_macd = _div(hist_s, ref)
        div_obv = _div(obv_s, ref)

        # --- 볼밴 / 꼬리 / 거래량 ---
        rng = highs[i] - lows[i]
        body_top = max(opens[i], closes[i])
        body_bot = min(opens[i], closes[i])
        if is_top:
            bb_touch = highs[i] > upper[i]                       # 고가 터치! (종가 X)
            wick_ratio = (highs[i] - body_top) / rng if rng > 0 else 0.0
        else:
            bb_touch = lows[i] < lower[i]
            wick_ratio = (body_bot - lows[i]) / rng if rng > 0 else 0.0

        band = upper[i] - lower[i]
        pct_b = (closes[i] - lower[i]) / band if band > 0 else 0.5
        vr = (vols[i] / vol_ma[i]) if vol_ma[i] else None

        out.update({
            "available": True,
            "div_rsi": div_rsi, "div_macd": div_macd, "div_obv": div_obv,
            "div_count": sum((div_rsi, div_macd, div_obv)),
            "price_extreme": price_extreme,
            "bb_touch": bool(bb_touch),
            "wick": bool(wick_ratio >= cls.WICK_RATIO),
            "wick_ratio": round(wick_ratio, 3),
            "rsi": round(rsi_s[i], 2),
            "macd_hist": round(hist_s[i], 8),
            "vol_ratio": round(vr, 2) if vr else None,
            "bb_mid": round(mid[i], 8),
            "bb_upper": round(upper[i], 8),
            "bb_lower": round(lower[i], 8),
            "price": round(closes[i], 8),
            "pct_b": round(pct_b, 3),
        })
        return out

    # ------------------------------------------------------------------
    # 볼밴 중단 상태 = 목표(TP)이자 관문
    # ------------------------------------------------------------------
    @classmethod
    def bb_mid_state(cls, r15: dict, side: str) -> dict[str, Any]:
        """현재가와 BB 중단의 관계 → 목표 거리 / 도달 여부.

        실측: 천장 후 **99.7%가 8시간 내 BB중단 도달** (중앙값 30분, -1.84%).
              단, 도달 후에는 **이탈 47.2% > 반등 18.3%** = 지지선이 아님!
        """
        out: dict[str, Any] = {
            "available": False, "position": None, "dist_pct": None,
            "reached": False, "target_pct": None,
        }
        if not r15.get("available"):
            return out
        price = r15["price"]
        mid = r15["bb_mid"]
        if not price or not mid:
            return out

        dist = (price - mid) / mid * 100
        if abs(dist) <= cls.MID_NEAR_PCT:
            position = "AT_MID"
        elif dist > 0:
            position = "ABOVE_MID"
        else:
            position = "BELOW_MID"

        out.update({
            "available": True,
            "position": position,
            "dist_pct": round(dist, 3),
            "reached": position == "AT_MID",
            # SHORT는 아래로, LONG은 위로 = 중단까지의 기대 수익률
            "target_pct": round(abs(dist), 3),
        })
        return out

    # ------------------------------------------------------------------
    # 종합 = 등급 / 점수 / 레벨
    # ------------------------------------------------------------------
    @classmethod
    def combine(
        cls,
        symbol: str,
        side: str,
        r15: dict,
        mid_state: dict,
        htf_1h: dict,
        htf_4h: dict,
    ) -> dict[str, Any]:
        """15m 주도 + 1H/4H 보조 → 천장(바닥) 등급 S/A/B/C/D."""
        signals: list[str] = []
        score = 0
        is_top = side.upper() != "LONG"
        word = "천장" if is_top else "바닥"
        div_word = "약세" if is_top else "강세"

        if not r15.get("available"):
            return {
                "available": False, "symbol": symbol, "side": side,
                "grade": "D", "stage": "UNKNOWN",
                "verdict": "➖ 데이터 부족 = 판정 불가", "color": "#94a3b8",
                "score": 0, "signals": [f"➖ {r15.get('note')}"],
                "tf_15m": r15, "bb_mid": mid_state,
                "tf_1h": htf_1h, "tf_4h": htf_4h, "levels": {},
            }

        n_div = r15["div_count"]

        # --- 1) 다이버전스 = 주력 (실측 lift 8~9배) ---
        if r15["div_rsi"]:
            score += cls.W_DIV_RSI
            signals.append(f"🔺 RSI {div_word} 다이버전스! (실측 적중 29.7% = 9.2배)")
        if r15["div_obv"]:
            score += cls.W_DIV_OBV
            signals.append(f"🔺 OBV {div_word} 다이버전스! (실측 적중 28.5% = 8.8배)")
        if r15["div_macd"]:
            score += cls.W_DIV_MACD
            signals.append(f"🔺 MACD {div_word} 다이버전스! (실측 적중 25.5% = 7.9배)")
        if n_div == 0:
            if r15.get("price_extreme"):
                signals.append(
                    f"➖ 가격은 신{'고' if is_top else '저'}가지만 지표가 함께 감 = 아직 {word} 아님!"
                )
            else:
                signals.append(f"➖ 최근 20봉 신{'고' if is_top else '저'}가 아님 = {word} 신호 없음")

        # --- 2) 볼밴 상단/하단 터치 ---
        if r15["bb_touch"]:
            score += cls.W_BB_TOUCH
            band = "상단" if is_top else "하단"
            signals.append(f"📊 BB {band} 고가 터치! (다이버전스와 결합 시 적중 38.5% = 11.9배)")
        elif r15.get("pct_b") is not None:
            signals.append(f"➖ BB {'상' if is_top else '하'}단 미터치 (%B {r15['pct_b']})")

        # --- 3) 꼬리 = 반대 압력 ---
        if r15["wick"]:
            score += cls.W_WICK
            tail = "윗꼬리" if is_top else "아랫꼬리"
            signals.append(f"🕯 {tail} {r15['wick_ratio']*100:.0f}% = 반대 압력 확인!")

        # --- 4) 1H / 4H = 보조 (거부권 없음!) ---
        want = "DOWN" if is_top else "UP"
        htf_help = 0
        for label, htf in (("1H", htf_1h), ("4H", htf_4h)):
            if not htf.get("available"):
                continue
            if htf["trend"] == want:
                htf_help += 1
                signals.append(f"🤝 {label} 추세 {htf['trend']} = {word} 방향 지원 (보조)")
            elif htf["trend"] != "FLAT":
                signals.append(f"↔️ {label} 추세 {htf['trend']} = 반대지만 「거부권 없음」 (보조!)")
        if htf_help:
            score += cls.W_HTF if htf_help >= 2 else cls.W_HTF // 2
            signals.append(
                "ℹ️ 실측상 1H/4H 보조 효과는 미미합니다 (32.2% → 33~34%). 참고용입니다."
            )

        # --- 참고 지표 (점수 X — 실측상 방해!) ---
        if r15.get("rsi") is not None:
            over = r15["rsi"] >= cls.RSI_OVERBOUGHT if is_top else r15["rsi"] <= 30
            if over:
                signals.append(
                    f"ℹ️ RSI {r15['rsi']} {'과매수' if is_top else '과매도'} — "
                    "단, 실측상 이 조건을 추가하면 적중률이 32%→22%로 떨어져 점수엔 반영 안 합니다!"
                )

        # --- 등급 (실측 적중률 구간 그대로) ---
        # 등급별 실측 적중률 = 구현 검증(24,980 표본) 값 기준!
        # (기저 3.29% 대비 배수. scripts/validate_bb_top_analyzer.py 로 재현 가능)
        if n_div >= 3 and r15["bb_touch"]:
            grade, stage = "S", "TRIGGER"
            verdict = f"🔥 S등급 {word}! (검증 적중 37.2% = 11.3배)"
        elif n_div >= 2 and r15["bb_touch"]:
            grade, stage = "A", "TRIGGER"
            verdict = f"🎯 A등급 {word}! (검증 적중 34.2% = 10.4배)"
        elif n_div >= 2:
            grade, stage = "B", "WATCH"
            verdict = f"⭐ B등급 = 다이버전스 {n_div}개인데 BB 미터치 (검증 적중 16.3%)"
        elif n_div >= 1:
            grade, stage = "C", "WATCH"
            verdict = "👀 C등급 = 다이버전스 1개 (검증 적중 15.7%)"
        else:
            grade, stage = "D", "NONE"
            verdict = f"➖ D등급 = {word} 신호 없음 (검증 적중 2.2% = 기저 이하!)"

        color = {"S": "#a855f7", "A": "#22c55e", "B": "#f59e0b",
                 "C": "#94a3b8", "D": "#64748b"}[grade]

        # --- 레벨 = BB 중단이 1차 목표! ---
        levels = {
            "entry_ref": r15["price"],
            "bb_mid": r15["bb_mid"],           # 🎯 TP1 (실측 도달률 99.7%)
            "bb_upper": r15["bb_upper"],
            "bb_lower": r15["bb_lower"],       # TP2 (중단 이탈 시)
            "tp1_target_pct": mid_state.get("target_pct"),
            "stop_ref": r15["bb_upper"] if is_top else r15["bb_lower"],
            "expected_bars_to_mid": cls.MID_MEDIAN_BARS,
            "expected_drop_pct": cls.MID_MEDIAN_DROP if is_top else -cls.MID_MEDIAN_DROP,
        }

        # --- BB 중단 안내 (지지선 아님을 명확히!) ---
        pos = mid_state.get("position")
        if pos == "AT_MID":
            signals.append(
                f"🎯 현재가가 「BB 중단 도달」! 실측 → 여기서 이탈 {cls.MID_BREAK_RATE}% vs "
                f"반등 {cls.MID_BOUNCE_RATE}% = 지지선이 아닙니다! 절반만 익절 권장!"
            )
        elif grade in ("S", "A"):
            signals.append(
                f"🎯 1차 목표 = BB 중단 {r15['bb_mid']} "
                f"(현재가 대비 {mid_state.get('target_pct')}%, 실측 중앙값 {cls.MID_MEDIAN_BARS}봉≈30분)"
            )

        return {
            "available": True,
            "symbol": symbol,
            "side": side.upper(),
            "grade": grade,
            "stage": stage,
            "verdict": verdict,
            "color": color,
            "score": min(score, 100),
            "div_count": n_div,
            "signals": signals,
            "tf_15m": r15,
            "bb_mid": mid_state,
            "tf_1h": htf_1h,
            "tf_4h": htf_4h,
            "levels": levels,
        }

    # ------------------------------------------------------------------
    # 진입점
    # ------------------------------------------------------------------
    def _fetch(self, symbol: str, interval: str, limit: int) -> list:
        if self.client is None:
            raise RuntimeError("binance_client 없음 (캔들을 직접 넘기세요!)")
        return self.client.get_klines(symbol=symbol, interval=interval, limit=limit)

    def _fail(self, symbol: str, side: str, msg: str) -> dict[str, Any]:
        return {
            "available": False, "symbol": symbol, "side": side.upper(),
            "grade": "D", "stage": "UNKNOWN", "verdict": "➖ 판정 불가",
            "color": "#94a3b8", "score": 0, "signals": [f"➖ {msg}"], "error": msg,
        }

    def analyze(
        self,
        symbol: str,
        side: str = "SHORT",
        klines_15m: list | None = None,
        klines_1h: list | None = None,
        klines_4h: list | None = None,
    ) -> dict[str, Any]:
        """15m 천장/바닥 종합 분석 (읽기 전용!). 예외 = available=False."""
        symbol = (symbol or "").upper()
        side = (side or "SHORT").upper()
        try:
            # ⚠️ `is not None` 으로 판정! (빈 리스트 = 「데이터 없음」이지
            #    「조회해와라」가 아님 — 예상 못 한 네트워크 호출 방지!)
            k15 = klines_15m if klines_15m is not None else self._fetch(symbol, "15m", self.KLINE_LIMIT)
            k1 = klines_1h if klines_1h is not None else self._fetch(symbol, "1h", 120)
            k4 = klines_4h if klines_4h is not None else self._fetch(symbol, "4h", 120)
        except Exception as e:
            logger.warning("[bb_top] 캔들 조회 실패 %s: %s", symbol, e)
            return self._fail(symbol, side, f"캔들 조회 실패: {e}")

        try:
            r15 = self.analyze_15m(k15, side)
            return self.combine(
                symbol, side, r15,
                self.bb_mid_state(r15, side),
                self.htf_trend(k1), self.htf_trend(k4),
            )
        except Exception as e:
            logger.warning("[bb_top] 계산 실패 %s: %s", symbol, e)
            return self._fail(symbol, side, f"계산 실패: {e}")


def to_learning_context(result: dict | None) -> dict[str, Any]:
    """학습 저장용 압축 스냅샷."""
    if not result:
        return {}
    r15 = result.get("tf_15m") or {}
    mid = result.get("bb_mid") or {}
    return {
        "available": bool(result.get("available")),
        "grade": result.get("grade"),
        "stage": result.get("stage"),
        "score": result.get("score"),
        "div_count": result.get("div_count"),
        "div_rsi": bool(r15.get("div_rsi")),
        "div_macd": bool(r15.get("div_macd")),
        "div_obv": bool(r15.get("div_obv")),
        "bb_touch": bool(r15.get("bb_touch")),
        "wick": bool(r15.get("wick")),
        "rsi": r15.get("rsi"),
        "bb_mid_position": mid.get("position"),
        "bb_mid_dist_pct": mid.get("dist_pct"),
        "trend_1h": (result.get("tf_1h") or {}).get("trend"),
        "trend_4h": (result.get("tf_4h") or {}).get("trend"),
        "levels": result.get("levels") or {},
    }
