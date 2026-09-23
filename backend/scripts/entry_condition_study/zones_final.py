"""주제를 단순 규칙으로 고정해 다시 잰다 (칸 하나를 고르지 않는다 = 과적합 방지).
LONG 주제 = 「4시간 볼밴 하단 이탈 뒤 반등 초입」  /  SHORT 주제 = 「짧은 시간 급반등 꼭대기」.
지금 켜진 게이트(P5 SHORT · P6 LONG)와 같은 데이터에서 나란히 비교한다."""
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    import zones as Z
import numpy as np
import pandas as pd

d = Z.d
pd.set_option("display.width", 250)
since_lo = d.h4_bb_bars_since_below_lower
since_up = d.h4_bb_bars_since_above_upper
low_d1 = d.d1_bb_pos.isin(["LOWER_HALF", "BELOW_LOWER"])

DEF = {
    "LONG": {
        "무작위 (전부)": pd.Series(True, index=d.index),
        "P6 지금 게이트 (24h≤−5 또는 5분고점−4)": (d.chg24 <= -5) | (d.m5_from_hi_pct <= -4),
        "L1 4H 하단이탈 뒤 1~7봉": since_lo.between(1, 7),
        "L2 L1 + 1H 저점서 +1.5~8% 반등중": since_lo.between(1, 7) & d.h1_from_lo_pct.between(1.5, 8),
        "L3 L1 + 5분 고점서 −1.5% 이상 눌림": since_lo.between(1, 7) & (d.m5_from_hi_pct <= -1.5),
        "L4 4H 상태 = 하단 뒤 반등": d.h4_bb_state == "REBOUND_AFTER_LOWER",
        "L5 L1 + 24h 과열 아님(<15)": since_lo.between(1, 7) & (d.chg24 < 15),
    },
    "SHORT": {
        "무작위 (전부)": pd.Series(True, index=d.index),
        "P5 지금 게이트 (1H고점 −3% 안 & 일봉 UP 아님)": (d.h1_from_hi_pct >= -3) & d.d1_bb_trend.notna() & (d.d1_bb_trend != "UP"),
        "S1 5분 저점서 +8% 이상": d.m5_from_lo_pct > 8,
        "S2 1H 저점서 +12% 이상": d.h1_from_lo_pct > 12,
        "S3 (S1 또는 S2) + 1H ATR>2.5": ((d.m5_from_lo_pct > 8) | (d.h1_from_lo_pct > 12)) & (d.h1_atr14_pct > 2.5),
        "S4 S3 + 일봉 하단권(하락 추세 속 급반등)": ((d.m5_from_lo_pct > 8) | (d.h1_from_lo_pct > 12)) & (d.h1_atr14_pct > 2.5) & low_d1,
        "S5 4시간 +6% 이상 급등": d.ret4h > 6,
    },
}


def stat(x, s):
    if len(x) == 0:
        return dict(clu=0)
    return dict(clu=x.clu.nunique(), roi=x[f"roi_{s}"].mean(), ex=x[f"ex_{s}"].mean(), win=(x[f"roi_{s}"] > 0).mean(),
                med=x[f"roi_{s}"].median(), sl=(x[f"hit_{s}"] == "SL").mean(), tp=(x[f"mfe_{s}"] >= 15).mean())


for side, defs in DEF.items():
    s = side[0].lower()
    print(f"\n==================== {side} ====================")
    rows = []
    for name, m in defs.items():
        m = m.fillna(False)
        x = d[m]
        a, b = stat(x[x.per == "disc"], s), stat(x[x.per == "hold"], s)
        daily = x.groupby("day").agg(clu=("clu", "nunique"), roi=(f"roi_{s}", "mean"), ex=(f"ex_{s}", "mean"))
        daily = daily[daily.clu >= 10]
        per_day = x.groupby("day").clu.nunique().mean()
        rows.append({"구간": name, "비중": m.mean(), "하루 종목수": per_day,
                     "발견 ROI": a.get("roi"), "발견 ex": a.get("ex"), "검증 ROI": b.get("roi"), "검증 ex": b.get("ex"),
                     "승률": (x[f"roi_{s}"] > 0).mean(), "중앙값": x[f"roi_{s}"].median(),
                     "손절률": (x[f"hit_{s}"] == "SL").mean(), "TP1도달": (x[f"mfe_{s}"] >= 15).mean(),
                     "ROI+날": f"{(daily.roi > 0).sum()}/{len(daily)}", "ex+날": f"{(daily.ex > 0).sum()}/{len(daily)}"})
    print(pd.DataFrame(rows).round(2).to_string(index=False))

# 가장 단순한 대표 두 개의 날짜별 표
for side, name in (("LONG", "L1 4H 하단이탈 뒤 1~7봉"), ("SHORT", "S3 (S1 또는 S2) + 1H ATR>2.5")):
    s = side[0].lower()
    m = DEF[side][name].fillna(False)
    x = d[m]
    t = x.groupby("day").agg(종목일=("clu", "nunique"), ROI=(f"roi_{s}", "mean"), 초과=(f"ex_{s}", "mean"),
                             승률=(f"roi_{s}", lambda v: (v > 0).mean()))
    t["무작위ROI"] = d.groupby("day")[f"roi_{s}"].mean()
    print(f"\n--- {side} · {name} 날짜별 ---")
    print(t.round(2).to_string())
