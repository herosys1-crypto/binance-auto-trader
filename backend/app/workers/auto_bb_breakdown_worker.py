"""🤖 AutoBBBreakdownWorker = BB 이탈 SUSTAINED 자동 진입! (v162 사장님!)

배경 (사장님 요청 2026-08-16):
"확률 85% 이상 추천 세팅할 수 있게 해주고 잘되면 자동으로 진행!
 지금 수동으로 바로 진입만 승인!
 자동으로 진입하는 전략 수량을 내가 1이상 설정할 수 있게 옵션!"

로직 (매 4시간!):
- system_settings 「auto_bb_break_daily_limit」 확인!
- 0 = OFF (수동만!)
- 1+ = 하루 최대 N개 = 자동 진입!
- SUSTAINED (3봉+ 지속 이탈!) 만 대상!
- 상위 confidence (24h 변동 큰 순!)
- 이미 오늘 진입 개수 확인 = 초과 X!
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.system_setting import SystemSetting
from app.models.strategy_suggestion import StrategySuggestion

logger = logging.getLogger(__name__)


def run_auto_bb_breakdown() -> dict:
    """매 4시간 = SUSTAINED 심볼 자동 진입! (사장님 옵션에 따라!)"""
    db: Session = SessionLocal()
    entered = 0
    skipped = 0
    try:
        # 1. 사장님 옵션 확인!
        limit_row = db.get(SystemSetting, "auto_bb_break_daily_limit")
        daily_limit = int(limit_row.value) if limit_row and limit_row.value else 0
        if daily_limit <= 0:
            return {"note": "auto_bb_break_daily_limit=0 (OFF!)", "entered": 0}

        # 2. 오늘 자동 진입 개수 확인!
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        today_auto_count = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.status == "EXECUTED")
            .where(StrategySuggestion.execution_mode == "AUTO")
            .where(StrategySuggestion.executed_at >= today_start)
            .where(StrategySuggestion.suggestion_type == "bb4h_bounce_failure")
        ).scalars().all()
        already_entered = len(today_auto_count)
        remaining = daily_limit - already_entered
        if remaining <= 0:
            return {
                "note": f"오늘 이미 {already_entered}건 진입 완료 (limit={daily_limit})",
                "entered": 0,
            }

        # 3. v165: SUSTAINED 심볼 조회 = 성공률 순 정렬!
        # bb_middle_scan.py의 scan_bb_breakdown 로직 재사용!
        from app.api.v1.bb_middle_scan import scan_bb_breakdown
        try:
            # SHORT (down!) + LONG (up!) 각각 스캔!
            scan_short = scan_bb_breakdown(
                interval="4h", direction="down", max_symbols=100,
                db=db, user_id=1,
            )
            scan_long = scan_bb_breakdown(
                interval="4h", direction="up", max_symbols=100,
                db=db, user_id=1,
            )
        except Exception as e:
            logger.warning("[auto_bb_breakdown] 스캔 실패: %s", e)
            return {"error": f"scan failed: {e}", "entered": 0}

        # SUSTAINED 통합 (성공률 순!)
        all_sustained = []
        for it in (scan_short.get("sustained") or []):
            all_sustained.append({**it, "side": "SHORT"})
        for it in (scan_long.get("sustained") or []):
            all_sustained.append({**it, "side": "LONG"})
        # 성공률 큰 순!
        all_sustained.sort(key=lambda x: -(x.get("success_probability") or 0))

        # v165 MVP: 로그 (다음 단계 = 실 진입!)
        top_picks = []
        for it in all_sustained[:remaining]:
            top_picks.append({
                "symbol": it["symbol"],
                "side": it["side"],
                "success_probability": it.get("success_probability"),
                "sustained_bars": it.get("sustained_bars"),
                "note": "다음 단계 = 실 create_strategy_instance 호출!",
            })
        logger.info(
            "[auto_bb_breakdown] v165: limit=%d, remaining=%d, top_picks=%d",
            daily_limit, remaining, len(top_picks),
        )
        return {
            "daily_limit": daily_limit,
            "today_auto_entered": already_entered,
            "remaining": remaining,
            "sustained_total": len(all_sustained),
            "top_picks": top_picks,
            "note": (
                "v165 = 성공률 순 정렬 완료! "
                "실 진입 = 다음 단계 (수동 검증 후!)"
            ),
        }
    except Exception as e:
        logger.warning("[auto_bb_breakdown] 실행 실패: %s", e)
        return {"error": str(e)}
    finally:
        db.close()
