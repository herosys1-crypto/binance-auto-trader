"""📚 차트 학습 일지 API (Fix 353) — 읽기 전용. 상태 · 보고서(JSON/markdown)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.services import chart_learning as CL
from app.workers import chart_learning_worker as W

router = APIRouter(prefix="/chart-learning", tags=["chart-learning"])


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
