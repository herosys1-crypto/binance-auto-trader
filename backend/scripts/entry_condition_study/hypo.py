import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    import analyze as A
import pandas as pd, numpy as np
d = A.d
H = {
 "LONG": {
  "L1 5일고점 대비 −10% 이하": lambda g: g.dh5 <= -10,
  "L2 24h −5% 이하": lambda g: g.chg24 <= -5,
  "L3 16시간 저점 +2% 이내": lambda g: g.h1_from_lo <= 2,
  "L4 5분 4시간고점 대비 −4% 이하": lambda g: g.m5_from_hi <= -4,
  "L5 일봉 상단돌파/유지 아님": lambda g: ~g.d1_bb_state.isin(["UPPER_BREAKOUT", "UPPER_RIDE"]) & g.d1_bb_state.notna(),
  "L6 일봉 %B ≤ 0.8": lambda g: g.d1_pctb <= 0.8,
  "L7 4H 상단 밖 이후 14봉+": lambda g: g.h4_bb_bars_since_above_upper >= 14,
  "L8 1H ATR ≤ 1.9%": lambda g: g.h1_atr14_pct <= 1.9,
  "L9 일봉 추세 DOWN 아님": lambda g: g.d1_bb_trend.notna() & (g.d1_bb_trend != "DOWN"),
  "L10 L3 & L6": lambda g: (g.h1_from_lo <= 2) & (g.d1_pctb <= 0.8),
  "L11 L6 & L7": lambda g: (g.d1_pctb <= 0.8) & (g.h4_bb_bars_since_above_upper >= 14),
 },
 "SHORT": {
  "S1 16시간 고점 −3% 이내": lambda g: g.h1_from_hi >= -3,
  "S2 일봉 추세 UP 아님": lambda g: g.d1_bb_trend.notna() & (g.d1_bb_trend != "UP"),
  "S3 1H ATR ≤ 1.9%": lambda g: g.h1_atr14_pct <= 1.9,
  "S4 4H 하단이탈 뒤 14봉+": lambda g: g.h4_bb_bars_since_below_lower >= 14,
  "S5 S1 & S2": lambda g: (g.h1_from_hi >= -3) & g.d1_bb_trend.notna() & (g.d1_bb_trend != "UP"),
  "S6 S1 & S3": lambda g: (g.h1_from_hi >= -3) & (g.h1_atr14_pct <= 1.9),
  "S7 S1 & S2 & S3": lambda g: (g.h1_from_hi >= -3) & g.d1_bb_trend.notna() & (g.d1_bb_trend != "UP") & (g.h1_atr14_pct <= 1.9),
 },
}
def ev(g, m):
    m = m.fillna(False); k, r = g[m], g[~m]
    if len(k) < 20: return None
    return len(k)/len(g), k.ex.mean(), r.ex.mean(), k.roi.mean(), (k.roi>0).mean(), A.clu_t(k), int((k.groupby("day").ex.mean()>0).sum()), k.day.nunique()
for side, hs in H.items():
    g = d[(d.side == side) & ~d.rule.str.startswith("baseline_")]
    disc, hold = g[g.opened_at < A.PREREG], g[g.opened_at >= A.PREREG]
    print(f"\n######## {side}  (규칙 합산 · 기준선 대비 ex)  전체 ex {g.ex.mean():+.2f} roi {g.roi.mean():+.2f}")
    for name, fn in hs.items():
        a, h = ev(disc, fn(disc)), ev(hold, fn(hold))
        rules = []
        for rule, gr in g.groupby("rule"):
            e = ev(gr, fn(gr))
            if e: rules.append((rule, e[1] - e[2]))
        better = sum(1 for _, x in rules if x > 0)
        print(f"{name:26s} 발견 {a[0]:.0%} ex{a[1]:+.2f}/나머지{a[2]:+.2f} | 검증 {h[0]:.0%} ex{h[1]:+.2f}/나머지{h[2]:+.2f} roi{h[3]:+.2f} 승{h[4]:.0%} t{h[5]:+.1f} 날{h[6]}/{h[7]} | 규칙개선 {better}/{len(rules)}")
# 약한 규칙 4 + 전체 규칙별 상세 (최선 조합)
best = {"LONG": ["L1 5일고점 대비 −10% 이하", "L3 16시간 저점 +2% 이내", "L11 L6 & L7"], "SHORT": ["S1 16시간 고점 −3% 이내", "S5 S1 & S2", "S7 S1 & S2 & S3"]}
print("\n######## 규칙별 (전체 8일 · 조건 충족 / 불충족 평균 ROI · 괄호 = 검증 기간)")
for rule, gr in d.groupby("rule"):
    side = gr.side.iloc[0]
    hold = gr[gr.opened_at >= A.PREREG]
    parts = [f"{rule:22s} {side:5s} 전체 roi{gr.roi.mean():+.2f} ex{gr.ex.mean():+.2f} |"]
    for name in best[side]:
        fn = H[side][name]
        m = fn(gr).fillna(False); mh = fn(hold).fillna(False)
        k, r = gr[m], gr[~m]
        parts.append(f"{name[:3]} {m.mean():.0%} roi{k.roi.mean():+.2f}/{r.roi.mean():+.2f} ex{k.ex.mean():+.2f} (검증 ex{hold[mh].ex.mean():+.2f}/{hold[~mh].ex.mean():+.2f})")
    print("  ".join(parts))
