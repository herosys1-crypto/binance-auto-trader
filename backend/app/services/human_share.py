"""🧮 Fix 434 (2026-10-10 사장님 「1」) — 전략 실현 손익을 「시스템 몫 / 사람 💉 추가 몫 / 출처 모름」으로 나눈다 (보고 전용).

계기: [[가상 vs 실주문 차이 2026-10-10]] — 규칙 가족 실거래 손실 −89.5 USDT 가 전부 사람의 「💉 포지션 추가」였다.
      Fix 400 (family_loss_breaker.family_share = 설계 자본 ÷ 실제 자본)은 **익절 완료(COMPLETED) 전략의 실제 자본이 0** 으로
      남아 사람 몫을 못 덜어낸다 (#4596 ARX +44.09 · #4624 MAGMA +6.60 이 가족 몫으로 셈) → 체결로 나눈다.

방법 = loss_cause(Fix 371b)의 **체결 재생**(진입 lot 을 쌓고 청산 체결마다 보유 비중대로 손익 배분) 재사용:
  진입 체결 출처: stage_no 있음 = plan(시스템) · `_ADHOC_AM_`/`_ADHOC_AL_` = auto_add(시스템 자동 추가)
                · `_ADHOC_M_`/`_ADHOC_L_` 이고 Fix 371(2026-09-14) 뒤 = manual_add(사람) · 그 전 = unknown(공용 접미사 시절)
  사람 몫 = manual lot 의 재생 손익 · 출처 모름 = unknown lot · 시스템 몫 = 실현 손익 − 둘
  수수료·펀딩(실현 − 재생 총손익)은 진입 명목 비율로 나눈다
  청산 체결이 모자라 재생이 안 되면(청산 비율 < 95%) 진입 명목 비율로 실현 손익을 나눈다 (method = notional).
매매 판정·차단기에는 쓰지 않는다 — 보고서(실거래 가족 집계 · 운영팀 게이트 판정)만.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from app.services.loss_cause import AUTO_SUFFIXES, _f, replay

FIX = "Fix434"
FIX371_AT = datetime(2026, 9, 14, tzinfo=timezone.utc)    # 이 뒤 자동 추가는 _ADHOC_AM_/_AL_ 로 찍힌다 (Fix 371)
MANUAL_SUFFIXES = ("_ADHOC_M_", "_ADHOC_L_")
MIN_CLOSED_RATIO = 0.95


def _aware(t: Any) -> datetime | None:
    if not isinstance(t, datetime):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def origin_of(entry: Mapping[str, Any]) -> str:
    cid = str(entry.get("client_order_id") or "")
    if entry.get("stage_no") is not None:
        return "plan"
    if any(s in cid for s in AUTO_SUFFIXES):
        return "auto_add"
    if any(s in cid for s in MANUAL_SUFFIXES):
        t = _aware(entry.get("t"))
        return "manual_add" if t is not None and t >= FIX371_AT else "unknown"
    if "_ENTRY" in cid:                       # SYM_ENTRY1_… = 시스템 1차 (stage_no 가 비어 있어도)
        return "plan"
    return "unknown"


def _pack(base: dict, hum: float, unk: float, method: str) -> dict[str, Any]:
    """반올림한 값끼리 합이 실현 손익과 같게 — 시스템 몫 = 실현 − 사람 − 모름 (반올림 뒤)."""
    h, u = round(hum, 4), round(unk, 4)
    return {**base, "system": round(base["realized"] - h - u, 4), "human": h, "unknown": u, "method": method}


def split(side: Any, entries: Sequence[Mapping[str, Any]], exits: Sequence[Mapping[str, Any]], realized: Any) -> dict[str, Any]:
    """{"system", "human", "unknown", "realized", "method", "human_n"(사람 추가 체결 수)} — USDT."""
    rp = _f(realized) or 0.0
    es = [{**e, "origin": origin_of(e)} for e in entries]
    human_n = sum(1 for e in es if e["origin"] == "manual_add")
    unk_n = sum(1 for e in es if e["origin"] == "unknown")
    base = {"realized": round(rp, 4), "human_n": human_n}
    if human_n == 0 and unk_n == 0:
        return {**base, "system": round(rp, 4), "human": 0.0, "unknown": 0.0, "method": "none"}
    def notional(kind: str) -> float:
        return sum((_f(e.get("qty")) or 0.0) * (_f(e.get("price")) or 0.0) for e in es if e["origin"] == kind)
    tot = sum(notional(k) for k in ("plan", "auto_add", "manual_add", "unknown"))
    r = replay(side, es, exits)
    if r["lots"] and r["closed_ratio"] >= MIN_CLOSED_RATIO and tot > 0:
        # 실현 − 재생 총손익 = 수수료·펀딩(대개 음수) → 진입 명목 비율로 나눈다 (큰 사람 추가의 수수료가 시스템 몫에 붙지 않게)
        fee = rp - r["pnl_gross"]
        hum = sum(l["pnl"] for l in r["lots"] if l["origin"] == "manual_add") + fee * notional("manual_add") / tot
        unk = sum(l["pnl"] for l in r["lots"] if l["origin"] == "unknown") + fee * notional("unknown") / tot
        return _pack(base, hum, unk, "replay")
    # 재생 불가 → 진입 명목(수량 × 가격) 비율
    if tot <= 0:
        return {**base, "system": round(rp, 4), "human": 0.0, "unknown": 0.0, "method": "none"}
    hum, unk = rp * notional("manual_add") / tot, rp * notional("unknown") / tot
    return _pack(base, hum, unk, "notional")


def split_for(db: Any, items: Iterable[tuple[int, str, Any]]) -> dict[int, dict[str, Any]]:
    """items = [(전략 id, side, realized_pnl), ...] → {id: split}. 체결은 쿼리 한 번."""
    from sqlalchemy import select
    from app.models.order import Order
    items = list(items)
    ids = [i for i, _s, _p in items]
    ev: dict[int, tuple[list, list]] = {i: ([], []) for i in ids}
    if ids:
        rows = db.execute(
            select(Order.strategy_instance_id, Order.purpose, Order.stage_no, Order.order_type, Order.client_order_id,
                   Order.executed_qty, Order.avg_price, Order.price, Order.created_at, Order.updated_at)
            .where(Order.strategy_instance_id.in_(ids), Order.executed_qty > 0, Order.purpose.in_(("ENTRY", "EXIT")))
            .order_by(Order.strategy_instance_id, Order.id)          # 같은 시각 체결도 실행마다 같은 순서 (교차 감사)
        ).all()
        for sid, purpose, stage_no, otype, cid, qty, avg_px, px, created, updated in rows:
            e = {"t": updated or created, "qty": qty, "price": avg_px if _f(avg_px) else px, "approx_price": not _f(avg_px),
                 "stage_no": stage_no, "order_type": otype, "client_order_id": cid}
            ev[sid][0 if purpose == "ENTRY" else 1].append(e)
    out: dict[int, dict[str, Any]] = {}
    for i, side, rp in items:
        try:
            out[i] = split(side, ev[i][0], ev[i][1], rp)
        except Exception as e:  # noqa: BLE001 — 한 전략의 이상한 체결이 보고 전체를 죽이지 않게 (교차 감사). 나누지 않고 드러낸다.
            r = _f(rp) or 0.0
            out[i] = {"system": round(r, 4), "human": 0.0, "unknown": 0.0, "realized": round(r, 4), "method": "error",
                      "human_n": 0, "error": str(e)[:120]}
    return out
