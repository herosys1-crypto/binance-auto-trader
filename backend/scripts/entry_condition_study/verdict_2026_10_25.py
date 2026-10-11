"""🧾 Fix 441 (2026-10-11 사장님 「1번 진행해줘」) — 10/23~25 통합 판정 보고서 (읽기 전용, 판정 기준을 미리 고정).

운영 서버에서:  docker compose exec -T api python - < scripts/entry_condition_study/verdict_2026_10_25.py
            (판정 날짜를 바꾸려면 환경변수 VERDICT_NOW=2026-10-25T00:00:00+00:00)

## 사전 등록 판정 기준 (2026-10-11 고정 — 결과를 보고 바꾸지 않는다. 숫자는 「Claude가 정함」)
  가상 규칙: 마감 n ≥ 30 · 진입일 ≥ 7일 · 평균 roi > 0 · 같은 날·같은 방향 무작위 대비 > 0 · 앞 절반 > 0 · 뒤 절반 > 0
            · 하루 1건 제한(종목당 하루 1번, 봉 순서) 합 > 0 · 이긴 날 ≥ 50%   →  모두 = ✅ 통과 / n·일수 미달 = ⏳ 보류 / 그 밖 = ❌ 기각
  실주문 가족: 시스템 몫(Fix 434) 합 > 0 · 끝난 n ≥ 5 → 통과 / n < 5 → 보류 / 그 밖 → 기각   (사람 💉 추가 몫은 따로 표시)
  운영팀 게이트: 칸 안 평균 − 칸 밖 평균 > 0 (가상 roi, 각 n ≥ 30) → 「막기」 후보
  각 대상은 **자기 배포 시각 이후** 행만 센다 (아래 CUTOFFS).

## 대상
  A 실주문 가족(장세 필터 뒤) · B 새 가상 규칙(합의 LONG · 급등 정점 SHORT 2) · C 외부 전략 가상 규칙(장세 필터 안/밖)
  D 규칙 가족 가상 규칙(장세 필터 안/밖) · E 운영팀 게이트(칸 안/밖)
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

sys.path.insert(0, "/app")

# ── 배포 시각 (UTC) — 이 뒤 진입만 센다 ──
CUTOFFS = {
    "emapb": "2026-10-09T10:02:00+00:00",            # Fix 423·424 EMA 추세 눌림 (아담쿠식)
    "fujimoto": "2026-10-09T18:12:00+00:00",          # Fix 427 일봉
    "mach7": "2026-10-09T18:12:00+00:00",
    "bbema": "2026-10-09T23:51:00+00:00",             # Fix 429
    "bbwave": "2026-10-10T01:10:00+00:00",            # Fix 431
    "trima": "2026-10-10T01:10:00+00:00",             # Fix 432
    "consensus": "2026-10-10T22:45:00+00:00",         # Fix 437
    "pumptop": "2026-10-11T03:05:00+00:00",           # Fix 438
    "regime": "2026-10-11T03:05:00+00:00",            # Fix 439 장세 필터 (규칙 가족)
    "ext_regime": "2026-10-11T10:08:00+00:00",        # Fix 440 장세 필터 (외부 전략)
}
CRIT = {"min_n": 30, "min_days": 7, "win_days": 0.5, "live_min_n": 5, "gate_min_n": 30}
CUTOFFS["mass_rebound"] = "2026-10-10T22:45:00+00:00"        # 📣 Fix 442 — 판정 재료는 가상 행이라 합의 LONG 배포 시각부터 같게
EXT_PREFIX = {"emapb_": "emapb", "fujimoto_": "fujimoto", "mach7_": "mach7", "bbema_": "bbema", "bbwave_": "bbwave", "trima_": "trima"}
NEW_RULES = {"consensus_long": "consensus", "pumptop_short_30": "pumptop", "pumptop_short_mid": "pumptop"}


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _f(x: Any) -> float | None:
    if isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def regime_ok(side: str, breadth: Any, chg24: Any, lo_breadth: float = 0.4, short_chg: float = 10.0) -> bool | None:
    """두 줄 법칙 (Fix 439 와 같은 정의). 모르면 None."""
    if side == "LONG":
        b = _f(breadth)
        return None if b is None or not 0.0 <= b <= 1.0 else b < lo_breadth
    c = _f(chg24)
    return None if c is None else c >= short_chg


def evaluate(rows: list[dict], base_mean: dict) -> dict:
    """rows = [{"d": date, "side", "symbol", "ts": entry_bar_ts, "roi"}] → 판정 지표 + 사전 등록 판정."""
    n = len(rows)
    if n == 0:
        return {"n": 0, "days": 0, "verdict": "⏳ 보류", "why": "표본 없음"}
    days = sorted({r["d"] for r in rows})
    mid = days[len(days) // 2]
    roi = sum(r["roi"] for r in rows) / n
    e = [r["roi"] - base_mean[(r["side"], r["d"])] for r in rows if (r["side"], r["d"]) in base_mean]
    edge = sum(e) / len(e) if e else None
    h1 = [r["roi"] for r in rows if r["d"] < mid]
    h2 = [r["roi"] for r in rows if r["d"] >= mid]
    a1 = sum(h1) / len(h1) if h1 else None
    a2 = sum(h2) / len(h2) if h2 else None
    first: dict = {}
    seen: set = set()
    for r in sorted(rows, key=lambda r: (r["d"], r["ts"])):
        if r["d"] in first or (r["d"], r["symbol"]) in seen:
            continue
        first[r["d"]] = r["roi"]
        seen.add((r["d"], r["symbol"]))
    cap_sum = sum(first.values()) * 10 / 100                    # 10 USDT 증거금 기준 USDT
    win_days = sum(1 for v in first.values() if v > 0) / len(first) if first else 0.0
    out = {"n": n, "days": len(days), "roi": roi, "edge": edge, "first_half": a1, "second_half": a2,
           "cap1_usdt": cap_sum, "win_days": win_days}
    if n < CRIT["min_n"] or len(days) < CRIT["min_days"]:
        out.update(verdict="⏳ 보류", why=f"표본 n {n}/{CRIT['min_n']} · 일 {len(days)}/{CRIT['min_days']}")
        return out
    fails = []
    if not roi > 0:
        fails.append("평균 ≤ 0")
    if edge is None or not edge > 0:
        fails.append("무작위 대비 ≤ 0")
    if a1 is None or not a1 > 0:
        fails.append("앞 절반 ≤ 0")
    if a2 is None or not a2 > 0:
        fails.append("뒤 절반 ≤ 0")
    if not cap_sum > 0:
        fails.append("하루 1건 합 ≤ 0")
    if win_days < CRIT["win_days"]:
        fails.append(f"이긴 날 {win_days:.0%} < {CRIT['win_days']:.0%}")
    out.update(verdict="✅ 통과" if not fails else "❌ 기각", why=" · ".join(fails) or "기준 모두 충족")
    return out


def live_verdict(system_sum: float, n_closed: int) -> str:
    if n_closed < CRIT["live_min_n"]:
        return "⏳ 보류"
    return "✅ 통과" if system_sum > 0 else "❌ 기각"


def _fmt(x: Any, p: str = "+.2f") -> str:
    return "—" if x is None else format(x, p)


def line(name: str, ev: dict) -> str:
    if not ev.get("n"):
        return f"| {name} | 0 | — | — | — | — | — | — | {ev['verdict']} {ev.get('why', '')} |"
    return (f"| {name} | {ev['n']} ({ev['days']}일) | {_fmt(ev['roi'])} | {_fmt(ev['edge'])} | {_fmt(ev['first_half'])} → {_fmt(ev['second_half'])} "
            f"| {_fmt(ev['cap1_usdt'], '+.1f')}U | {ev['win_days']:.0%} | {ev['verdict']} | {ev['why']} |")


def main() -> None:  # pragma: no cover — 운영 DB 필요
    from sqlalchemy import select, text
    from app.core.database import SessionLocal
    from app.core.redis_client import get_redis_client
    from app.services import human_share as HS
    from app.services import rule_families as RF
    from app.models.strategy_instance import StrategyInstance as SI
    from app.models.strategy_template import StrategyTemplate as ST

    now = _dt(os.environ["VERDICT_NOW"]) if os.environ.get("VERDICT_NOW") else datetime.now(timezone.utc)
    earliest = min(_dt(v) for v in CUTOFFS.values())
    db = SessionLocal()
    try:
        q = text("""select rule, side, symbol, entry_bar_ts ts, opened_at, opened_at::date d, (engines->'live'->>'roi')::float roi,
                    chg_24h, snapshot->>'market_breadth' mb, snapshot->'rules_fired' rf
                    from paper_trades where source='live' and status='CLOSED' and opened_at >= :since and opened_at <= :now
                    and engines->'live'->>'roi' is not null""")
        rows = [dict(r._mapping) for r in db.execute(q, {"since": earliest, "now": now})]
        base: dict = defaultdict(list)
        for r in rows:
            if r["rule"].startswith("baseline_"):
                base[(r["side"], r["d"])].append(r["roi"])
        bm = {k: sum(v) / len(v) for k, v in base.items()}
        print(f"# 통합 판정 보고서 — {now:%Y-%m-%d %H:%M} UTC (사전 등록 기준 2026-10-11 고정)\n")
        print("기준: n ≥ 30 · 7일 이상 · 평균 > 0 · 무작위 대비 > 0 · 앞·뒤 절반 > 0 · 하루 1건 합 > 0 · 이긴 날 ≥ 50%\n")
        hdr = "| 대상 | n | 평균 roi % | 무작위 대비 | 앞 → 뒤 | 하루 1건(10U) | 이긴 날 | 판정 | 사유 |\n|---|---|---|---|---|---|---|---|---|"

        print("## B. 새 가상 규칙 (강화판)\n" + hdr)
        for rule, ck in NEW_RULES.items():
            xs = [r for r in rows if r["rule"] == rule and r["opened_at"] >= _dt(CUTOFFS[ck])]
            print(line(rule, evaluate(xs, bm)))

        print("\n## C. 외부 전략 가상 규칙 — 장세 필터 안 / 밖\n" + hdr)
        ext_rules = sorted({r["rule"] for r in rows if any(r["rule"].startswith(p) for p in EXT_PREFIX)})
        for rule in ext_rules:
            ck = next(v for p, v in EXT_PREFIX.items() if rule.startswith(p))
            xs = [r for r in rows if r["rule"] == rule and r["opened_at"] >= _dt(CUTOFFS[ck])]
            ins = [r for r in xs if regime_ok(r["side"], r["mb"], r["chg_24h"]) is True]
            outs = [r for r in xs if regime_ok(r["side"], r["mb"], r["chg_24h"]) is False]
            print(line(f"{rule} · 필터 안", evaluate(ins, bm)))
            print(line(f"{rule} · 필터 밖", evaluate(outs, bm)))

        print("\n## D. 규칙 가족 가상 규칙 — 장세 필터 안 / 밖 (Fix 439 배포 뒤)\n" + hdr)
        for fam in RF.FAMILIES:
            if fam.rule in NEW_RULES:
                continue
            xs = [r for r in rows if r["rule"] == fam.rule and r["opened_at"] >= _dt(CUTOFFS["regime"])]
            ins = [r for r in xs if regime_ok(r["side"], r["mb"], r["chg_24h"]) is True]
            outs = [r for r in xs if regime_ok(r["side"], r["mb"], r["chg_24h"]) is False]
            print(line(f"{fam.key} · 필터 안", evaluate(ins, bm)))
            print(line(f"{fam.key} · 필터 밖", evaluate(outs, bm)))

        print("\n## A. 실주문 가족 — 장세 필터 뒤 실현 (시스템 몫 · 사람 💉 추가 몫 따로)\n")
        print("| 가족 | 모드 | 끝난 n | 시스템 몫 USDT | 사람 추가 몫 | 진행 중 | 판정 |\n|---|---|---|---|---|---|---|")
        from app.core.strategy_status import TERMINAL_STATUSES
        st_of = {f.stype: f for f in RF.FAMILIES}
        got = db.execute(select(SI.id, SI.side, SI.status, SI.realized_pnl, ST.strategy_type)
                         .join(ST, ST.id == SI.strategy_template_id)
                         .where(ST.strategy_type.in_(list(st_of)), SI.created_at >= _dt(CUTOFFS["regime"]), SI.created_at <= now)).all()
        closed = [(sid, side, rp, stype) for sid, side, status, rp, stype in got if status in TERMINAL_STATUSES]
        sp = HS.split_for(db, [(sid, side, rp) for sid, side, rp, _s in closed]) if closed else {}
        agg: dict = defaultdict(lambda: [0, 0.0, 0.0, 0])
        for sid, side, status, rp, stype in got:
            a = agg[st_of[stype].key]
            if status in TERMINAL_STATUSES:
                a[0] += 1
                a[1] += sp.get(sid, {}).get("system", float(rp or 0))
                a[2] += sp.get(sid, {}).get("human", 0.0)
            else:
                a[3] += 1
        for fam in RF.FAMILIES:
            mode = RF.mode_of(db, fam.key)
            if mode != "on" and fam.key not in agg:
                continue
            n, s, h, op = agg[fam.key]
            print(f"| {fam.label} | {mode} | {n} | {s:+.2f} | {h:+.2f} | {op} | {live_verdict(s, n)} |")

        print("\n## F. 📣 시장 전체 동시 반등 (Fix 442) — 같은 봉 LONG 규칙 4개+ 종목 16개+ 순간의 LONG 진입 (봉·종목당 1건)\n" + hdr)
        from app.services import mass_rebound as MR
        side_of = {}
        for r_ in rows:
            if not r_["rule"].startswith("baseline_"):
                side_of.setdefault(r_["rule"], r_["side"])
        mr_rows = [r_ for r_ in rows if r_["opened_at"] >= _dt(CUTOFFS["mass_rebound"])]
        bars = MR.retro_bars(mr_rows, side_of=side_of)
        one: dict = {}
        for r_ in mr_rows:
            if r_["ts"] in bars and r_["side"] == "LONG" and not r_["rule"].startswith("baseline_") and r_["rule"] not in NEW_RULES:
                one.setdefault((r_["ts"], r_["symbol"]), r_)
        print(line(f"동시 반등 봉 {len(bars)}개", evaluate(list(one.values()), bm)))

        print("\n## E. 운영팀 게이트 (Fix 433) — 칸 안 / 밖 (가상 roi, 그림자 기록)\n")
        r = get_redis_client()
        recs = []
        for k in r.scan_iter("council:gate:*", count=500):
            try:
                recs.append(json.loads(r.get(k)))
            except Exception:  # noqa: BLE001
                pass
        pids = [x["paper_trade_id"] for x in recs if x.get("paper_trade_id")]
        roi_of = {}
        if pids:
            for pid, eng in db.execute(text("select id, engines from paper_trades where id = any(:ids) and status='CLOSED'"),
                                       {"ids": pids}).all():
                if isinstance(eng, dict) and isinstance(eng.get("live"), dict) and _f(eng["live"].get("roi")) is not None:
                    roi_of[pid] = float(eng["live"]["roi"])
        g = {"안": [], "밖": []}
        for x in recs:
            v = roi_of.get(x.get("paper_trade_id"))
            if v is not None and x.get("in_cells") is not None:
                g["안" if x["in_cells"] else "밖"].append(v)
        mi = sum(g["안"]) / len(g["안"]) if g["안"] else None
        mo = sum(g["밖"]) / len(g["밖"]) if g["밖"] else None
        print(f"칸 안 n {len(g['안'])} 평균 {_fmt(mi)} · 칸 밖 n {len(g['밖'])} 평균 {_fmt(mo)}")
        if len(g["안"]) >= CRIT["gate_min_n"] and len(g["밖"]) >= CRIT["gate_min_n"] and mi is not None and mo is not None:
            print("→ " + ("✅ 「칸 밖 막기」 후보 (안 > 밖)" if mi > mo else "❌ 막지 않는다 (안 ≤ 밖)"))
        else:
            print(f"→ ⏳ 보류 (각 n ≥ {CRIT['gate_min_n']} 필요)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
