"""차트 분석 서비스 = 신 「OBV 자동 재진입」 로직 (v130!)

spec: docs/CHART_REENTRY_STRATEGY_SPEC.md
사장님 요청 2026-08-06.

로직:
  1. 4H OBV = 첫 하락 봉 감지 (진행 중 봉!)
  2. 15m + 1h OBV = 하락 추세 확인 (조기 신호!)
  3. 손절가 대비 10% 상승 or 하락 확인
  = 모든 조건 만족 → True (진입 신호!)

헌법 v130:
  '차트 분석 신호 = OBV 반전 = 사장님 자율 정확 재진입!'
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)


class ChartAnalyzer:
    """OBV 기반 신호 판정 (v130)."""

    def __init__(self, binance_client):
        """
        Args:
            binance_client: BinanceClient 인스턴스 (get_klines 지원)
        """
        self.client = binance_client

    @staticmethod
    def compute_cci(klines: list, period: int = 20) -> list[float]:
        """kline 리스트 → CCI (Commodity Channel Index) 리스트 (v219 사장님 정점 감지!).

        공식:
          Typical Price (TP) = (High + Low + Close) / 3
          SMA_TP = TP 의 period 이동 평균
          Mean Deviation (MD) = mean(|TP - SMA_TP|)  # period 창 안!
          CCI = (TP - SMA_TP) / (0.015 * MD)

        CCI 값 해석:
          +200 이상 = 매우 강한 상승 (정점 근접 = SHORT 진입 근거!)
          -200 이하 = 매우 강한 하락
          -100 ~ +100 = 정상 범위

        Returns:
            list[float] — 각 봉의 CCI. 초기 period-1 개는 0.0 (계산 불가).
        """
        if not klines or len(klines) < period:
            return [0.0] * len(klines) if klines else []
        try:
            tps: list[float] = []
            for kl in klines:
                h = float(kl[2])
                l = float(kl[3])
                c = float(kl[4])
                tps.append((h + l + c) / 3.0)
        except (ValueError, TypeError, IndexError):
            return [0.0] * len(klines)

        cci: list[float] = [0.0] * len(klines)
        for i in range(period - 1, len(tps)):
            window = tps[i - period + 1 : i + 1]
            sma = sum(window) / period
            md = sum(abs(x - sma) for x in window) / period
            if md == 0:
                cci[i] = 0.0
                continue
            cci[i] = (tps[i] - sma) / (0.015 * md)
        return cci

    @staticmethod
    def compute_obv(klines: list) -> list[Decimal]:
        """kline 리스트 → OBV 리스트.

        klines format (Binance):
          [ [open_time, open, high, low, close, volume, close_time, ...], ... ]
          close = index 4, volume = index 5

        OBV(t) = OBV(t-1) + vol(t)  if close(t) > close(t-1)
               = OBV(t-1) - vol(t)  if close(t) < close(t-1)
               = OBV(t-1)           if ==

        Returns:
            list[Decimal] — kline 각 봉의 누적 OBV
        """
        if not klines or len(klines) < 2:
            return []
        obv: list[Decimal] = [Decimal("0")]  # 첫 봉 = 0 (기준!)
        prev_close = Decimal(str(klines[0][4]))
        for kl in klines[1:]:
            close = Decimal(str(kl[4]))
            vol = Decimal(str(kl[5]))
            if close > prev_close:
                obv.append(obv[-1] + vol)
            elif close < prev_close:
                obv.append(obv[-1] - vol)
            else:
                obv.append(obv[-1])
            prev_close = close
        return obv

    def check_4h_first_bear_bar(self, symbol: str) -> bool:
        """4H OBV = 첫 하락 봉 감지 (진행 중 봉이 이전 봉 대비 OBV 감소).

        조건:
          - 이전 4H 봉 (완전 봉) = OBV 상승 (bull!)
          - 현재 4H 봉 (진행 중) = OBV 하락 (bear!)
          = 첫 하락 봉!
        """
        try:
            kl = self.client.get_klines(symbol=symbol, interval="4h", limit=50)
            if not kl or len(kl) < 3:
                return False
            obv = self.compute_obv(kl)
            if len(obv) < 3:
                return False
            # 이전 봉 = 상승, 현재 봉 = 하락
            prev_prev = obv[-3]  # 2봉 전
            prev = obv[-2]       # 직전 완료 봉
            curr = obv[-1]       # 진행 중 봉
            was_bullish = prev > prev_prev
            is_bearish = curr < prev
            return was_bullish and is_bearish
        except Exception as e:
            logger.warning("[chart_analyzer] 4H OBV 검사 실패 %s: %s", symbol, e)
            return False

    def check_15m_1h_bearish_trend(self, symbol: str) -> bool:
        """15m + 1h OBV = 하락 추세 확인 (조기 신호).

        조건:
          - 15m 최근 3봉 OBV = 하락!
          - 1h 최근 2봉 OBV = 하락!
        """
        try:
            # 15m 최근 3봉 하락
            kl_15m = self.client.get_klines(symbol=symbol, interval="15m", limit=10)
            if not kl_15m or len(kl_15m) < 4:
                return False
            obv_15m = self.compute_obv(kl_15m)
            if len(obv_15m) < 4:
                return False
            _bear_15m = (
                obv_15m[-1] < obv_15m[-2]
                and obv_15m[-2] < obv_15m[-3]
                and obv_15m[-3] < obv_15m[-4]
            )
            if not _bear_15m:
                return False

            # 1h 최근 2봉 하락
            kl_1h = self.client.get_klines(symbol=symbol, interval="1h", limit=10)
            if not kl_1h or len(kl_1h) < 3:
                return False
            obv_1h = self.compute_obv(kl_1h)
            if len(obv_1h) < 3:
                return False
            _bear_1h = obv_1h[-1] < obv_1h[-2] and obv_1h[-2] < obv_1h[-3]
            return _bear_1h
        except Exception as e:
            logger.warning("[chart_analyzer] 15m/1h OBV 검사 실패 %s: %s", symbol, e)
            return False

    def check_price_moved_10pct(
        self,
        symbol: str,
        prev_stop_price: Decimal,
    ) -> tuple[bool, Decimal]:
        """직전 손절가 대비 10% 이상 상승 or 하락 확인.

        Returns:
            (조건 만족?, 현재가)
        """
        try:
            # 최신 1분 봉 = 현재가
            kl = self.client.get_klines(symbol=symbol, interval="1m", limit=1)
            if not kl:
                return (False, Decimal("0"))
            current = Decimal(str(kl[-1][4]))
            if prev_stop_price <= 0:
                return (False, current)
            move_pct = abs((current - prev_stop_price) / prev_stop_price) * Decimal("100")
            return (move_pct >= Decimal("10"), current)
        except Exception as e:
            logger.warning("[chart_analyzer] 가격 이동 검사 실패 %s: %s", symbol, e)
            return (False, Decimal("0"))

    def check_obv_reverse_signal(
        self,
        symbol: str,
        prev_stop_price: Decimal,
    ) -> tuple[bool, dict]:
        """OBV 재진입 종합 신호.

        3가지 조건 모두 만족 시 True:
          1. 4H OBV 첫 하락 봉
          2. 15m + 1h OBV 하락 추세
          3. 손절가 대비 10% 이상 이동

        Returns:
            (신호 발생?, {상세 정보 dict})
        """
        cond1 = self.check_4h_first_bear_bar(symbol)
        cond2 = self.check_15m_1h_bearish_trend(symbol)
        cond3, current_price = self.check_price_moved_10pct(symbol, prev_stop_price)
        signal = cond1 and cond2 and cond3
        detail = {
            "signal": signal,
            "cond_4h_first_bear": cond1,
            "cond_15m_1h_bearish": cond2,
            "cond_price_10pct": cond3,
            "current_price": str(current_price),
            "prev_stop_price": str(prev_stop_price),
        }
        if signal:
            logger.info(
                "[chart_analyzer v130] 🎯 OBV 재진입 신호! symbol=%s detail=%s",
                symbol, detail,
            )
        return (signal, detail)

    # ==========================================================================
    # 🌟 v222 (2026-08-23): 다중 시간대 통합 진입 헬퍼
    # spec: docs/MULTI_TIMEFRAME_ENTRY_SPEC_v222.md
    # ==========================================================================

    @staticmethod
    def analyze_timeframe(bc, symbol: str, interval: str, limit: int = 80) -> dict:
        """단일 시간대 지표 5개 딕셔너리 반환 (v222!).

        Returns:
            {closes, obv, rsi_now, rsi_prev, macd_hist, cci_now, cci_prev, bb_up, bb_lo}
            실패 시 {} 반환 (헌법 v127: 캐시 우선 = 인접 실행 재사용!)
        """
        try:
            # 캐시 확인 (Redis TTL = interval별 다름!)
            from app.core.redis_client import get_redis_client
            r = get_redis_client()
            cache_ttl = {"4h": 300, "1h": 180, "15m": 60}.get(interval, 60)
            # 🚨 Fix 123 (2026-08-26): 캐시 키에 limit 이 빠져 있었다!
            #   옛: kline_cache:{symbol}:{interval}
            #   → limit=20 으로 캐시된 20봉이 limit=80 요청을 그대로 만족시킨다.
            #   → peak_confirmation.confirm_peak 은 40봉(PEAK_LOOKBACK_BARS)이 필요한데
            #     20봉만 받으면 swing peak 이 적게 세어져 「정점 아님」으로 오판 =
            #     사장님 정점 SHORT 가 조용히 차단된다 (Fix 111 을 무력화!).
            #   신: limit 을 키에 포함 + 캐시가 요청보다 짧으면 재조회.
            cache_key = f"kline_cache:{symbol}:{interval}:{int(limit)}"
            kl = None
            try:
                cached = r.get(cache_key)
                if cached:
                    import json as _j
                    _c = _j.loads(cached)
                    # 길이 부족한 캐시는 버린다 (지표 창이 짧아져 오판하는 것 방지)
                    if isinstance(_c, list) and len(_c) >= min(int(limit), 30):
                        kl = _c
            except Exception:
                pass
            if not kl or not isinstance(kl, list):
                kl = bc.get_klines(symbol=symbol, interval=interval, limit=limit)
                if isinstance(kl, list) and len(kl) >= 30:
                    try:
                        import json as _j
                        r.setex(cache_key, cache_ttl, _j.dumps(kl))
                    except Exception:
                        pass
            if not isinstance(kl, list) or len(kl) < 30:
                return {}

            from app.services.bb_4h_band_analyzer import BB4HBandAnalyzer
            closes = [float(k[4]) for k in kl]
            obv = [float(x) for x in ChartAnalyzer.compute_obv(kl)]
            rsi_now = BB4HBandAnalyzer._calc_rsi(closes)
            rsi_prev = BB4HBandAnalyzer._calc_rsi(closes[:-1])
            cci = ChartAnalyzer.compute_cci(kl)
            mid, up, lo = BB4HBandAnalyzer.bollinger(closes)

            # MACD 히스토그램!
            macd_hist = []
            try:
                if len(closes) >= 35:
                    ema12 = BB4HBandAnalyzer._calc_ema(closes, 12)
                    ema26 = BB4HBandAnalyzer._calc_ema(closes, 26)
                    macd_line = [a - b for a, b in zip(ema12[26 - 12:], ema26)]
                    if len(macd_line) >= 10:
                        sig = BB4HBandAnalyzer._calc_ema(macd_line, 9)
                        if sig:
                            macd_hist = [m - s for m, s in zip(macd_line[-len(sig):], sig)]
            except Exception:
                pass

            return {
                "closes": closes,
                "obv": obv,
                "rsi_now": rsi_now,
                "rsi_prev": rsi_prev,
                "macd_hist": macd_hist,
                "cci_now": cci[-1] if cci else None,
                "cci_prev": cci[-2] if len(cci) >= 2 else None,
                "bb_up_last": up[-1] if up else None,
                "bb_lo_last": lo[-1] if lo else None,
                "kl_count": len(kl),
            }
        except Exception as e:
            logger.warning("[chart_analyzer v222] analyze_timeframe %s %s 실패: %s",
                           symbol, interval, e)
            return {}

    @staticmethod
    def compute_reversal_score(analysis: dict, side: str) -> int:
        """반전 점수 (0~5)! 4H는 5지표, 1h/15m은 부분 지표만 사용!

        SHORT = 정점 반전 (하락 시작!)
        LONG  = 저점 반전 (상승 시작!)
        """
        if not analysis:
            return 0
        score = 0
        closes = analysis.get("closes") or []
        obv = analysis.get("obv") or []
        rsi_n = analysis.get("rsi_now")
        rsi_p = analysis.get("rsi_prev")
        hist = analysis.get("macd_hist") or []
        cci_n = analysis.get("cci_now")
        cci_p = analysis.get("cci_prev")
        up = analysis.get("bb_up_last")
        lo = analysis.get("bb_lo_last")
        side_u = (side or "").upper()

        if side_u == "SHORT":
            # BB 상단 밖!
            if up is not None and closes and closes[-1] > up:
                score += 1
            # OBV 최고점 (최근 LOOKBACK 최대!)
            if len(obv) >= 20 and obv[-1] >= max(obv[-20:]):
                score += 1
            # MACD 히스토그램 최고점 + 꺾임!
            if len(hist) >= 20 and hist[-2] >= max(hist[-20:]) and hist[-1] < hist[-2]:
                score += 1
            # RSI ≥70 + 꺾임!
            if rsi_n is not None and rsi_p is not None and rsi_n >= 70 and rsi_n < rsi_p:
                score += 1
            # CCI ≥200 + 꺾임!
            if cci_n is not None and cci_p is not None and cci_n >= 200 and cci_n < cci_p:
                score += 1
        else:  # LONG!
            # BB 하단 밖!
            if lo is not None and closes and closes[-1] < lo:
                score += 1
            # OBV 최저점 (최근 LOOKBACK 최소!)
            if len(obv) >= 20 and obv[-1] <= min(obv[-20:]):
                score += 1
            # MACD 히스토그램 최저점 + 반등!
            if len(hist) >= 20 and hist[-2] <= min(hist[-20:]) and hist[-1] > hist[-2]:
                score += 1
            # RSI ≤30 + 반등!
            if rsi_n is not None and rsi_p is not None and rsi_n <= 30 and rsi_n > rsi_p:
                score += 1
            # CCI ≤-200 + 반등!
            if cci_n is not None and cci_p is not None and cci_n <= -200 and cci_n > cci_p:
                score += 1
        return score

    @staticmethod
    def multi_tf_entry_score(bc, symbol: str, side: str) -> dict:
        """3 시간대 (4h/1h/15m) 통합 진입 점수 (v222!).

        Returns:
            {enter, confidence, weighted, score_4h, score_1h, score_15m,
             signals_4h, signals_1h, signals_15m, spec_version: "v222"}
        """
        a4 = ChartAnalyzer.analyze_timeframe(bc, symbol, "4h", limit=120)
        a1 = ChartAnalyzer.analyze_timeframe(bc, symbol, "1h", limit=80)
        a15 = ChartAnalyzer.analyze_timeframe(bc, symbol, "15m", limit=60)

        s4 = ChartAnalyzer.compute_reversal_score(a4, side)   # 0~5
        s1 = ChartAnalyzer.compute_reversal_score(a1, side)   # 0~3 실 사용
        s15 = ChartAnalyzer.compute_reversal_score(a15, side)  # 0~3 실 사용
        # 1h/15m은 최대 3점만 유의미 (BB/OBV/RSI 반전만!)
        s1_capped = min(s1, 3)
        s15_capped = min(s15, 3)

        weighted = (s4 / 5.0) * 0.5 + (s1_capped / 3.0) * 0.3 + (s15_capped / 3.0) * 0.2
        # 4H 대장 최소 4/5 + weighted 0.75 이상 = 진입!
        enter = (s4 >= 4 and weighted >= 0.75)
        confidence = 0.0
        if enter:
            confidence = round(0.80 + (weighted - 0.75) * 0.6, 4)
            confidence = min(confidence, 0.95)

        return {
            "enter": enter,
            "confidence": confidence,
            "weighted": round(weighted, 4),
            "score_4h": s4,
            "score_1h": s1_capped,
            "score_15m": s15_capped,
            "side": side,
            "spec_version": "v222",
        }
