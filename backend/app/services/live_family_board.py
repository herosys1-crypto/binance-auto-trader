"""🧑‍⚖️ Fix 436 (2026-10-10 사장님 「1번 진행」) — 운영팀 카드의 「가족별 실거래」 (읽기 전용, 화면용).

성적표(Fix 430)는 가상매매만 본다 → 켜 둔 자동 가족이 **실제로** 버는지를 같은 카드에서 본다.
  가족마다: 최근 N일(기본 30) 생성 전략 · 끝난 건 · 진행 중 · 실현 합 = 시스템 몫 + 사람 💉 추가 몫 + 출처 모름 (Fix 434)
           · 손실 차단기 상태(Fix 435 최근 7일 가족 몫 — **청산 시각** 기준 / 기준 / 걸림) · 규칙 가족이면 모드(off/shadow/on)
사람이 만든 전략(family_for = None)은 넣지 않는다. 주문·설정을 바꾸지 않는다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

FIX = "Fix436"
DEFAULT_DAYS = 30


def _r(x: float) -> float:
    return round(float(x), 2)


def build(db: Any, *, days: int = DEFAULT_DAYS, now: datetime | None = None) -> dict[str, Any]:
    from sqlalchemy import select
    from app.core.strategy_status import TERMINAL_STATUSES
    from app.models.strategy_instance import StrategyInstance as SI
    from app.models.strategy_template import StrategyTemplate as ST
    from app.services import auto_family_registry as AF
    from app.services import family_loss_breaker as FB
    from app.services import human_share as HS
    from app.services import rule_families as RF

    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    rows = db.execute(
        select(SI.id, SI.side, SI.status, SI.realized_pnl, SI.created_at, SI.entry_origin, ST.strategy_type, ST.name)
        .join(ST, ST.id == SI.strategy_template_id).where(SI.created_at >= since, SI.created_at <= now)
    ).all()
    fams: dict[str, dict[str, Any]] = {}
    picked = []
    for sid, side, status, rp, ca, origin, stype, name in rows:
        fam = AF.family_for(strategy_type=stype, template_name=name, entry_origin=origin, created_at=ca)
        if fam is None:
            continue
        f = fams.setdefault(fam.key, {"key": fam.key, "label": fam.label, "sides": set(), "n": 0, "closed": 0, "open": 0,
                                      "realized": 0.0, "system": 0.0, "human": 0.0, "unknown": 0.0, "human_n": 0, "wins": 0})
        f["n"] += 1
        f["sides"].add(side)
        if status in TERMINAL_STATUSES:
            f["closed"] += 1
            picked.append((fam.key, sid, side, rp))
        else:
            f["open"] += 1
    try:
        sp = HS.split_for(db, [(sid, side, rp) for _k, sid, side, rp in picked]) if picked else {}
    except Exception as e:  # noqa: BLE001 — 분해가 안 되면 전부 「출처 모름」(시스템 몫으로 우기지 않는다)
        logger.warning("[%s] 사람 몫 분해 실패: %s", FIX, e)
        sp = {}
    for key, sid, _side, rp in picked:
        f, h = fams[key], sp.get(sid) or {"system": 0.0, "human": 0.0, "unknown": float(rp or 0), "human_n": 0}   # Gemini: 모르면 모름
        f["realized"] += float(rp or 0)
        f["system"] += h["system"]
        f["human"] += h["human"]
        f["unknown"] += h["unknown"]
        f["human_n"] += int(h.get("human_n") or 0) > 0
        f["wins"] += h["system"] > 0
    rf_keys = {f.key for f in RF.FAMILIES}
    modes = {k: RF.mode_of(db, k) for k in rf_keys}
    for k in modes:                                       # 실주문(on) 규칙 가족은 거래가 없어도 보인다
        if modes[k] == "on" and k not in fams:
            lab = RF.FAMILY_BY_KEY[k].label
            fams[k] = {"key": k, "label": lab, "sides": {RF.FAMILY_BY_KEY[k].side}, "n": 0, "closed": 0, "open": 0,
                       "realized": 0.0, "system": 0.0, "human": 0.0, "unknown": 0.0, "human_n": 0, "wins": 0}
    breaker_ok = True
    try:
        br = FB.all_states(db, list(fams), now=now)
    except Exception as e:  # noqa: BLE001 — 화면은 차단기 조회 실패로 죽지 않는다
        logger.warning("[%s] 차단기 상태 조회 실패: %s", FIX, e)
        br, breaker_ok = {}, False
    out = []
    for k, f in fams.items():
        b = br.get(k) or {}
        out.append({
            "key": k, "label": f["label"], "sides": sorted(f["sides"]), "mode": modes.get(k),
            "n": f["n"], "closed": f["closed"], "open": f["open"], "wins": f["wins"],
            "realized": _r(f["realized"]), "system": _r(f["system"]), "human": _r(f["human"]), "unknown": _r(f["unknown"]),
            "human_n": f["human_n"],
            "breaker": {"pnl": b.get("pnl"), "limit": b.get("limit"), "days": b.get("days"), "tripped": b.get("tripped")} if b else None,
        })
    # 켜 둔 실주문 가족 먼저, 그다음 최근 거래가 있는 가족(시스템 몫 오름차순 = 나쁜 것 먼저)
    out.sort(key=lambda x: (x["mode"] != "on", x["closed"] == 0 and x["open"] == 0, x["system"]))
    tot = {k: _r(sum(x[k] for x in out)) for k in ("realized", "system", "human", "unknown")}
    return {"fix": FIX, "at": now.isoformat(), "days": days, "families": out, "total": tot, "breaker_ok": breaker_ok}
