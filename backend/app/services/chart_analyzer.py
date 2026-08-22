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
