"""Admin — CSV export endpoints (회계/세무 분석용).

전략 인스턴스 + 주문 전체를 CSV 로 다운로드.
2026-05-14 Phase 4 split: 기존 admin.py 에서 분리.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/export/strategies")
def export_strategies_csv(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """전략 인스턴스 전체를 CSV 로 내보내기. 회계/세무 분석용."""
    import csv
    import io
    from sqlalchemy import select as sa_select
    from app.models.strategy_instance import StrategyInstance
    from fastapi.responses import StreamingResponse

    rows = db.execute(
        sa_select(StrategyInstance).order_by(StrategyInstance.id.asc())
    ).scalars().all()

    buf = io.StringIO()
    # 한글 Excel 호환 — UTF-8 BOM 추가
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow([
        "id", "심볼", "방향", "상태", "현재단계", "레버리지",
        "시작가", "평균진입가", "포지션수량", "투입자본",
        "실현손익", "미실현손익", "최대손실%", "최대이익%",
        "크라이시스진입시각", "크라이시스첫TP시각", "재진입대기",
        "시작시각", "종료시각", "생성시각",
    ])
    for r in rows:
        writer.writerow([
            r.id, r.symbol, r.side, r.status, r.current_stage, r.leverage,
            str(r.start_price) if r.start_price else "",
            str(r.avg_entry_price) if r.avg_entry_price else "",
            str(r.current_position_qty), str(r.invested_capital),
            str(r.realized_pnl), str(r.unrealized_pnl),
            str(r.max_loss_pct) if r.max_loss_pct is not None else "",
            str(r.max_profit_pct) if r.max_profit_pct is not None else "",
            r.crisis_mode_triggered_at.isoformat() if r.crisis_mode_triggered_at else "",
            r.crisis_first_tp_done_at.isoformat() if r.crisis_first_tp_done_at else "",
            "TRUE" if r.reentry_ready else "FALSE",
            r.started_at.isoformat() if r.started_at else "",
            r.stopped_at.isoformat() if r.stopped_at else "",
            r.created_at.isoformat() if r.created_at else "",
        ])
    buf.seek(0)
    filename = f"strategies_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/orders")
def export_orders_csv(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """주문 전체를 CSV 로 내보내기."""
    import csv
    import io
    from sqlalchemy import select as sa_select
    from app.models.order import Order
    from fastapi.responses import StreamingResponse

    rows = db.execute(
        sa_select(Order).order_by(Order.id.asc())
    ).scalars().all()

    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow([
        "id", "전략ID", "단계", "유형", "심볼", "방향", "포지션방향", "주문타입",
        "거래소주문ID", "트리거가", "지정가", "주문수량", "체결수량", "체결단가",
        "상태", "발송시각", "갱신시각",
    ])
    for o in rows:
        writer.writerow([
            o.id, o.strategy_instance_id, o.stage_no or "", o.purpose, o.symbol,
            o.side, o.position_side, o.order_type,
            o.exchange_order_id or "",
            str(o.trigger_price) if o.trigger_price else "",
            str(o.price) if o.price else "",
            str(o.orig_qty) if o.orig_qty else "",
            str(o.executed_qty),
            str(o.avg_price) if o.avg_price else "",
            o.status,
            o.created_at.isoformat() if o.created_at else "",
            o.updated_at.isoformat() if o.updated_at else "",
        ])
    buf.seek(0)
    filename = f"orders_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
