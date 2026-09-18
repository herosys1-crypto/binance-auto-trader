"""운영 모듈(opportunity_zones)이 분석(opportunity.parquet)과 같은 자리를 고르나 — 워커와 같은 재료로 재현."""
import bisect, json, sys, random
from pathlib import Path
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # backend/
from app.services import chart_state as CS
from app.services import chart_learning as CL
from app.services import opportunity_zones as OZ
import opportunity_scan as S

d = pd.read_parquet(HERE / "opportunity.parquet")
d["tms"] = d.t.astype("int64") // 10**6
sl = d.h4_bb_bars_since_below_lower
d["L1"] = sl.between(1, 7)
spike = ((d.m5_from_lo_pct > 8) | (d.h1_from_lo_pct > 12)) & (d.h1_atr14_pct > 2.5)
d["S3"] = spike
d["S4"] = spike & d.d1_bb_pos.isin(["LOWER_HALF", "BELOW_LOWER"])

random.seed(7)
syms = sorted(d.symbol.unique())
pick = random.sample(syms, 60)
agree = {"L1": [0, 0], "S3": [0, 0], "S4": [0, 0]}
mism = []
for sym in pick:
    bars = S._load(sym)
    b15 = S._m15(bars["5m"][0])
    t15 = [x[0] for x in b15]
    k4, c4 = bars["4h"]
    k1d, c1d = bars["1d"]
    for r in d[d.symbol == sym].itertuples():
        t = r.tms
        j = bisect.bisect_left(t15, t)          # 진입 뒤 첫 15분봉
        pre15 = b15[max(0, j - 262):j]           # 워커: 15분봉 262개 (진입 시각까지 닫힌 것)
        if len(pre15) < 60:
            continue
        k1h = CL.aggregate(pre15, CL.MS_1H)
        close1h = [int(b[0]) + CL.MS_1H for b in k1h]
        n1 = bisect.bisect_right(close1h, t)
        kl1h = k1h[max(0, n1 - 60):n1]
        n4 = bisect.bisect_right(c4, t)
        kl4h = k4[max(0, n4 - 60):n4]
        nd = bisect.bisect_right(c1d, t)
        kl1d = k1d[max(0, nd - 60):nd]
        mine = {"L1": OZ.on_hour(pre15) and OZ.l1_rebound(kl4h),
                "S3": OZ.needs_daily(pre15, kl1h)}
        mine["S4"] = mine["S3"] and OZ.d1_low_half(kl1d)
        for k in agree:
            want = bool(getattr(r, k))
            agree[k][0] += int(mine[k] == want)
            agree[k][1] += 1
            if mine[k] != want and len(mism) < 12:
                mism.append((k, sym, r.t, want, mine[k], r.h1_from_lo_pct, r.m5_from_lo_pct, r.h1_atr14_pct,
                             r.h4_bb_bars_since_below_lower, r.d1_bb_pos, len(kl1h)))
for k, (a, n) in agree.items():
    print(f"{k}: 일치 {a}/{n} = {a / n:.2%}")
for m in mism:
    print(m)
