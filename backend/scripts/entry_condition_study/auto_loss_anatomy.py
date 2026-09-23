"""자동매매 −1,858 해부 — 읽기 전용. 가족별 이긴 건/진 건 크기 · 주별 · 종료 사유."""
import sys
sys.path.insert(0, "/app")
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models.strategy_instance import StrategyInstance as SI
from app.models.strategy_template import StrategyTemplate as ST
from app.services import auto_family_registry as AF

db = SessionLocal()
now = datetime.now(timezone.utc)
try:
    rows = db.execute(select(SI.id, SI.symbol, SI.side, SI.status, SI.realized_pnl, SI.created_at, SI.stopped_at,
                             SI.entry_origin, SI.last_error_message, ST.strategy_type, ST.name)
                      .join(ST, ST.id == SI.strategy_template_id)
                      .where(SI.created_at >= now - timedelta(days=45))).all()
    fam_rows = defaultdict(list)
    for r in rows:
        fam = AF.family_for(strategy_type=r.strategy_type, template_name=r.name, entry_origin=r.entry_origin, created_at=r.created_at)
        if fam is None:
            continue
        fam_rows[f"{fam.label} · {r.side}"].append(r)
    for k in sorted(fam_rows, key=lambda k: sum(float(x.realized_pnl or 0) for x in fam_rows[k])):
        xs = fam_rows[k]
        ps = [float(x.realized_pnl or 0) for x in xs]
        wins = [p for p in ps if p > 0]; losses = [p for p in ps if p < 0]; zero = sum(1 for p in ps if p == 0)
        tot = sum(ps)
        if abs(tot) < 20 and len(xs) < 20:
            continue
        print(f"\n■ {k}: {len(xs)}건 합 {tot:+.1f} · 이김 {len(wins)} (평균 {sum(wins) / max(len(wins), 1):+.1f}) · "
              f"짐 {len(losses)} (평균 {sum(losses) / max(len(losses), 1):+.1f}) · 0원 {zero}")
        wk = defaultdict(list)
        for x in xs:
            wk[x.created_at.strftime("%m/%d")[:5] if False else (x.created_at - timedelta(days=x.created_at.weekday())).strftime("%m/%d주")].append(float(x.realized_pnl or 0))
        print("   주별:", " · ".join(f"{w} {len(v)}건 {sum(v):+.0f}" for w, v in sorted(wk.items())))
        worst = sorted(xs, key=lambda x: float(x.realized_pnl or 0))[:4]
        print("   큰 손실:", " | ".join(f"{x.symbol} {float(x.realized_pnl):+.0f} ({x.created_at:%m-%d})" for x in worst))
finally:
    db.close()
