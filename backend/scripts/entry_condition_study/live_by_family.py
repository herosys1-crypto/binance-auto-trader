"""실거래 성적 — 읽기 전용. 가족별(자동/사람) 실현 손익 · 최근 30일 · 최근 7일 (8/20~ 자동매매 기간 포함).

🧮 Fix 434: 자동 가족 손익을 「시스템 몫 / 사람 💉 추가 몫 / 출처 모름」으로 나눠 같이 보여 준다 (app/services/human_share).
   가족 성적을 말할 때는 **시스템 몫**을 본다 — 사람이 키운 물량의 손익이 가족 판단을 가리지 않게.
"""
import sys
sys.path.insert(0, "/app")
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models.strategy_instance import StrategyInstance as SI
from app.models.strategy_template import StrategyTemplate as ST
from app.services import auto_family_registry as AF
from app.services import human_share as HS

db = SessionLocal()
now = datetime.now(timezone.utc)
try:
    rows = db.execute(select(SI.id, SI.side, SI.status, SI.realized_pnl, SI.unrealized_pnl, SI.created_at,
                             SI.entry_origin, ST.strategy_type, ST.name)
                      .join(ST, ST.id == SI.strategy_template_id)
                      .where(SI.created_at >= now - timedelta(days=45))).all()
    agg = defaultdict(lambda: {"n": 0, "pnl": 0.0, "win": 0, "loss_sum": 0.0, "n14": 0, "pnl14": 0.0, "open": 0,
                               "sys": 0.0, "hum": 0.0, "unk": 0.0, "hum_n": 0, "sys14": 0.0})
    sp = HS.split_for(db, [(r[0], r[1], r[3]) for r in rows])
    for sid, side, status, rp, up, ca, origin, stype, name in rows:
        fam = AF.family_for(strategy_type=stype, template_name=name, entry_origin=origin, created_at=ca)
        key = ("사람" if fam is None else fam.label) + " · " + side
        a = agg[key]
        p = float(rp or 0)
        a["n"] += 1; a["pnl"] += p; a["win"] += p > 0
        if p < 0:
            a["loss_sum"] += p
        h = sp.get(sid) or {"system": p, "human": 0.0, "unknown": 0.0, "human_n": 0}
        a["sys"] += h["system"]; a["hum"] += h["human"]; a["unk"] += h["unknown"]; a["hum_n"] += h["human_n"] > 0
        if ca >= now - timedelta(days=14):
            a["n14"] += 1; a["pnl14"] += p; a["sys14"] += h["system"]
        if status not in ("COMPLETED", "STOPPED", "CANCELLED", "FAILED", "LIQUIDATED", "CLOSED"):
            a["open"] += 1
    print(f"최근 45일 전략 {len(rows)}개 (실현 손익 USDT)")
    print(f"{'가족 · 방향':34s} {'건':>4s} {'실현 합':>9s} {'이긴 비율':>7s} {'손실 합':>9s} | {'최근14일 건':>9s} {'합':>8s} | 진행중"
          f" | {'시스템 몫':>9s} {'사람 추가 몫':>10s}(건) {'모름':>7s} {'14일 시스템':>10s}")
    for k, a in sorted(agg.items(), key=lambda x: x[1]["pnl"]):
        tail = (f" | {a['sys']:+9.1f} {a['hum']:+10.1f}({a['hum_n']}) {a['unk']:+7.1f} {a['sys14']:+10.1f}"
                if not k.startswith("사람") else "")
        print(f"{k:34s} {a['n']:4d} {a['pnl']:+9.1f} {a['win'] / a['n']:7.0%} {a['loss_sum']:+9.1f} | {a['n14']:9d} {a['pnl14']:+8.1f} | {a['open']}{tail}")
    tot = sum(a["pnl"] for a in agg.values())
    auto = sum(a["pnl"] for k, a in agg.items() if not k.startswith("사람"))
    auto_sys = sum(a["sys"] for k, a in agg.items() if not k.startswith("사람"))
    auto_hum = sum(a["hum"] for k, a in agg.items() if not k.startswith("사람"))
    print(f"\n합계 {tot:+.1f} · 자동 {auto:+.1f} (시스템 몫 {auto_sys:+.1f} · 사람 💉 추가 몫 {auto_hum:+.1f}) · 사람 전략 {tot - auto:+.1f}")
finally:
    db.close()
