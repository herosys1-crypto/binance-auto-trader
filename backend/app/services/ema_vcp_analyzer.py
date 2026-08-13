"""📐 EMA + VCP 멀티 타임프레임 분석 (v137 신!)

spec: docs/EMA_VCP_MTF_STRATEGY_SPEC.md
사장님 요청 2026-08-14 (유튜브 「쿨라매기 이동평균선 매매전략」 정리 자료).

로직 (4H 나침반 → 1H 작전지도 → 15m 방아쇠):
  1. 4H  = EMA50 추세 필터 (역방향 = 진입 금지!)
  2. 1H  = 정배열 + VCP(변동성 수축) + 거래량 고갈 + 돌파선 확정
  3. 15m = 돌파 + 거래량 폭발 = 방아쇠 + 손절선/익절 기준 산출

= **읽기 전용 분석!** 주문 X (사장님 판단 보조 + 학습 저장 전용!)

산출 = 셋업 등급 (A/B/C/D):
  A = 지금 방아쇠! (4H 추세 + 1H 셋업 완성 + 15m 돌파+거래량)
  B = 셋업 완성, 돌파 대기!
  C = 4H 추세만 OK = 관망!
  D = 4H 역방향 = 진입 금지!

헌법 v137:
  'EMA/VCP 셋업 등급 = 진입 시 학습 저장 → 등급별 실제 승률로 검증!'
  (= 남의 매매법도 우리 데이터로 검증해서 쓴다!)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class EMAVCPAnalyzer:
    """EMA 정배열 + VCP 수축 + 돌파 = 멀티 타임프레임 셋업 판정."""

    # --- 이동평균 ---
    EMA_FAST = 10
    EMA_MID = 20
    EMA_SLOW = 50

    # --- 4H 나침반 ---
    SLOPE_LOOKBACK = 5          # EMA50 기울기 = 5봉 전 대비
    SLOPE_FLAT_PCT = 0.1        # ±0.1% 미만 = 횡보 취급

    # --- 1H 작전지도 ---
    VCP_WINDOW = 18             # 최근 18봉 = 3구간 × 6봉
    VCP_SEGMENTS = 3
    VCP_CONTRACT_RATIO = 0.66   # 마지막 구간 ≤ 첫 구간 × 0.66 = 수축 인정
    VOL_DRY_RATIO = 0.8         # 최근 6봉 평균 ≤ 이전 12봉 평균 × 0.8 = 거래량 고갈
    PIVOT_LOOKBACK = 20         # 돌파선 = 최근 20 완료봉 고점/저점
    RALLY_LOOKBACK = 40         # 「첫 반등 무시」 = EMA20 교차 횟수 집계 구간

    # --- 15m 방아쇠 ---
    VOL_SPIKE_RATIO = 1.5       # 돌파봉 거래량 ≥ 최근 평균 × 1.5 = 폭발
    VOL_SPIKE_BASE = 20         # 거래량 평균 기준 봉 수
    SWING_LOOKBACK = 10         # 손절 = 최근 10 완료봉 스윙 로우/하이

    # --- 캔들 요청 개수 ---
    KLINE_LIMIT = 120

    def __init__(self, binance_client=None):
        """
        Args:
            binance_client: BinanceClient (get_klines 지원). 캔들을 직접
                넘겨서 계산만 할 거면 None 가능 (= 순수 계산 모드!).
        """
        self.client = binance_client

    # ------------------------------------------------------------------
    # 순수 계산 (네트워크 X = 테스트 가능!)
    # ------------------------------------------------------------------
    @staticmethod
    def ema_series(values: list[float], period: int) -> list[float | None]:
        """EMA 시리즈 (입력과 길이 동일, 앞부분은 None).

        시드 = 첫 period개의 SMA (일반 차트 툴과 동일 방식!).
        """
        n = len(values)
        out: list[float | None] = [None] * n
        if period <= 0 or n < period:
            return out
        k = 2.0 / (period + 1)
        prev = sum(values[:period]) / period
        out[period - 1] = prev
        for i in range(period, n):
            prev = values[i] * k + prev * (1 - k)
            out[i] = prev
        return out

    @staticmethod
    def split_klines(klines: list) -> dict[str, list[float]]:
        """Binance kline → OHLCV 리스트.

        kline = [open_time, open, high, low, close, volume, close_time, ...]
        """
        return {
            "opens": [float(k[1]) for k in klines],
            "highs": [float(k[2]) for k in klines],
            "lows": [float(k[3]) for k in klines],
            "closes": [float(k[4]) for k in klines],
            "volumes": [float(k[5]) for k in klines],
        }

    @staticmethod
    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    @classmethod
    def _range_pct(cls, highs: list[float], lows: list[float], closes: list[float]) -> float:
        """구간 변동폭 % = (최고가 - 최저가) / 평균 종가 × 100."""
        if not highs or not lows or not closes:
            return 0.0
        base = cls._mean(closes)
        if base <= 0:
            return 0.0
        return (max(highs) - min(lows)) / base * 100

    @classmethod
    def _rally_count(
        cls,
        closes: list[float],
        ema20: list[float | None],
        side: str,
        lookback: int,
    ) -> int:
        """EMA20 교차 횟수 = 지금이 몇 번째 파동인가?

        영상의 「첫 상승(반등)은 무조건 관망」을 기계화한 근사 규칙:
          LONG  = 종가가 EMA20을 아래→위로 뚫은 횟수
          SHORT = 종가가 EMA20을 위→아래로 뚫은 횟수
        1회 = 첫 반등 (= 관망!), 2회 이상 = 바닥 다지기 후 = 진입 후보!
        """
        n = min(len(closes), len(ema20))
        start = max(1, n - lookback)
        count = 0
        for i in range(start, n):
            e_now, e_prev = ema20[i], ema20[i - 1]
            if e_now is None or e_prev is None:
                continue
            if side == "LONG":
                if closes[i - 1] <= e_prev and closes[i] > e_now:
                    count += 1
            else:
                if closes[i - 1] >= e_prev and closes[i] < e_now:
                    count += 1
        return count

    # ------------------------------------------------------------------
    # 4H = 나침반 (거시 추세 필터)
    # ------------------------------------------------------------------
    @classmethod
    def analyze_4h(cls, klines: list, side: str) -> dict[str, Any]:
        """4H EMA50 = 진입 방향 허가 여부.

        LONG  허가 = 종가 > EMA50 AND EMA50 우상향
        SHORT 허가 = 종가 < EMA50 AND EMA50 우하향
        (= 영상: 「4시간봉 50 EMA 아래면 매수 금지」의 양방향 확장!)
        """
        out: dict[str, Any] = {
            "available": False,
            "ok": False,
            "direction": None,
            "price": None,
            "ema50": None,
            "slope_pct": None,
            "note": None,
        }
        need = cls.EMA_SLOW + cls.SLOPE_LOOKBACK
        if not klines or len(klines) < need:
            out["note"] = f"4H 캔들 부족 ({len(klines or [])}/{need})"
            return out

        closes = cls.split_klines(klines)["closes"]
        ema50 = cls.ema_series(closes, cls.EMA_SLOW)
        e_now = ema50[-1]
        e_prev = ema50[-1 - cls.SLOPE_LOOKBACK]
        if e_now is None or e_prev is None or e_prev <= 0:
            out["note"] = "4H EMA50 계산 불가"
            return out

        price = closes[-1]
        slope = (e_now - e_prev) / e_prev * 100
        if slope > cls.SLOPE_FLAT_PCT and price > e_now:
            direction = "UP"
        elif slope < -cls.SLOPE_FLAT_PCT and price < e_now:
            direction = "DOWN"
        else:
            direction = "FLAT"

        out.update({
            "available": True,
            "ok": (direction == "UP" and side == "LONG")
                  or (direction == "DOWN" and side == "SHORT"),
            "direction": direction,
            "price": round(price, 8),
            "ema50": round(e_now, 8),
            "slope_pct": round(slope, 3),
        })
        return out

    # ------------------------------------------------------------------
    # 1H = 작전 지도 (셋업 형성)
    # ------------------------------------------------------------------
    @classmethod
    def analyze_1h(cls, klines: list, side: str) -> dict[str, Any]:
        """1H = 정배열 + VCP 수축 + 거래량 고갈 + 돌파선.

        VCP/거래량/돌파선은 **완료봉만** 사용 (진행 중 봉 = 불완전!).
        정배열은 현재 진행봉 기준 (= 지금 상태!).
        """
        out: dict[str, Any] = {
            "available": False,
            "aligned": False,
            "vcp_contracting": False,
            "volume_dry": False,
            "first_rally_only": True,
            "setup_complete": False,
            "breakout_level": None,
            "ema10": None,
            "ema20": None,
            "ema50": None,
            "vcp_ranges": [],
            "vcp_ratio": None,
            "vol_ratio": None,
            "rally_count": 0,
            "note": None,
        }
        need = cls.EMA_SLOW + cls.VCP_WINDOW + 2
        if not klines or len(klines) < need:
            out["note"] = f"1H 캔들 부족 ({len(klines or [])}/{need})"
            return out

        d = cls.split_klines(klines)
        closes = d["closes"]
        ema10 = cls.ema_series(closes, cls.EMA_FAST)
        ema20 = cls.ema_series(closes, cls.EMA_MID)
        ema50 = cls.ema_series(closes, cls.EMA_SLOW)
        e10, e20, e50 = ema10[-1], ema20[-1], ema50[-1]
        if e10 is None or e20 is None or e50 is None:
            out["note"] = "1H EMA 계산 불가"
            return out

        # 정배열 (LONG) / 역배열 (SHORT)
        aligned = (e10 > e20 > e50) if side == "LONG" else (e10 < e20 < e50)

        # --- 완료봉만 사용! (진행 중 봉 = 마지막 index 제외) ---
        c_high = d["highs"][:-1]
        c_low = d["lows"][:-1]
        c_close = closes[:-1]
        c_vol = d["volumes"][:-1]

        # VCP = 최근 18 완료봉을 3구간으로 나눠 변동폭 축소 확인
        seg_len = cls.VCP_WINDOW // cls.VCP_SEGMENTS
        win_h = c_high[-cls.VCP_WINDOW:]
        win_l = c_low[-cls.VCP_WINDOW:]
        win_c = c_close[-cls.VCP_WINDOW:]
        ranges: list[float] = []
        for i in range(cls.VCP_SEGMENTS):
            s = i * seg_len
            e = s + seg_len
            ranges.append(round(cls._range_pct(win_h[s:e], win_l[s:e], win_c[s:e]), 3))
        vcp_ratio = round(ranges[-1] / ranges[0], 3) if ranges[0] > 0 else None
        # 계단식 축소 or 마지막 구간이 첫 구간의 66% 이하 = 수축 인정!
        vcp_contracting = bool(
            (ranges[0] > ranges[1] > ranges[2] and ranges[2] > 0)
            or (vcp_ratio is not None and vcp_ratio <= cls.VCP_CONTRACT_RATIO)
        )

        # 거래량 고갈 = 최근 6봉 평균 vs 그 이전 12봉 평균
        recent_vol = cls._mean(c_vol[-seg_len:])
        prev_vol = cls._mean(c_vol[-cls.VCP_WINDOW:-seg_len])
        vol_ratio = round(recent_vol / prev_vol, 3) if prev_vol > 0 else None
        volume_dry = bool(vol_ratio is not None and vol_ratio <= cls.VOL_DRY_RATIO)

        # 돌파선 = 최근 20 완료봉의 고점(LONG) / 저점(SHORT)
        pivot_h = c_high[-cls.PIVOT_LOOKBACK:]
        pivot_l = c_low[-cls.PIVOT_LOOKBACK:]
        breakout_level = max(pivot_h) if side == "LONG" else min(pivot_l)

        # 「첫 반등 무시」 필터
        rally_count = cls._rally_count(c_close, ema20[:-1], side, cls.RALLY_LOOKBACK)
        first_rally_only = rally_count <= 1

        out.update({
            "available": True,
            "aligned": aligned,
            "vcp_contracting": vcp_contracting,
            "volume_dry": volume_dry,
            "first_rally_only": first_rally_only,
            "setup_complete": bool(
                aligned and vcp_contracting and volume_dry and not first_rally_only
            ),
            "breakout_level": round(breakout_level, 8),
            "ema10": round(e10, 8),
            "ema20": round(e20, 8),
            "ema50": round(e50, 8),
            "vcp_ranges": ranges,
            "vcp_ratio": vcp_ratio,
            "vol_ratio": vol_ratio,
            "rally_count": rally_count,
        })
        return out

    # ------------------------------------------------------------------
    # 15m = 방아쇠 (정밀 타점 + 리스크)
    # ------------------------------------------------------------------
    @classmethod
    def analyze_15m(
        cls,
        klines: list,
        side: str,
        breakout_level: float | None,
    ) -> dict[str, Any]:
        """15m = 1H 돌파선 통과 + 거래량 폭발 + 손절/절반익절 기준.

        - breakout_intrabar = 진행 중 봉이 돌파선 통과 (= 가장 빠른 포착!)
        - breakout_closed   = 직전 완료봉 **종가**가 돌파선 통과 (= 확정!)
        - vol_spike_ratio   = 직전 완료봉 거래량 / 이전 20봉 평균
          (진행 중 봉은 거래량이 아직 안 찼으므로 = 완료봉 기준!)
        """
        out: dict[str, Any] = {
            "available": False,
            "breakout_intrabar": False,
            "breakout_closed": False,
            "volume_spike": False,
            "vol_spike_ratio": None,
            "price": None,
            "ema20": None,
            "lost_ema20": False,
            "stop_loss": None,
            "risk_pct": None,
            "note": None,
        }
        need = max(cls.EMA_MID, cls.VOL_SPIKE_BASE, cls.SWING_LOOKBACK) + 2
        if not klines or len(klines) < need:
            out["note"] = f"15m 캔들 부족 ({len(klines or [])}/{need})"
            return out

        d = cls.split_klines(klines)
        closes = d["closes"]
        ema20 = cls.ema_series(closes, cls.EMA_MID)
        e20 = ema20[-1]
        price = closes[-1]

        # 완료봉!
        c_high = d["highs"][:-1]
        c_low = d["lows"][:-1]
        c_close = closes[:-1]
        c_vol = d["volumes"][:-1]

        if breakout_level and breakout_level > 0:
            if side == "LONG":
                breakout_intrabar = d["highs"][-1] > breakout_level
                breakout_closed = c_close[-1] > breakout_level
            else:
                breakout_intrabar = d["lows"][-1] < breakout_level
                breakout_closed = c_close[-1] < breakout_level
        else:
            breakout_intrabar = breakout_closed = False

        base_vol = cls._mean(c_vol[-cls.VOL_SPIKE_BASE:])
        vol_ratio = round(c_vol[-1] / base_vol, 3) if base_vol > 0 else None
        volume_spike = bool(vol_ratio is not None and vol_ratio >= cls.VOL_SPIKE_RATIO)

        # 손절 = 직전 스윙 로우(LONG) / 스윙 하이(SHORT)
        if side == "LONG":
            stop_loss = min(c_low[-cls.SWING_LOOKBACK:])
            lost_ema20 = bool(e20 is not None and c_close[-1] < e20)
        else:
            stop_loss = max(c_high[-cls.SWING_LOOKBACK:])
            lost_ema20 = bool(e20 is not None and c_close[-1] > e20)

        risk_pct = round(abs(price - stop_loss) / price * 100, 2) if price > 0 else None

        out.update({
            "available": True,
            "breakout_intrabar": breakout_intrabar,
            "breakout_closed": breakout_closed,
            "volume_spike": volume_spike,
            "vol_spike_ratio": vol_ratio,
            "price": round(price, 8),
            "ema20": round(e20, 8) if e20 is not None else None,
            "lost_ema20": lost_ema20,
            "stop_loss": round(stop_loss, 8),
            "risk_pct": risk_pct,
        })
        return out

    # ------------------------------------------------------------------
    # 종합 = 등급 / 점수 / 신호
    # ------------------------------------------------------------------
    @classmethod
    def combine(
        cls,
        symbol: str,
        side: str,
        r4h: dict,
        r1h: dict,
        r15m: dict,
    ) -> dict[str, Any]:
        """3개 타임프레임 → 셋업 등급 (A/B/C/D) + 점수 + 사장님 신호."""
        signals: list[str] = []
        score = 0

        available = bool(r4h.get("available") and r1h.get("available") and r15m.get("available"))

        # 1) 4H 나침반
        # v139 점수 재배분 근거 (실측 백테스트 = 실매매 309건 + 추천 761건):
        #   상위 타임프레임(4H 추세 / 1H 정배열)은 **양쪽 데이터에서 일관되게 유효**
        #     trend_ok    : 실매매 중앙 +15.96 USDT / 추천 4h +1.18%p
        #     aligned_1h  : 실매매 중앙 +16.68 USDT / 추천 4h +1.18%p
        #   하위 트리거(15m 돌파 / 거래량 폭발)는 **양쪽이 상반** → 가중치 축소
        #     vol_spike   : 실매매 +5.54 USDT 이지만 추천 4h **-1.37%p**
        #     breakout    : 실매매 +4.51 USDT 이지만 추천 4h **-0.50%p**
        #   = 「필터는 맞고 트리거는 불확실」 → 필터에 점수를 몰아줍니다.
        if r4h.get("ok"):
            score += 30
            signals.append(
                f"✅ 4H 추세 {r4h['direction']} (EMA50 기울기 {r4h['slope_pct']}%) = {side} 허가!"
            )
        elif r4h.get("available"):
            if r4h.get("direction") == "FLAT":
                signals.append("⚠️ 4H 추세 = 횡보 (EMA50 방향 불명) = 관망!")
            else:
                signals.append(
                    f"🚫 4H 추세 {r4h['direction']} = {side} 역방향! (영상 원칙: 진입 금지!)"
                )
        else:
            signals.append(f"➖ 4H 판정 불가: {r4h.get('note')}")

        # 2) 1H 셋업
        if r1h.get("available"):
            if r1h.get("aligned"):
                score += 25   # v139: 20 → 25 (양쪽 데이터에서 일관되게 유효!)
                signals.append(
                    "✅ 1H " + ("정배열 (10>20>50)" if side == "LONG" else "역배열 (10<20<50)") + " 확인!"
                )
            else:
                signals.append("⚠️ 1H 이평선 배열 미완성 = 셋업 대기!")

            if r1h.get("vcp_contracting"):
                score += 15
                signals.append(
                    f"✅ VCP 수축! 변동폭 {r1h['vcp_ranges']}% → 비율 {r1h['vcp_ratio']} (힘 응축!)"
                )
            else:
                signals.append(f"➖ 변동성 수축 X (구간 변동폭 {r1h['vcp_ranges']}%)")

            if r1h.get("volume_dry"):
                score += 10
                signals.append(f"✅ 거래량 고갈 ({r1h['vol_ratio']}x) = 매도세 소진!")
            else:
                signals.append(f"➖ 거래량 아직 안 마름 ({r1h['vol_ratio']}x)")

            if r1h.get("first_rally_only"):
                signals.append(
                    f"⚠️ 첫 {'반등' if side == 'LONG' else '반락'}만 확인 (교차 {r1h['rally_count']}회) "
                    "= 영상 원칙: 무조건 관망! "
                    "(v139 실측: 이 상태 진입 172건 중앙 -21.4 USDT vs 통과 137건 -1.8 USDT)"
                )
            else:
                # v139: 10 → 15. 실매매 백테스트에서 가장 강한 단일 필터 중 하나!
                #   first_rally_only=Y 172건 중앙 -21.42 USDT
                #   first_rally_only=N 137건 중앙  -1.81 USDT  = 차이 +19.6 USDT
                score += 15
                signals.append(
                    f"✅ 두 번째 이상 파동 (교차 {r1h['rally_count']}회) = 바닥 다지기 통과!"
                )
        else:
            signals.append(f"➖ 1H 판정 불가: {r1h.get('note')}")

        # 3) 15m 방아쇠
        if r15m.get("available"):
            lvl = r1h.get("breakout_level")
            # v139: 돌파 10 → 3, 거래량 폭발 5 → 2 로 축소!
            #   두 데이터셋이 상반됨 (실매매 +, 추천 4h −) = 신뢰 못 함 =
            #   등급 판정에는 계속 쓰되 **점수 비중은 낮춤** (과최적화 방지!)
            if r15m.get("breakout_closed"):
                score += 3
                signals.append(f"🎯 15m 종가 돌파 확정! (돌파선 {lvl})")
            elif r15m.get("breakout_intrabar"):
                score += 2
                signals.append(f"⏳ 15m 장중 돌파 중! (돌파선 {lvl}, 종가 확정 대기!)")
            else:
                signals.append(f"➖ 돌파 대기 (돌파선 {lvl}, 현재가 {r15m['price']})")

            if r15m.get("volume_spike"):
                score += 2
                signals.append(
                    f"🔥 15m 거래량 {r15m['vol_spike_ratio']}x 폭발 = 진짜 시세! "
                    "(단, v139 실측상 4시간 뒤 되돌림 경향 = 추격 금지!)"
                )
            elif r15m.get("breakout_intrabar") or r15m.get("breakout_closed"):
                signals.append(
                    f"⚠️ 돌파했으나 거래량 {r15m['vol_spike_ratio']}x = 가짜 돌파(휩쏘) 주의!"
                )
        else:
            signals.append(f"➖ 15m 판정 불가: {r15m.get('note')}")

        # --- 등급 판정 ---
        trend_blocked = r4h.get("available") and not r4h.get("ok")
        breakout = bool(r15m.get("breakout_closed") or r15m.get("breakout_intrabar"))
        if not available:
            grade, stage, verdict = "D", "UNKNOWN", "➖ 데이터 부족 = 판정 불가"
        elif trend_blocked:
            grade, stage, verdict = "D", "AVOID", "🚫 4H 역방향 = 진입 금지!"
        elif r1h.get("setup_complete") and breakout and r15m.get("volume_spike"):
            grade, stage, verdict = "A", "TRIGGER", "🎯 A등급 = 지금이 방아쇠!"
        elif r1h.get("setup_complete"):
            grade, stage, verdict = "B", "SETUP", "⭐ B등급 = 셋업 완성, 돌파 대기!"
        else:
            grade, stage, verdict = "C", "WATCH", "👀 C등급 = 추세만 OK, 셋업 형성 중!"

        color = {"A": "#22c55e", "B": "#f59e0b", "C": "#94a3b8", "D": "#ef4444"}[grade]

        return {
            "available": available,
            "symbol": symbol,
            "side": side,
            "grade": grade,
            "stage": stage,
            "verdict": verdict,
            "color": color,
            "score": min(score, 100),
            "signals": signals,
            "tf_4h": r4h,
            "tf_1h": r1h,
            "tf_15m": r15m,
            "levels": {
                "breakout": r1h.get("breakout_level"),
                "stop_loss": r15m.get("stop_loss"),
                "risk_pct": r15m.get("risk_pct"),
                "exit_half_15m_ema20": r15m.get("ema20"),
                "exit_full_1h_ema20": r1h.get("ema20"),
            },
        }

    # ------------------------------------------------------------------
    # 진입점
    # ------------------------------------------------------------------
    def _fetch(self, symbol: str, interval: str) -> list:
        if self.client is None:
            raise RuntimeError("binance_client 없음 (캔들을 직접 넘기세요!)")
        return self.client.get_klines(symbol=symbol, interval=interval, limit=self.KLINE_LIMIT)

    def analyze(
        self,
        symbol: str,
        side: str = "LONG",
        klines_4h: list | None = None,
        klines_1h: list | None = None,
        klines_15m: list | None = None,
    ) -> dict[str, Any]:
        """심볼 EMA/VCP 종합 분석 (읽기 전용!).

        캔들을 넘기면 그대로 쓰고, 없으면 Binance에서 조회합니다.
        어떤 예외도 신호로 새지 않게 = fail-safe (available=False)!
        """
        symbol = (symbol or "").upper()
        side = (side or "LONG").upper()
        try:
            # `is not None` = 빈 리스트를 「조회해와라」로 오해하지 않게! (v140 fix)
            k4 = klines_4h if klines_4h is not None else self._fetch(symbol, "4h")
            k1 = klines_1h if klines_1h is not None else self._fetch(symbol, "1h")
            k15 = klines_15m if klines_15m is not None else self._fetch(symbol, "15m")
        except Exception as e:
            logger.warning("[ema_vcp] 캔들 조회 실패 %s: %s", symbol, e)
            return {
                "available": False,
                "symbol": symbol,
                "side": side,
                "grade": "D",
                "stage": "UNKNOWN",
                "verdict": "➖ 캔들 조회 실패 = 판정 불가",
                "color": "#94a3b8",
                "score": 0,
                "signals": [f"➖ 캔들 조회 실패: {e}"],
                "error": str(e),
            }

        try:
            r4 = self.analyze_4h(k4, side)
            r1 = self.analyze_1h(k1, side)
            r15 = self.analyze_15m(k15, side, r1.get("breakout_level"))
            return self.combine(symbol, side, r4, r1, r15)
        except Exception as e:
            logger.warning("[ema_vcp] 계산 실패 %s: %s", symbol, e)
            return {
                "available": False,
                "symbol": symbol,
                "side": side,
                "grade": "D",
                "stage": "UNKNOWN",
                "verdict": "➖ 계산 실패 = 판정 불가",
                "color": "#94a3b8",
                "score": 0,
                "signals": [f"➖ 계산 실패: {e}"],
                "error": str(e),
            }


def to_learning_context(result: dict | None) -> dict[str, Any]:
    """학습 저장용 압축 스냅샷 (entry_context / exit_context).

    JSONB 크기를 아끼려고 = 등급 + 핵심 플래그 + 레벨만!
    (= 나중에 「등급별 실제 승률」 집계의 키가 됩니다!)
    """
    if not result:
        return {}
    tf1 = result.get("tf_1h") or {}
    tf4 = result.get("tf_4h") or {}
    tf15 = result.get("tf_15m") or {}
    return {
        "available": bool(result.get("available")),
        "grade": result.get("grade"),
        "stage": result.get("stage"),
        "score": result.get("score"),
        "trend_4h": tf4.get("direction"),
        "trend_ok": bool(tf4.get("ok")),
        "aligned_1h": bool(tf1.get("aligned")),
        "vcp_contracting": bool(tf1.get("vcp_contracting")),
        "volume_dry": bool(tf1.get("volume_dry")),
        "first_rally_only": bool(tf1.get("first_rally_only")),
        "rally_count": tf1.get("rally_count"),
        "breakout_closed": bool(tf15.get("breakout_closed")),
        "volume_spike": bool(tf15.get("volume_spike")),
        "levels": result.get("levels") or {},
    }
