"""마틴게일 2단계 500 → +90% 1500 · 손절 = 다 들어간 뒤 총 증거금 −30% / −40% (2026-10-21 사장님 「1단계 500 2단계를 +90%에 1500 손절 -30 -40%으로 검증해줘」) — 읽기 전용 · 로컬.
신호·익절·수수료·청산 모델 = martingale_200_600_1600 의 run · 레버 1 · 10일 / 20일. 비교 = 지난안 · 4단계안.
⚠️ 레버 1 에서 1단계 500 만 있을 때 청산가 ≈ 1단계가 +99% → 2단계(+90%) 와 9%p 차이 — 하루에 +90% 를 건너뛰어 +99% 를 넘으면 2단계 전에 청산.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
_a = importlib.util.spec_from_file_location("m26", HERE / "martingale_200_600_1600_2026_10_21.py")
M26 = importlib.util.module_from_spec(_a)
_a.loader.exec_module(M26)
_b = importlib.util.spec_from_file_location("m4", HERE / "martingale_4stage_2026_10_21.py")
M4 = importlib.util.module_from_spec(_b)
_b.loader.exec_module(M4)
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
    cases = [("500 → +90% 1500 · 손절 −30%", (500, 1500), (1.0, 1.9), 0.30),
             ("500 → +90% 1500 · 손절 −40%", (500, 1500), (1.0, 1.9), 0.40),
             ("비교: 4단계 10/300/600/2000 · +15%씩 · −30%", (10, 300, 600, 2000), (1.0, 1.15, 1.3225, 1.520875), 0.30),
             ("비교: 지난안 100/300/1000 · +20%씩 · −40%", (100, 300, 1000), (1.0, 1.2, 1.44), 0.40)]
    print(f"# 2단계 500 → +90% 1500 — 세력 펌프·덤프 SHORT 신호 {len(evs)} · 레버 1 · 수수료 포함 · 펀딩·미끄러짐 미반영\n")
    print("| 안 | 총 증거금 | 마지막 단계 진입 때 손실(총 대비) | 평단 | 손절 가격 | 손절 1건 | 청산가(다 들어간 뒤) |\n|---|---|---|---|---|---|---|")
    for nm, m, u, loss in cases:
        p_ = M26.plan(m, u, loss)
        print(f"| {nm} | {p_['tot']:,} | −{p_['loss_at3']:.0f} ({p_['loss_at3'] / p_['tot']:.1%}) | {(p_['avg'] - 1) * 100:+.0f}% | "
              f"+{(p_['stop'] - 1) * 100:.0f}% | −{loss * p_['tot']:.0f} | +{(p_['liq'] - 1) * 100:.0f}% |")
    q1 = 500
    print(f"- 1단계 500 만 있을 때 청산가 ≈ +{((500 - 500 * M26.MM) / q1) * 100:.0f}% (2단계 +90% 와 차이 9%p)")
    # 2단계 직전 위험: 하루 안에 +90% 를 처음 넘은 날 고가가 +99% 이상인 경우
    gap = 0
    for e in evs:
        h, c, n = e["h"], e["c"], e["n"]
        j = next((j for j in range(n + 1, min(len(c), n + 21)) if h[j] >= c[n] * 1.9), None)
        if j is not None and h[j] >= c[n] * 1.99:
            gap += 1
    print(f"- 2단계(+90%)를 처음 넘은 날 고가가 +99% 이상까지 간 경우 = {gap}건 (일봉 안 순서상 2단계가 먼저 체결된다고 가정 — 실제로는 미끄러지면 청산 위험)\n")
    hdr = "| 안 | 거래 | 합 USDT | 승률 | 앞 → 뒤 | 단계 분포 | 손절 / 청산 | 최악 1건 | 최대 낙폭 | 손절 뒤 바로 하락 | 연도별 |\n|---|---|---|---|---|---|---|---|---|---|---|"
    for hold in (10, 20):
        for grp, keep in (("전체", lambda e: True), ("🐋 소형·큰손", lambda e: e["whale"])):
            g = [e for e in evs if keep(e)]
            print(f"\n## 보유 {hold}일 · {grp} ({len(g)})\n" + hdr)
            for nm, m, u, loss in cases:
                M4.HOLD = hold
                _t(nm, g, m, u, loss, hold)


def _t(name, evs, margins, mults, loss, hold):
    from collections import defaultdict
    pl = M26.plan(margins, mults, loss)
    out, regret, stops = [], 0, 0
    for e in sorted(evs, key=lambda e: e["d"]):
        r = M26.run(e, margins, mults, pl["stop"], hold)
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
    yr = defaultdict(float)
    for r in out:
        st[r["stages"]] += 1
        yr[r["d"][:4]] += r["pnl"]
    liq = sum(r["why"] == "청산" for r in out)
    print(f"| {name} | {len(out)} | {sum(p):+,.0f} | {sum(x > 0 for x in p) / len(p):.0%} | {a:+,.0f} → {b:+,.0f} | "
          + "/".join(str(st[k]) for k in range(1, len(margins) + 1)) + f" | {stops} / {liq} | {min(p):+,.0f} | {mdd:+,.0f} | {regret}/{stops} | "
          + " ".join(f"{y}:{v:+,.0f}" for y, v in sorted(yr.items())) + " |")


if __name__ == "__main__":
    main()
