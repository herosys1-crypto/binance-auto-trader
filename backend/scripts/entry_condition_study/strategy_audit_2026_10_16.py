"""전 전략 검토표 (2026-10-16 사장님 「모든 자동매매 전략 검토 · 되는 것만 남기고 나머지 폐기/전면 수정」) — 읽기 전용.

가상매매(source=live) 끝난 행 45일. 규칙마다:
  전체      n · 순수익 평균(roi − 0.4) · 같은 날·같은 방향 무작위 대비(edge)
  필터 안   두 줄 법칙(Fix 439): LONG = 진입 시장폭 < 0.4 · SHORT = 24h +10% 이상
  안정성    필터 안 앞 절반 / 뒤 절반 날짜의 순수익 평균, 플러스 날 비율(하루 평균 > 0, 하루 5건 이상인 날)
  하루 1건  필터 안 그날 첫 진입 1건만 — 실주문과 같은 크기
판정(Claude가 정함, 「손실 없음」은 불가능하므로 「기대값 플러스가 두 기간 모두에서 유지」로 바꿔 씀):
  ✅ 유지  필터 안 n ≥ 100 · 순수익 > 0 · edge > 0 · 앞·뒤 절반 모두 순수익 > 0 · 플러스 날 ≥ 55% · 하루 1건 순수익 > 0
  🛠 수정  필터 안 순수익 > 0 이지만 위 중 하나 이상 실패 (또는 필터 밖에서만 좋음)
  ❌ 폐기  필터 안·밖 모두 순수익 ≤ 0 이거나 edge ≤ −0.5
운영:  docker compose exec -T api python - < scripts/entry_condition_study/strategy_audit_2026_10_16.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402

DAYS = 45
NET = 0.4
KST_OFF = timedelta(hours=9)                         # 하루 = KST(실주문 「하루 최대」 와 같은 경계, auto_family_registry)
BASE = "baseline_"

SQL = text("""
    SELECT rule, side, opened_at, (opened_at AT TIME ZONE 'UTC')::date AS d, engines->'live'->>'roi' AS roi,
           snapshot->>'market_breadth' AS mb, chg_24h
    FROM paper_trades
    WHERE source = 'live' AND status = 'CLOSED' AND opened_at > :since AND engines->'live'->>'roi' IS NOT NULL
""")


def num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def in_filter(side, mb, chg):
    return (mb is not None and mb < 0.4) if side == "LONG" else (chg is not None and chg >= 10)


def mean(v):
    return sum(v) / len(v) if v else None


def main():
    db = SessionLocal()
    rows = []
    try:
        res = db.execute(SQL, {"since": datetime.now(timezone.utc) - timedelta(days=DAYS)},
                         execution_options={"stream_results": True})
        for r in res:
            roi = num(r.roi)
            if roi is not None and r.side in ("LONG", "SHORT"):
                rows.append((str(r.rule), r.side, r.opened_at, (r.opened_at + KST_OFF).date(), roi, num(r.mb), num(r.chg_24h)))
    finally:
        db.close()

    base = defaultdict(list)                          # (side, d) → roi
    by_rule = defaultdict(list)
    for rule, side, at, d, roi, mb, chg in rows:
        if rule.startswith(BASE):
            base[(side, d)].append(roi)
        else:
            by_rule[(rule, side)].append((at, d, roi, mb, chg))
    bm = {k: mean(v) for k, v in base.items()}
    days = sorted({r[3] for r in rows})
    mid = days[len(days) // 2] if days else None

    out = []
    for (rule, side), xs in by_rule.items():
        allv = [x[2] for x in xs]
        edge = mean([x[2] - bm[(side, x[1])] for x in xs if (side, x[1]) in bm])
        fx = [x for x in xs if in_filter(side, x[3], x[4])]
        fv = [x[2] for x in fx]
        h1 = [x[2] for x in fx if x[1] < mid]
        h2 = [x[2] for x in fx if x[1] >= mid]
        perday = defaultdict(list)
        for x in fx:
            perday[x[1]].append(x)
        dm = [mean([y[2] for y in v]) for v in perday.values() if len(v) >= 5]
        first = [min(v, key=lambda y: y[0])[2] for v in perday.values()]
        fedge = mean([x[2] - bm[(side, x[1])] for x in fx if (side, x[1]) in bm])
        net = lambda v: None if not v else mean(v) - NET   # noqa: E731
        c = {"rule": rule, "side": side, "n": len(allv), "net": net(allv), "edge": edge,
             "fn": len(fv), "fnet": net(fv), "fedge": fedge, "h1": net(h1), "h2": net(h2),
             "pday": (sum(m > 0 for m in dm) / len(dm)) if dm else None, "ndays": len(dm),
             "one": net(first), "n1": len(first)}
        ok = (c["fn"] >= 100 and (c["fnet"] or -1) > 0 and (c["fedge"] or -1) > 0 and (c["h1"] or -1) > 0
              and (c["h2"] or -1) > 0 and (c["pday"] or 0) >= 0.55 and (c["one"] or -1) > 0)
        dead = ((c["fnet"] is None or c["fnet"] <= 0) and (c["net"] or -1) <= 0) or (edge is not None and edge <= -0.5)
        c["verdict"] = "✅ 유지" if ok else ("❌ 폐기" if dead else "🛠 수정")
        out.append(c)

    f = lambda x, p=2: "—" if x is None else f"{x:+.{p}f}"   # noqa: E731
    print(f"# 전 전략 검토표 — 가상 끝난 행 {len(rows):,} · {days[0]}~{days[-1]} ({len(days)}일) · 순수익 = roi − {NET}")
    print("| 판정 | 규칙 | 방향 | 전체 n | 전체 순수익 | edge | 필터 안 n | 필터 안 순수익 | 필터 edge | 앞 절반 | 뒤 절반 | 플러스 날 | 하루 1건 순수익(n) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    order = {"✅ 유지": 0, "🛠 수정": 1, "❌ 폐기": 2}
    for c in sorted(out, key=lambda c: (order[c["verdict"]], -(c["fnet"] or -99))):
        pd = "—" if c["pday"] is None else f"{c['pday']:.0%} ({c['ndays']})"
        print(f"| {c['verdict']} | {c['rule']} | {c['side']} | {c['n']} | {f(c['net'])} | {f(c['edge'])} | {c['fn']} | "
              f"{f(c['fnet'])} | {f(c['fedge'])} | {f(c['h1'])} | {f(c['h2'])} | {pd} | {f(c['one'])} ({c['n1']}) |")
    for side in ("LONG", "SHORT"):
        v = [x for k, xs in base.items() if k[0] == side for x in xs]
        print(f"무작위 {side}: n {len(v)} · 순수익 {f(mean(v) - NET if v else None)}")


if __name__ == "__main__":
    main()
