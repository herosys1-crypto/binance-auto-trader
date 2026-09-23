"""미세조정 후보 — 두 기간(발견/검증) 모두 통과 쪽이 나은 것만 사전등록 대상으로 고른다."""
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    import analyze as A
d, P = A.d, A.PREREG
S  = lambda x: (x.h1_from_hi >= -3) & x.d1_bb_trend.notna() & (x.d1_bb_trend != "UP")           # 지금 SHORT 게이트
L  = lambda x: (x.chg24 <= -5) | (x.m5_from_hi <= -4)                                            # 지금 LONG 게이트
Q  = lambda x: (x.h1_from_hi <= -1.5) & (x.chg24 < 20) & ~((x.chg24 >= 0) & (x.chg24 < 5))        # P7
CAND = {
 "SHORT": {
   "지금 게이트 S": S,
   "S & 1H ATR ≤1.9": lambda x: S(x) & (x.h1_atr14_pct <= 1.9),
   "S & 1H ATR ≤1.5": lambda x: S(x) & (x.h1_atr14_pct <= 1.5),
   "S & 1H ATR ≤2.5": lambda x: S(x) & (x.h1_atr14_pct <= 2.5),
   "S & 4H 하단이탈 14봉+": lambda x: S(x) & (x.h4_bb_bars_since_below_lower >= 14),
   "S & 일봉 %B ≥0.5": lambda x: S(x) & (x.d1_pctb >= 0.5),
 },
 "LONG": {
   "지금 게이트 L": L,
   "P7 (Q)": Q,
   "L and Q": lambda x: L(x) & Q(x),
   "L or Q": lambda x: L(x) | Q(x),
   "Q & 일봉 %B ≤0.5": lambda x: Q(x) & (x.d1_pctb <= 0.5),
   "L or (Q & %B≤0.5)": lambda x: L(x) | (Q(x) & (x.d1_pctb <= 0.5)),
 },
}
for side, cand in CAND.items():
    g = d[(d.side == side) & ~d.rule.str.startswith("baseline_")]
    b = d[d.rule == f"baseline_{side}"]
    print(f"\n### {side} 규칙 진입 {len(g)}건 (무작위 {len(b)}건)")
    print(f"{'후보':22s} | {'발견 통과 ROI/ex (막힘)':>34s} | {'검증 통과 ROI/ex (막힘)':>34s} | {'무작위검증차':>7s} 일치")
    for name, f in cand.items():
        out, ok = [], True
        for gg in (g[g.opened_at < P], g[g.opened_at >= P]):
            m = f(gg).fillna(False); k, r = gg[m], gg[~m]
            if len(k) < 40 or len(r) < 40:
                out.append("        표본 부족        "); ok = False; continue
            out.append(f"{len(k)/len(gg):3.0%} {k.roi.mean():+6.2f}/{k.ex.mean():+5.2f} ({r.roi.mean():+6.2f}/{r.ex.mean():+5.2f})")
            if k.ex.mean() <= r.ex.mean(): ok = False
        bh = b[b.opened_at >= P]; mb = f(bh).fillna(False)
        bd = (bh[mb].ex.mean() - bh[~mb].ex.mean()) if mb.sum() > 30 else float("nan")
        print(f"{name:22s} | {out[0]:>34s} | {out[1]:>34s} | {bd:+7.2f} {'✅' if ok else ''}")
