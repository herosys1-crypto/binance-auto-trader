from pathlib import Path
import io, contextlib, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # backend/
with contextlib.redirect_stdout(io.StringIO()):
    import analyze as A
from app.services import entry_conditions as EC
d = A.d
def ver(r):
    s = {"chart_state": {"h1": {"from_hi_pct": r.h1_from_hi}, "m5": {"from_hi_pct": r.m5_from_hi},
                         "d1": {"bb": {"trend": r.d1_bb_trend if isinstance(r.d1_bb_trend, str) else None}}}}
    s = {k: v for k, v in s.items()}
    import math
    for tf in ("h1", "m5"):
        v = s["chart_state"][tf]["from_hi_pct"]
        if v is None or (isinstance(v, float) and math.isnan(v)): s["chart_state"][tf]["from_hi_pct"] = None
    chg = None if r.chg24 != r.chg24 else r.chg24
    return EC.evaluate(r.side, s, chg_24h=chg)["verdict"]
d["gate"] = [ver(r) for r in d.itertuples()]
rules = d[~d.rule.str.startswith("baseline_")]
print("모듈 판정 분포:", rules.groupby(["side", "gate"]).size().to_dict())
for side in ("LONG", "SHORT"):
    for per, g in (("발견", rules[(rules.side == side) & (rules.opened_at < A.PREREG)]), ("검증", rules[(rules.side == side) & (rules.opened_at >= A.PREREG)])):
        k, r = g[g.gate == "pass"], g[g.gate != "pass"]
        print(f"{side} {per}: 통과 {len(k)/len(g):.0%} roi{k.roi.mean():+.2f} ex{k.ex.mean():+.2f} 승{(k.roi>0).mean():.0%} | 막힘 roi{r.roi.mean():+.2f} ex{r.ex.mean():+.2f} | 전체 roi{g.roi.mean():+.2f}")
print()
print(f"{'규칙':22s} {'방향':5s} {'전체 roi':>8s} {'통과율':>6s} {'통과 roi':>8s} {'통과 ex':>8s} {'막힘 roi':>8s} | 검증: 통과 ex / 막힘 ex")
for rule, g in d.groupby("rule"):
    h = g[g.opened_at >= A.PREREG]
    k, r = g[g.gate == "pass"], g[g.gate != "pass"]
    hk, hr = h[h.gate == "pass"], h[h.gate != "pass"]
    print(f"{rule:22s} {g.side.iloc[0]:5s} {g.roi.mean():+8.2f} {len(k)/len(g):6.0%} {k.roi.mean():+8.2f} {k.ex.mean():+8.2f} {r.roi.mean():+8.2f} | {hk.ex.mean():+.2f} / {hr.ex.mean():+.2f} (n{len(hk)})")
d[["id","rule","side","gate","roi","ex"]].to_csv("gate_replay.csv", index=False)
