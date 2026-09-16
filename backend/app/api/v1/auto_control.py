"""🎛 Fix 374 (2026-09-16 사장님) — 자동매매 관제실 API.

사장님 verbatim: "자동매매 준비 가족 12종과 모든 자동매매를 한곳으로 모아서 사용과 관리가 편리하게 ui를 개선해줘"

  GET   /auto-control/overview          한 판 (전체 스위치 · 가족 29종 · 오늘/현재 건수 · 그림자 수)
  PATCH /auto-control/settings          여러 칸 한 번에 저장 (화이트리스트 밖 키·범위 밖 값이면 **아무것도 저장 안 함**)
  POST  /auto-control/halt              자동매매 전면 중단/재개 (사장님 버튼 — 되돌리는 한 칸)
  POST  /auto-control/bulk              안전한 방향 일괄 적용 (off | shadow 만 — on 일괄은 만들지 않는다)

설계 (실자금 화면이라 보수적으로):
  · 이 API 는 설정만 만진다. 주문·청산·전략 생성은 하지 않는다.
  · 일괄 적용은 **끄는 방향만** 제공한다. 켜는 것은 가족마다 하나씩 사장님이 누른다 (CLAUDE.md 2 · 헌법 64).
  · 모든 저장은 `system_settings.updated_by` 에 사장님 user_id 를 남긴다 (Fix 193 설정 변경 감사).
  · 화면이 죽지 않게 집계 실패는 500 이 아니라 `count_error` 로 알린다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auto-control", tags=["auto-control"])

BULK_SAFE = ("off", "shadow")          # 일괄로 허용하는 방향 (켜기 일괄 금지)


@router.get("/overview")
def overview(db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)) -> dict:
    """관제실 한 판 (읽기 전용)."""
    from app.services.auto_control_state import build
    return build(db)


@router.patch("/settings")
def patch_settings(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """`{"changes": {"키": "값", ...}}` — 전부 또는 전무."""
    from app.services.auto_control_state import apply
    changes = payload.get("changes") if isinstance(payload, dict) else None
    if not isinstance(changes, dict):
        raise HTTPException(status_code=400, detail="changes 객체가 필요합니다")
    try:
        return apply(db, changes, user_id=user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post("/halt")
def set_halt(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """`{"halt": true|false}` — 자동매매 전면 중단(Fix 371) 켜고 끄기.

    🚨 `halt=false`(재개) 는 실자금이 나가기 시작하는 조작이다. 가족별 모드가 `on` 인 것만 실제로 주문한다.
    """
    from app.services.auto_control_state import apply, build
    if "halt" not in payload:
        raise HTTPException(status_code=400, detail="halt 값이 필요합니다 (true = 중단)")
    want = payload["halt"]
    if isinstance(want, str):
        want = want.strip().lower() not in ("0", "off", "false", "no")
    try:
        apply(db, {"auto_trading_halt": "1" if want else "0"}, user_id=user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    state = build(db)
    on_now = [p["label"] for p in state["panels"] if p["state"] == "on"]
    logger.warning("[Fix374] 자동매매 전면 %s (user=%s) — 지금 on 인 가족 %d종: %s",
                   "중단" if want else "재개", user_id, len(on_now), ", ".join(on_now) or "없음")
    return {"halted": state["halted"], "on_families": on_now,
            "kill_switches": state["kill_switches"]}


@router.post("/bulk")
def bulk(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """`{"target": "off"|"shadow", "group": "<그룹명 또는 생략>"}` — 그 그룹의 가족 스위치를 안전한 방향으로.

    `mode3` 가족은 그 값으로, `switch` 가족은 끄기(0)로 맞춘다 (shadow 가 없는 워커는 shadow 요청 시 건너뛴다).
    """
    from app.services.auto_control import panels
    from app.services.auto_control_state import apply
    target = str(payload.get("target") or "").strip().lower()
    if target not in BULK_SAFE:
        raise HTTPException(status_code=400, detail=f"일괄 적용은 {' 또는 '.join(BULK_SAFE)} 만 됩니다 (켜기는 가족마다 따로)")
    group = payload.get("group")
    changes: dict[str, str] = {}
    skipped: list[str] = []
    for p in panels():
        if p.gate is None or (group and p.group != group):
            continue
        if p.gate.kind == "mode3":
            changes[p.gate.key] = target
        elif p.gate.kind == "switch":
            if target == "off":
                changes[p.gate.key] = "0"
            else:
                skipped.append(p.label)          # 그림자가 없는 워커 — 끄지도 켜지도 않는다
        else:
            skipped.append(p.label)
    if not changes:
        return {"changed": 0, "saved": [], "skipped": skipped}
    try:
        out = apply(db, changes, user_id=user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    logger.warning("[Fix374] 일괄 %s (group=%s · %d칸 · user=%s)", target, group or "전체", out["changed"], user_id)
    return {**out, "skipped": skipped}
