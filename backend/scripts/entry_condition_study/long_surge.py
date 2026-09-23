"""상승 초입 LONG(surge_start_346) 전략 완성용 분석 + LONG 게이트 2안 검증.

가설은 **미리 정한다** (AVAUSDT #235653 사례에서 나온 「급등 뒤 1시간 되돌림」).
발견 = 사전등록 이전(~9/13 22:16) · 검증 = 이후. 조건은 발견에서만 고르고 검증은 나중에 본다.
"""
import io
import contextlib

with contextlib.redirect_stdout(io.StringIO()):
    import analyze as A          # 전처리(ex = 같은 6시간 창 무작위 대비) 재사용

import numpy as np
import pandas as pd

d = A.d
P = A.PREREG


def ev(g, mask, label=""):
    m = mask.fillna(False)
    k, r = g[m], g[~m]
    if len(k) < 15:
        return None
    return dict(label=label, n=len(k), share=len(k) / len(g), roi=k.roi.mean(), ex=k.ex.mean(),
                win=(k.roi > 0).mean(), t=A.clu_t(k), rest_roi=r.roi.mean() if len(r) else np.nan,
                rest_ex=r.ex.mean() if len(r) else np.nan,
                days=k.day.nunique(), dpos=int((k.groupby("day").ex.mean() > 0).sum()))


def show(rows, title):
    print(f"\n## {title}")
    print(f"{'조건':44s} {'비중':>5s} {'n':>5s} {'ROI':>7s} {'ex':>7s} {'승률':>5s} {'t':>5s} | {'막힌쪽ROI':>9s} {'막힌쪽ex':>8s} 날")
    for r in rows:
        if not r:
            continue
        print(f"{r['label'][:44]:44s} {r['share']:5.0%} {r['n']:5d} {r['roi']:+7.2f} {r['ex']:+7.2f} "
              f"{r['win']:5.0%} {r['t'] if r['t']==r['t'] else 0:+5.1f} | {r['rest_roi']:+9.2f} {r['rest_ex']:+8.2f} {r['dpos']}/{r['days']}")


# ─────────────────────── ① 상승 초입 LONG 단독 ───────────────────────
g = d[d.rule == "surge_start_346"]
disc, hold = g[g.opened_at < P], g[g.opened_at >= P]
print(f"# 상승 초입 LONG (surge_start_346) — 전체 {len(g)}건 (발견 {len(disc)} · 검증 {len(hold)})")
print(f"  전체 평균 ROI {g.roi.mean():+.2f} · 무작위 대비 {g.ex.mean():+.2f} · 승률 {(g.roi>0).mean():.0%}")

def buckets(g, col, edges, fmt="{:.0f}"):
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (g[col] >= lo) & (g[col] < hi)
        out.append(ev(g, m, f"{col} {fmt.format(lo)}~{fmt.format(hi)}"))
    return out

for period, gg in (("발견", disc), ("검증", hold)):
    show(buckets(gg, "chg24", [-100, -5, 0, 5, 10, 20, 40, 1000]), f"① 24시간 변동 구간 · {period}")
    show(buckets(gg, "h1_from_hi", [-100, -10, -5, -3, -1.5, 0.1], "{:.1f}"), f"② 1시간(16봉) 고점 대비 · {period}")

# 미리 정한 가설 (급등 뒤 되돌림)
H = {
    "A 24h≥10 & 1H되돌림≤−5": lambda x: (x.chg24 >= 10) & (x.h1_from_hi <= -5),
    "B 24h≥10 & 1H되돌림≤−3": lambda x: (x.chg24 >= 10) & (x.h1_from_hi <= -3),
    "C 24h≥20 & 1H되돌림≤−5": lambda x: (x.chg24 >= 20) & (x.h1_from_hi <= -5),
    "D 24h≥5  & 1H되돌림≤−5": lambda x: (x.chg24 >= 5) & (x.h1_from_hi <= -5),
    "E 1H되돌림≤−5 (변동 무관)": lambda x: x.h1_from_hi <= -5,
    "F 지금 게이트(24h≤−5 or 5분≤−4)": lambda x: (x.chg24 <= -5) | (x.m5_from_hi <= -4),
    "G 게이트 or A": lambda x: (x.chg24 <= -5) | (x.m5_from_hi <= -4) | ((x.chg24 >= 10) & (x.h1_from_hi <= -5)),
    "H 게이트 or B": lambda x: (x.chg24 <= -5) | (x.m5_from_hi <= -4) | ((x.chg24 >= 10) & (x.h1_from_hi <= -3)),
}
for period, gg in (("발견", disc), ("검증", hold)):
    show([ev(gg, f(gg), n) for n, f in H.items()], f"③ 가설 · {period}")

# ─────────────────────── ② LONG 전체(규칙 합산)에서 같은 가설 ───────────────────────
L = d[(d.side == "LONG") & ~d.rule.str.startswith("baseline_")]
bL = d[d.rule == "baseline_LONG"]
for period, gg in (("발견", L[L.opened_at < P]), ("검증", L[L.opened_at >= P])):
    show([ev(gg, f(gg), n) for n, f in H.items()], f"④ LONG 규칙 합산 · {period}")
show([ev(bL[bL.opened_at >= P], f(bL[bL.opened_at >= P]), n) for n, f in H.items()], "⑤ 무작위 LONG · 검증")

# ─────────────────────── ③ 규칙별로 게이트 2안(G) 효과 ───────────────────────
print("\n## ⑥ 규칙별 게이트 비교 (검증 기간 · 통과 ROI/ex)")
print(f"{'규칙':22s} {'전체ROI':>8s} | {'지금(F)':>18s} | {'2안(G)':>18s}")
for rule, gr in d[d.side == "LONG"].groupby("rule"):
    h = gr[gr.opened_at >= P]
    if len(h) < 30:
        continue
    f1, f2 = ev(h, H["F 지금 게이트(24h≤−5 or 5분≤−4)"](h)), ev(h, H["G 게이트 or A"](h))
    s = lambda r: f"{r['share']:3.0%} {r['roi']:+6.2f}/{r['ex']:+6.2f}" if r else "     표본부족    "
    print(f"{rule:22s} {h.roi.mean():+8.2f} | {s(f1):>18s} | {s(f2):>18s}")
