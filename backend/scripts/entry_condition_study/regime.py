import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    import analyze as A
import numpy as np
d, P = A.d, A.PREREG
S = lambda x: (x.h1_from_hi >= -3) & x.d1_bb_trend.notna() & (x.d1_bb_trend != "UP")          # P5
L = lambda x: (x.chg24 <= -5) | (x.m5_from_hi <= -4)                                          # P6
Q = lambda x: (x.h1_from_hi <= -1.5) & (x.chg24 < 20) & ~((x.chg24 >= 0) & (x.chg24 < 5))      # P7
def row(g, m, name):
    m = m.fillna(False); k, r = g[m], g[~m]
    if len(k) < 15 or len(r) < 15: return None
    return f"{name:16s} 통과 {len(k)/len(g):3.0%} ROI {k.roi.mean():+6.2f} ex {k.ex.mean():+6.2f} | 막힘 ROI {r.roi.mean():+6.2f} ex {r.ex.mean():+6.2f} | 차이 ROI {k.roi.mean()-r.roi.mean():+6.2f}"
for side, gate, gname in (("SHORT", S, "P5 SHORT게이트"), ("LONG", L, "P6 LONG게이트"), ("LONG", Q, "P7 고점추격금지")):
    g = d[(d.side == side) & ~d.rule.str.startswith("baseline_")]
    print(f"\n## {gname} ({side} 규칙 진입 {len(g)}건)")
    for per, gg in (("발견", g[g.opened_at < P]), ("검증", g[g.opened_at >= P])):
        r = row(gg, gate(gg), f"{per} 전체")
        print("  ", r)
        for mkt in ("MKT_UP", "MKT_FLAT", "MKT_DOWN"):
            sub = gg[gg.mkt == mkt]
            rr = row(sub, gate(sub), f"{per} {mkt}") if len(sub) > 40 else None
            if rr: print("     ", rr)
print("\n## 국면별 전체 성적 (규칙 진입)")
for side in ("LONG", "SHORT"):
    g = d[(d.side == side) & ~d.rule.str.startswith("baseline_")]
    print(f"  {side}: " + " · ".join(f"{m} n{len(g[g.mkt==m])} ROI {g[g.mkt==m].roi.mean():+.2f}" for m in ("MKT_UP","MKT_FLAT","MKT_DOWN","MKT_NA")))
