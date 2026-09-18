"""세력 CCI 전략 채점 — 무작위(같은 6시간 창) 대비, 발견/검증 두 기간, 날짜별."""
import numpy as np
import pandas as pd

d = pd.read_parquet("bbcci_signals.parquet")
o = pd.read_parquet("opportunity.parquet")
o["win6"] = o.t.dt.floor("6h")
base = o.groupby("win6").agg(bl=("roi_l", "mean"), bs=("roi_s", "mean"))
d["win6"] = d.t.dt.floor("6h")
d = d.merge(base, left_on="win6", right_index=True, how="inner")
d["base"] = np.where(d.side == "L", d.bl, d.bs)
d["ex"] = d.roi_live - d.base
d["day"] = d.t.dt.date
d["clu"] = d.symbol + "|" + d.day.astype(str)
SPLIT = pd.Timestamp("2026-09-14", tz="UTC")
d["per"] = np.where(d.t < SPLIT, "발견", "검증")
pd.set_option("display.width", 250)

rows = []
for (tf, sig), g in d.groupby(["tf", "sig"]):
    r = {"tf": tf, "신호": sig, "건수": len(g), "종목일": g.clu.nunique(), "하루": round(len(g) / g.day.nunique(), 1)}
    for per in ("발견", "검증"):
        x = g[g.per == per]
        r[f"{per} 초과"] = x.ex.mean()
        r[f"{per} live"] = x.roi_live.mean()
        r[f"{per} own"] = x.roi_own.mean()
    daily = g.groupby("day").ex.mean()
    r["초과+날"] = f"{(daily > 0).sum()}/{len(daily)}"
    r["승률 live"] = (g.roi_live > 0).mean()
    r["승률 own"] = (g.roi_own > 0).mean()
    r["own 중앙"] = g.roi_own.median()
    rows.append(r)
print("※ live = 우리 실매매 청산(24h) · own = 전략서 청산 · 초과 = 같은 6시간 창 무작위 대비(live 청산)")
print(pd.DataFrame(rows).round(2).to_string(index=False))

print("\n무작위 기준 (live 청산 24h):")
for per, m in (("발견", o.t < SPLIT), ("검증", o.t >= SPLIT)):
    print(f"  {per}: LONG {o[m].roi_l.mean():+.2f} · SHORT {o[m].roi_s.mean():+.2f}")
