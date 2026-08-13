"""📉 BB4HScanner = 자동 전략 제안을 4시간봉 볼밴 기준으로! (v143a 신!)

Team: Strategy Suggestion
사장님 최종 결정 2026-08-14:
  "자동전략 제안은 4시간봉이 볼밴 중단과 하단 깨는 경우로 해줘 롱과 숏을"

= 기존 PumpDumpPredictor(24h 급등락 순위)를 대체하는 **실측 기반 제안 소스**.

4가지 트리거 (전부 실측 기대값 양수, 롱·숏 대칭):

  ┌ 중단 하향 이탈 → SHORT : 하단 도달 82.8%, SL -5% 기대값 **+0.42%** (13,053건)
  ├ 중단 상향 돌파 → LONG  : 상단 도달 86.6%, SL -5% 기대값 **+0.44%** (13,045건)
  ├ 하단 하향 이탈 → SHORT : 추가 하락 중앙 8.13%, +5%/-5% 기대값 +0.14% (5,286건)
  └ 상단 상향 돌파 → LONG  : 추가 상승 중앙 10.23%, +8%/-5% 기대값 +0.27% (5,802건)

  (scripts/study_4h_bb_middle_break.py — 178심볼 × 215,561 4h 캔들)

⚠️ 중단 이탈이 밴드 이탈보다 기대값이 2~3배 높습니다 → confidence 에 반영합니다.

헌법 v143a:
  '자동 제안은 24h 순위가 아니라 **실측 기대값이 있는 신호**에서 나온다'
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent
from app.services.bb_4h_band_analyzer import BB4HBandAnalyzer

logger = logging.getLogger(__name__)


class BB4HScanner(BaseAgent):
    TEAM = "strategy_suggestion"
    AGENT_NAME = "bb_4h_scanner"

    # 스캔 대상 = 24h 거래대금 상위 N (API 호출 한도 고려)
    SCAN_TOP_N = 100
    # 이탈 후 몇 봉까지 「신선한」 신호로 볼 것인가
    FRESH_BARS = 2

    # (트리거, side, TP%, SL%, 기대값%, 표본, confidence)
    PLAYS = {
        "MID_DOWN": ("SHORT", None, 5.0, 0.42, 13053, 0.78),   # TP = 하단 (동적)
        "MID_UP": ("LONG", None, 5.0, 0.44, 13045, 0.80),      # TP = 상단 (동적)
        "LOWER_BREAK": ("SHORT", 5.0, 5.0, 0.14, 5286, 0.62),
        "UPPER_BREAK": ("LONG", 8.0, 5.0, 0.27, 5802, 0.68),
    }

    def _top_symbols(self, bc) -> list[str]:
        """24h 거래대금 상위 USDT 선물 심볼."""
        try:
            tickers = bc.get_24hr_ticker()
            if not isinstance(tickers, list):
                return []
            usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
            usdt.sort(key=lambda x: float(x.get("quoteVolume", 0) or 0), reverse=True)
            return [str(t["symbol"]) for t in usdt[: self.SCAN_TOP_N]]
        except Exception as e:
            logger.warning("[%s] 심볼 목록 조회 실패: %s", self.AGENT_NAME, e)
            return []

    @classmethod
    def classify(cls, st: dict) -> str | None:
        """4H BB 상태 → 트리거 종류.

        우선순위: **밴드 이탈 > 중단 이탈** (밴드를 깬 게 더 최근 사건이므로).
        단 confidence 는 중단 이탈이 더 높습니다 (실측 기대값 2~3배).
        """
        if not st.get("available"):
            return None
        close = st.get("close")
        lower, upper = st.get("lower"), st.get("upper")
        if close is None or lower is None or upper is None:
            return None

        # 1) 밴드 밖으로 종가 마감 = 밴드 이탈
        if close < lower:
            return "LOWER_BREAK"
        if close > upper:
            return "UPPER_BREAK"

        # 2) 중단 이탈이 신선한가?
        cross = st.get("cross")
        bars = st.get("bars_since_cross")
        if cross and bars is not None and bars <= cls.FRESH_BARS:
            return "MID_DOWN" if cross == "DOWN" else "MID_UP"
        return None

    @classmethod
    def build_prediction(cls, symbol: str, trigger: str, st: dict) -> dict[str, Any]:
        """트리거 → 제안 dict (PumpDumpPredictor 와 같은 형식)."""
        side, tp_pct, sl_pct, ev, n, conf = cls.PLAYS[trigger]
        close = st.get("close") or 0
        mid, lower, upper = st.get("mid"), st.get("lower"), st.get("upper")

        if trigger == "MID_DOWN":
            target = lower
            reason = (
                f"📉 4H 중단 하향 이탈 → 하단 목표! "
                f"실측 도달률 82.8% (표본 {n:,}건), 예상 20시간. "
                f"SL -{sl_pct:.0f}% 기준 기대값 {ev:+.2f}%"
            )
        elif trigger == "MID_UP":
            target = upper
            reason = (
                f"📈 4H 중단 상향 돌파 → 상단 목표! "
                f"실측 도달률 86.6% (표본 {n:,}건), 예상 16시간. "
                f"SL -{sl_pct:.0f}% 기준 기대값 {ev:+.2f}%"
            )
        elif trigger == "LOWER_BREAK":
            target = close * (1 - tp_pct / 100) if close else None
            reason = (
                f"📉 4H **하단 이탈**! 실측 추가 하락 중앙값 8.13% (표본 {n:,}건). "
                f"+{tp_pct:.0f}%/-{sl_pct:.0f}% 기준 기대값 {ev:+.2f}% "
                "(⚠️ 중단 이탈보다 기대값 낮음)"
            )
        else:  # UPPER_BREAK
            target = close * (1 + tp_pct / 100) if close else None
            reason = (
                f"📈 4H **상단 돌파**! 실측 추가 상승 중앙값 10.23% (표본 {n:,}건). "
                f"+{tp_pct:.0f}%/-{sl_pct:.0f}% 기준 기대값 {ev:+.2f}% "
                "(⚠️ 중단 이탈보다 기대값 낮음)"
            )

        change_pct = None
        if close and target:
            change_pct = round((target - close) / close * 100, 2)

        return {
            "symbol": symbol,
            "type": f"bb4h_{trigger.lower()}",
            "side": side,
            "confidence": conf,
            "change_pct": change_pct,
            "volume": 0,
            "reason": reason,
            # 참고 레벨 (generator 가 config 로 쓸 수 있게)
            "bb_mid": mid,
            "bb_lower": lower,
            "bb_upper": upper,
            "target_price": target,
            "sl_pct": sl_pct,
            "expected_value_pct": ev,
        }

    def execute(self, db, decrypt_text) -> dict:
        """4H BB 스캔 → 제안 후보 리스트."""
        self.validate("BB4H_SCAN")

        from sqlalchemy import select
        from app.integrations.binance.client import BinanceClient
        from app.models.exchange_account import ExchangeAccount

        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            return {"predictions": [], "error": "no mainnet account"}

        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )

        symbols = self._top_symbols(bc)
        analyzer = BB4HBandAnalyzer(bc)
        predictions: list[dict] = []
        counts: dict[str, int] = {}

        for sym in symbols:
            try:
                kl = bc.get_klines(symbol=sym, interval="4h",
                                   limit=BB4HBandAnalyzer.KLINE_LIMIT)
                if not isinstance(kl, list):
                    continue
                st = analyzer.state(kl)
                trigger = self.classify(st)
                if not trigger:
                    continue
                predictions.append(self.build_prediction(sym, trigger, st))
                counts[trigger] = counts.get(trigger, 0) + 1
            except Exception as e:
                logger.debug("[%s] %s 스캔 실패: %s", self.AGENT_NAME, sym, e)
                continue

        # 기대값 높은 신호(중단 이탈)를 앞으로!
        predictions.sort(key=lambda p: -float(p.get("confidence") or 0))

        logger.info(
            "[%s] 4H BB 스캔 완료: %d심볼 중 %d건 (%s)",
            self.AGENT_NAME, len(symbols), len(predictions), counts,
        )
        return {"predictions": predictions, "scanned": len(symbols), "counts": counts}
