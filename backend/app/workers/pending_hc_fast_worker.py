"""🎯 v218 (2026-08-22 사장님!): PENDING_HC 급속 진입 워커!

사장님 요구 (verbatim, 2026-08-22):
"실시간으로 급등과 급락을 하는 심볼들을 매매하기 때문에 = 빠른 대응 필요!"

## 배경:
auto_bb_breakdown = 1h 주기 (v218 = 4h → 1h!) = API 부담으로 그 이상 X!
= 하지만 = PENDING 85%+ suggestion (DB만 조회!) = **매 2분** 즉시 진입 가능!

## 로직:
1. daily_limit 체크! (auto_bb_break_daily_limit!)
2. PENDING 85%+ suggestion 조회 (API X!)
3. 활성 심볼 제외!
4. 급등/급락 필터 (헌법 64: 24h ±15%!)
5. auto_bb_breakdown_worker의 `_create_auto_bb_strategy` 재사용!
6. 성공 시 = 원본 suggestion = EXECUTED 갱신!

## 안전:
- daily_limit 공유 (auto_bb_breakdown과!)
- 활성 심볼 skip
- 최근 24h 손실 심볼 skip
- fail-open X (v218 fix: 실패 = suggestion PENDING 유지!)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.strategy_suggestion import StrategySuggestion

logger = logging.getLogger(__name__)

MAX_PER_CYCLE = 5  # 한 사이클 최대 5건 (남발 방지!)


def run_pending_hc_fast() -> dict:
    """매 2분 = PENDING_HC 급속 진입!"""
    db: Session = SessionLocal()
    entered = 0
    skipped = 0
    results: list[dict] = []
    try:
        # 1. daily_limit 체크!
        from app.models.system_setting import SystemSetting
        limit_row = db.get(SystemSetting, "auto_bb_break_daily_limit")
        daily_limit = int(limit_row.value) if limit_row and limit_row.value else 0
        if daily_limit <= 0:
            return {"note": "daily_limit=0 (OFF!)", "entered": 0}

        # 2. auto_bb_breakdown_worker에서 함수 재사용!
        from app.workers.auto_bb_breakdown_worker import (
            _count_used_slots, _create_auto_bb_strategy,
            _get_active_symbol_keys, _get_recent_loss_symbol_keys,
        )
        # 🎯 Fix 112b (2026-08-26): 동시 보유 상한 = 이 워커도 신규 포지션을 만든다!
        from app.services.position_limit import check_position_slot
        _slot_ok, _slot_why, _act, _cap = check_position_slot(db, "pending_hc_fast")
        if not _slot_ok:
            logger.warning("[pending_hc_fast+Fix112b] SKIP: %s", _slot_why)
            return {"note": _slot_why, "entered": 0}

        used = _count_used_slots(db)
        remaining = min(daily_limit - used, _cap - _act)   # 두 예산 중 작은 쪽!
        if remaining <= 0:
            return {"note": f"daily {used}/{daily_limit} concurrent {_act}/{_cap}", "entered": 0}

        # 3. PENDING 85%+ suggestion 조회 (DB만 = API X!)
        pending_hc = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.status == "PENDING")
            .where(StrategySuggestion.confidence_score >= Decimal("0.85"))
            .order_by(StrategySuggestion.confidence_score.desc())
            .limit(MAX_PER_CYCLE * 3)  # 필터 후 부족 대비 3배!
        ).scalars().all()
        if not pending_hc:
            return {"note": "PENDING_HC 없음!", "entered": 0}

        # 4. 활성 심볼 + 최근 24h 손실 심볼 제외!
        active_keys = _get_active_symbol_keys(db)
        recent_loss_keys = _get_recent_loss_symbol_keys(db)

        # 5. 각 후보 진입!
        for ps in pending_hc:
            if remaining <= 0 or entered >= MAX_PER_CYCLE:
                break

            key = f"{ps.symbol}:{ps.side}"
            if key in active_keys:
                skipped += 1
                continue
            if key in recent_loss_keys:
                skipped += 1
                continue

            _pcfg = ps.strategy_config if isinstance(ps.strategy_config, dict) else {}
            # 🚨 Fix 236 (2026-08-31 사장님): 하드코딩 자본 기본값 제거.
            #   옛 코드는 설정에 capitals 가 없으면 **500 USDT 를 지어내** 진입했다.
            #   사장님이 정하지 않은 금액으로 실자금이 나가는 경로다 → fail-closed.
            _capitals = _pcfg.get("capitals") or []
            if not _capitals:
                skipped += 1
                logger.warning(
                    "[Fix236] %s %s 자본 설정 없음 = 진입 skip "
                    "(하드코딩 기본값 금지 — 사장님이 정한 값만 쓴다)",
                    ps.symbol, ps.side,
                )
                continue
            _leverage = _pcfg.get("leverage", 2)
            cfg = {"capitals": _capitals, "leverage": _leverage}

            try:
                new_strategy = _create_auto_bb_strategy(
                    db, ps.symbol, ps.side, cfg,
                    strategy_type_suffix="_PENDING_HC_FAST",
                )
                # v218 fix: 실패 시 = None 반환 = suggestion PENDING 유지 (재시도!)
                if not new_strategy:
                    skipped += 1
                    logger.info(
                        "[PENDING_HC_FAST] ❌ %s %s 진입 실패 = PENDING 유지 (재시도!)",
                        ps.symbol, ps.side,
                    )
                    continue

                # 원본 suggestion = EXECUTED 갱신!
                ps.status = "EXECUTED"
                ps.execution_mode = "AUTO"
                ps.executed_at = datetime.now(timezone.utc)
                ps.executed_strategy_id = new_strategy.id
                ps.outcome_status = "PENDING"

                db.commit()
                remaining -= 1
                entered += 1
                results.append({
                    "symbol": ps.symbol, "side": ps.side,
                    "confidence": float(ps.confidence_score or 0),
                    "strategy_id": new_strategy.id,
                    "suggestion_id": ps.id,
                })
                logger.info(
                    "[PENDING_HC_FAST] ✅ %s %s 급속 진입! conf=%.0f%% (id=%d)",
                    ps.symbol, ps.side,
                    float(ps.confidence_score or 0) * 100, new_strategy.id,
                )
            except Exception as e:
                logger.warning(
                    "[PENDING_HC_FAST] %s %s 진입 실패: %s",
                    ps.symbol, ps.side, e,
                )
                skipped += 1
                db.rollback()

        logger.info(
            "[PENDING_HC_FAST] 완료: entered=%d skipped=%d",
            entered, skipped,
        )
        return {
            "entered": entered,
            "skipped": skipped,
            "results": results,
        }
    except Exception as e:
        logger.exception("[PENDING_HC_FAST] 실행 실패: %s", e)
        return {"error": str(e), "entered": 0}
    finally:
        db.close()
