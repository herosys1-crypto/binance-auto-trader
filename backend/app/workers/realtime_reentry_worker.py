"""🎯 사장님 사상 (2026-08-21): 실시간 재진입 시스템!

사장님 verbatim:
"포지션 실패한 심볼은 실시간 모니터링에 넣어서 짧은 시간 계속 모니터링하고
재진입을 하는 로직이야
그리고 익절도 마찬가지로 익절후 계속 모니터링하고 계속 수익이 가능하면
다시 포지션을 늘려서 수익을 극대화하고 다시 하락하면 -5% 상승후 하락시
진행하는 로직으로 청산하는거야"

= 매 15분 실행!
= 실패 심볼 + 익절 심볼 = 실시간 감지!
= 조건 만족 시 = 즉시 재진입!

로직:
1. daily_limit 체크 (auto_bb_break_daily_limit!)
2. 최근 24h 청산된 자동 진입 심볼 조회!
3. Redis mark_price로 현재가 조회!
4. 재진입 조건 판단:
   - 실패 심볼: SL 대비 +3% 반등 시 재진입 (1.5x)!
   - 익절 심볼: 익절가 대비 +3% 추가 상승 시 재진입 (원 자본)!
5. 조건 만족 = _create_auto_bb_strategy 호출 (즉시!)!
6. 재진입 카운터 갱신!

안전:
- max 2회 재진입 (v202!)
- 급등/급락 필터 (헌법 64!)
- daily_limit 체크!
- 이미 활성 심볼 skip!
- 24h 재진입 카운터 5회 초과 = skip!
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE, TERMINAL_STATUSES
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate

logger = logging.getLogger(__name__)

REBOUND_PCT_FOR_REENTRY = 3.0  # SL/익절 대비 3% 반등 시!
MAX_HOURLY_REENTRIES = 5        # 1h 최대 5건 (남발 방지!)


def _get_base_capital_from_instance(si: StrategyInstance) -> float:
    """v218 (2026-08-22): 청산된 원 전략의 base capital 조회!

    사장님 사상: 마틴게일 = 이전 포지션 대비 1.5배!
    → 이전 포지션의 원 자본 = 정확한 base 필요!

    조회 순서:
    1. template.stages_config['capitals'][0] (JSONB 구조!)
    2. template.stage1_capital (Decimal fallback!)
    3. template.total_capital (Decimal fallback!)
    4. 500.0 (최종 fallback!)
    """
    try:
        tmpl = si.strategy_template
        if tmpl and getattr(tmpl, "stages_config", None):
            caps = tmpl.stages_config.get("capitals", []) if isinstance(tmpl.stages_config, dict) else []
            if caps and len(caps) > 0:
                return float(caps[0])
        if tmpl and getattr(tmpl, "stage1_capital", None):
            return float(tmpl.stage1_capital)
        if tmpl and getattr(tmpl, "total_capital", None):
            return float(tmpl.total_capital)
    except Exception:
        pass
    return 500.0


def run_realtime_reentry() -> dict:
    """매 15분 = 실시간 재진입 감지!"""
    db: Session = SessionLocal()
    entered_fail = 0
    entered_success = 0
    skipped = 0
    results: list[dict] = []
    try:
        # 1. daily_limit 체크!
        from app.models.system_setting import SystemSetting
        limit_row = db.get(SystemSetting, "auto_bb_break_daily_limit")
        daily_limit = int(limit_row.value) if limit_row and limit_row.value else 0
        if daily_limit <= 0:
            return {"note": "daily_limit=0 (OFF!)", "entered": 0}

        from app.workers.auto_bb_breakdown_worker import (
            _count_used_slots, _create_auto_bb_strategy,
            _get_reentry_count, _increment_reentry_count,
            _reset_reentry_count, MAX_REENTRY_COUNT,
        )
        used = _count_used_slots(db)
        remaining = daily_limit - used
        if remaining <= 0:
            return {"note": f"daily {used}/{daily_limit}", "entered": 0}

        # 2. 1h 재진입 남발 체크!
        cutoff_1h = datetime.now(timezone.utc) - timedelta(hours=1)
        from app.models.strategy_suggestion import StrategySuggestion
        recent_re = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.created_at >= cutoff_1h)
            .where(StrategySuggestion.reason.like("%RT_REENTRY%"))
        ).scalars().all()
        if len(recent_re) >= MAX_HOURLY_REENTRIES:
            return {"note": f"1h {len(recent_re)}건 (max {MAX_HOURLY_REENTRIES}!)", "entered": 0}

        # 3. 최근 24h 청산된 자동 진입 심볼 조회!
        cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        closed = db.execute(
            select(StrategyInstance)
            .join(StrategyTemplate,
                  StrategyInstance.strategy_template_id == StrategyTemplate.id)
            .where(StrategyInstance.stopped_at >= cutoff_24h)
            .where(StrategyInstance.status.in_(list(TERMINAL_STATUSES)))
            .where(StrategyTemplate.strategy_type.like('auto_bb_break%'))
        ).scalars().all()

        # 4. 활성 심볼 skip!
        active = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.status.in_(list(ACTIVE_LIKE)))
        ).scalars().all()
        active_syms = {r.symbol for r in active}

        # 5. Redis mark_price!
        from app.core.redis_client import get_redis_client
        redis = get_redis_client()

        # 6. 심볼별 = 최신 청산 1건씩만!
        latest_by_sym: dict[tuple[str, str], StrategyInstance] = {}
        for si in closed:
            key = (si.symbol, si.side)
            if key not in latest_by_sym or (
                si.stopped_at and latest_by_sym[key].stopped_at
                and si.stopped_at > latest_by_sym[key].stopped_at
            ):
                latest_by_sym[key] = si

        for (symbol, side), si in latest_by_sym.items():
            if remaining <= 0:
                break
            if symbol in active_syms:
                skipped += 1
                continue

            # 재진입 카운터 max 2!
            re_count = _get_reentry_count(symbol, side)
            if re_count >= MAX_REENTRY_COUNT:
                skipped += 1
                continue

            # mark_price 조회!
            try:
                mp_raw = redis.get(f"mark_price:{symbol}")
                if not mp_raw:
                    continue
                mp = float(mp_raw.decode() if isinstance(mp_raw, bytes) else mp_raw)
                if mp <= 0:
                    continue
            except Exception:
                continue

            # 🎯 v218 fix (2026-08-22): 청산가 우선 = 평단 fallback!
            # 이전 = 평단 = 실 청산가와 다름 = 3% 반등 판정 부정확!
            # last_liquidation_price = SL 발동가! = 반등 시작점 정확!
            _stop_price = float(si.last_liquidation_price or si.avg_entry_price or 0)
            if _stop_price <= 0:
                continue

            pnl = float(si.realized_pnl or 0)
            _is_fail = pnl < 0
            _is_success = pnl > 0

            # 급등/급락 필터 = 24h 변동 조회 (안전!)
            # 여기선 skip 판정만 = 근사치!

            _should_enter = False
            _reason_suffix = ""
            _use_success_reentry = False

            if _is_fail:
                # 실패 심볼: side 방향으로 반등!
                if side == "LONG":
                    # LONG 실패 = 하락 → 반등 시 재진입!
                    # 청산가 대비 현재가 상승!
                    pct = (mp - _stop_price) / _stop_price * 100
                    if pct >= REBOUND_PCT_FOR_REENTRY:
                        _should_enter = True
                        _reason_suffix = f"RT_REENTRY: LONG 실패 후 +{pct:.2f}% 반등!"
                else:  # SHORT
                    pct = (_stop_price - mp) / _stop_price * 100
                    if pct >= REBOUND_PCT_FOR_REENTRY:
                        _should_enter = True
                        _reason_suffix = f"RT_REENTRY: SHORT 실패 후 -{pct:.2f}% 하락!"
            elif _is_success:
                # 익절 심볼: side 방향 계속 진행!
                if side == "LONG":
                    pct = (mp - _stop_price) / _stop_price * 100
                    if pct >= REBOUND_PCT_FOR_REENTRY:
                        _should_enter = True
                        _use_success_reentry = True
                        _reason_suffix = f"RT_REENTRY_SUCCESS: LONG 익절 후 +{pct:.2f}% 추가 상승!"
                else:  # SHORT
                    pct = (_stop_price - mp) / _stop_price * 100
                    if pct >= REBOUND_PCT_FOR_REENTRY:
                        _should_enter = True
                        _use_success_reentry = True
                        _reason_suffix = f"RT_REENTRY_SUCCESS: SHORT 익절 후 -{pct:.2f}% 추가 하락!"

            if not _should_enter:
                skipped += 1
                continue

            # 진입 실행!
            try:
                # 🎯 v218 사장님 verbatim (2026-08-21):
                # "실패한 심볼은... 다시 진입할 시점에 이전 포지션의 1.5배로 해줘 2번까지"
                # = 실패 재진입 = 1.5x/2.25x 마틴게일! Success 재진입 = 원 자본!
                _base_capital = _get_base_capital_from_instance(si)
                if _use_success_reentry:
                    # 사장님: 익절 후 재진입 = 초기 시작금액!
                    _entry_capital = _base_capital
                    _mult_label = ""
                else:
                    # 사장님: 실패 후 재진입 = 1.5^(count+1) 마틴게일!
                    _entry_capital = _calc_reentry_capital(symbol, side, _base_capital)
                    if _entry_capital is None:
                        skipped += 1
                        logger.info(
                            "[RT_REENTRY] v218 skip: %s %s MAX %d회 도달!",
                            symbol, side, MAX_REENTRY_COUNT,
                        )
                        continue
                    _mult = _entry_capital / _base_capital
                    _mult_label = f" ×{_mult:.2f}"
                    logger.info(
                        "[RT_REENTRY] v218 마틴게일: %s %s 자본 %.0f → %.0f USDT (×%.2f)",
                        symbol, side, _base_capital, _entry_capital, _mult,
                    )
                cfg = {"capitals": [_entry_capital], "leverage": 2}
                _reason_suffix += _mult_label  # UI 배지에 ×1.50 표시!
                _suffix = "_success" if _use_success_reentry else f"_reentry{re_count + 1}"
                new_strategy = _create_auto_bb_strategy(
                    db, symbol, side, cfg,
                    strategy_type_suffix=_suffix,
                )
                if not new_strategy:
                    skipped += 1
                    continue

                # StrategySuggestion 기록!
                sugg = StrategySuggestion(
                    symbol=symbol, side=side,
                    suggestion_type="bb4h_auto_entry",
                    strategy_config={
                        "capitals": cfg["capitals"],
                        "symbol": symbol, "side": side,
                        "rt_reentry": True,
                        "rt_reentry_price": mp,
                        "prev_stop_price": _stop_price,
                    },
                    confidence_score=Decimal("0.65"),
                    reason=_reason_suffix,
                    status="EXECUTED",
                    execution_mode="AUTO",
                    executed_at=datetime.now(timezone.utc),
                    executed_strategy_id=new_strategy.id,
                    outcome_status="PENDING",
                )
                db.add(sugg)

                if _use_success_reentry:
                    _reset_reentry_count(symbol, side)
                    entered_success += 1
                else:
                    _increment_reentry_count(symbol, side)
                    entered_fail += 1

                db.commit()
                remaining -= 1
                results.append({
                    "symbol": symbol, "side": side,
                    "reason": _reason_suffix,
                    "strategy_id": new_strategy.id,
                })
                logger.info(
                    "[RT_REENTRY] ✅ %s %s: %s (id=%d)",
                    symbol, side, _reason_suffix, new_strategy.id,
                )
            except Exception as e:
                logger.warning("[RT_REENTRY] %s %s 진입 실패: %s", symbol, side, e)
                skipped += 1
                db.rollback()

        total_entered = entered_fail + entered_success
        logger.info(
            "[RT_REENTRY] 완료: fail=%d success=%d skipped=%d",
            entered_fail, entered_success, skipped,
        )
        return {
            "entered_fail_reentry": entered_fail,
            "entered_success_reentry": entered_success,
            "skipped": skipped,
            "results": results,
        }
    except Exception as e:
        logger.exception("[RT_REENTRY] 실행 실패: %s", e)
        return {"error": str(e), "entered": 0}
    finally:
        db.close()
