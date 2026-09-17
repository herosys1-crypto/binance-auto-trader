"""가상 진입마다 **진입 시점에 닫혀 있던 봉만으로** 운영과 같은 chart_state 계산을 다시 한다 (미래참조 없음)."""
import bisect
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # backend/
from app.services import chart_state as CS  # noqa: E402

HERE = Path(__file__).parent
TH = dict(CS.THRESHOLDS)
d = pd.read_csv(HERE / "dumpall.csv", parse_dates=["opened_at"], low_memory=False)
d = d[d.done.astype(str).str.lower() == "true"].copy()
d["oms"] = (d.opened_at.astype("int64") // 10**6).astype("int64")

IVS = {"1d": ("d1", 60), "4h": ("h4", 60), "1h": ("h1", 60), "5m": ("m5", 120)}
TF_KEYS = ("pctb", "rsi14", "macd_dir", "ema_align", "atr14_pct", "vol_ratio20", "chg_last_pct", "mid_slope3_pct", "bb_width_pct")
BB_KEYS = ("state", "trend", "pos", "bias", "dist_mid_pct", "dist_up_pct", "dist_lo_pct", "bars_since_above_upper", "bars_since_below_lower")
ST_KEYS = ("range_pos", "near_top", "near_bottom")

rows = []
for sym, g in d.groupby("symbol"):
    p = HERE / "klines" / f"{sym}.json"
    if not p.exists():
        continue
    raw = json.loads(p.read_text())
    bars = {}
    for iv in IVS:
        b = CS.normalize(raw.get(iv) or [], iv)
        seen, uniq = set(), []
        for x in b:
            if x[0] not in seen:
                seen.add(x[0]); uniq.append(x)
        uniq.sort(key=lambda x: x[0])
        bars[iv] = (uniq, [x[0] + CS.MS[iv] for x in uniq])   # 봉 마감 시각
    for r in g.itertuples(index=False):
        feat = {"id": r.id}
        for iv, (key, lim) in IVS.items():
            b, closes = bars[iv]
            j = bisect.bisect_right(closes, r.oms)          # 마감 ≤ 진입 시각 인 봉만
            sl = b[max(0, j - lim):j]
            if len(sl) < 30:
                continue
            blk = CS._block(iv, sl, TH)
            for k in TF_KEYS:
                feat[f"{key}_{k}"] = blk.get(k)
            if "bb" in blk:
                for k in BB_KEYS:
                    feat[f"{key}_bb_{k}"] = blk["bb"].get(k)
                feat[f"{key}_bb_events"] = "|".join(blk["bb"].get("events") or [])
            if "st" in blk:
                for k in ST_KEYS:
                    feat[f"{key}_st_{k}"] = blk["st"].get(k)
                feat[f"{key}_st_events"] = "|".join(blk["st"].get("events") or [])
            # 최근 흐름 (진입 전 누적 변화)
            c = [x[4] for x in sl]
            n_back = {"1d": 3, "4h": 6, "1h": 4, "5m": 12}[iv]
            if len(c) > n_back:
                feat[f"{key}_ret{n_back}"] = round((c[-1] / c[-1 - n_back] - 1) * 100, 3)
            hi = max(x[2] for x in sl[-n_back * 4:]) if len(sl) >= n_back * 4 else None
            if hi:
                feat[f"{key}_from_hi"] = round((c[-1] / hi - 1) * 100, 3)
                lo = min(x[3] for x in sl[-n_back * 4:])
                feat[f"{key}_from_lo"] = round((c[-1] / lo - 1) * 100, 3) if lo else None
        rows.append(feat)

f = pd.DataFrame(rows)
out = d.merge(f, on="id", how="left")
out.to_parquet(HERE / "features.parquet", index=False)
print(len(out), "rows ·", out["d1_pctb"].notna().sum(), "with d1 ·", out["m5_pctb"].notna().sum(), "with m5")
