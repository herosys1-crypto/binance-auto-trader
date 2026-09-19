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

    for side, pred in (("LONG", lambda x: x[2] is not None and x[2] >= 0.55), ("SHORT", lambda x: x[2] is not None and x[2] <= 0.45)):
        print("\n■", side, "추가 — 날짜별 (시장폭 조건 통과 vs 제외, 1건 평균 USDT)")
        good = 0; both = 0
        for d in sorted({x[6] for x in lots}):
            a = [x for x in lots if x[6] == d and x[0] == side]
            k = [x for x in a if pred(x)]; r = [x for x in a if not pred(x)]
            if len(k) >= 20 and len(r) >= 20:
                both += 1; mk = sum(x[4] for x in k) / len(k); mr = sum(x[4] for x in r) / len(r); good += mk > mr
                print(f"  {d}: 통과 {len(k):4d}건 평균 {mk:+7.2f} | 제외 {len(r):4d}건 평균 {mr:+7.2f} {'O' if mk > mr else ''}")
            else:
                print(f"  {d}: 통과 {len(k):4d}건 · 제외 {len(r):4d}건 (한쪽 20건 미만)")
        print(f"  -> 통과가 나은 날 {good}/{both}")
finally:
    db.close()
