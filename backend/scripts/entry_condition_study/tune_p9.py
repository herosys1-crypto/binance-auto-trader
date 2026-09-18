"""P9 재측정 — h4 하단이탈 「없음(None)」을 어떻게 볼지에 따라 결과가 갈리는지 본다.
   None = 최근 60봉 안에 하단 이탈이 아예 없었다 = P9 의 취지(무너진 직후 아님)에는 **통과**여야 한다.
"""
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    import analyze as A

d, P = A.d, A.PREREG
S = lambda x: (x.h1_from_hi >= -3) & x.d1_bb_trend.notna() & (x.d1_bb_trend != "UP")
B = "h4_bb_bars_since_below_lower"

VAR = {
    "S 만 (기준)": lambda x: S(x),
    "S & (>=14)  [처음 잰 것]": lambda x: S(x) & (x[B] >= 14),
    "S & (>=14 또는 이탈없음)": lambda x: S(x) & (x[B].isna() | (x[B] >= 14)),
    "S & 이탈없음만": lambda x: S(x) & x[B].isna(),
    "S & (>=24 또는 이탈없음)": lambda x: S(x) & (x[B].isna() | (x[B] >= 24)),
    "S & (>=8 또는 이탈없음)": lambda x: S(x) & (x[B].isna() | (x[B] >= 8)),
}

g = d[(d.side == "SHORT") & ~d.rule.str.startswith("baseline_")]
print(f"SHORT 규칙 진입 {len(g)}건 · {B} 없음 비율 {g[B].isna().mean():.0%}")
print(f"{'변형':28s} | {'발견 통과(막힘)':>30s} | {'검증 통과(막힘)':>30s} 일치")
for name, f in VAR.items():
    out, ok = [], True
    for gg in (g[g.opened_at < P], g[g.opened_at >= P]):
        m = f(gg).fillna(False)
        k, r = gg[m], gg[~m]
        if len(k) < 40 or len(r) < 40:
            out.append("      표본 부족      "); ok = False; continue
        out.append(f"{len(k)/len(gg):3.0%} {k.ex.mean():+5.2f} ({r.ex.mean():+5.2f})")
        if k.ex.mean() <= r.ex.mean():
            ok = False
    print(f"{name:28s} | {out[0]:>30s} | {out[1]:>30s} {'OK' if ok else ''}")

# 이탈없음 행만 따로: 정말 좋은 자리인가?
for label, gg in (("발견", g[g.opened_at < P]), ("검증", g[g.opened_at >= P])):
    sub = gg[S(gg).fillna(False)]
    a = sub[sub[B].isna()]
    b = sub[sub[B].notna() & (sub[B] >= 14)]
    c = sub[sub[B].notna() & (sub[B] < 14)]
    print(f"{label}: 게이트통과 {len(sub)} → 이탈없음 {len(a)} ex {a.ex.mean():+5.2f} | "
          f"14봉+ {len(b)} ex {b.ex.mean():+5.2f} | 14봉미만 {len(c)} ex {c.ex.mean():+5.2f}")
