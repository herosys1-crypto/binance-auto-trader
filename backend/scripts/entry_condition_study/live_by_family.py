"""실거래 성적 — 읽기 전용. 가족별(자동/사람) 실현 손익 · 최근 30일 · 최근 7일 (8/20~ 자동매매 기간 포함)."""
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
    rows = db.execute(select(SI.id, SI.side, SI.status, SI.realized_pnl, SI.unrealized_pnl, SI.created_at,
                             SI.entry_origin, ST.strategy_type, ST.name)
                      .join(ST, ST.id == SI.strategy_template_id)
                      .where(SI.created_at >= now - timedelta(days=45))).all()
    agg = defaultdict(lambda: {"n": 0, "pnl": 0.0, "win": 0, "loss_sum": 0.0, "n14": 0, "pnl14": 0.0, "open": 0})
    for sid, side, status, rp, up, ca, origin, stype, name in rows:
        fam = AF.family_for(strategy_type=stype, template_name=name, entry_origin=origin, created_at=ca)
        key = ("사람" if fam is None else fam.label) + " · " + side
        a = agg[key]
        p = float(rp or 0)
        a["n"] += 1; a["pnl"] += p; a["win"] += p > 0
        if p < 0:
            a["loss_sum"] += p
        if ca >= now - timedelta(days=14):
            a["n14"] += 1; a["pnl14"] += p
        if status not in ("COMPLETED", "STOPPED", "CANCELLED", "FAILED", "LIQUIDATED", "CLOSED"):
            a["open"] += 1
    print(f"최근 45일 전략 {len(rows)}개 (실현 손익 USDT)")
    print(f"{'가족 · 방향':34s} {'건':>4s} {'실현 합':>9s} {'이긴 비율':>7s} {'손실 합':>9s} | {'최근14일 건':>9s} {'합':>8s} | 진행중")
    for k, a in sorted(agg.items(), key=lambda x: x[1]["pnl"]):
        print(f"{k:34s} {a['n']:4d} {a['pnl']:+9.1f} {a['win'] / a['n']:7.0%} {a['loss_sum']:+9.1f} | {a['n14']:9d} {a['pnl14']:+8.1f} | {a['open']}")
    tot = sum(a["pnl"] for a in agg.values())
    auto = sum(a["pnl"] for k, a in agg.items() if not k.startswith("사람"))
    print(f"\n합계 {tot:+.1f} · 자동 {auto:+.1f} · 사람 {tot - auto:+.1f}")
finally:
    db.close()
