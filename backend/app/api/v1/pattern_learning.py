"""🎓 v187 사장님: 성공/실패 패턴 학습 API!"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.workers.pattern_learning_worker import get_learning_insights, run_pattern_learning

router = APIRouter(prefix="/pattern-learning", tags=["pattern-learning"])


@router.get("/insights")
def get_insights(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """v187 학습 인사이트 조회!"""
    insights = get_learning_insights(db)
    if not insights:
        return {"note": "no insights yet (매 1h 자동 갱신!)", "insights": None}
    return {"insights": insights}


@router.post("/refresh")
def refresh_insights(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """v187 학습 인사이트 즉시 갱신!"""
    result = run_pattern_learning()
    return {"note": "학습 갱신 완료!", **result}
