"""가족별 손실 차단기 모의 — 읽기 전용. 그 시점까지 **끝난** 거래만 보고 가족을 멈췄다면 45일 자동 손익이 어땠나.
규칙: 새 전략이 만들어지는 순간, 같은 가족의 최근 N일 안에 끝난 거래 실현 합이 −X 미만이면 그 전략은 만들지 않는다(=그 손익 없음).
(한 번 멈추면 사람이 다시 켤 때까지 멈춤 = latch 도 따로 잰다)"""
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
    rows = db.execute(select(SI.side, SI.realized_pnl, SI.created_at, SI.stopped_at, SI.entry_origin, ST.strategy_type, ST.name)
                      .join(ST, ST.id == SI.strategy_template_id)
                      .where(SI.created_at >= now - timedelta(days=45))).all()
    fams = defaultdict(list)
    for side, rp, ca, sa, origin, stype, name in rows:
        fam = AF.family_for(strategy_type=stype, template_name=name, entry_origin=origin, created_at=ca)
        if fam is None:
            continue
        fams[fam.key].append((ca, sa or ca, float(rp or 0)))
    actual = sum(p for v in fams.values() for _, _, p in v)
    print(f"자동 실제 합 {actual:+.1f} ({sum(len(v) for v in fams.values())}건)")
    for days in (3, 7):
        for x in (30, 50, 100):
            for latch in (False, True):
                tot = 0.0; blocked = 0; saved_fams = {}
                for key, v in fams.items():
                    v = sorted(v)
                    stopped = False; kept = 0.0
                    for ca, sa, p in v:
                        recent = sum(q for c2, s2, q in v if s2 < ca and s2 >= ca - timedelta(days=days))
                        trip = recent < -x
                        if latch and trip:
                            stopped = True
                        if (latch and stopped) or (not latch and trip):
                            blocked += 1
                            continue
                        kept += p
                    tot += kept
                    saved_fams[key] = kept - sum(p for _, _, p in v)
                top = sorted(saved_fams.items(), key=lambda kv: -abs(kv[1]))[:3]
                print(f"  최근 {days}일 합 < −{x:<3d} {'멈춘 뒤 계속 멈춤' if latch else '회복하면 다시 진입'}: "
                      f"자동 합 {tot:+8.1f} (막은 전략 {blocked:3d}) · 차이 큰 가족 " +
                      ", ".join(f"{k} {d:+.0f}" for k, d in top))
finally:
    db.close()
