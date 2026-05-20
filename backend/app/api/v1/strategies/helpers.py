"""Strategies — 공통 helper 함수 (모든 submodule 에서 재사용).

2026-05-14 Phase 4 split: 기존 strategies.py 1,384줄에서 분리.
2026-05-20: live mark price 기반 unrealized_pnl 재계산 (PNL stale 5~13 USDT
            차이 해소). mark_price_cache (WebSocket markPrice 1s push) 우선,
            miss 시 DB stored 값 fallback.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.schemas.strategy import StrategyDetailResponse
from app.services.mark_price_cache import calc_unrealized_pnl, get_mark_prices_bulk


def _count_active_stages(tpl) -> int:
    """Template 의 활성 단계 수 — stages_config.capitals 중 0/None 아닌 항목 카운트.

    옵션 C (1~10단계 동적). 결과 fallback 4 (backward-compat).
    """
    if not tpl:
        return 4
    cfg = getattr(tpl, "stages_config", None) or {}
    capitals = cfg.get("capitals") or []
    n = sum(1 for c in capitals if c not in (None, "") and Decimal(str(c)) > 0)
    return n if n > 0 else 4


def _count_active_tps(tpl) -> int:
    """Template 의 활성 TP 수 — tp1~10_percent 중 NOT NULL 카운트.

    2026-05-06: 1~10 동적 (사용자 요청 10단계 익절 확장). fallback 4 (backward-compat).
    """
    if not tpl:
        return 4
    n = sum(1 for i in range(1, 11) if getattr(tpl, f"tp{i}_percent", None) is not None)
    return n if n > 0 else 4


def _enrich_response(resp: StrategyDetailResponse, tpl) -> StrategyDetailResponse:
    """응답에 template 기반 카운트 채우기.

    Note: unrealized_pnl 라이브 재계산은 list/get 엔드포인트에서 batch 로 적용
    (apply_live_unrealized_pnl 또는 apply_live_unrealized_pnl_batch). 단건만 갱신
    하려면 호출 측에서 별도로 처리.
    """
    resp.total_active_stages = _count_active_stages(tpl)
    resp.total_active_tps = _count_active_tps(tpl)
    return resp


def apply_live_unrealized_pnl(resp: StrategyDetailResponse) -> StrategyDetailResponse:
    """단건 응답의 unrealized_pnl 을 라이브 마크 가격으로 재계산.

    캐시 hit: side/qty/entry/mark 로 PNL 재계산.
    miss: DB stored 값 그대로 (fallback).
    """
    if not resp.symbol or not resp.current_position_qty or not resp.avg_entry_price:
        return resp
    prices = get_mark_prices_bulk([resp.symbol])
    mark = prices.get(resp.symbol.upper())
    if mark is None:
        return resp
    resp.unrealized_pnl = calc_unrealized_pnl(
        side=resp.side,
        qty=Decimal(resp.current_position_qty),
        entry_price=Decimal(resp.avg_entry_price),
        mark_price=mark,
    )
    return resp


def apply_live_unrealized_pnl_batch(responses: list[StrategyDetailResponse]) -> list[StrategyDetailResponse]:
    """list 응답 전체의 unrealized_pnl 을 라이브 마크 가격으로 재계산.

    Redis mget 1회로 모든 심볼 한 번에 조회 (N+1 회피).
    캐시 miss 인 심볼은 stored 값 유지.
    """
    if not responses:
        return responses
    # 활성 포지션이 있는 응답만 — qty=0 / entry=None 은 PNL 0 이라 재계산 불필요
    candidates = [
        r for r in responses
        if r.symbol and r.current_position_qty and r.avg_entry_price
    ]
    if not candidates:
        return responses
    symbols = {r.symbol.upper() for r in candidates}
    prices = get_mark_prices_bulk(symbols)
    if not prices:
        return responses
    for r in candidates:
        mark = prices.get(r.symbol.upper())
        if mark is None:
            continue
        r.unrealized_pnl = calc_unrealized_pnl(
            side=r.side,
            qty=Decimal(r.current_position_qty),
            entry_price=Decimal(r.avg_entry_price),
            mark_price=mark,
        )
    return responses


def _fetch_tp_counts_batch(db: Session, strategy_ids: set[int]) -> dict[int, dict]:
    """notifications 에서 strategy 별 TP 발동 카운트 + TRAILING 여부 batch fetch.

    N+1 방지: 모든 strategy 한 번에 query.
    2026-05-14 Phase 5: PostgreSQL regex (~) + ANY() + COUNT(...) FILTER → portable SQL 로 변경.
    이전엔 sqlite 테스트에서 호출 불가. 이제 양 DB 모두 지원 → N+1 회귀 테스트 가능.
    semantic 동등: TP1~5 익절 (TRAILING 제외) 카운트 + TRAILING 발생 여부.

    title 패턴:
      "[TP1 익절 체결]" / "[TP2 익절 체결]" / ... / "[TP5 익절 체결]"
      "[TRAILING_TP 익절 체결]"

    Returns: {strategy_id: {"tp_count": int, "has_trailing": bool}}
    """
    if not strategy_ids:
        return {}
    from sqlalchemy import case, func, or_, select as sa_select
    from app.models.notification import Notification

    # TP1~5 익절 (TRAILING 제외) — OR 로 묶음
    tp_like = or_(*[Notification.title.like(f"%[TP{n} 익절%") for n in range(1, 6)])
    not_trailing = ~Notification.title.like("%TRAILING%")
    is_trailing = Notification.title.like("%TRAILING_TP%")

    rows = db.execute(
        sa_select(
            Notification.strategy_instance_id,
            func.sum(case((tp_like & not_trailing, 1), else_=0)).label("tp_count"),
            func.max(case((is_trailing, 1), else_=0)).label("has_trailing"),
        )
        .where(Notification.strategy_instance_id.in_(strategy_ids))
        .where(Notification.send_status.in_(["SENT", "PENDING"]))
        .group_by(Notification.strategy_instance_id)
    ).all()
    return {
        r.strategy_instance_id: {
            "tp_count": int(r.tp_count or 0),
            "has_trailing": bool(r.has_trailing),
        }
        for r in rows
    }


def _resolve_close_reason(strategy, counts: dict, total_active_tps: int) -> str:
    """status + 발동 카운트로 마지막 종료 사유 추론.

    Returns: TP_FINAL / TRAILING / SL / MANUAL / NONE
    """
    st = (strategy.status or "").upper()
    tp_count = counts.get("tp_count", 0) if counts else 0
    has_trailing = counts.get("has_trailing", False) if counts else False
    if st in ("CLOSED_BY_SL", "STOPPED_BY_SL"):
        return "SL"
    if st == "STOPPED":
        return "MANUAL"
    if st == "COMPLETED" or st == "REENTRY_READY":
        if has_trailing:
            return "TRAILING"
        if tp_count >= total_active_tps:
            return "TP_FINAL"
        # 진입했는데 종료, TP/Trail 없음 → 기타 (예: SL fast path)
        return "SL" if tp_count == 0 else "TRAILING"
    return "NONE"
