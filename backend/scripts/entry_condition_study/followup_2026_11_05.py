"""대기 항목 재측정 (2026-11-05 사장님 「이거먼저 개발해줘」) — 읽기 전용 · 운영 서버에서:
  docker compose exec -T api python - < scripts/entry_condition_study/followup_2026_11_05.py

  R 재가동 조건(D-080): ① 상승장 날(그날 가상 진입 평균 시장폭 ≥ 0.6, 통합 판정과 같은 정의) ≥ 10 ② S4 필터 안(24h ≥ +10%) 상위 3일 뺀 날 단위 90% 하한 > 0
  P P8·P9(9/18 후보): SHORT 게이트 + 1H ATR ≤ 1.5 / 4H 하단이탈 뒤 ≥ 14봉 — 9/19 이후 새 표본, 지금 쓰는 장세 필터 안에서도 비교
  S 볼밴 스윙 그림자 기록: 날짜별 신호 수 · 빠진 날 · 지금 모드
  G 운영팀 게이트 칸 안/밖 날 단위 비교 (council_gate_report.py 는 건별 평균)
순수익 = roi − 0.4 (Fix 452 가정, 실측 아님). 부트스트랩 2,000번 · 90% (Claude가 정함).
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

sys.path.insert(0, "/app")
from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.redis_client import get_redis_client  # noqa: E402
from app.services import entry_conditions as EC  # noqa: E402

NET = 0.4
S4 = "zone_s4_spike_top_short"
SINCE = "2026-09-18"
PRE_P = "2026-09-19"
ATR_MAX, SINCE_MIN = 1.5, 14.0   # paper_report_v3.TUNE 과 같은 값


def boot(xs, n=2000, seed=7):
    rnd = random.Random(seed)
    ms = sorted(sum(rnd.choice(xs) for _ in xs) / len(xs) for _ in range(n))
    return ms[int(n * 0.05)], ms[int(n * 0.95)]


def day_line(name, by_day):
    """by_day = {날짜: [roi]} → 날 평균의 평균 · 90% · 상위 3일 뺀 값."""
    if not by_day:
        return f"| {name} | 0 | — | — | — | — |"
    dm = {d: sum(v) / len(v) for d, v in by_day.items()}
    xs = list(dm.values())
    a, b = boot(xs)
    top = sorted(dm, key=dm.get, reverse=True)[:3]
    rest = [v for d, v in dm.items() if d not in top]
    ra, rb = boot(rest) if rest else (float("nan"), float("nan"))
    n = sum(len(v) for v in by_day.values())
    return (f"| {name} | {n}건·{len(xs)}일 | {sum(xs) / len(xs):+.2f} | {a:+.2f}~{b:+.2f} | "
            f"{(sum(rest) / len(rest)) if rest else float('nan'):+.2f} | {ra:+.2f}~{rb:+.2f} |")


def half(rows):
    """rows = [(d, roi)] → 앞 절반·뒤 절반 평균."""
    ds = sorted({d for d, _ in rows})
    if len(ds) < 2:
        return "—"
    mid = ds[len(ds) // 2]
    a = [r for d, r in rows if d < mid]
    b = [r for d, r in rows if d >= mid]
    return f"{sum(a) / max(1, len(a)):+.2f} → {sum(b) / max(1, len(b)):+.2f}"


def section_r(db):
    print("## R. 재가동 조건\n")
    db.execute(text("set statement_timeout = 300000"))
    rows = db.execute(text("""select (opened_at + interval '9 hours')::date d, avg((snapshot->>'market_breadth')::float) mb, count(*) n
        from paper_trades where source='live' and opened_at >= :s and snapshot ? 'market_breadth'
        group by 1 order by 1"""), {"s": SINCE}).all()
    mb = {r.d: float(r.mb) for r in rows if r.mb is not None}
    up = [d for d, v in mb.items() if v >= 0.6]
    down = [d for d, v in mb.items() if v <= 0.4]
    print(f"- 시장폭 있는 날 {len(mb)} ({min(mb)}~{max(mb)}) · 상승장(≥0.6) **{len(up)}일** · 하락장(≤0.4) {len(down)}일")
    print("- 상승장 날: " + ", ".join(str(d)[5:] for d in sorted(up)))
    last = [d for d in up if d >= date(2026, 10, 25)]
    print(f"- 10/25 판정 뒤 상승장 날 {len(last)}일")
    since_snap = db.execute(text("""select (opened_at + interval '9 hours')::date d, (engines->'live'->>'roi')::float roi, chg_24h
        from paper_trades where source='live' and status='CLOSED' and rule=:r and opened_at >= :s
        and engines->'live'->>'roi' is not null"""), {"r": S4, "s": SINCE}).all()
    inside = defaultdict(list)
    for x in since_snap:
        try:
            if float(x.chg_24h) >= 10:
                inside[x.d].append(float(x.roi) - NET)
        except (TypeError, ValueError):
            pass
    print("\n| S4 필터 안 순수익 | 표본 | 날 평균 | 90% | 상위 3일 뺀 | 상위 3일 뺀 90% |\n|---|---|---|---|---|---|")
    print(day_line("전체", inside))
    print(day_line("10/25 뒤", {d: v for d, v in inside.items() if d >= date(2026, 10, 25)}))
    print(day_line("상승장 날만", {d: v for d, v in inside.items() if mb.get(d, 0) >= 0.6}))
    print(day_line("상승장 아닌 날", {d: v for d, v in inside.items() if d in mb and mb[d] < 0.6}))
    print(f"\n- S4 진입이 있었던 상승장 날: {sum(1 for d in inside if mb.get(d, 0) >= 0.6)}일")
    n_open = db.execute(text("select count(*) from paper_trades where source='live' and status<>'CLOSED' and rule=:r"), {"r": S4}).scalar()
    print(f"- 아직 안 끝난 S4 가상 {n_open}건(위 표에 없음 — 최근 날짜일수록 빨리 끝난 거래만 들어감)")
    for k in ("auto_trading_halt", "rf_zone_s4_mode", "scheduled_entry_enabled"):
        row = db.execute(text("select value from system_settings where key=:k"), {"k": k}).first()
        print(f"- {k} = {row[0] if row else '(없음)'}")


def section_g(db):
    print("\n## G. 운영팀 게이트 — 날 단위 (칸 안 − 칸 밖, 두 칸이 모두 있는 날)\n")
    r = get_redis_client()
    recs = []
    for k in r.scan_iter("council:gate:*", count=500):
        try:
            recs.append(json.loads(r.get(k)))
        except (TypeError, ValueError):
            pass
    pids = [x["paper_trade_id"] for x in recs if x.get("paper_trade_id")]
    info = {}
    for i in range(0, len(pids), 1000):
        for row in db.execute(text("""select id, (opened_at + interval '9 hours')::date d, (engines->'live'->>'roi')::float roi
            from paper_trades where id = any(:ids) and status='CLOSED' and engines->'live'->>'roi' is not null"""), {"ids": pids[i:i + 1000]}):
            info[row.id] = (row.d, float(row.roi))
    fam = defaultdict(lambda: {True: defaultdict(list), False: defaultdict(list)})
    for x in recs:
        v = info.get(x.get("paper_trade_id"))
        if v and x.get("in_cells") is not None:
            fam[x.get("family")][bool(x["in_cells"])][v[0]].append(v[1])
    print("| 가족 | 안 n | 밖 n | 비교 날 | 안−밖 날 평균 | 90% | 첫·끝 날 |\n|---|---|---|---|---|---|---|")
    for name in sorted(fam, key=str):
        a, b = fam[name][True], fam[name][False]
        both = sorted(set(a) & set(b))
        na, nb = sum(map(len, a.values())), sum(map(len, b.values()))
        if len(both) < 5:
            print(f"| {name} | {na} | {nb} | {len(both)} | — | 표본 부족 | — |")
            continue
        ds = [sum(a[d]) / len(a[d]) - sum(b[d]) / len(b[d]) for d in both]
        lo, hi = boot(ds)
        print(f"| {name} | {na} | {nb} | {len(both)} | {sum(ds) / len(ds):+.2f} | {lo:+.2f}~{hi:+.2f} | {str(both[0])[5:]}~{str(both[-1])[5:]} |")


def section_p(db):
    print("\n## P. P8·P9 (9/19 이후 · SHORT · baseline 제외)\n")
    q = text("""select opened_at::date d, chg_24h, (engines->'live'->>'roi')::float roi,
        snapshot->'chart_state'->'h1'->>'from_hi_pct' h1hi, snapshot->'chart_state'->'m5'->>'from_hi_pct' m5hi,
        snapshot->'chart_state'->'d1'->'bb'->>'trend' tr, snapshot->'chart_state'->'h1'->>'atr14_pct' atr,
        snapshot->'chart_state'->'h4'->'bb'->>'bars_since_below_lower' sl
        from paper_trades where source='live' and status='CLOSED' and side='SHORT' and opened_at >= :s
        and rule not like 'baseline_%' and engines->'live'->>'roi' is not null""")
    cells = defaultdict(list)
    n = no_state = 0
    res = db.execute(q.execution_options(yield_per=2000), {"s": PRE_P})
    for r in res:
        n += 1
        if r.h1hi is None or r.tr is None:
            no_state += 1
            continue
        snap = {"chart_state": {"h1": {"from_hi_pct": float(r.h1hi)}, "m5": {"from_hi_pct": float(r.m5hi) if r.m5hi is not None else None},
                                "d1": {"bb": {"trend": r.tr}}}}
        gate = EC.evaluate("SHORT", snap)["verdict"] == "pass"
        try:
            inf = float(r.chg_24h) >= 10
        except (TypeError, ValueError):
            inf = False
        net = float(r.roi) - NET
        for scope, ok in (("전체", True), ("필터 안", inf)):
            if not ok:
                continue
            if r.atr is not None:
                cells[(scope, "P8", gate and float(r.atr) <= ATR_MAX)].append((r.d, net))
            if r.sl is not None:
                cells[(scope, "P9", gate and float(r.sl) >= SINCE_MIN)].append((r.d, net))
            cells[(scope, "게이트만", gate)].append((r.d, net))
    print(f"- SHORT 행 {n:,} · 차트 값 없음(옛 행 상세 정리·값 없음) {no_state:,}\n")
    print("| 범위 | 후보 | 통과 n·일 | 통과 평균 | 앞→뒤 | 제외 n | 제외 평균 | 차이 |\n|---|---|---|---|---|---|---|---|")
    for scope in ("전체", "필터 안"):
        for name in ("게이트만", "P8", "P9"):
            k, e = cells.get((scope, name, True), []), cells.get((scope, name, False), [])
            if not k or not e:
                print(f"| {scope} | {name} | {len(k)} | — | — | {len(e)} | — | — |")
                continue
            km, em = sum(x for _, x in k) / len(k), sum(x for _, x in e) / len(e)
            print(f"| {scope} | {name} | {len(k):,}·{len({d for d, _ in k})}일 | {km:+.2f} | {half(k)} | {len(e):,} | {em:+.2f} | {km - em:+.2f} |")


def section_s(db):
    print("\n## S. 볼밴 스윙 그림자\n")
    r = get_redis_client()
    by, sides = Counter(), Counter()
    oldest_ttl = None
    for k in r.scan_iter("bbswing:shadow:*", count=2000):
        try:
            p = json.loads(r.get(k) or "{}")
        except ValueError:
            continue
        name = k.decode() if isinstance(k, bytes) else k
        parts = name.split(":")
        sides[parts[3] if len(parts) > 3 else "?"] += 1
        d = str(p.get("at") or p.get("ts") or p.get("signal_at") or "")[:10]
        if not d and parts[-1].isdigit():
            from datetime import datetime, timezone
            d = datetime.fromtimestamp(int(parts[-1]) / 1000, timezone.utc).date().isoformat()
        by[d] += 1
    print(f"- 신호 {sum(by.values()):,} · 방향 {dict(sides)}")
    ds = sorted(d for d in by if d)
    if ds:
        print(f"- 첫 날 {ds[0]} · 마지막 날 {ds[-1]} · 있는 날 {len(ds)}일")
        a, b = date.fromisoformat(ds[0]), date.fromisoformat(ds[-1])
        miss = [str(a + timedelta(days=i)) for i in range((b - a).days + 1) if str(a + timedelta(days=i)) not in by]
        print(f"- 빠진 날: {miss or '없음'}")
        print("- 날짜별: " + " ".join(f"{d[5:]}:{by[d]}" for d in ds))
    cyc = r.get("bbswing:last_cycle")
    print(f"- 마지막 사이클: {(cyc.decode() if isinstance(cyc, bytes) else cyc or '없음')[:160]}")
    row = db.execute(text("select value from system_settings where key='bb_swing_mode'")).first()
    print(f"- bb_swing_mode = {row[0] if row else '(기본 shadow)'}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    db = SessionLocal()
    try:
        for part in (section_r, section_g, section_p, section_s):
            if len(sys.argv) < 2 or part.__name__[-1] in sys.argv[1]:
                part(db)
    finally:
        db.rollback()
        db.close()


main()
