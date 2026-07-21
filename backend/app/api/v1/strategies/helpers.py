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
    """Template 의 활성 TP 수 — tp1~20_percent 중 NOT NULL 카운트.

    2026-05-06: 1~10 동적 (사용자 요청 10단계 익절 확장). fallback 4 (backward-compat).
    2026-07-22 v120 CRITICAL: TP20 확장! 사장님 진짜 root cause fix!
    """
    if not tpl:
        return 4
    n = sum(1 for i in range(1, 21) if getattr(tpl, f"tp{i}_percent", None) is not None)
    return n if n > 0 else 4


def _enrich_response(resp: StrategyDetailResponse, tpl) -> StrategyDetailResponse:
    """응답에 template 기반 카운트 채우기.

    Note: unrealized_pnl 라이브 재계산은 list/get 엔드포인트에서 batch 로 적용
    (apply_live_unrealized_pnl 또는 apply_live_unrealized_pnl_batch). 단건만 갱신
    하려면 호출 측에서 별도로 처리.
    """
    resp.total_active_stages = _count_active_stages(tpl)
    resp.total_active_tps = _count_active_tps(tpl)
    # 2026-06-03: SL 한도 시각화용 — frontend 「전략 인스턴스」 카드에
    # SL 한도 USDT (total_capital × sl_pct / 100, 레버리지 무관 PR #57) 표시.
    if tpl and getattr(tpl, "stop_loss_percent_of_capital", None) is not None:
        resp.stop_loss_percent_of_capital = Decimal(str(tpl.stop_loss_percent_of_capital))
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

    # 🌟 2026-06-15 사장님 critical fix v2: TP1~20 모두 + "체결" anchor!
    # 옛 silent bug: `[TP{n} 익절%` (n=1~5) → TP6~10 누락 + 다른 알림 우연 매칭!
    # 사장님 OPGUSDT #140 = 실제 TP1/TP2/TP3 = 3건 But backend = 5 반환!
    # 신: "체결" 단어 anchor 추가 → 정확 매칭 (= 진입 알림 등 우연 매칭 차단!)
    # 2026-07-22 v120: TP20 확장!
    tp_like = or_(*[Notification.title.like(f"%[TP{n} 익절 체결%") for n in range(1, 21)])
    not_trailing = ~Notification.title.like("%TRAILING%")
    is_trailing = Notification.title.like("%TRAILING_TP%")

    # 🌟 2026-06-16 사장님 critical fix v3: FAILED 도 포함! (사장님 #162 龙虾USDT 사례!)
    # 옛 silent bug: send_status in ['SENT', 'PENDING'] = Telegram FAILED 알림 = 카운트 X!
    # 사장님 #162 = TP1, TP2 발동 + Telegram 일시 끊김 → 알림 FAILED!
    # = tp_count = 0 (= 실제 = 2!) silent bug!
    # 신: Telegram status 무관 = TP 발동 자체 = 카운트!
    rows = db.execute(
        sa_select(
            Notification.strategy_instance_id,
            func.sum(case((tp_like & not_trailing, 1), else_=0)).label("tp_count"),
            func.max(case((is_trailing, 1), else_=0)).label("has_trailing"),
        )
        .where(Notification.strategy_instance_id.in_(strategy_ids))
        .where(Notification.send_status.in_(["SENT", "PENDING", "FAILED"]))  # 🛡 FAILED 도 카운트!
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

    Returns: TP_FINAL / TRAILING / SL / MANUAL / NEVER_ENTERED / NONE

    2026-06-02 (#29 fix): STOPPED 가 무조건 MANUAL 이었던 분류 부정확 해소.
      - stage=0 + qty=0 + avg_entry=0 + realized=0 인 STOPPED 는 NEVER_ENTERED (진입실패)
        → LIMIT 가격 잘못 입력해서 한 번도 체결 안 된 strategy
      - 그 외 STOPPED 는 MANUAL (사용자 emergency_stop / stop 클릭)
    """
    st = (strategy.status or "").upper()
    tp_count = counts.get("tp_count", 0) if counts else 0
    has_trailing = counts.get("has_trailing", False) if counts else False
    if st in ("CLOSED_BY_SL", "STOPPED_BY_SL"):
        return "SL"
    if st == "STOPPED":
        # 진입실패 판정: 단계 0 + 수량 0 + 평단 0 + 실현손익 0 (한 번도 거래 X)
        stage = getattr(strategy, "current_stage", 0) or 0
        qty = getattr(strategy, "current_position_qty", None)
        avg_entry = getattr(strategy, "avg_entry_price", None)
        realized = getattr(strategy, "realized_pnl", None)
        qty_zero = qty is None or float(qty or 0) == 0
        entry_zero = avg_entry is None or float(avg_entry or 0) == 0
        realized_zero = realized is None or float(realized or 0) == 0
        if stage == 0 and qty_zero and entry_zero and realized_zero:
            return "NEVER_ENTERED"
        return "MANUAL"
    if st == "COMPLETED" or st == "REENTRY_READY":
        if has_trailing:
            return "TRAILING"
        if tp_count >= total_active_tps:
            return "TP_FINAL"
        # 진입했는데 종료, TP/Trail 없음 → 기타 (예: SL fast path)
        return "SL" if tp_count == 0 else "TRAILING"
    return "NONE"
