import csv, sys
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, Float, cast
from app.core.database import SessionLocal
from app.models.paper_trade import PaperTrade as P
S = P.snapshot
def f(e, n): return cast(e.astext, Float).label(n)
def t(e, n): return e.astext.label(n)
cols = [P.id, P.symbol, P.side, P.rule, P.opened_at, P.entry_price, P.tags,
  f(P.engines["live"]["roi"], "roi"), t(P.engines["live"]["done"], "done"), t(P.engines["live"]["hit"], "hit"),
  f(P.engines["live_sl15"]["roi"], "roi_sl15"), f(P.engines["live_stale24"]["roi"], "roi_stale"),
  f(S["chg_24h"], "chg24"), f(S["rsi14_15m"], "rsi15"), f(S["pctb_15m"], "pctb15"),
  f(S["hist_4h"][1], "h4hist"), f(S["hist_4h"][0], "h4hist_prev"),
  f(S["hist_15m"][2], "m15hist"), f(S["hist_15m"][1], "m15hist_prev"),
  t(S["accel3"], "accel3"), f(S["dist_high5d_pct"], "dh5")]
cutoff = datetime.now(timezone.utc) - timedelta(days=10)
db = SessionLocal(); w = csv.writer(sys.stdout)
try:
    first = True
    for row in db.execute(select(*cols).where(P.source=="live", P.status=="CLOSED", P.opened_at>=cutoff).execution_options(yield_per=5000)):
        m = row._mapping
        if first: w.writerow(list(m.keys())); first = False
        w.writerow([("|".join(v) if isinstance(v, list) else v) for v in m.values()])
finally:
    db.close()
