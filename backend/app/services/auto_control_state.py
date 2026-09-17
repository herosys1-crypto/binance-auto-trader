"""🎛 Fix 374 (2026-09-16) — 자동매매 관제실: 현황 집계(build) · 설정 저장(apply).

레지스트리(어떤 자동매매가 있고 어떤 설정을 쓰는가)는 `auto_control.py` 가 단일 진실이다.
이 모듈은 그 레지스트리를 받아 **읽고 세고 저장**만 한다 — 판정·주문은 없다.

집계 원칙:
  · 설정 200여 칸을 키마다 조회하면 화면이 느리다 → `_rows` 로 한 번에 읽는다.
  · 가족별 건수도 전략 행을 **한 번만** 읽어 파이썬에서 가족으로 나눈다 (가족 분류는 `auto_family_registry` 가 진실).
  · 집계가 실패해도 화면은 떠야 한다 → 실패는 `count_error` 로 알리고 0 으로 보여 준다
    (🚨 단, **진입을 막는 판정**은 여기가 아니라 워커의 `count_today` 가 하고 그쪽은 실패 시 막는다 = fail-closed).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from app.services.auto_control import (
    DETECTORS,
    FIX,
    GROUPS,
    OFF_WORDS,
    Ctl,
    _shared_rule_ctls,
    global_ctls,
    panels,
    whitelist,
)

logger = logging.getLogger(__name__)


# ───────────────────────── 현황 집계 ─────────────────────────
def _rows(db: Any, keys: Iterable[str]) -> dict[str, str]:
    """설정 행을 **한 번에** 읽는다 (칸이 200개라 키마다 조회하면 화면이 느려진다)."""
    keys = list(keys)
    if not keys:
        return {}
    try:
        from sqlalchemy import select
        from app.models.system_setting import SystemSetting
        got = db.execute(select(SystemSetting.key, SystemSetting.value)
                         .where(SystemSetting.key.in_(keys))).all()
        return {k: ("" if v is None else str(v)) for k, v in got}
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] 설정 일괄 조회 실패: %s", FIX, e)
        return {}


def _family_counts(db: Any) -> tuple[dict[str, int], dict[str, int], str | None]:
    """(오늘 KST 가족별 진입 수, 지금 살아 있는 가족별 수, 오류). 전략 행을 한 번만 읽는다."""
    today: dict[str, int] = {}
    live: dict[str, int] = {}
    try:
        from sqlalchemy import or_, select
        from app.core.strategy_status import ACTIVE_LIKE
        from app.models.strategy_instance import StrategyInstance as SI
        from app.models.strategy_template import StrategyTemplate as T
        from app.services import auto_family_registry as AF
        day0 = AF.kst_day_start()
        rows = db.execute(
            select(SI.entry_origin, SI.current_stage, SI.status, SI.is_archived, SI.created_at, T.strategy_type, T.name)
            .join(T, T.id == SI.strategy_template_id, isouter=True)
            .where(or_(SI.created_at >= day0, SI.status.in_(tuple(ACTIVE_LIKE))))
        ).all()
        for origin, stage, status, archived, created, stype, tname in rows:
            fam = AF.family_for(strategy_type=stype, template_name=tname, entry_origin=origin, created_at=created)
            if fam is None:
                continue
            created_at = created if created is None or created.tzinfo else created.replace(tzinfo=timezone.utc)
            if created_at is not None and created_at >= day0 and AF.counts_toward_today(
                    stage=stage, status=status, archived=bool(archived)):
                today[fam.key] = today.get(fam.key, 0) + 1
            if not archived and status in ACTIVE_LIKE:
                live[fam.key] = live.get(fam.key, 0) + 1
        return today, live, None
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] 가족별 건수 집계 실패: %s", FIX, e)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {}, {}, str(e)


SHADOW_SCAN_CAP = 20000          # Redis 키를 무한정 훑지 않는다 (Claude가 정함)


def _shadow_counts() -> dict[str, int]:
    """규칙 가족 그림자 기록 수 (rf:shadow:<가족>:<심볼>:<행id>, 7일 TTL)."""
    out: dict[str, int] = {}
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        if r is None:
            return out
        seen = 0
        for raw in r.scan_iter(match="rf:shadow:*", count=1000):
            seen += 1
            if seen > SHADOW_SCAN_CAP:
                logger.info("[%s] 그림자 키가 %d개를 넘어 집계를 끊었다", FIX, SHADOW_SCAN_CAP)
                break
            parts = (raw.decode() if isinstance(raw, bytes) else str(raw)).split(":")
            if len(parts) >= 4:
                out[parts[2]] = out.get(parts[2], 0) + 1
    except Exception as e:  # noqa: BLE001
        logger.debug("[%s] 그림자 집계 생략: %s", FIX, e)
    return out


def _kill_switches(db: Any) -> list[dict]:
    try:
        from sqlalchemy import select
        from app.models.account_kill_switch import AccountKillSwitch as KS
        return [{"account_id": r.exchange_account_id, "reason": r.reason_code,
                 "message": r.reason_message,
                 "at": r.triggered_at.isoformat() if r.triggered_at else None}
                for r in db.execute(select(KS).where(KS.is_enabled.is_(True))).scalars().all()]
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] Kill-Switch 조회 실패: %s", FIX, e)
        return []


def _ctl_dict(c: Ctl, vals: dict[str, str]) -> dict:
    raw = vals.get(c.key)
    return {"key": c.key, "label": c.label, "kind": c.kind, "help": c.help,
            "lo": c.lo, "hi": c.hi, "off_means": c.off_means, "source": c.source, "ref": c.ref,
            "default": c.default, "value": c.default if raw in (None, "") else raw,
            "is_default": raw in (None, ""), "row_exists": raw is not None}


def _is_off(c: Ctl, value: str) -> bool:
    if c.kind == "mode3":
        return value.lower() == "off"
    if c.kind == "switch":
        return value.strip().lower() in OFF_WORDS
    if c.off_means:
        try:
            return float(value) == float(c.off_means)
        except (TypeError, ValueError):
            return False
    return False


def build(db: Any) -> dict:
    """관제실 화면 한 판. 읽기만 한다 (설정을 만들지도 고치지도 않는다)."""
    ps = panels()
    wl = whitelist()
    vals = _rows(db, wl.keys())
    today, live, count_err = _family_counts(db)
    shadow = _shadow_counts()

    halt = wl["auto_trading_halt"]
    halt_val = vals.get(halt.key)
    halted = halt_val is None or str(halt_val).strip().lower() not in OFF_WORDS

    out_panels = []
    for p in ps:
        gate = _ctl_dict(p.gate, vals) if p.gate is not None else None
        state = "no_gate"
        if gate is not None and p.gate.kind == "gate3":
            state = "gate_only"              # Fix 376: 켜기 스위치 없이 차트 게이트만 있는 줄 — 실주문 on/off 로 세지 않는다
        elif gate is not None:
            v = str(gate["value"])
            state = "off" if _is_off(p.gate, v) else ("shadow" if v.lower() == "shadow" else "on")
        dm = f"daily_max_{p.fam}" if (p.fam and p.daily) else ""
        out_panels.append({
            "fam": p.fam, "label": p.label, "group": p.group, "job": p.job, "every": p.every,
            "note": p.note, "state": state, "gate": gate,
            "ctls": [_ctl_dict(c, vals) for c in p.ctls],
            "daily_max": _ctl_dict(wl[dm], vals) if dm else None,
            "today": today.get(p.fam, 0) if p.fam else None,
            "live": live.get(p.fam, 0) if p.fam else None,
            "shadow": shadow.get(p.fam) if p.fam else None,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "halted": halted,
        "halt_reason": "행이 없어 기본값으로 중단 중" if halt_val is None else None,
        "kill_switches": _kill_switches(db),
        "globals": [_ctl_dict(c, vals) for c in global_ctls()],
        "shared_rule": [_ctl_dict(c, vals) for c in _shared_rule_ctls()],
        "panels": out_panels,
        "detectors": [{"job": j, "note": n} for j, n in DETECTORS],
        "groups": list(GROUPS),
        "count_error": count_err,
        "summary": {
            "on": sum(1 for p in out_panels if p["state"] == "on"),
            "shadow": sum(1 for p in out_panels if p["state"] == "shadow"),
            "off": sum(1 for p in out_panels if p["state"] == "off"),
            "total": len(out_panels),
            "entered_today": sum(today.values()),
            "live_now": sum(live.values()),
        },
    }


# ───────────────────────── 저장 ─────────────────────────
def apply(db: Any, changes: dict[str, Any], *, user_id: int | None = None) -> dict:
    """화이트리스트 키만 저장. 한 칸이라도 값이 이상하면 **아무것도 저장하지 않는다**(전부 또는 전무).

    켜기(on)든 끄기(off)든 이 함수는 사장님이 화면에서 누른 값만 그대로 쓴다 — 스스로 정하지 않는다.
    """
    wl = whitelist()
    if not isinstance(changes, dict) or not changes:
        raise ValueError("바꿀 설정이 없습니다")
    if len(changes) > 100:
        raise ValueError("한 번에 100칸까지만 저장합니다")
    unknown = [k for k in changes if k not in wl]
    if unknown:
        raise ValueError(f"관제실에서 다룰 수 없는 설정입니다: {', '.join(sorted(unknown)[:5])}")

    cleaned = {k: wl[k].clean(v) for k, v in changes.items()}      # 여기서 ValueError → 저장 전 중단

    from app.services.system_settings_service import SystemSettingsService
    svc = SystemSettingsService(db)
    done = []
    for key, value in cleaned.items():
        before = svc.get(key)
        if before == value:
            done.append({"key": key, "value": value, "changed": False})
            continue
        svc.set(key, value, updated_by=user_id, description=f"자동매매 관제실 ({FIX})")
        logger.info("[%s] 관제실 저장 %s: %r → %r (user=%s)", FIX, key, before, value, user_id)
        done.append({"key": key, "value": value, "before": before, "changed": True})
    return {"saved": done, "changed": sum(1 for d in done if d["changed"])}
