"""「90% 성공」은 가능한가 — 좋은 조건을 겹칠수록 승률·수익·표본이 어떻게 되나 (83,927 자리 · 실매매 청산 24h).
그리고 「승률」을 청산 설계로 올리면(익절을 아주 작게) 돈은 어떻게 되나."""
import io, contextlib, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
with contextlib.redirect_stdout(io.StringIO()):
    import zones as Z
import numpy as np
import pandas as pd

d = Z.d.copy()
d["hour"] = d.t.dt.floor("h")
d["breadth"] = d.groupby("hour").chg24.transform(lambda v: (v > 0).mean())      # 그 시각 시장폭 (24h 오른 종목 비율)
since_lo = d.h4_bb_bars_since_below_lower
L1 = since_lo.between(1, 7)
S4 = ((d.m5_from_lo_pct > 8) | (d.h1_from_lo_pct > 12)) & (d.h1_atr14_pct > 2.5) & d.d1_bb_pos.isin(["LOWER_HALF", "BELOW_LOWER"])

STACK = {
    "LONG": [
        ("아무 데나 (무작위)", pd.Series(True, index=d.index)),
        ("L1 4H 하단 이탈 뒤 1~7봉", L1),
        ("+ 시장폭 ≥ 0.55", L1 & (d.breadth >= 0.55)),
        ("+ 1H 저점서 +1.5~8% 반등중", L1 & (d.breadth >= 0.55) & d.h1_from_lo_pct.between(1.5, 8)),
        ("+ 24h 과열 아님(<15)", L1 & (d.breadth >= 0.55) & d.h1_from_lo_pct.between(1.5, 8) & (d.chg24 < 15)),
        ("+ 1H RSI 40~60", L1 & (d.breadth >= 0.55) & d.h1_from_lo_pct.between(1.5, 8) & (d.chg24 < 15) & d.h1_rsi14.between(40, 60)),
    ],
    "SHORT": [
        ("아무 데나 (무작위)", pd.Series(True, index=d.index)),
        ("S4 하락추세 속 급반등 꼭대기", S4),
        ("+ 시장폭 ≤ 0.45", S4 & (d.breadth <= 0.45)),
        ("+ 1H RSI ≥ 60", S4 & (d.breadth <= 0.45) & (d.h1_rsi14 >= 60)),
    ],
}
print("※ 실매매 청산(손절 −25 ROI · TP1 15 · 트레일링) 24시간 · 승률 = ROI>0 비율 · 날짜 = 그날 평균 ROI>0 인 날")
for side, steps in STACK.items():
    s = side[0].lower()
    print(f"\n=== {side} — 조건을 하나씩 더 쌓으면 ===")
    print(f"{'조건':34s} {'하루 건':>6s} | {'발견 승률':>7s} {'ROI':>6s} | {'검증 승률':>7s} {'ROI':>6s} | {'ROI+ 날':>7s}")
    for name, m in steps:
        m = m.fillna(False)
        x = d[m]
        out = []
        for per in ("disc", "hold"):
            y = x[x.per == per]
            out.append(f"{(y[f'roi_{s}'] > 0).mean():7.0%} {y[f'roi_{s}'].mean():+6.2f}" if len(y) >= 30 else f"{'표본<30':>14s}")
        dl = x.groupby("day")[f"roi_{s}"].mean()
        print(f"{name:34s} {len(x) / d.day.nunique():6.1f} | {out[0]} | {out[1]} | {(dl > 0).sum():>3d}/{len(dl)}")

# 승률을 청산 설계로 올리면 — 무작위 LONG 에 「+X% 가격이면 바로 익절, −손절」만 적용 (24h 최대/최소로 근사)
print("\n=== 승률을 청산으로 올리면? (무작위 LONG · 24시간 안 최고/최저로 근사, 먼저 닿는 쪽은 모름 → 낙관적 가정) ===")
mfe, mae = d.mfe_l, d.mae_l          # ROI 단위 (레버리지 2)
for tp in (2, 4, 8):
    for sl in (25,):
        win = mfe >= tp
        lose = (~win) & (mae <= -sl)
        other = ~(win | lose)
        roi = np.where(win, tp, np.where(lose, -sl, d.roi_l.clip(-sl, tp)))
        print(f"  익절 +{tp:<2d} ROI / 손절 −{sl}: 승률 {win.mean():.0%} · 1건 평균 ROI {roi.mean():+.2f}")
