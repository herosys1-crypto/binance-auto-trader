"""☁️ 파라볼릭 SAR + 일목균형표 구름대 멀티 타임프레임 분석 (v138 신!)

spec: docs/SAR_ICHIMOKU_MTF_STRATEGY_SPEC.md
사장님 요청 2026-08-14 (해외선물 「파라볼릭 SAR + 구름대」 매매법 정리 자료).

로직 (4H 나침반 → 1H 교차검증 → 15m 방아쇠):
  1. 4H  = 구름대 위/아래 = 진입 방향 제한 (구름 안 = 관망!)
  2. 1H  = 같은 방향 구름대 유지 (2중 필터) + 얇은 구름 / 눌림목 가산
  3. 15m = 구름 방향 유지 + **SAR 전환 첫 점** = 방아쇠!

= **읽기 전용 분석!** 주문 X (사장님 판단 보조 + 학습 저장 전용!)

⚠️ 리페인팅 방지 (헌법 v127):
  SAR / 구름 판정은 **완료봉만** 사용합니다.
  진행 중 봉의 SAR는 찍혔다 사라질 수 있음 = 그걸 신호로 쓰면 silent bug!
  현재가는 `current_price` 로 따로 보고합니다.

헌법 v138:
  '파라볼릭 단독 = 횡보장 가짜 신호! 구름대 필터 없는 SAR 신호 = 신뢰 금지!'
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SARIchimokuAnalyzer:
    """PSAR 전환 + 일목 구름대 필터 = 멀티 타임프레임 추세 추종 판정."""

    # --- 파라볼릭 SAR (Wilder 기본값) ---
    SAR_STEP = 0.02
    SAR_MAX = 0.2

    # --- 일목균형표 (구름대만 사용!) ---
    TENKAN = 9          # 전환선
    KIJUN = 26          # 기준선
    SENKOU_B = 52       # 선행스팬2
    SHIFT = 26          # 선행 이동 (구름 = 26봉 전 데이터로 만들어짐!)

    # --- 판정 임계값 ---
    FLIP_FRESH_BARS = 3     # SAR 전환 후 3봉 이내 = 「첫 점」 = 신선한 신호!
    THIN_CLOUD_PCT = 1.5    # 구름 두께 ≤ 1.5% = 얇음 (= 저항 약함!)
    NEAR_CLOUD_PCT = 2.0    # 구름까지 이격 ≤ 2% = 눌림목 근접!

    KLINE_LIMIT = 120

    def __init__(self, binance_client=None):
        """
        Args:
            binance_client: BinanceClient (get_klines 지원). 캔들을 직접
                넘기면 None 가능 (= 순수 계산 모드!).
        """
        self.client = binance_client

    # ------------------------------------------------------------------
    # 순수 계산
    # ------------------------------------------------------------------
    @staticmethod
    def split_klines(klines: list) -> dict[str, list[float]]:
        """Binance kline → OHLCV."""
        return {
            "highs": [float(k[2]) for k in klines],
            "lows": [float(k[3]) for k in klines],
            "closes": [float(k[4]) for k in klines],
        }

    @classmethod
    def psar(
        cls,
        highs: list[float],
        lows: list[float],
        closes: list[float],
    ) -> tuple[list[float | None], list[bool | None]]:
        """Wilder 파라볼릭 SAR.

        Returns:
            (sar 값 리스트, 상승추세 여부 리스트) — 입력과 길이 동일.
            상승추세 True = SAR 점이 캔들 **아래** (매수 구간!)
        """
        n = len(closes)
        sar_out: list[float | None] = [None] * n
        trend_out: list[bool | None] = [None] * n
        if n < 3:
            return sar_out, trend_out

        uptrend = closes[1] >= closes[0]
        sar = lows[0] if uptrend else highs[0]
        ep = highs[1] if uptrend else lows[1]
        af = cls.SAR_STEP
        sar_out[0] = sar
        trend_out[0] = uptrend

        for i in range(1, n):
            sar = sar + af * (ep - sar)
            prev_low = lows[i - 1]
            prev_high = highs[i - 1]
            prev2_low = lows[i - 2] if i >= 2 else prev_low
            prev2_high = highs[i - 2] if i >= 2 else prev_high

            if uptrend:
                # SAR는 직전 2봉 저가를 넘어설 수 없음!
                sar = min(sar, prev_low, prev2_low)
                if lows[i] < sar:
                    # 🔄 전환! (상승 → 하락)
                    uptrend = False
                    sar = ep
                    ep = lows[i]
                    af = cls.SAR_STEP
                elif highs[i] > ep:
                    ep = highs[i]
                    af = min(af + cls.SAR_STEP, cls.SAR_MAX)
            else:
                sar = max(sar, prev_high, prev2_high)
                if highs[i] > sar:
                    # 🔄 전환! (하락 → 상승)
                    uptrend = True
                    sar = ep
                    ep = highs[i]
                    af = cls.SAR_STEP
                elif lows[i] < ep:
                    ep = lows[i]
                    af = min(af + cls.SAR_STEP, cls.SAR_MAX)

            sar_out[i] = sar
            trend_out[i] = uptrend

        return sar_out, trend_out

    @staticmethod
    def _mid_range(highs: list[float], lows: list[float], idx: int, period: int) -> float | None:
        """(기간 최고가 + 기간 최저가) / 2 — 일목 기본 계산식."""
        if idx < period - 1 or idx >= len(highs):
            return None
        window_h = highs[idx - period + 1: idx + 1]
        window_l = lows[idx - period + 1: idx + 1]
        return (max(window_h) + min(window_l)) / 2

    @classmethod
    def cloud_state(cls, klines: list) -> dict[str, Any]:
        """일목 구름대 현재 상태 (**완료봉 기준!**).

        구름 = 26봉 전 데이터로 만들어진 선행스팬1/2 영역.
          선행스팬1 = (전환선 + 기준선) / 2   [26봉 전 값]
          선행스팬2 = (52봉 최고 + 최저) / 2  [26봉 전 값]
        """
        out: dict[str, Any] = {
            "available": False,
            "position": None,       # ABOVE / BELOW / INSIDE
            "top": None,
            "bottom": None,
            "close": None,
            "current_price": None,
            "thickness_pct": None,
            "dist_pct": None,       # 구름까지 이격 % (작을수록 눌림목!)
            "thin": False,
            "near": False,
            "note": None,
        }
        need = cls.SHIFT + cls.SENKOU_B + 2
        if not klines or len(klines) < need:
            out["note"] = f"캔들 부족 ({len(klines or [])}/{need})"
            return out

        d = cls.split_klines(klines)
        highs, lows, closes = d["highs"], d["lows"], d["closes"]

        out["current_price"] = round(closes[-1], 8)

        # 완료봉 기준! (진행 중 봉 = 마지막 index 제외)
        i = len(closes) - 2
        src = i - cls.SHIFT  # 구름을 만든 시점!
        if src < 0:
            out["note"] = "선행 이동분 부족"
            return out

        tenkan = cls._mid_range(highs, lows, src, cls.TENKAN)
        kijun = cls._mid_range(highs, lows, src, cls.KIJUN)
        senkou_b = cls._mid_range(highs, lows, src, cls.SENKOU_B)
        if tenkan is None or kijun is None or senkou_b is None:
            out["note"] = "구름 계산 불가"
            return out

        senkou_a = (tenkan + kijun) / 2
        top = max(senkou_a, senkou_b)
        bottom = min(senkou_a, senkou_b)
        close = closes[i]

        if close > top:
            position = "ABOVE"
            dist_pct = (close - top) / close * 100
        elif close < bottom:
            position = "BELOW"
            dist_pct = (bottom - close) / close * 100
        else:
            position = "INSIDE"
            dist_pct = 0.0

        thickness = (top - bottom) / close * 100 if close > 0 else None

        out.update({
            "available": True,
            "position": position,
            "top": round(top, 8),
            "bottom": round(bottom, 8),
            "close": round(close, 8),
            "thickness_pct": round(thickness, 3) if thickness is not None else None,
            "dist_pct": round(dist_pct, 3),
            "thin": bool(thickness is not None and thickness <= cls.THIN_CLOUD_PCT),
            "near": bool(position != "INSIDE" and dist_pct <= cls.NEAR_CLOUD_PCT),
        })
        return out

    @classmethod
    def sar_state(cls, klines: list) -> dict[str, Any]:
        """SAR 현재 상태 (**완료봉 기준!**).

        flip_bars_ago = 0 → 직전 완료봉에서 전환 = 「첫 점」!
        """
        out: dict[str, Any] = {
            "available": False,
            "uptrend": None,
            "sar": None,
            "flip_bars_ago": None,
            "fresh_flip": False,
            "note": None,
        }
        if not klines or len(klines) < 6:
            out["note"] = f"캔들 부족 ({len(klines or [])}/6)"
            return out

        bars = klines[:-1]  # 진행 중 봉 제외!
        d = cls.split_klines(bars)
        sar_vals, trends = cls.psar(d["highs"], d["lows"], d["closes"])
        if not trends or trends[-1] is None:
            out["note"] = "SAR 계산 불가"
            return out

        cur = trends[-1]
        flip_bars_ago = None
        for back in range(1, len(trends)):
            idx = len(trends) - 1 - back
            if trends[idx] is None:
                break
            if trends[idx] != cur:
                flip_bars_ago = back - 1
                break

        out.update({
            "available": True,
            "uptrend": bool(cur),
            "sar": round(sar_vals[-1], 8) if sar_vals[-1] is not None else None,
            "flip_bars_ago": flip_bars_ago,
            "fresh_flip": bool(
                flip_bars_ago is not None and flip_bars_ago <= cls.FLIP_FRESH_BARS
            ),
        })
        return out

    # ------------------------------------------------------------------
    # 타임프레임별 판정
    # ------------------------------------------------------------------
    @staticmethod
    def _cloud_ok(position: str | None, side: str) -> bool:
        return (position == "ABOVE" and side == "LONG") or (
            position == "BELOW" and side == "SHORT"
        )

    @classmethod
    def analyze_4h(cls, klines: list, side: str) -> dict[str, Any]:
        """4H = 나침반. 구름 위 = LONG만 / 구름 아래 = SHORT만 / 구름 안 = 관망!"""
        cloud = cls.cloud_state(klines)
        cloud["ok"] = cls._cloud_ok(cloud.get("position"), side)
        return cloud

    @classmethod
    def analyze_1h(cls, klines: list, side: str) -> dict[str, Any]:
        """1H = 교차검증. 같은 방향 구름 유지 + 얇은 구름 / 눌림목 = 이상적!"""
        cloud = cls.cloud_state(klines)
        sar = cls.sar_state(klines)
        cloud["ok"] = cls._cloud_ok(cloud.get("position"), side)
        cloud["sar"] = sar
        cloud["sar_aligned"] = bool(
            sar.get("available")
            and ((sar["uptrend"] and side == "LONG") or (not sar["uptrend"] and side == "SHORT"))
        )
        # 얇은 구름 or 눌림목 근접 = 영상의 「가장 이상적」 조건!
        cloud["ideal"] = bool(cloud["ok"] and (cloud.get("thin") or cloud.get("near")))
        return cloud

    @classmethod
    def analyze_15m(cls, klines: list, side: str) -> dict[str, Any]:
        """15m = 방아쇠. 구름 방향 유지 + SAR 전환 첫 점 + 손절/익절 기준."""
        cloud = cls.cloud_state(klines)
        sar = cls.sar_state(klines)
        cloud["ok"] = cls._cloud_ok(cloud.get("position"), side)
        cloud["sar"] = sar

        aligned = bool(
            sar.get("available")
            and ((sar["uptrend"] and side == "LONG") or (not sar["uptrend"] and side == "SHORT"))
        )
        cloud["sar_aligned"] = aligned
        # 방아쇠 = 방향 일치 + 신선한 전환!
        cloud["trigger"] = bool(aligned and sar.get("fresh_flip"))

        # 손절 = 구름 반대편 끝 (영상: 「구름대 하단 이탈 마감」)
        if cloud.get("available"):
            stop = cloud["bottom"] if side == "LONG" else cloud["top"]
            price = cloud.get("close") or 0
            cloud["stop_loss"] = stop
            cloud["risk_pct"] = (
                round(abs(price - stop) / price * 100, 2) if price else None
            )
        else:
            cloud["stop_loss"] = None
            cloud["risk_pct"] = None
        return cloud

    # ------------------------------------------------------------------
    # 종합
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
        """3개 타임프레임 → 등급 (A/B/C/D) + 점수 + 사장님 신호."""
        signals: list[str] = []
        score = 0
        available = bool(
            r4h.get("available") and r1h.get("available") and r15m.get("available")
        )

        def _pos_ko(p: str | None) -> str:
            return {"ABOVE": "구름 위", "BELOW": "구름 아래", "INSIDE": "구름 안"}.get(p or "", "-")

        # 1) 4H 나침반
        if r4h.get("ok"):
            score += 30
            signals.append(f"✅ 4H {_pos_ko(r4h['position'])} = {side} 방향만 허가!")
        elif r4h.get("available"):
            if r4h.get("position") == "INSIDE":
                signals.append("🚫 4H 구름 「내부」 = 추세 불명! (영상 원칙: 매매 쉬고 관망!)")
            else:
                signals.append(f"🚫 4H {_pos_ko(r4h['position'])} = {side} 역방향! 진입 금지!")
        else:
            signals.append(f"➖ 4H 판정 불가: {r4h.get('note')}")

        # 2) 1H 교차검증
        # v139 점수 재배분 근거 (실측 백테스트 = 실매매 309건 + 추천 761건):
        #   cloud_1h_ok = **가장 강력한 단일 조건** (실매매 중앙 +18.70 USDT / 추천 +1.58%p)
        #   cloud_4h_ok 도 양쪽 유효 (+18.37 USDT / +0.55%p)
        #   반면 cloud_15m_ok 은 상반 (실매매 +9.32 USDT / 추천 **-0.60%p**) → 비중 축소
        if r1h.get("available"):
            if r1h.get("ok"):
                score += 30   # v139: 25 → 30 (양쪽 데이터에서 최강 조건!)
                signals.append(f"✅ 1H {_pos_ko(r1h['position'])} 유지 = 2중 필터 통과!")
            else:
                signals.append(f"⚠️ 1H {_pos_ko(r1h['position'])} = 상위 추세와 불일치!")

            if r1h.get("ideal"):
                score += 10
                bits = []
                if r1h.get("thin"):
                    bits.append(f"구름 얇음 {r1h['thickness_pct']}%")
                if r1h.get("near"):
                    bits.append(f"눌림목 근접 {r1h['dist_pct']}%")
                signals.append(f"⭐ 1H {' + '.join(bits)} = 이상적 셋업!")
        else:
            signals.append(f"➖ 1H 판정 불가: {r1h.get('note')}")

        # 3) 15m 방아쇠
        sar15 = r15m.get("sar") or {}
        if r15m.get("available"):
            if r15m.get("ok"):
                score += 10   # v139: 15 → 10 (두 데이터셋 상반 = 신뢰 낮춤!)
                signals.append(f"✅ 15m {_pos_ko(r15m['position'])} 유지!")
            else:
                signals.append(f"⚠️ 15m {_pos_ko(r15m['position'])} = 하위 프레임 이탈!")

            if r15m.get("sar_aligned"):
                score += 10
                dot = "아래" if side == "LONG" else "위"
                signals.append(f"✅ 15m SAR 점이 캔들 {dot} = {side} 구간!")
            elif sar15.get("available"):
                signals.append(f"⚠️ 15m SAR 방향 불일치 = {side} 신호 아님!")

            if r15m.get("trigger"):
                score += 10
                signals.append(
                    f"🎯 15m SAR 전환 첫 점! ({sar15.get('flip_bars_ago')}봉 전) = 방아쇠!"
                )
            elif r15m.get("sar_aligned") and sar15.get("flip_bars_ago") is not None:
                signals.append(
                    f"➖ SAR 전환 {sar15['flip_bars_ago']}봉 경과 = 첫 점 아님 (추격 주의!)"
                )
        else:
            signals.append(f"➖ 15m 판정 불가: {r15m.get('note')}")

        # --- 등급 ---
        blocked = r4h.get("available") and not r4h.get("ok")
        if not available:
            grade, stage, verdict = "D", "UNKNOWN", "➖ 데이터 부족 = 판정 불가"
        elif blocked:
            reason = "구름 내부 = 관망!" if r4h.get("position") == "INSIDE" else "4H 역방향 = 진입 금지!"
            grade, stage, verdict = "D", "AVOID", f"🚫 {reason}"
        elif r1h.get("ok") and r15m.get("ok") and r15m.get("trigger"):
            grade, stage, verdict = "A", "TRIGGER", "🎯 A등급 = SAR 전환 첫 점 = 방아쇠!"
            # 🚨 v139 실측 경고 (숨기지 않고 사장님께 그대로 보고!)
            #   추천 761건 백테스트: SAR A등급 41건의 4h 적중률 = **22.0%** (평균 -2.09%)
            #   같은 데이터에서 B등급 166건은 43.4% (+1.40%) = **A가 B보다 나빴음!**
            #   → 「전환 첫 점」이 이미 단기 과열 정점일 수 있다는 뜻.
            #   실매매(309건)에서는 반대로 sar_fresh 가 +5.83 USDT 로 유리했기에
            #   등급 자체는 유지하되, 경고를 반드시 노출합니다 (헌법 3번).
            if not r1h.get("ideal"):
                signals.append(
                    "🚨 주의: SAR A등급은 실측상 되돌림 위험이 큽니다 "
                    "(추천 백테스트 41건 적중률 22% < B등급 43%). "
                    "1H 구름이 얇거나 눌림목일 때만 신뢰하세요!"
                )
        elif r1h.get("ok") and r15m.get("ok"):
            grade, stage, verdict = "B", "SETUP", "⭐ B등급 = 3중 정렬 완료, SAR 전환 대기!"
        else:
            grade, stage, verdict = "C", "WATCH", "👀 C등급 = 4H만 OK, 하위 정렬 대기!"

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
                "cloud_top_15m": r15m.get("top"),
                "cloud_bottom_15m": r15m.get("bottom"),
                "stop_loss": r15m.get("stop_loss"),
                "risk_pct": r15m.get("risk_pct"),
                "sar_15m": (r15m.get("sar") or {}).get("sar"),
                "sar_1h": (r1h.get("sar") or {}).get("sar"),
            },
        }

    # ------------------------------------------------------------------
    # 진입점
    # ------------------------------------------------------------------
    def _fetch(self, symbol: str, interval: str) -> list:
        if self.client is None:
            raise RuntimeError("binance_client 없음 (캔들을 직접 넘기세요!)")
        return self.client.get_klines(symbol=symbol, interval=interval, limit=self.KLINE_LIMIT)

    def _fail(self, symbol: str, side: str, msg: str) -> dict[str, Any]:
        return {
            "available": False,
            "symbol": symbol,
            "side": side,
            "grade": "D",
            "stage": "UNKNOWN",
            "verdict": "➖ 판정 불가",
            "color": "#94a3b8",
            "score": 0,
            "signals": [f"➖ {msg}"],
            "error": msg,
        }

    def analyze(
        self,
        symbol: str,
        side: str = "LONG",
        klines_4h: list | None = None,
        klines_1h: list | None = None,
        klines_15m: list | None = None,
    ) -> dict[str, Any]:
        """SAR + 구름대 종합 분석 (읽기 전용!). 예외 = available=False (fail-safe)."""
        symbol = (symbol or "").upper()
        side = (side or "LONG").upper()
        try:
            # `is not None` = 빈 리스트를 「조회해와라」로 오해하지 않게! (v140 fix)
            k4 = klines_4h if klines_4h is not None else self._fetch(symbol, "4h")
            k1 = klines_1h if klines_1h is not None else self._fetch(symbol, "1h")
            k15 = klines_15m if klines_15m is not None else self._fetch(symbol, "15m")
        except Exception as e:
            logger.warning("[sar_ichimoku] 캔들 조회 실패 %s: %s", symbol, e)
            return self._fail(symbol, side, f"캔들 조회 실패: {e}")

        try:
            return self.combine(
                symbol, side,
                self.analyze_4h(k4, side),
                self.analyze_1h(k1, side),
                self.analyze_15m(k15, side),
            )
        except Exception as e:
            logger.warning("[sar_ichimoku] 계산 실패 %s: %s", symbol, e)
            return self._fail(symbol, side, f"계산 실패: {e}")


def to_learning_context(result: dict | None) -> dict[str, Any]:
    """학습 저장용 압축 스냅샷 (entry_context)."""
    if not result:
        return {}
    t4 = result.get("tf_4h") or {}
    t1 = result.get("tf_1h") or {}
    t15 = result.get("tf_15m") or {}
    sar15 = t15.get("sar") or {}
    return {
        "available": bool(result.get("available")),
        "grade": result.get("grade"),
        "stage": result.get("stage"),
        "score": result.get("score"),
        "cloud_4h": t4.get("position"),
        "cloud_4h_ok": bool(t4.get("ok")),
        "cloud_1h": t1.get("position"),
        "cloud_1h_ok": bool(t1.get("ok")),
        "cloud_1h_ideal": bool(t1.get("ideal")),
        "cloud_15m_ok": bool(t15.get("ok")),
        "sar_aligned": bool(t15.get("sar_aligned")),
        "sar_fresh_flip": bool(sar15.get("fresh_flip")),
        "flip_bars_ago": sar15.get("flip_bars_ago"),
        "levels": result.get("levels") or {},
    }
