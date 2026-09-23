"""고친 기준(끝난 상태 = TERMINAL · 시각은 stopped_at 없으면 updated_at)으로 가족별 실현 손익 — 읽기 전용."""
import sys
sys.path.insert(0, "/app")
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select
from app.core.database import SessionLocal
from app.core.strategy_status import TERMINAL_STATUSES
from app.models.strategy_instance import StrategyInstance as SI
from app.models.strategy_template import StrategyTemplate as ST
from app.services import auto_family_registry as AF

db = SessionLocal()
now = datetime.now(timezone.utc)
closed_at = func.coalesce(SI.stopped_at, SI.updated_at)
rows = db.execute(select(SI.realized_pnl, SI.created_at, closed_at, SI.entry_origin, SI.status,
                         ST.strategy_type, ST.name)
                  .join(ST, ST.id == SI.strategy_template_id)
                  .where(SI.status.in_(tuple(TERMINAL_STATUSES)))).all()
agg = defaultdict(lambda: [0.0, 0, 0.0, 0, 0.0, 0])
for rp, ca, sa, origin, status, stype, name in rows:
    fam = AF.family_for(strategy_type=stype, template_name=name, entry_origin=origin, created_at=ca)
    if fam is None:
        continue
    p = float(rp or 0)
    a = agg[fam.label]
    a[0] += p
    a[1] += 1
    if sa >= now - timedelta(days=30):
        a[2] += p
        a[3] += 1
    if sa >= now - timedelta(days=7):
        a[4] += p
        a[5] += 1
print("고친 기준 — 가족별 실현 손익 (끝난 전략만 · 사람 전략 제외)")
print(f"{'가족':26s} {'전체':>12s} {'30일':>12s} {'7일':>11s}")
for lab, (t, tn, m, mn, w, wn) in sorted(agg.items(), key=lambda kv: kv[1][0]):
    flag = "  <- 7일 -30 초과" if w < -30 else ""
    print(f"{lab:26s} {t:+8.1f}({tn:3d}) {m:+8.1f}({mn:3d}) {w:+8.1f}({wn:2d}){flag}")
print(f"{'자동 합계':26s} {sum(v[0] for v in agg.values()):+8.1f}      "
      f"{sum(v[2] for v in agg.values()):+8.1f}      {sum(v[4] for v in agg.values()):+8.1f}")
db.close()
