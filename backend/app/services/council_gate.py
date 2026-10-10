"""🧑‍⚖️ Fix 433 (2026-10-10 사장님 「1번 진행」) — 운영팀 게이트 **기록 전용** 단계 (규칙 가족 전용, 진입을 막지 않는다).

운영팀 성적표(Fix 430, Redis council:latest)의 「오늘 쓸 칸」(규칙·방향·시장폭 구간)에 지금 진입이 들어가는지를
규칙 가족 워커(rule_family_worker)가 진입 때마다 기록한다 → 2주 뒤 「칸 안 진입 vs 칸 밖 진입」 실거래 손익을 비교해
실제로 막을지(사장님 승인) 정한다. 이 단계에는 막는 코드가 없다 — 'on' 을 넣어도 기록만(경고).
기록: council:gate:{가족}:{가상행 id} (60일) — 실주문은 진입 성공 뒤 전략 id 와 함께.
설정 council_gate_mode = off | shadow (기본 shadow, 「Claude가 정함」).
"""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

FIX = "Fix433"
MODE_KEY = "council_gate_mode"
REPORT_KEY = "council:latest"
RECORD_TTL = 60 * 86400
STALE_AFTER = timedelta(hours=48)       # 보고서가 이틀 넘게 안 바뀌면 「모름」 (워커가 멈춘 것)
CACHE_S = 300
_cache: dict[str, Any] = {"t": None, "v": None}
_warned_on = False


@dataclass(frozen=True)
class Cells:
    cells: dict          # (rule, side, b) → edge
    lo: float
    hi: float
    d: str | None
    at: datetime | None


def mode_of(get) -> str:
    """get(key) → 설정 문자열. off | shadow. 'on' 은 이 단계에 없다 → shadow + 경고 1회. 그 밖 = 기본 shadow."""
    global _warned_on
    try:
        v = str(get(MODE_KEY) or "shadow").strip().lower()
    except Exception:  # noqa: BLE001
        v = "shadow"
    if v == "on":
        if not _warned_on:
            logger.warning("[%s] council_gate_mode=on 이지만 이 단계는 기록 전용 → shadow 로 동작 (막기는 2주 판정 + 사장님 승인 뒤)", FIX)
            _warned_on = True
        return "shadow"
    return v if v in ("off", "shadow") else "shadow"


def _num(x: Any) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def parse(raw: Any) -> Cells | None:
    try:
        data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        E = data["E_today"]
        p = data.get("params") or {}
        lo, hi = _num(p.get("lo")), _num(p.get("hi"))
        if lo is None or hi is None or not lo < hi:
            lo, hi = 0.4, 0.6
        cells = {}
        for c in E.get("cells") or []:
            if isinstance(c, dict) and c.get("rule") and c.get("side") in ("LONG", "SHORT") and c.get("b"):
                cells[(str(c["rule"]), c["side"], str(c["b"]))] = _num(c.get("edge"))
        at = None
        try:
            at = datetime.fromisoformat(str(data.get("at")))
            at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            at = None
        return Cells(cells=cells, lo=lo, hi=hi, d=E.get("d"), at=at)
    except Exception:  # noqa: BLE001 — 깨진 보고서 = 모름
        return None


def load(r, *, now_mono: float | None = None) -> Cells | None:
    """Redis council:latest → Cells. 프로세스 캐시 5분. 없거나 실패 = None (= 모름)."""
    t = time.monotonic() if now_mono is None else now_mono
    if _cache["t"] is not None and t - _cache["t"] < CACHE_S:
        return _cache["v"]
    try:
        raw = r.get(REPORT_KEY)
        v = parse(raw) if raw else None
    except Exception as e:  # noqa: BLE001
        logger.debug("[%s] 성적표 읽기 실패: %s", FIX, e)
        v = None
    _cache["t"], _cache["v"] = t, v
    return v


def bucket(mb: float | None, lo: float, hi: float) -> str:
    if mb is None:
        return "?"
    return "low" if mb < lo else ("mid" if mb <= hi else "high")


def judge(cells: Cells | None, rule: str, side: str, mb: Any, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    m = _num(mb)
    m = m if m is not None and 0.0 <= m <= 1.0 else None
    if cells is None:
        return {"b": bucket(m, 0.4, 0.6), "in_cells": None, "why": "성적표 없음", "report_d": None, "stale": None, "edge": None}
    b = bucket(m, cells.lo, cells.hi)
    stale = cells.at is None or now - cells.at > STALE_AFTER
    out = {"b": b, "report_d": cells.d, "stale": stale, "edge": cells.cells.get((rule, side, b))}
    if stale:
        out.update(in_cells=None, why="성적표 오래됨(48시간+)")
    elif b == "?":
        out.update(in_cells=None, why="시장폭 모름")
    else:
        out.update(in_cells=(rule, side, b) in cells.cells, why="")
    return out


def tally(stat: dict, res: dict) -> None:
    c = stat.setdefault("council", {"in": 0, "out": 0, "unknown": 0})
    k = "unknown" if res.get("in_cells") is None else ("in" if res["in_cells"] else "out")
    c[k] += 1


def record(r, fam_key: str, row_id: int, payload: dict, ttl: int = RECORD_TTL) -> bool:
    try:
        r.setex(f"council:gate:{fam_key}:{row_id}", ttl, json.dumps(payload, ensure_ascii=False, default=str))
        return True
    except Exception as e:  # noqa: BLE001
        logger.debug("[%s] 기록 실패: %s", FIX, e)
        return False


def mode_from_db(db) -> str:
    def get(key):
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        return None if row is None else row.value
    try:
        return mode_of(get)
    except Exception:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return "shadow"
