"""세력 CCI 를 「필터」로 모든 자리(기회 지도 83,927)에 걸면 나아지나 — 1시간봉 기준, 같은 6시간 창 무작위 대비."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
import bbcci_backtest as B
import opportunity_scan as OS

o = pd.read_parquet("opportunity.parquet")
o["tms"] = o.t.astype("int64") // 10**6
feat = []
for sym in o.symbol.unique():
    b = OS._load(sym)["1h"][0]
    if len(b) < 130:
        continue
    a = np.array(b, dtype=float)
    I = B.indicators(a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5])
    close_t = a[:, 0].astype(np.int64) + 3_600_000
    feat.append(pd.DataFrame({"symbol": sym, "tms": close_t, "fc": I["fc"], "fc1": np.roll(I["fc"], 1),
                              "above_mb": a[:, 4] > I["mb"], "bw_rank": I["bw_rank"], "volok": a[:, 5] > I["vs"] * 1.2}))
f = pd.concat(feat)
d = o.merge(f, on=["symbol", "tms"], how="inner")
d["win6"] = d.t.dt.floor("6h")
for s in ("l", "s"):
    d[f"ex_{s}"] = d[f"roi_{s}"] - d.groupby("win6")[f"roi_{s}"].transform("mean")
d["day"] = d.t.dt.date
SPLIT = pd.Timestamp("2026-09-14", tz="UTC")
d["per"] = np.where(d.t < SPLIT, "발견", "검증")
print(f"자리 {len(d):,}")

F = {
    "LONG": {"세력CCI>0": d.fc > 0, "세력CCI>0 & 종가>중심선": (d.fc > 0) & d.above_mb,
             "세력CCI>100": d.fc > 100, "세력CCI 0선 상향 교차": (d.fc1 <= 0) & (d.fc > 0),
             "스퀴즈(폭 하위20%)": d.bw_rank <= 0.2, "거래량>1.2배": d.volok,
             "(비교) 기회지도 L1": d.h4_bb_bars_since_below_lower.between(1, 7)},
    "SHORT": {"세력CCI<0": d.fc < 0, "세력CCI<0 & 종가<중심선": (d.fc < 0) & ~d.above_mb,
              "세력CCI<−100": d.fc < -100, "세력CCI 0선 하향 교차": (d.fc1 >= 0) & (d.fc < 0),
              "스퀴즈(폭 하위20%)": d.bw_rank <= 0.2, "거래량>1.2배": d.volok},
}
for side, fs in F.items():
    s = side[0].lower()
    print(f"\n=== {side} — 필터 통과 vs 제외 (초과 ROI, 무작위 대비) ===")
    for name, m in fs.items():
        m = m.fillna(False)
        out = []
        for per in ("발견", "검증"):
            k, e = d[m & (d.per == per)], d[~m & (d.per == per)]
            out.append(f"{per} {k[f'ex_{s}'].mean():+5.2f} (제외 {e[f'ex_{s}'].mean():+5.2f})")
        daily = d[m].groupby("day")[f"ex_{s}"].mean() - d[~m].groupby("day")[f"ex_{s}"].mean()
        print(f"  {name:22s} 통과 {m.mean():4.0%} | {out[0]} | {out[1]} | 통과가 나은 날 {(daily > 0).sum()}/{len(daily)}")
