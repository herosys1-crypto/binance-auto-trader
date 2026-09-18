"""기회 지도에서 「들어가면 이익이 큰 구간」 찾기.

- 모든 종목·모든 1시간 마감 진입을 실매매 청산 규칙으로 채점한 opportunity.parquet 를 읽는다.
- 시장 전체 방향을 빼기 위해 **같은 6시간 창 전체 평균 대비 초과(ex)** 로 본다.
- 발견(9/9~9/13)에서 찾은 구간 → 검증(9/14~)에서 다시 재서 **양쪽 다 이긴 것만** 남긴다.
- 같은 종목의 연속 시간 진입은 서로 겹치므로 「종목×날짜」 묶음 수(클러스터)로 표본을 센다.
"""
import itertools
import sys

import numpy as np
import pandas as pd

d = pd.read_parquet("opportunity.parquet")
SPLIT = pd.Timestamp("2026-09-14", tz="UTC")
d["win6"] = d.t.dt.floor("6h")
d["day"] = d.t.dt.date
d["clu"] = d.symbol + "|" + d.day.astype(str)
for s in ("l", "s"):
    d[f"ex_{s}"] = d[f"roi_{s}"] - d.groupby("win6")[f"roi_{s}"].transform("mean")
d["per"] = np.where(d.t < SPLIT, "disc", "hold")

NUM = {
    "chg24": [-99, -15, -8, -3, 0, 3, 8, 15, 30, 999],
    "ret4h": [-99, -6, -3, -1, 0, 1, 3, 6, 999],
    "h1_from_hi_pct": [-99, -12, -8, -5, -3, -1.5, -0.5, 0.01],
    "h1_from_lo_pct": [-0.01, 0.5, 1.5, 3, 5, 8, 12, 999],
    "m5_from_hi_pct": [-99, -8, -5, -3, -1.5, -0.5, 0.01],
    "m5_from_lo_pct": [-0.01, 0.5, 1.5, 3, 5, 8, 999],
    "d1_from_hi_pct": [-99, -40, -25, -15, -8, -3, 0.01],
    "d1_pctb": [-9, 0, 0.2, 0.4, 0.6, 0.8, 1.0, 9],
    "h4_pctb": [-9, 0, 0.2, 0.4, 0.6, 0.8, 1.0, 9],
    "h1_pctb": [-9, 0, 0.2, 0.4, 0.6, 0.8, 1.0, 9],
    "d1_rsi14": [0, 30, 40, 50, 60, 70, 100],
    "h4_rsi14": [0, 30, 40, 50, 60, 70, 100],
    "h1_rsi14": [0, 30, 40, 50, 60, 70, 100],
    "h1_atr14_pct": [0, 0.8, 1.2, 1.8, 2.5, 4, 99],
    "h1_vol_ratio20": [0, 0.5, 0.8, 1.2, 2, 4, 999],
    "h4_bb_bars_since_below_lower": [-1, 0.5, 3.5, 7.5, 14.5, 30.5, 61],
    "h4_bb_bars_since_above_upper": [-1, 0.5, 3.5, 7.5, 14.5, 30.5, 61],
}
CAT = ["d1_bb_trend", "h4_bb_trend", "d1_bb_pos", "h4_bb_pos", "d1_bb_state", "h4_bb_state",
       "h1_macd_dir", "h4_macd_dir", "h1_ema_align", "h4_ema_align"]

B = pd.DataFrame(index=d.index)
for c, edges in NUM.items():
    v = d[c].astype(float)
    lab = pd.cut(v, edges, include_lowest=True).astype(str)
    if c.startswith("h4_bb_bars_since"):
        lab = lab.where(v.notna(), "없음(60봉+)")
    B[c] = lab.where(v.notna() | c.startswith("h4_bb_bars_since"), np.nan)
for c in CAT:
    B[c] = d[c].astype(str).where(d[c].notna(), np.nan)
FEATS = list(B.columns)


def cell_stats(mask, s):
    out = {}
    for per in ("disc", "hold"):
        m = mask & (d.per == per)
        x = d.loc[m]
        if len(x) == 0:
            out[per] = None; continue
        daily = x.groupby("day")[f"ex_{s}"].mean()
        out[per] = {"n": len(x), "clu": x.clu.nunique(), "sym": x.symbol.nunique(), "days": len(daily),
                    "roi": x[f"roi_{s}"].mean(), "ex": x[f"ex_{s}"].mean(),
                    "win": (x[f"roi_{s}"] > 0).mean(), "pos_days": (daily > 0).mean(),
                    "tp1": (x[f"mfe_{s}"] >= 15).mean(), "sl": (x[f"hit_{s}"] == "SL").mean()}
    return out


def scan(s, depth):
    res = []
    combos = [(f,) for f in FEATS] if depth == 1 else list(itertools.combinations(FEATS, 2))
    for combo in combos:
        key = B[list(combo)].astype(str).agg(" & ".join, axis=1) if depth == 2 else B[combo[0]].astype(str)
        ok = B[list(combo)].notna().all(axis=1)
        disc = d.per == "disc"
        g = d.loc[ok & disc].groupby(key[ok & disc])
        agg = g.agg(n=(f"ex_{s}", "size"), ex=(f"ex_{s}", "mean"), roi=(f"roi_{s}", "mean"), clu=("clu", "nunique"),
                    sym=("symbol", "nunique"))
        agg = agg[(agg.clu >= 120) & (agg.sym >= 30)]
        for lab, r in agg.iterrows():
            res.append({"feat": " × ".join(combo), "cell": lab, "combo": combo, "d_n": r.n, "d_clu": r.clu,
                        "d_ex": r.ex, "d_roi": r.roi})
    R = pd.DataFrame(res)
    # 검증 기간 값
    hold = []
    for r in R.itertuples():
        combo = r.combo
        key = B[list(combo)].astype(str).agg(" & ".join, axis=1) if len(combo) == 2 else B[combo[0]].astype(str)
        m = (key == r.cell) & (d.per == "hold")
        x = d.loc[m]
        daily = x.groupby("day")[f"ex_{s}"].mean() if len(x) else pd.Series(dtype=float)
        hold.append({"h_n": len(x), "h_clu": x.clu.nunique() if len(x) else 0,
                     "h_ex": x[f"ex_{s}"].mean() if len(x) else np.nan,
                     "h_roi": x[f"roi_{s}"].mean() if len(x) else np.nan,
                     "h_win": (x[f"roi_{s}"] > 0).mean() if len(x) else np.nan,
                     "h_pos": (daily > 0).mean() if len(daily) else np.nan, "h_days": len(daily)})
    return pd.concat([R.reset_index(drop=True), pd.DataFrame(hold)], axis=1)


if __name__ == "__main__":
    pd.set_option("display.width", 250, "display.max_colwidth", 80, "display.max_rows", 200)
    print(f"행 {len(d):,} · 종목 {d.symbol.nunique()} · {d.t.min():%m-%d %H:%M} ~ {d.t.max():%m-%d %H:%M}")
    for per in ("disc", "hold"):
        x = d[d.per == per]
        print(f"  {per}: {len(x):,}행 · 무작위 진입 평균 ROI LONG {x.roi_l.mean():+.2f} / SHORT {x.roi_s.mean():+.2f} "
              f"· 승률 {(x.roi_l>0).mean():.0%}/{(x.roi_s>0).mean():.0%}")
    depth = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    for s, name in (("l", "LONG"), ("s", "SHORT")):
        R = scan(s, depth)
        R.to_pickle(f"zones_{name}_{depth}.pkl")
        top = R[(R.d_ex > 0)].sort_values("d_ex", ascending=False)
        k = max(1, len(top) // 10)
        head = top.head(k)
        agree_top = (head.h_ex > 0).mean()
        agree_all = ((R.d_ex > 0) == (R.h_ex > 0)).mean()
        print(f"\n### {name} depth{depth}: 구간 {len(R)}개 · 발견 상위 10%({k}개) 중 검증에서도 +: {agree_top:.0%} "
              f"(전체 방향 일치율 {agree_all:.0%})")
        surv = R[(R.d_ex >= 2) & (R.d_roi > 0) & (R.h_ex > 0) & (R.h_roi > 0) & (R.h_clu >= 60) & (R.h_pos >= 0.6)]
        surv = surv.assign(score=surv[["d_ex", "h_ex"]].min(axis=1)).sort_values("score", ascending=False)
        cols = ["feat", "cell", "d_clu", "d_roi", "d_ex", "h_clu", "h_roi", "h_ex", "h_win", "h_pos", "h_days"]
        print(surv[cols].head(25).round(2).to_string(index=False))
