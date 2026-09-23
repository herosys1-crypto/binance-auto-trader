"""운영 모듈(entry_conditions)로 상승 초입 LONG 조건을 가상 데이터에 재생 — 분석 수치와 같은지 확인."""
import io, contextlib, math, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # backend/
with contextlib.redirect_stdout(io.StringIO()):
    import analyze as A
from app.services import entry_conditions as EC
d, P = A.d, A.PREREG
def n(x): return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)
def verdict(r, family=None):
    s = {"chart_state": {"h1": {"from_hi_pct": n(r.h1_from_hi)}, "m5": {"from_hi_pct": n(r.m5_from_hi)},
                         "d1": {"bb": {"trend": r.d1_bb_trend if isinstance(r.d1_bb_trend, str) else None}}}}
    return EC.evaluate(r.side, s, chg_24h=n(r.chg24), family=family)["verdict"]
g = d[d.rule == "surge_start_346"].copy()
g["v"] = [verdict(r, "rf_surge_long") for r in g.itertuples()]
g["v_old"] = [verdict(r) for r in g.itertuples()]
print("상승 초입 LONG — 운영 모듈 재생")
for label, col in (("새 가족 조건", "v"), ("옛 방향 공통", "v_old")):
    for per, gg in (("발견", g[g.opened_at < P]), ("검증", g[g.opened_at >= P])):
        k, r = gg[gg[col] == "pass"], gg[gg[col] != "pass"]
        print(f"  {label} {per}: 통과 {len(k)}/{len(gg)} ({len(k)/len(gg):.0%}) ROI {k.roi.mean():+.2f} ex {k.ex.mean():+.2f} "
              f"승 {(k.roi>0).mean():.0%} t {A.clu_t(k) if len(k)>20 else float('nan'):+.1f} | 막힘 ROI {r.roi.mean():+.2f} ex {r.ex.mean():+.2f} "
              f"| 날 {int((k.groupby('day').ex.mean()>0).sum())}/{k.day.nunique()}")
# 막힌 이유 분포 (검증)
h = g[g.opened_at >= P]
from collections import Counter
c = Counter()
for r in h.itertuples():
    s = {"chart_state": {"h1": {"from_hi_pct": n(r.h1_from_hi)}, "m5": {"from_hi_pct": n(r.m5_from_hi)}, "d1": {"bb": {"trend": None}}}}
    res = EC.evaluate("LONG", s, chg_24h=n(r.chg24), family="rf_surge_long")
    for w in (res["why"] or ["통과"]):
        c[w.split(" ")[0] if res["verdict"] != "pass" else "통과"] += 1
print("  검증 기간 사유:", dict(c))
