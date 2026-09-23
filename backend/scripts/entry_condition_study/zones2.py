"""두 지표 조합 구간 — 「두 기간 모두」 + 「날짜별로도 대부분」 이긴 것만. 절대 ROI 도 같이 본다."""
import io, contextlib, itertools, sys
with contextlib.redirect_stdout(io.StringIO()):
    import zones as Z
import numpy as np
import pandas as pd

d, B, FEATS = Z.d, Z.B, Z.FEATS
pd.set_option("display.width", 260, "display.max_colwidth", 90, "display.max_rows", 300)


def daily_table(mask, s):
    x = d.loc[mask]
    g = x.groupby("day")
    t = pd.DataFrame({"clu": g.clu.nunique(), "roi": g[f"roi_{s}"].mean(), "ex": g[f"ex_{s}"].mean()})
    return t[t.clu >= 15]


def summarize(mask, s):
    out = {}
    for per in ("disc", "hold"):
        x = d.loc[mask & (d.per == per)]
        out[per] = x
    t = daily_table(mask, s)
    return {
        "d_clu": out["disc"].clu.nunique(), "d_roi": out["disc"][f"roi_{s}"].mean(), "d_ex": out["disc"][f"ex_{s}"].mean(),
        "h_clu": out["hold"].clu.nunique(), "h_roi": out["hold"][f"roi_{s}"].mean(), "h_ex": out["hold"][f"ex_{s}"].mean(),
        "days": len(t), "ex_days+": (t.ex > 0).mean() if len(t) else np.nan,
        "roi_days+": (t.roi > 0).mean() if len(t) else np.nan,
        "win": (d.loc[mask, f"roi_{s}"] > 0).mean(), "med": d.loc[mask, f"roi_{s}"].median(),
        "sl": (d.loc[mask, f"hit_{s}"] == "SL").mean(),
    }


if __name__ == "__main__":
    s = sys.argv[1] if len(sys.argv) > 1 else "s"
    name = {"l": "LONG", "s": "SHORT"}[s]
    res = []
    keys = {f: B[f].astype(str) for f in FEATS}
    for f1, f2 in itertools.combinations(FEATS, 2):
        ok = B[f1].notna() & B[f2].notna()
        key = keys[f1] + " & " + keys[f2]
        sub = d.loc[ok]
        g = sub.groupby([key[ok], sub.per])
        a = g.agg(clu=("clu", "nunique"), ex=(f"ex_{s}", "mean"), roi=(f"roi_{s}", "mean")).unstack("per")
        a = a.dropna()
        a = a[(a[("clu", "disc")] >= 60) & (a[("clu", "hold")] >= 40)]
        a = a[(a[("ex", "disc")] > 1) & (a[("ex", "hold")] > 1) & (a[("roi", "disc")] > 0) & (a[("roi", "hold")] > 0)]
        for lab in a.index:
            res.append((f1, f2, lab))
    print(f"{name}: 두 기간 모두 ex>1 · ROI>0 인 조합 구간 {len(res)}개 → 날짜별 확인")
    rows = []
    for f1, f2, lab in res:
        m = (keys[f1] + " & " + keys[f2]) == lab
        r = summarize(m, s)
        r.update({"feat": f"{f1} × {f2}", "cell": lab})
        rows.append(r)
    R = pd.DataFrame(rows)
    if len(R):
        R = R[(R.days >= 6) & (R["ex_days+"] >= 0.7)]
        R["score"] = R[["d_ex", "h_ex"]].min(axis=1)
        cols = ["feat", "cell", "d_clu", "d_roi", "d_ex", "h_clu", "h_roi", "h_ex", "days", "ex_days+", "roi_days+", "win", "med", "sl"]
        print(R.sort_values("score", ascending=False)[cols].head(40).round(2).to_string(index=False))
        R.to_pickle(f"zones2_{name}.pkl")
