"""🔍 AnalysisAgent = 패턴 발견!

역할:
- MemoryAgent 데이터 → 패턴 분석!
- 심볼별 성공 패턴!
- 시간대별 성공률!
- 진입 X 심볼 = 놓친 기회!
- 인사이트 생성!
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class AnalysisAgent(BaseAgent):
    TEAM = "learning"
    AGENT_NAME = "analysis_agent"

    def execute(self, memory_data: dict[str, Any]) -> dict[str, Any]:
        """패턴 발견!"""
        trades = memory_data.get("trades", []) or []
        suggestions = memory_data.get("suggestions", []) or []
        observations = memory_data.get("observations", []) or []

        insights: list[dict[str, Any]] = []

        # 1. 거래 성공률 (심볼별)
        trade_stats: dict[str, dict[str, float]] = {}
        for t in trades:
            if not t.pnl_pct:
                continue
            s = trade_stats.setdefault(t.symbol, {"wins": 0, "losses": 0, "pnl_sum": 0.0})
            pnl = float(t.pnl_pct or 0)
            if pnl > 0:
                s["wins"] += 1
            elif pnl < 0:
                s["losses"] += 1
            s["pnl_sum"] += pnl
        top_trade_symbols = sorted(
            trade_stats.items(),
            key=lambda x: x[1]["pnl_sum"],
            reverse=True,
        )[:5]

        # 2. 예측 성공률 (심볼별)
        pred_stats: dict[str, dict[str, int]] = {}
        for s in suggestions:
            if s.outcome_status not in ("SUCCESS", "FAIL"):
                continue
            ps = pred_stats.setdefault(s.symbol, {"total": 0, "wins": 0})
            ps["total"] += 1
            if s.outcome_status == "SUCCESS":
                ps["wins"] += 1

        top_pred_symbols = sorted(
            [(sym, s["wins"] / s["total"] if s["total"] else 0, s["total"])
             for sym, s in pred_stats.items() if s["total"] >= 2],
            key=lambda x: x[1],
            reverse=True,
        )[:5]

        # 3. 관찰: 진입 X 심볼 중 큰 변동 = 놓친 기회!
        big_moves = [
            {
                "symbol": o.symbol,
                "observed_at": o.observed_at.isoformat() if o.observed_at else None,
                "change_24h": float(o.change_24h_later or 0),
                "side_would_have": o.side_would_have,
            }
            for o in observations
            if o.change_24h_later is not None and abs(float(o.change_24h_later)) >= 5
        ][:20]

        # 인사이트 생성!
        if top_trade_symbols:
            best_sym, best_stats = top_trade_symbols[0]
            insights.append({
                "type": "TOP_TRADE",
                "level": "info",
                "text": f"🏆 최고 수익 심볼: {best_sym} = 누적 {best_stats['pnl_sum']:+.1f}% ({best_stats['wins']}승 {best_stats['losses']}패!)",
            })

        if top_pred_symbols:
            best_sym, best_rate, total = top_pred_symbols[0]
            insights.append({
                "type": "TOP_PREDICTION",
                "level": "info",
                "text": f"🎯 최고 예측 심볼: {best_sym} = 성공률 {best_rate*100:.0f}% ({total}건!)",
            })

        # 놓친 기회!
        if big_moves:
            miss = big_moves[0]
            insights.append({
                "type": "MISSED_OPPORTUNITY",
                "level": "warn",
                "text": f"💡 놓친 기회: {miss['symbol']} = 24h {miss['change_24h']:+.1f}% (진입했으면 {miss['side_would_have']}!)",
            })

        # 4. 트레일링 늦음 감지!
        trail_late = sum(
            1 for t in trades
            if t.max_profit_pct and float(t.max_profit_pct) >= 20
            and t.pnl_pct is not None and float(t.pnl_pct) < 5
        )
        if trail_late >= 3:
            insights.append({
                "type": "TRAIL_LATE",
                "level": "warn",
                "text": f"⚠️ 트레일링 늦음 {trail_late}건! (피크 +20%+ 도달 후 <+5%로 종료!)",
            })

        return {
            "insights": insights,
            "top_trade_symbols": [
                {"symbol": s, "pnl_sum": st["pnl_sum"], "wins": st["wins"], "losses": st["losses"]}
                for s, st in top_trade_symbols
            ],
            "top_pred_symbols": [
                {"symbol": s, "rate": round(r * 100, 1), "total": t}
                for s, r, t in top_pred_symbols
            ],
            "big_moves_missed": big_moves,
            "trail_late_count": trail_late,
        }
