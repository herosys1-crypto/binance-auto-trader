"""Fix 433 — 운영팀 게이트(기록 전용) 판정 보고서. 읽기 전용 · 운영 서버에서: docker compose exec -T api python - < 이 파일

council:gate:{가족}:{가상행 id} 기록을 모아
  · 실주문(mode=on)  : 전략 id → 실현 손익(USDT) · 칸 안 / 칸 밖 / 모름 비교
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
        for sid, status, rp in db.execute(select(SI.id, SI.status, SI.realized_pnl).where(SI.id.in_(sids))).all():
            pnl[sid] = (status, float(rp or 0))
    pids = [x["paper_trade_id"] for x in recs if x.get("mode") == "shadow" and x.get("paper_trade_id")]
    roi = {}
    if pids:
        for pid, st, eng in db.execute(select(PaperTrade.id, PaperTrade.status, PaperTrade.engines).where(PaperTrade.id.in_(pids))).all():
            if st == "CLOSED" and isinstance(eng, dict) and isinstance(eng.get("live"), dict):
                roi[pid] = eng["live"].get("roi")
finally:
    db.close()

agg = defaultdict(lambda: [0, 0.0, 0])          # (mode, 가족, 칸) → [끝난 건, 합, 진행·미정]
for x in recs:
    cell = "모름" if x.get("in_cells") is None else ("칸 안" if x["in_cells"] else "칸 밖")
    key = (x.get("mode"), x.get("family"), cell)
    if x.get("mode") == "on":
        st, p = pnl.get(x.get("strategy_id"), (None, None))
        if st in ("COMPLETED", "STOPPED", "CLOSED", "LIQUIDATED") and p is not None:
            agg[key][0] += 1; agg[key][1] += p        # noqa: E702
        else:
            agg[key][2] += 1
    else:
        v = roi.get(x.get("paper_trade_id"))
        if isinstance(v, (int, float)):
            agg[key][0] += 1; agg[key][1] += v        # noqa: E702
        else:
            agg[key][2] += 1
print(f"운영팀 게이트 기록 {len(recs)}건 (실주문 = 실현 USDT 합 · 그림자 = 가상 roi % 평균)")
for (mode, fam, cell), (n, s, pend) in sorted(agg.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]), kv[0][2])):
    val = f"합 {s:+.2f} USDT" if mode == "on" else (f"평균 {s / n:+.2f}%" if n else "—")
    print(f"  {mode:6s} {fam:18s} {cell:4s}  끝남 {n:3d} · {val} · 진행 중 {pend}")
