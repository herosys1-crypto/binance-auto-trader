"""🧭 심볼 관리 재진입 API (Fix 365, 2026-09-09) — 명부 조회/추가/초기화/해제.

사장님 (verbatim): "첫 진입에 실패하면 청산하고 재진입 모니터링으로 특별 관리해서 우선 포지션 진입할 심볼로
관리를 하고 재진입 모니터링 후 다시 10usdt로 진입해서 성공하면 포지션추가로 가는걸로 해줘 10usdt로 성공할때까지
10번까지 반복해줘 … 한번 선택한 종목을 지속적으로 분석하면서 관리 재진입하는거야"

이 파일은 판정을 하지 않는다 — 명부 행을 보여주고, 사장님이 심볼을 추가/초기화/해제하는 것만 다룬다.
실제 감시·진입 판정은 app/workers/managed_symbol_worker.py + app/services/managed_symbols.py (다른 담당).

명부 심볼 → StrategyInstance 이어붙이기(user_id/account/template)는 이 심볼로 사장님이 이미 만든
「📊 새 전략 (OBV 자동)」 인스턴스에서만 가져온다 — 워커가 알아서 새 심볼·계정을 고르면 안 되기 때문
(스펙 0번: "워커는 새 심볼을 스스로 고르지 않는다").

ManagedSymbol / app.services.managed_symbols 는 여기서 **핸들러 안에서만** import 한다 — 다른 담당자가
병렬로 그 파일들을 고치는 동안 이 API 모듈의 임포트 시점 자체가 깨지지 않게 하기 위함
(house rule: 매매 판정과 화면/API 코드는 분리해 배치 — app/api/v1/paper_trading.py 와 같은 패턴).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/managed-symbols", tags=["managed-symbols"])

# letters+digits 만, USDT 로 끝나는 선물 심볼만 허용 (fail-closed — 이상한 값으로 명부를 만들지 않는다)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")

_NO_OBV_INSTANCE_MSG = (
    "이 심볼로 만든 OBV 자동 인스턴스가 없어 템플릿을 정할 수 없습니다 — "
    "먼저 「📊 새 전략 (OBV 자동)」로 한 번 만들어 주세요"
)


class ManagedSymbolCreate(BaseModel):
    symbol: str
    note: str | None = None


def _jsonable(v: Any) -> Any:
    """JSONB/Numeric/datetime → JSON-safe 값 (Decimal→float, datetime→ISO)."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def _row_to_dict(row: Any) -> dict[str, Any]:
    """ManagedSymbol ORM row → 컬럼 전체를 JSON-safe dict 로 (컬럼 추가돼도 자동 반영)."""
    return {c.name: _jsonable(getattr(row, c.name)) for c in row.__table__.columns}


def _norm_symbol(raw: str) -> str:
    sym = str(raw or "").strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(status_code=400, detail=f"심볼 형식이 올바르지 않습니다 (예: SOLUSDT): {raw!r}")
    return sym


def _active_info(db: Session, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """심볼별 활성(비종료) StrategyInstance 의 방향 집합 + 인스턴스 id 목록. (배치 — N+1 방지)"""
    if not symbols:
        return {}
    from sqlalchemy import select

    from app.core.strategy_status import TERMINAL_STATUSES
    from app.models.strategy_instance import StrategyInstance

    rows = db.execute(
        select(StrategyInstance.id, StrategyInstance.symbol, StrategyInstance.side)
        .where(StrategyInstance.symbol.in_(symbols))
        .where(StrategyInstance.status.notin_(list(TERMINAL_STATUSES)))
        .where(StrategyInstance.is_archived.is_(False))
    ).all()
    out: dict[str, dict[str, Any]] = {}
    for sid, sym, side in rows:
        entry = out.setdefault(sym, {"sides": set(), "ids": []})
        entry["sides"].add(str(side).upper())
        entry["ids"].append(int(sid))
    return out


def _item(db: Session, row: Any) -> dict[str, Any]:
    info = _active_info(db, [row.symbol]).get(row.symbol, {"sides": set(), "ids": []})
    return {
        **_row_to_dict(row),
        "active_sides": sorted(info["sides"]),
        "active_instance_ids": info["ids"],
    }


def _settings_dict(db: Session) -> dict[str, Any]:
    from app.services import managed_symbols as MS

    return {
        MS.S_MODE: MS.loss_ladder_mode(db),
        MS.S_ENABLED: MS.get_bool(db, MS.S_ENABLED),
        MS.S_ENTRY: MS.get_bool(db, MS.S_ENTRY),
        # 상한은 워커(app/workers/managed_symbol_worker.py)가 실제로 쓰는 값과 반드시 같아야 한다
        # (Fix 359 교훈: 화면이 엔진과 다른 문턱을 보여주면 사장님이 잘못된 값을 믿는다).
        MS.S_MAX_ATTEMPTS: MS.get_int(db, MS.S_MAX_ATTEMPTS, 1, 100),
        MS.S_DAILY: MS.get_int(db, MS.S_DAILY, 0, 1000),
    }


def _last_cycle() -> dict | None:
    try:
        from app.core.redis_client import get_redis_client
        from app.services import managed_symbols as MS

        raw = get_redis_client().get(MS.REDIS_CYCLE_KEY)
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001 — 화면이 죽으면 안 된다. None = 「모름」, [] 와는 구분해 돌려준다.
        logger.warning("[Fix365] last_cycle 조회 실패: %s", e)
        return None


@router.get("")
def list_managed_symbols(
    include_released: int = 0,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """명부 전체 + 워커 마지막 사이클(Redis) + 유효 설정. WATCHING → EXHAUSTED → RELEASED 순, 그 안에서 최신순."""
    from sqlalchemy import case, select

    from app.models.managed_symbol import ManagedSymbol
    from app.services import managed_symbols as MS

    order_rank = case(
        (ManagedSymbol.status == MS.STATUS_WATCHING, 0),
        (ManagedSymbol.status == MS.STATUS_EXHAUSTED, 1),
        else_=2,
    )
    q = select(ManagedSymbol)
    if not include_released:
        q = q.where(ManagedSymbol.status != MS.STATUS_RELEASED)
    q = q.order_by(order_rank, ManagedSymbol.updated_at.desc())
    rows = db.execute(q).scalars().all()

    active = _active_info(db, [r.symbol for r in rows])
    items = []
    for r in rows:
        info = active.get(r.symbol, {"sides": set(), "ids": []})
        items.append({
            **_row_to_dict(r),
            "active_sides": sorted(info["sides"]),
            "active_instance_ids": info["ids"],
        })

    return {"items": items, "last_cycle": _last_cycle(), "settings": _settings_dict(db)}


@router.post("")
def add_managed_symbol(
    payload: ManagedSymbolCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """심볼을 명부에 올린다 (upsert). 신규면 그 심볼의 최신 OBV 자동 인스턴스에서 계정/템플릿을 물려받는다."""
    from sqlalchemy import select

    from app.models.managed_symbol import ManagedSymbol
    from app.models.strategy_instance import StrategyInstance
    from app.models.strategy_template import StrategyTemplate
    from app.services import managed_symbols as MS

    symbol = _norm_symbol(payload.symbol)

    row = db.execute(select(ManagedSymbol).where(ManagedSymbol.symbol == symbol)).scalar_one_or_none()
    if row is not None:
        row.status = MS.STATUS_WATCHING
        row.attempts = 0
        if payload.note is not None:
            row.note = payload.note
        db.commit()
        logger.info("[Fix365] %s 재등록 (사장님) — WATCHING, 시도 0", symbol)
        return _item(db, row)

    si = db.execute(
        select(StrategyInstance)
        .join(StrategyTemplate, StrategyInstance.strategy_template_id == StrategyTemplate.id)
        .where(StrategyInstance.symbol == symbol)
        .where(StrategyTemplate.trigger_mode == "OBV_REVERSE")
        .order_by(StrategyInstance.id.desc())
    ).scalars().first()
    if si is None:
        raise HTTPException(status_code=400, detail=_NO_OBV_INSTANCE_MSG)

    row = ManagedSymbol(
        symbol=symbol,
        user_id=si.user_id,
        exchange_account_id=si.exchange_account_id,
        strategy_template_id=si.strategy_template_id,
        status=MS.STATUS_WATCHING,
        attempts=0,
        max_attempts=MS.get_int(db, MS.S_MAX_ATTEMPTS, 1, 100),
        successes=0,
        total_entries=0,
        origin_instance_id=si.id,
        note=payload.note,
        last_reasons={"state": "✚ 수동 등록 (사장님)"},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("[Fix365] %s 신규 등록 (사장님) — 계정 #%s, 템플릿 #%s (근거 인스턴스 #%s)",
                symbol, row.exchange_account_id, row.strategy_template_id, si.id)
    return _item(db, row)


def _get_or_404(db: Session, managed_symbol_id: int):
    from app.models.managed_symbol import ManagedSymbol

    row = db.get(ManagedSymbol, managed_symbol_id)
    if row is None:
        raise HTTPException(status_code=404, detail="관리 심볼을 찾을 수 없습니다")
    return row


@router.post("/{managed_symbol_id}/reset")
def reset_managed_symbol(
    managed_symbol_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """연속 실패 카운트를 0으로, WATCHING 으로 되돌린다 (EXHAUSTED 해제 포함)."""
    from app.services import managed_symbols as MS

    row = _get_or_404(db, managed_symbol_id)
    row.attempts = 0
    row.status = MS.STATUS_WATCHING
    row.last_reasons = {**(row.last_reasons or {}), "state": "↺ 초기화 (사장님)"}
    db.commit()
    logger.info("[Fix365] %s(#%s) 초기화 (사장님)", row.symbol, row.id)
    return _item(db, row)


@router.delete("/{managed_symbol_id}")
def release_managed_symbol(
    managed_symbol_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """명부에서 해제한다 (행은 지우지 않는다 — RELEASED 로 표시만). 워커가 이 뒤로 이 심볼을 건드리지 않는다."""
    from app.services import managed_symbols as MS

    row = _get_or_404(db, managed_symbol_id)
    row.status = MS.STATUS_RELEASED
    row.released_at = datetime.now(timezone.utc)
    row.last_reasons = {**(row.last_reasons or {}), "state": "✕ 해제 (사장님)"}
    db.commit()
    logger.info("[Fix365] %s(#%s) 해제 (사장님)", row.symbol, row.id)
    return _item(db, row)
