"""Fix 433 — 운영팀 게이트(기록 전용) 판정 보고서. 읽기 전용 · 운영 서버에서: docker compose exec -T api python - < 이 파일

council:gate:{가족}:{가상행 id} 기록을 모아
  · 실주문(mode=on)  : 전략 id → 실현 손익(USDT) · 칸 안 / 칸 밖 / 모름 비교 — 🧮 Fix 434: **시스템 몫**으로 비교(사람 💉 추가 몫은 따로)
  · 그림자(mode=shadow): 가상행 결과(engines.live.roi %) · 칸 안 / 칸 밖 비교
2주 뒤 「칸 밖 진입」이 꾸준히 나쁘면 → 막기(사장님 승인). 표본이 적으면 판정하지 않는다.
"""
import json
import sys
from collections import defaultdict

sys.path.insert(0, "/app")
from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.redis_client import get_redis_client  # noqa: E402
from app.models.paper_trade import PaperTrade  # noqa: E402
from app.models.strategy_instance import StrategyInstance as SI  # noqa: E402
from app.services import human_share as HS  # noqa: E402

r = get_redis_client()
recs = []
for k in r.scan_iter("council:gate:*", count=500):
    try:
        recs.append(json.loads(r.get(k)))
    except Exception:  # noqa: BLE001
        pass
db = SessionLocal()
try:
    sids = [x["strategy_id"] for x in recs if x.get("strategy_id")]
    pnl = {}
    if sids:
        got = db.execute(select(SI.id, SI.status, SI.realized_pnl, SI.side).where(SI.id.in_(sids))).all()
        sp = HS.split_for(db, [(sid, side, rp) for sid, _st, rp, side in got])
        for sid, status, _rp, _side in got:
            pnl[sid] = (status, sp[sid]["system"], sp[sid]["human"])
    pids = [x["paper_trade_id"] for x in recs if x.get("mode") == "shadow" and x.get("paper_trade_id")]
    roi = {}
    if pids:
        for pid, st, eng in db.execute(select(PaperTrade.id, PaperTrade.status, PaperTrade.engines).where(PaperTrade.id.in_(pids))).all():
            if st == "CLOSED" and isinstance(eng, dict) and isinstance(eng.get("live"), dict):
                roi[pid] = eng["live"].get("roi")
finally:
    db.close()

agg = defaultdict(lambda: [0, 0.0, 0, 0.0])     # (mode, 가족, 칸) → [끝난 건, 합(시스템 몫), 진행·미정, 사람 추가 몫]
for x in recs:
    cell = "모름" if x.get("in_cells") is None else ("칸 안" if x["in_cells"] else "칸 밖")
    key = (x.get("mode"), x.get("family"), cell)
    if x.get("mode") == "on":
        st, p, hp = pnl.get(x.get("strategy_id"), (None, None, 0.0))
        if st in ("COMPLETED", "STOPPED", "CLOSED", "LIQUIDATED") and p is not None:
            agg[key][0] += 1; agg[key][1] += p; agg[key][3] += hp        # noqa: E702
        else:
            agg[key][2] += 1
    else:
        v = roi.get(x.get("paper_trade_id"))
        if isinstance(v, (int, float)):
            agg[key][0] += 1; agg[key][1] += v        # noqa: E702
        else:
            agg[key][2] += 1
print(f"운영팀 게이트 기록 {len(recs)}건 (실주문 = 시스템 몫 실현 USDT 합, 사람 💉 추가 몫 따로 · 그림자 = 가상 roi % 평균)")
for (mode, fam, cell), (n, s, pend, hs) in sorted(agg.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]), kv[0][2])):
    val = f"시스템 몫 합 {s:+.2f} USDT (사람 추가 몫 {hs:+.2f})" if mode == "on" else (f"평균 {s / n:+.2f}%" if n else "—")
    print(f"  {mode:6s} {fam:18s} {cell:4s}  끝남 {n:3d} · {val} · 진행 중 {pend}")
