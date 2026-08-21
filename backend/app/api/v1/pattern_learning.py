"""🎓 v187 사장님: 성공/실패 패턴 학습 API!"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.workers.pattern_learning_worker import (
    get_learning_health_check,
    get_learning_insights,
    run_pattern_learning,
)

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


@router.get("/health-check")
def health_check(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🎓 v208 사장님 (2026-08-21): 학습 축적 상태 헬스 체크!

    확인:
    - 총 자동 진입 (최근 30일)
    - entry_snapshot 저장률
    - outcome 확정률 (SUCCESS+FAIL / total)
    - 학습 가능 표본 수
    - 각 조건 필드별 non-null 카운트!
    - insights 신선도 (age_hours)!
    """
    return get_learning_health_check(db)
