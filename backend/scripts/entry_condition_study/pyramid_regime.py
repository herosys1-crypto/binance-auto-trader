"""조건 붙인 피라미딩 — 읽기 전용. 가상매매가 병렬 기록한 추가 lot(live_both = 운영 추가 조건 · 양방향)을
진입 시점 시장 국면(태그 MKT_UP/DOWN, 시장폭 값)으로 갈라 두 기간(하락장 9/9~9/14 · 상승장 9/15~)에서 잰다."""
import sys
sys.path.insert(0, "/app")
from datetime import datetime, timezone
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models.paper_trade import PaperTrade as P
from app.services import paper_trading as PT

db = SessionLocal()
SPLIT = datetime(2026, 9, 15, tzinfo=timezone.utc)
try:
    rows = db.execute(select(P.side, P.tags, P.opened_at, P.snapshot["market_breadth"].astext, P.adds, P.symbol)
                      .where(P.source == "live", P.status == "CLOSED",
                             P.opened_at >= datetime(2026, 9, 9, tzinfo=timezone.utc))).all()
    print(f"마감 행 {len(rows)} · 시장폭 문턱 UP ≥{PT.BREADTH_UP} / DOWN ≤{PT.BREADTH_DOWN}")
    lots = []
    for side, tags, t, br, adds, sym in rows:
        tags = tags or []
        reg = "UP" if "MKT_UP" in tags else ("DOWN" if "MKT_DOWN" in tags else ("FLAT" if any(str(x).startswith("MKT_") for x in tags) else None))
        try:
            b = float(br) if br not in (None, "", "null") else None
        except ValueError:
            b = None
        for lot in (adds or {}).get("live_both") or []:
            p = lot.get("pnl_usdt")
            if p is None:
                continue
            lots.append((side, reg, b, "하락장 9/9~14" if t < SPLIT else "상승장 9/15~", p, sym, t.date()))
    print(f"추가 lot {len(lots)}")

    def show(title, pred):
        print(f"\n■ {title}")
        for per in ("하락장 9/9~14", "상승장 9/15~"):
            for side in ("LONG", "SHORT"):
                a = [x for x in lots if x[3] == per and x[0] == side]
                k = [x for x in a if pred(x)]
                r = [x for x in a if not pred(x)]
                f = lambda xs: (f"{len(xs):5d}건 합 {sum(x[4] for x in xs):+9.0f} 평균 {sum(x[4] for x in xs) / len(xs):+6.2f}"
                                if xs else "    0건")
                print(f"  {per} {side:5s} | 조건 통과 {f(k)} | 제외 {f(r)}")

    for per in ("하락장 9/9~14", "상승장 9/15~"):
        for side in ("LONG", "SHORT"):
            a = [x for x in lots if x[3] == per and x[0] == side]
            print(f"  {per} {side}: 전체 {len(a)}건 합 {sum(x[4] for x in a):+.0f} · 국면태그 {dict((g, sum(1 for x in a if x[1] == g)) for g in ('UP', 'DOWN', 'FLAT', None))}")

    show("C1 국면 태그 일치 (LONG=MKT_UP · SHORT=MKT_DOWN 일 때만 추가)",
         lambda x: (x[0] == "LONG" and x[1] == "UP") or (x[0] == "SHORT" and x[1] == "DOWN"))
    show("C2 국면 반대만 막기 (LONG 은 MKT_DOWN 아닐 때 · SHORT 은 MKT_UP 아닐 때)",
         lambda x: (x[0] == "LONG" and x[1] != "DOWN") or (x[0] == "SHORT" and x[1] != "UP"))
    show("C3 시장폭 값 (LONG 은 ≥0.55 · SHORT 은 ≤0.45)",
         lambda x: x[2] is not None and ((x[0] == "LONG" and x[2] >= 0.55) or (x[0] == "SHORT" and x[2] <= 0.45)))

    # 날짜별 — C1 통과 lot 의 날짜별 합
    print("\n■ C1 통과 lot 날짜별 합 (방향 무관)")
    days = sorted({x[6] for x in lots})
    for d in days:
        k = [x for x in lots if x[6] == d and ((x[0] == "LONG" and x[1] == "UP") or (x[0] == "SHORT" and x[1] == "DOWN"))]
        r = [x for x in lots if x[6] == d and not ((x[0] == "LONG" and x[1] == "UP") or (x[0] == "SHORT" and x[1] == "DOWN"))]
        print(f"  {d}: 통과 {len(k):5d}건 {sum(x[4] for x in k):+9.0f} | 제외 {len(r):5d}건 {sum(x[4] for x in r):+9.0f}")
finally:
    db.close()
