"""규칙마다 「이기는 차트 조건」 찾기 — 발견(사전등록 이전) / 검증(사전등록 이후) 분리.

지표: excess = 그 진입 ROI − 같은 방향 무작위 기준선의 같은 6시간 창 평균 (없으면 같은 날).
조건 후보: 수치 특징 분위 문턱(≤/≥) · 범주 특징 같음 · 상위 후보 2개 조합.
발견 데이터에서 고를 때 조건: 유지 n ≥ max(60, 20%) · 4조각(시간 반쪽 × 심볼 홀짝) 모두 excess > 0 · 순위 = 4조각 최소값.
검증 데이터는 **고른 뒤에만** 본다.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
PREREG = pd.Timestamp("2026-09-13T22:16:00Z")
d = pd.read_parquet(HERE / "features.parquet")
d = d[d.roi.notna()].copy()
d["day"] = d.opened_at.dt.floor("D")
d["win6"] = d.opened_at.dt.floor("6h")
d["odd"] = d.symbol.map(lambda s: sum(map(ord, s)) % 2)
d["clu"] = d.symbol + "|" + d.opened_at.dt.floor("h").astype(str)

# 태그 → 범주
tags = d.tags.fillna("").str.split("|")
for t in ("UP24", "DOWN24", "UP3D", "UP5D", "DOWN3D", "DOWN5D"):
    d[f"tag_{t}"] = tags.map(lambda x, t=t: t in x)
d["mkt"] = tags.map(lambda x: next((y for y in x if y.startswith("MKT_")), "MKT_NA"))
d["h4hist_up"] = (d.h4hist > d.h4hist_prev)
d["m15hist_up"] = (d.m15hist > d.m15hist_prev)

# 기준선 (방향·6시간 창)
base = d[d.rule.str.startswith("baseline_")]
bw = base.groupby(["side", "win6"]).roi.agg(["mean", "size"])
bd = base.groupby(["side", "day"]).roi.mean()
def base_of(r):
    k = (r.side, r.win6)
    if k in bw.index and bw.loc[k, "size"] >= 10:
        return bw.loc[k, "mean"]
    return bd.get((r.side, r.day), np.nan)
keys = pd.MultiIndex.from_frame(d[["side", "win6"]])
m_w = bw.reindex(keys)
m_d = bd.reindex(pd.MultiIndex.from_frame(d[["side", "day"]])).values
d["base"] = np.where(m_w["size"].values >= 10, m_w["mean"].values, m_d)
d["ex"] = d.roi - d.base
d["half"] = (d.opened_at >= d.opened_at.quantile(0.5)).astype(int)   # 시간 반쪽 (전체 기준 중앙값)

NUM = [c for c in d.columns if c.startswith(("d1_", "h4_", "h1_", "m5_")) and d[c].dtype.kind in "fi"
       and not c.endswith(("_events",))] + ["chg24", "rsi15", "pctb15", "dh5"]
CAT = [c for c in d.columns if c.endswith(("_macd_dir", "_ema_align", "_bb_state", "_bb_trend", "_bb_pos", "_st_near_top", "_st_near_bottom"))] \
      + ["mkt", "h4hist_up", "m15hist_up", "accel3"] + [c for c in d.columns if c.startswith("tag_")]
NUM = [c for c in NUM if c not in CAT]


def cond_masks(g: pd.DataFrame):
    """(이름, 마스크 함수) — 문턱은 발견 데이터 분위에서 정한다."""
    out = []
    for c in NUM:
        s = g[c].dropna()
        if len(s) < 100:
            continue
        for q in (0.2, 0.33, 0.5, 0.67, 0.8):
            v = float(s.quantile(q))
            out.append((f"{c} <= {v:.3g}", c, "le", v))
            out.append((f"{c} >= {v:.3g}", c, "ge", v))
    for c in CAT:
        vc = g[c].dropna().astype(str).value_counts()
        for val, n in vc.items():
            if n >= 40:
                out.append((f"{c} == {val}", c, "eq", val))
                out.append((f"{c} != {val}", c, "ne", val))
    return out


def apply(g, spec):
    _, c, op, v = spec
    x = g[c]
    if op == "le":
        return x <= v
    if op == "ge":
        return x >= v
    xs = x.astype(str)
    return (xs == v) if op == "eq" else ((xs != v) & x.notna())


def pieces(k):
    return [k[(k.half == h) & (k.odd == o)].ex.mean() for h in (0, 1) for o in (0, 1)]


def clu_t(k):
    c = k.groupby("clu").ex.mean()
    if len(c) < 20:
        return np.nan
    return c.mean() / (c.std(ddof=1) / np.sqrt(len(c)))


def score(g, mask, min_n):
    k = g[mask.fillna(False)]
    if len(k) < min_n:
        return None
    p = pieces(k)
    if any(np.isnan(p)):
        return None
    return {"n": len(k), "ex": k.ex.mean(), "roi": k.roi.mean(), "win": (k.roi > 0).mean(), "pmin": min(p), "t": clu_t(k)}


def search(g):
    g = g.copy()
    g["half"] = (g.opened_at >= g.opened_at.median()).astype(int)   # 발견 데이터 안에서 시간 반쪽
    min_n = max(60, int(0.2 * len(g)))
    specs = cond_masks(g)
    res = []
    for sp in specs:
        s = score(g, apply(g, sp), min_n)
        if s and s["pmin"] > 0:
            res.append((sp, s))
    res.sort(key=lambda x: -x[1]["pmin"])
    top = res[:25]
    combos = []
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            a, b = top[i][0], top[j][0]
            if a[1] == b[1]:
                continue
            s = score(g, apply(g, a) & apply(g, b), min_n)
            if s and s["pmin"] > top[i][1]["pmin"]:
                combos.append(((a, b), s))
    combos.sort(key=lambda x: -x[1]["pmin"])
    return top[:5], combos[:5]


def evaluate(g, spec):
    m = apply(g, spec[0]) & apply(g, spec[1]) if isinstance(spec, tuple) and isinstance(spec[0], tuple) else apply(g, spec)
    k = g[m.fillna(False)]
    rest = g[~m.fillna(False)]
    if len(k) == 0:
        return {"n": 0}
    return {"n": len(k), "share": len(k) / len(g), "ex": k.ex.mean(), "roi": k.roi.mean(), "win": (k.roi > 0).mean(),
            "t": clu_t(k), "rest_ex": rest.ex.mean() if len(rest) else np.nan, "all_ex": g.ex.mean(), "all_roi": g.roi.mean(),
            "days_pos": int((k.groupby("day").ex.mean() > 0).sum()), "days": int(k.day.nunique())}


def name(spec):
    return " & ".join(s[0] for s in spec) if isinstance(spec[0], tuple) else spec[0]


report = {}
for rule, g in d.groupby("rule"):
    disc, hold = g[g.opened_at < PREREG], g[g.opened_at >= PREREG]
    if len(disc) < 200 or len(hold) < 60:
        continue
    top, combos = search(disc)
    cands = [c[0] for c in combos[:3]] + [t[0] for t in top[:3]]
    out = []
    for sp in cands:
        out.append({"cond": name(sp), "disc": evaluate(disc, sp), "hold": evaluate(hold, sp)})
    report[rule] = {"side": g.side.iloc[0], "n": len(g), "all_ex": g.ex.mean(), "all_roi": g.roi.mean(),
                    "disc_ex": disc.ex.mean(), "hold_ex": hold.ex.mean(), "cands": out}
    print(rule, len(g), f"ex {g.ex.mean():+.2f}", "후보", len(out), flush=True)

(HERE / "conditions.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=float))
print("saved")
