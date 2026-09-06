"""📚 차트 학습 일지 API (Fix 353) — 읽기 전용. 상태 · 보고서(JSON/markdown) · 실매매 조인(Fix 355)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.services import chart_learning as CL
from app.services import chart_learning_trades as CLT
from app.workers import chart_learning_worker as W

router = APIRouter(prefix="/chart-learning", tags=["chart-learning"])

# 실매매 조인은 인스턴스+주문+이벤트를 통째로 훑는다 — report(학습 일지만) 보다 무겁다.
# 사장님 doc 실측(scratchpad wf) 은 14일 기준이었으므로 60일을 상한으로 둔다(더 필요하면 CLI 사용).
_TRADES_MAX_DAYS = 60


@router.get("/status")
def chart_learning_status(db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)) -> dict:
    """날짜별 행 수(PENDING/DONE/EXPIRED)."""
    return W.status(db)


@router.get("/report")
def chart_learning_report(days: int = 60, db: Session = Depends(get_db),
                          user_id: int = Depends(get_current_user_id)) -> dict:
    """자리별 기준선 + 규칙별 결과 + 교차검증 (JSON)."""
    return W.build_report_from_db(db, max(1, min(days, 3650)))


@router.get("/report.md", response_class=PlainTextResponse)
def chart_learning_report_md(days: int = 60, db: Session = Depends(get_db),
                             user_id: int = Depends(get_current_user_id)) -> str:
    return CL.render_markdown(W.build_report_from_db(db, max(1, min(days, 3650))))


@router.get("/trades")
def chart_learning_trades(days: int = 14, db: Session = Depends(get_db),
                          user_id: int = Depends(get_current_user_id)) -> dict:
    """실매매(strategy_instances/orders/risk_events) × 학습 일지 라벨 조인 집계 (JSON, Fix 355)."""
    rows = CLT.build_trade_dataset(db, max(1, min(days, _TRADES_MAX_DAYS)))
    return CLT.summarize(rows)


@router.get("/trades.md", response_class=PlainTextResponse)
def chart_learning_trades_md(days: int = 14, db: Session = Depends(get_db),
                             user_id: int = Depends(get_current_user_id)) -> str:
    rows = CLT.build_trade_dataset(db, max(1, min(days, _TRADES_MAX_DAYS)))
    return CLT.render_markdown(CLT.summarize(rows))
