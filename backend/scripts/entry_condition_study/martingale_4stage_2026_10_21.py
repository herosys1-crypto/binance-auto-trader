"""① 1단계 승률 ② 4단계 마틴게일 10 → 300 → 600 → 2000 (2026-10-21 사장님) — 읽기 전용 · 로컬.

사장님: 「1단계에서 승률이 얼마가 되는지? 1단계는 그냥 10usdt로 하고 2단계 300 3단계 600 4단계 2000은 어떤가?」
① 지난안(100 → +20% 300 → +20% 1000 · 손절 −40%)에서 단계별로 끝난 거래의 결과(익절·시간·손절) · 1단계만 단독(손절 +25%/+44%/없음)일 때 승률
② 10 / 300 / 600 / 2000 (합 2,910) · 간격(사장님 숫자 없음 → 지난안 +20% 이어서를 기본, ±5%p 비교) · 손절 = 다 들어간 뒤 총 증거금 −30% / −40%
신호·익절·수수료·청산 = martingale_200_600_1600 의 run 그대로 (단계 수만 늘림). 레버 1 · 10일.
"""
from __future__ import annotations

import importlib.util
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
_m = importlib.util.spec_from_file_location("m26", HERE / "martingale_200_600_1600_2026_10_21.py")
M26 = importlib.util.module_from_spec(_m)
_m.loader.exec_module(M26)
MG = M26.MG


def main():
    info = MG.D3.coin_info()
    evs = []
    for p in sorted(MG.DBB.CACHE.glob("*_1d.json")):
        ci = info.get(MG.D3.base_of(p.name[:-8]), {})
        whale = (ci.get("mcap") or 9e99) < 2e8 and (ci.get("float") or 9) < 0.6
        try:
            evs += MG.events(json.loads(p.read_text()), whale)
        except Exception:  # noqa: BLE001
            pass
    # ① 지난안 단계별
    mg, mu = (100, 300, 1000), (1.0, 1.2, 1.44)
    pl = M26.plan(mg, mu, 0.40)
    rs = [r for r in (M26.run(e, mg, mu, pl["stop"], 10) for e in evs) if r]
    print(f"# ① 1단계 승률 — 지난안 100 → +20% 300 → +20% 1000 · 손절 −40% · 신호 {len(rs)}\n")
    print("| 어디까지 들어갔나 | 거래 | 이긴 비율 | 익절 / 시간 정리 / 손절 | 합 USDT | 건당 |\n|---|---|---|---|---|---|")
    for k in (1, 2, 3):
        g = [r for r in rs if r["stages"] == k]
        if g:
            w = defaultdict(int)
            for r in g:
                w[r["why"]] += 1
            print(f"| {k}단계까지 | {len(g)} ({len(g) / len(rs):.0%}) | {sum(r['pnl'] > 0 for r in g) / len(g):.0%} | {w['익절']} / {w['시간']} / {w['손절']} | "
                  f"{sum(r['pnl'] for r in g):+,.0f} | {sum(r['pnl'] for r in g) / len(g):+.1f} |")
    print("\n1단계 100 만 단독(추가 없음):")
    print("| 손절 | 거래 | 이긴 비율 | 합 USDT | 앞 → 뒤 |\n|---|---|---|---|---|")
    for s in (1.25, 1.44, 1.73, 99):
        g = [r for r in (M26.run(e, (100,), (1.0,), s, 10) for e in evs) if r]
        ds = sorted({r["d"] for r in g})
        mid = ds[len(ds) // 2]
        print(f"| {'+' + format((s - 1) * 100, '.0f') + '%' if s < 99 else '없음(청산까지)'} | {len(g)} | {sum(r['pnl'] > 0 for r in g) / len(g):.0%} | "
              f"{sum(r['pnl'] for r in g):+,.0f} | {sum(r['pnl'] for r in g if r['d'] < mid):+,.0f} → {sum(r['pnl'] for r in g if r['d'] >= mid):+,.0f} |")
    # ② 4단계
    print("\n# ② 4단계 10 → 300 → 600 → 2000 (합 2,910) · 레버 1 · 10일\n")
    print("| 안 | 4단계 진입 때 손실(총 대비) | 평단 | 손절 가격 | 손절 1건 | 청산가 |\n|---|---|---|---|---|---|")
    cases = []
    for gap in (15, 20, 25):
        g1 = 1 + gap / 100
        mu4 = (1.0, g1, g1 ** 2, g1 ** 3)
        for loss in (0.30, 0.40):
            cases.append((f"이어서 +{gap}% (+{gap}/+{(g1 ** 2 - 1) * 100:.0f}/+{(g1 ** 3 - 1) * 100:.0f}%) · 손절 −{loss:.0%}", (10, 300, 600, 2000), mu4, loss))
    cases.append(("비교: 지난안 100/300/1000 · +20% 이어서 · −40%", (100, 300, 1000), (1.0, 1.2, 1.44), 0.40))
    for nm, m4, u4, loss in cases:
        p_ = M26.plan(m4, u4, loss)
        print(f"| {nm} | −{p_['loss_at3']:.0f} ({p_['loss_at3'] / p_['tot']:.1%}) | {(p_['avg'] - 1) * 100:+.0f}% | +{(p_['stop'] - 1) * 100:.0f}% | "
              f"−{loss * p_['tot']:.0f} | +{(p_['liq'] - 1) * 100:.0f}% |")
    hdr = ("| 안 | 거래 | 합 USDT | 승률 | 앞 → 뒤 | 1/2/3단계 | 손절 / 청산 | 최악 1건 | 최대 낙폭 | 손절 뒤 바로 하락 | 연도별 |\n"
           "|---|---|---|---|---|---|---|---|---|---|---|")
    for grp, keep in (("전체", lambda e: True), ("🐋 소형·큰손", lambda e: e["whale"])):
        g = [e for e in evs if keep(e)]
        print(f"\n## {grp} ({len(g)})\n" + hdr.replace("1/2/3단계", "단계 분포(1/2/3/4)"))
        for nm, m4, u4, loss in cases:
            _table4(nm, g, m4, u4, loss)


def _table4(name, evs, margins, mults, loss):
    pl = M26.plan(margins, mults, loss)
    out, regret, stops = [], 0, 0
    for e in sorted(evs, key=lambda e: e["d"]):
        r = M26.run(e, margins, mults, pl["stop"], 10)
        if r is None:
            continue
        out.append(r)
        if r["why"] == "손절":
            stops += 1
            lw, c, n = e["lw"], e["c"], e["n"]
            tp = min(e["half"], c[n] * pl["avg"] * 0.995)
            if any(lw[j] <= tp for j in range(r["j_end"] + 1, min(len(c), r["j_end"] + 11))):
                regret += 1
    p = [r["pnl"] for r in out]
    ds = sorted({r["d"] for r in out})
    mid = ds[len(ds) // 2]
    a = sum(r["pnl"] for r in out if r["d"] < mid)
    b = sum(r["pnl"] for r in out if r["d"] >= mid)
    cum = pk = mdd = 0.0
    for r in sorted(out, key=lambda r: r["d"]):
        cum += r["pnl"]
        pk = max(pk, cum)
        mdd = min(mdd, cum - pk)
    st = defaultdict(int)
    for r in out:
        st[r["stages"]] += 1
    yr = defaultdict(float)
    for r in out:
        yr[r["d"][:4]] += r["pnl"]
    liq = sum(r["why"] == "청산" for r in out)
    dist = "/".join(str(st[k]) for k in range(1, len(margins) + 1))
    print(f"| {name} | {len(out)} | {sum(p):+,.0f} | {sum(x > 0 for x in p) / len(p):.0%} | {a:+,.0f} → {b:+,.0f} | {dist} | {stops} / {liq} | "
          f"{min(p):+,.0f} | {mdd:+,.0f} | {regret}/{stops} | " + " ".join(f"{y}:{v:+,.0f}" for y, v in sorted(yr.items())) + " |")


if __name__ == "__main__":
    main()
