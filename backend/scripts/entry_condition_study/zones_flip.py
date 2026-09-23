"""무엇이 뒤집혔나 — 주요 지표 구간별로 발견/검증 초과(ex)를 나란히, 그리고 날짜별 시장 국면."""
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    import zones as Z
d, B = Z.d, Z.B
import pandas as pd

# 날짜별 시장: 무작위 LONG 평균 ROI (= 그날 시장 방향)
print("날짜별 무작위 진입 평균 ROI (24h 뒤 결과):")
g = d.groupby("day")
print(pd.DataFrame({"n": g.size(), "LONG": g.roi_l.mean().round(2), "SHORT": g.roi_s.mean().round(2),
                    "시장폭(24h 오른 종목%)": g.chg24.apply(lambda v: (v > 0).mean()).round(2)}).to_string())

for s, name in (("l", "LONG"), ("s", "SHORT")):
    print(f"\n######## {name} — 구간별 초과 ROI (발견 → 검증) · n 은 클러스터")
    for f in ("chg24", "h1_from_hi_pct", "h1_from_lo_pct", "d1_pctb", "h4_pctb", "h1_rsi14", "d1_bb_trend", "h4_bb_pos", "h1_atr14_pct"):
        rows = []
        for lab, idx in B.groupby(f).groups.items():
            x = d.loc[idx]
            a, b = x[x.per == "disc"], x[x.per == "hold"]
            if a.clu.nunique() < 80 or b.clu.nunique() < 50:
                continue
            rows.append(f"{lab}: {a[f'ex_{s}'].mean():+5.1f}→{b[f'ex_{s}'].mean():+5.1f}")
        print(f"  {f:16s} " + " | ".join(rows))
