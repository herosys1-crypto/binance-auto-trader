"""차단기 모의 (고친 기준) — 끝난 상태 = TERMINAL · 시각은 stopped_at 없으면 updated_at. 읽기 전용.
그 시점까지 **끝난** 거래만 보고 가족을 멈췄다면 자동 손익이 어땠나."""
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
rows = db.execute(select(SI.realized_pnl, SI.created_at, closed_at, SI.entry_origin, ST.strategy_type, ST.name)
                  .join(ST, ST.id == SI.strategy_template_id)
                  .where(SI.status.in_(tuple(TERMINAL_STATUSES)))).all()
fams = defaultdict(list)
for rp, ca, sa, origin, stype, name in rows:
    fam = AF.family_for(strategy_type=stype, template_name=name, entry_origin=origin, created_at=ca)
    if fam is not None:
        fams[fam.key].append((ca, sa, float(rp or 0)))
actual = sum(p for v in fams.values() for _, _, p in v)
print(f"실제 자동 합 {actual:+.1f} ({sum(len(v) for v in fams.values())}건 · 끝난 전략만)")
for days in (3, 7, 14):
    for limit in (30, 50, 100):
        for latch in (False, True):
            tot, blocked = 0.0, 0
            per_fam = {}
            for key, v in fams.items():
                v = sorted(v)
                stopped, kept = False, 0.0
                for ca, sa, p in v:
                    recent = sum(q for c2, s2, q in v if s2 < ca and s2 >= ca - timedelta(days=days))
                    trip = recent < -limit
                    if latch and trip:
                        stopped = True
                    if (latch and stopped) or (not latch and trip):
                        blocked += 1
                        continue
                    kept += p
                tot += kept
                per_fam[key] = kept - sum(p for _, _, p in v)
            top = sorted(per_fam.items(), key=lambda kv: -abs(kv[1]))[:3]
            print(f"  최근 {days:2d}일 < −{limit:<3d} {'유지' if latch else '회복시 재개'}: 자동 합 {tot:+8.1f} "
                  f"(막은 전략 {blocked:3d}) · " + ", ".join(f"{k} {d:+.0f}" for k, d in top if abs(d) > 1))
db.close()
