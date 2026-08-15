"""🔍 PatternDetector = v149/v150/v151 로직 = 과거 패턴 스캔!

Team: Chart Pattern Learning
= 1달치 4H 캔들 = 매 봉 슬라이딩 → 패턴 감지!
= 발견 시 = 그 시점 = 「감지 이벤트」 기록!
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.agents.base import BaseAgent
from app.services.bb_4h_band_analyzer import BB4HBandAnalyzer

logger = logging.getLogger(__name__)


class PatternDetector(BaseAgent):
    TEAM = "chart_pattern_learning"
    AGENT_NAME = "pattern_detector"

    # 슬라이딩 윈도우 = 최근 N봉씩 검사!
    # 1달 (180봉) 중 = 최근 30봉 = 대상!
    SCAN_TAIL_BARS = 30

    def scan(self, symbol: str, klines_4h: list) -> list[dict[str, Any]]:
        """과거 시점별 = 패턴 감지!

        각 시점 = 앞뒤 캔들 슬라이싱해서 v149/v150/v151 signal 호출!
        """
        detected: list[dict[str, Any]] = []
        if not klines_4h or len(klines_4h) < 100:
            return detected

        # 최근 30봉 = 각 시점에서 감지 시도!
        # (초기 검사는 = 미래 데이터 없음이라 outcome 판정 불가!)
        for i in range(len(klines_4h) - self.SCAN_TAIL_BARS, len(klines_4h)):
            # 그 시점까지의 데이터로 = 스캔 (미래 데이터 X)
            slice_kl = klines_4h[:i + 1]
            if len(slice_kl) < 60:
                continue

            # 그 시점의 close_time!
            close_time_ms = int(slice_kl[-1][6])
            detected_at = datetime.fromtimestamp(close_time_ms / 1000, tz=timezone.utc)

            # 3가지 신호 검사!
            for sig_func, sig_name in [
                (BB4HBandAnalyzer.bounce_failure_signal, "bb4h_bounce_failure"),
                (BB4HBandAnalyzer.bottom_reversal_signal, "bb4h_bottom_reversal"),
                (BB4HBandAnalyzer.top_reversal_signal, "bb4h_top_reversal"),
            ]:
                try:
                    result = sig_func(slice_kl)
                    if not result.get("detected"):
                        continue
                    conf = float(result.get("confidence") or 0)
                    if conf < 0.85:
                        continue
                    detected.append({
                        "symbol": symbol,
                        "pattern_type": sig_name,
                        "side": result.get("side"),
                        "detected_at": detected_at,
                        "entry_price": result.get("current_price"),
                        "confidence": conf,
                        "context": {k: v for k, v in result.items() if k not in ("detected", "reason")},
                    })
                except Exception as e:
                    logger.debug("[%s] %s 스캔 실패: %s", self.AGENT_NAME, symbol, e)
                    continue

        return detected
