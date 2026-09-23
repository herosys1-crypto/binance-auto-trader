import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    import analyze as A
import numpy as np
d, P = A.d, A.PREREG
def ev(g, m):
    m = m.fillna(False); k, r = g[m], g[~m]
    if len(k) < 15: return None
    return dict(n=len(k), share=len(k)/len(g), roi=k.roi.mean(), ex=k.ex.mean(), win=(k.roi>0).mean(),
                t=A.clu_t(k), rroi=r.roi.mean() if len(r) else np.nan, rex=r.ex.mean() if len(r) else np.nan,
                dpos=int((k.groupby("day").ex.mean()>0).sum()), days=k.day.nunique())
C = {
 "① 고점추격 금지 (1H고점 −1.5% 이하)":       lambda x: x.h1_from_hi <= -1.5,
 "② 과열 금지 (24h < 20)":                  lambda x: x.chg24 < 20,
 "③ ①&②":                                 lambda x: (x.h1_from_hi <= -1.5) & (x.chg24 < 20),
 "④ ①&② & 24h 0~5 제외":                   lambda x: (x.h1_from_hi <= -1.5) & (x.chg24 < 20) & ~((x.chg24 >= 0) & (x.chg24 < 5)),
 "⑤ ③ & 일봉 UP 아님":                      lambda x: (x.h1_from_hi <= -1.5) & (x.chg24 < 20) & (x.d1_bb_trend != "UP"),
 "⑥ ③ & 5분 위치 ≤ 0.85":                   lambda x: (x.h1_from_hi <= -1.5) & (x.chg24 < 20) & (x.m5_st_range_pos <= 0.85),
 "지금 게이트 F":                            lambda x: (x.chg24 <= -5) | (x.m5_from_hi <= -4),
 "③ or F":                                 lambda x: ((x.h1_from_hi <= -1.5) & (x.chg24 < 20)) | (x.chg24 <= -5) | (x.m5_from_hi <= -4),
}
def show(title, g):
    print(f"\n## {title}  (전체 n={len(g)} ROI {g.roi.mean():+.2f} ex {g.ex.mean():+.2f})")
    print(f"{'조건':34s} {'비중':>5s} {'n':>5s} {'ROI':>7s} {'ex':>7s} {'승률':>5s} {'t':>5s} | {'막힘ROI':>8s} {'막힘ex':>7s} 날")
    for n, f in C.items():
        r = ev(g, f(g))
        if not r: print(f"{n:34s}  표본 부족"); continue
        print(f"{n:34s} {r['share']:5.0%} {r['n']:5d} {r['roi']:+7.2f} {r['ex']:+7.2f} {r['win']:5.0%} "
              f"{0 if r['t']!=r['t'] else r['t']:+5.1f} | {r['rroi']:+8.2f} {r['rex']:+7.2f} {r['dpos']}/{r['days']}")
g = d[d.rule == "surge_start_346"]
show("상승 초입 LONG · 발견(9/9~9/13)", g[g.opened_at < P])
show("상승 초입 LONG · 검증(9/14~9/18)", g[g.opened_at >= P])
L = d[(d.side=="LONG") & ~d.rule.str.startswith("baseline_")]
show("LONG 규칙 합산 · 발견", L[L.opened_at < P]); show("LONG 규칙 합산 · 검증", L[L.opened_at >= P])
b = d[d.rule=="baseline_LONG"]; show("무작위 LONG · 검증", b[b.opened_at >= P])
# 규칙별 ③ 효과 (검증)
print("\n## 규칙별 ③(고점추격·과열 금지) · 검증")
for rule, gr in d[d.side=="LONG"].groupby("rule"):
    h = gr[gr.opened_at >= P]
    r = ev(h, C["③ ①&②"](h))
    if r: print(f"  {rule:22s} 통과 {r['share']:3.0%} ROI {r['roi']:+6.2f}/ex {r['ex']:+6.2f} | 막힘 ROI {r['rroi']:+6.2f}/ex {r['rex']:+6.2f}")
