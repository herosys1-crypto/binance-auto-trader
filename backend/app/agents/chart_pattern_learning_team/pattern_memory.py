"""💾 PatternMemory = 발견 패턴 저장 + outcome 자동 tracking!

Team: Chart Pattern Learning
= chart_patterns 테이블에 저장!
= 24h/48h/7d 후 = 실제 outcome 자동 update!
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.models.chart_pattern import ChartPattern

logger = logging.getLogger(__name__)


class PatternMemory(BaseAgent):
    TEAM = "chart_pattern_learning"
    AGENT_NAME = "pattern_memory"

    def store(self, db: Session, patterns: list[dict[str, Any]]) -> int:
        """발견된 패턴 저장 (중복 방지!)."""
        stored = 0
        for p in patterns:
            try:
                # 이미 존재?
                existing = db.execute(
                    select(ChartPattern)
                    .where(ChartPattern.symbol == p["symbol"])
                    .where(ChartPattern.pattern_type == p["pattern_type"])
                    .where(ChartPattern.detected_at == p["detected_at"])
                ).scalar_one_or_none()
                if existing:
                    continue

                entry_price = p.get("entry_price")
                if entry_price is None:
                    continue

                pat = ChartPattern(
                    symbol=p["symbol"],
                    pattern_type=p["pattern_type"],
                    side=p.get("side") or "SHORT",
                    detected_at=p["detected_at"],
                    entry_price=Decimal(str(entry_price)),
                    confidence=Decimal(str(p.get("confidence") or 0)),
                    pattern_context=p.get("context") or {},
                    outcome_status="PENDING",
                )
                db.add(pat)
                stored += 1
            except Exception as e:
                logger.debug("[%s] store 실패: %s", self.AGENT_NAME, e)
                continue

        if stored:
            db.commit()
        return stored

    def track_outcomes(self, db: Session, bc, hours_max: int = 168) -> dict:
        """PENDING 패턴 = 실제 outcome 자동 계산!"""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_max)
        rows = db.execute(
            select(ChartPattern)
            .where(ChartPattern.outcome_status == "PENDING")
            .where(ChartPattern.detected_at >= cutoff)
        ).scalars().all()

        updated = 0
        success = 0
        fail = 0
        expired = 0
        price_cache: dict[str, list] = {}

        for pat in rows:
            try:
                # 심볼 = 4H 캔들 (한 번만!)
                if pat.symbol not in price_cache:
                    try:
                        kl = bc.get_klines(symbol=pat.symbol, interval="4h", limit=100)
                        price_cache[pat.symbol] = kl if isinstance(kl, list) else []
                    except Exception:
                        continue
                kl = price_cache.get(pat.symbol, [])
                if not kl:
                    continue

                entry_ms = int(pat.detected_at.timestamp() * 1000)
                entry_price = float(pat.entry_price or 0)
                if entry_price <= 0:
                    continue

                # 24h/48h/7d 후 가격!
                def _price_at(delta_h: int) -> float | None:
                    target_ms = entry_ms + delta_h * 3600 * 1000
                    if target_ms > int(datetime.now(timezone.utc).timestamp() * 1000):
                        return None  # 미래
                    for k in kl:
                        if int(k[6]) >= target_ms:
                            return float(k[4])
                    return None

                p24 = _price_at(24)
                p48 = _price_at(48)
                p7d = _price_at(168)

                if p24 is not None:
                    pat.outcome_price_24h = Decimal(str(p24))
                if p48 is not None:
                    pat.outcome_price_48h = Decimal(str(p48))
                if p7d is not None:
                    pat.outcome_price_7d = Decimal(str(p7d))

                # 판정 (48h 후!)
                is_long = pat.side == "LONG"
                if p48 is not None:
                    move_pct = ((p48 - entry_price) / entry_price) * 100
                    if is_long:
                        # LONG = 상승이 좋음!
                        pat.outcome_status = "SUCCESS" if move_pct >= 3 else "FAIL"
                    else:
                        # SHORT = 하락이 좋음!
                        pat.outcome_status = "SUCCESS" if move_pct <= -3 else "FAIL"
                    pat.outcome_max_favorable_pct = Decimal(str(round(
                        move_pct if is_long else -move_pct, 4,
                    )))
                    if pat.outcome_status == "SUCCESS":
                        success += 1
                    else:
                        fail += 1
                elif p24 is None:
                    # 24h 이후에도 = 시간 부족!
                    continue

                # 판정 없이 = 168h 지나면 EXPIRED!
                elapsed = (datetime.now(timezone.utc) - pat.detected_at).total_seconds() / 3600
                if elapsed > 168 and pat.outcome_status == "PENDING":
                    pat.outcome_status = "EXPIRED"
                    expired += 1

                pat.outcome_checked_at = datetime.now(timezone.utc)
                updated += 1
            except Exception as e:
                logger.debug("[%s] track 실패: %s", self.AGENT_NAME, e)
                continue

        db.commit()
        return {"updated": updated, "success": success, "fail": fail, "expired": expired}
