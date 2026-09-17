import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    import analyze as A
import numpy as np
d, P = A.d, A.PREREG
F = lambda x: (x.chg24 <= -5) | (x.m5_from_hi <= -4)
Q4 = lambda x: (x.h1_from_hi <= -1.5) & (x.chg24 < 20) & ~((x.chg24 >= 0) & (x.chg24 < 5))
C = {"④ 단독": Q4, "④ and F": lambda x: Q4(x) & F(x), "④ or F": lambda x: Q4(x) | F(x), "F 단독": F,
     "④ & 1H되돌림≤−3": lambda x: Q4(x) & (x.h1_from_hi <= -3),
     "④ & 일봉 하단권(%B≤0.5)": lambda x: Q4(x) & (x.d1_pctb <= 0.5)}
def ev(g, m):
    m = m.fillna(False); k, r = g[m], g[~m]
    if len(k) < 15: return None
    return (len(k)/len(g), len(k), k.roi.mean(), k.ex.mean(), (k.roi>0).mean(), A.clu_t(k),
            r.roi.mean(), r.ex.mean(), int((k.groupby("day").ex.mean()>0).sum()), k.day.nunique())
for title, g in (("상승 초입 LONG", d[d.rule=="surge_start_346"]),
                 ("LONG 규칙 합산", d[(d.side=="LONG") & ~d.rule.str.startswith("baseline_")]),
                 ("무작위 LONG", d[d.rule=="baseline_LONG"])):
    print(f"\n## {title}")
    print(f"{'조건':26s} | {'발견: 비중 ROI ex (막힘ex)':>34s} | {'검증: 비중 ROI ex (막힘ex) 날':>38s}")
    for n, f in C.items():
        a, h = ev(g[g.opened_at < P], f(g[g.opened_at < P])), ev(g[g.opened_at >= P], f(g[g.opened_at >= P]))
        fa = f"{a[0]:3.0%} {a[2]:+6.2f} {a[3]:+6.2f} ({a[7]:+5.2f})" if a else "         표본 부족        "
        fh = f"{h[0]:3.0%} {h[2]:+6.2f} {h[3]:+6.2f} ({h[7]:+5.2f}) {h[8]}/{h[9]} t{0 if h[5]!=h[5] else h[5]:+.1f}" if h else "표본 부족"
        print(f"{n:26s} | {fa:>34s} | {fh}")
