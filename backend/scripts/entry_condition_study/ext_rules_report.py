"""후지모토·마하세븐 가상 규칙 채택 판정 (읽기 전용, 대기열 4) — 운영 보고서(build_report)를 해당 규칙 + 기준선 행만으로 돌린다.

ssh root@VPS "cd ~/binance-auto-trader/backend && docker compose exec -T api python -" \
  < backend/scripts/entry_condition_study/ext_rules_report.py
전체 행 보고서는 VPS 메모리 사고(1.8GB) 전력이 있어 규칙을 좁히고 필요한 열만 읽는다. 기준선 행이 너무 많으면 최근 N일로 자른다.
"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select

from app.core.database import SessionLocal
from app.models.paper_trade import PaperTrade as P
from app.services import paper_trading as PT

MAX_ROWS = 60000
EXT_PREFIXES = ("fujimoto", "mach7", "emapb", "bbema", "bbwave", "trima")    # 📈 Fix 423 EMA 추세 눌림 · 📊 Fix 429 볼린저 EMA
EXT = or_(*[P.rule.like(f"{p}%") for p in EXT_PREFIXES])

db = SessionLocal()
try:
    cnt = db.execute(select(P.rule, P.status, func.count(), func.min(P.opened_at), func.max(P.opened_at))
                     .where(P.source == "live", or_(EXT, P.rule.like("baseline_%")))
                     .group_by(P.rule, P.status)).all()
    for r in cnt:
        print("count", r[0], r[1], r[2], r[3], r[4])
    since = min((r[3] for r in cnt if r[0].startswith(EXT_PREFIXES)), default=None)
    if since is None:
        raise SystemExit("후지모토·마하세븐 가상 행 없음")
    base_n = sum(r[2] for r in cnt if r[0].startswith("baseline_") and r[1] == "CLOSED")
    days = None
    if base_n > MAX_ROWS:                        # 기준선이 너무 많으면 최근으로 자른다 (규칙 행과 같은 창)
        days = 14
        since = max(since, datetime.now(timezone.utc) - timedelta(days=days))
    cols = (P.symbol, P.side, P.rule, P.status, P.source, P.opened_at, P.entry_bar_ts, P.engines, P.tags)
    rows = []
    for m in db.execute(select(*cols).where(P.source == "live", P.status == "CLOSED", P.opened_at >= since,
                                            or_(EXT, P.rule.like("baseline_%")))
                        .execution_options(yield_per=5000)):
        d = dict(m._mapping)
        d["opened_at"] = d["opened_at"].isoformat()
        rows.append(d)
        if len(rows) > MAX_ROWS * 1.5:
            raise SystemExit(f"행이 너무 많음 {len(rows)} — 창을 줄일 것")
    print("window_since", since.isoformat(), "cut_days", days, "rows", len(rows))
    known = {r.key for r in PT.RULES}
    ext_keys = sorted({r["rule"] for r in rows if r["rule"].startswith(EXT_PREFIXES)})
    print("ext_rules", ext_keys, "in_RULES", [k for k in ext_keys if k in known])
    rep = PT.build_report(rows)
    out = {"period": rep.get("period"), "n": rep.get("n"), "rules": {}}
    for k in ext_keys:
        g = (rep["rules"].get(k) or {}).get("groups", {})
        out["rules"][k] = {grp: {eng: {x: st.get(x) for x in ("n", "mean", "win", "baseline", "delta")}
                                 | {"cv": {c: (st["cv"].get(c) or {}).get("delta") for c in
                                           ("sym_even", "sym_odd", "time_early", "time_late")}
                                    if st.get("cv") else None, "cv4": (st.get("cv") or {}).get("all_positive")}
                                 for eng, st in gg.items()}
                           for grp, gg in g.items()}
    out["recommend"] = [e for e in rep["recommend"]["entries"] + rep["recommend"]["variants"]
                        if e["rule"].startswith(EXT_PREFIXES)]
    print("REPORT " + json.dumps(out, default=str, ensure_ascii=False))
finally:
    db.close()
