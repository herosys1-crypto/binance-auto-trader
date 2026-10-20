"""3단계 1,400 진입 뒤 손절선을 「총 증거금 대비 −10~−50%」로 둘 때 (2026-10-21 사장님) — 읽기 전용 · 로컬.

사장님: 「3단계 1400까지 진입하고 -10% 이상 손실이면 손절을 해야하는 건지 이런경우 얼마나 더 올라가는지 확인해줘
        만약에 손절하고 바로 하락하는 경우면 -50%까지는 지켜봐야 하는거 아닌가?」
마틴게일 = 100 → +20% 300 → +20% 1000 (1단계가 대비 +44%) · 레버 1 · 평단 1.3404 · 수량 1,044.44/1단계가
총 증거금 대비 손실 L% ↔ 손절 가격(1단계가 대비) = 1.3404 + L × 1400 / 1044.44
본다: ① 3단계까지 간 건의 「3단계 뒤 최고가」 분포 ② 손절선별 결과 ③ 손절 뒤 10일 안에 익절가까지 내려온 비율(= 손절하고 바로 하락)
신호·익절·수수료 = martingale_20_20 그대로.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
_m = importlib.util.spec_from_file_location("m20", HERE / "martingale_20_20_2026_10_21.py")
M20 = importlib.util.module_from_spec(_m)
_m.loader.exec_module(M20)
MG = M20.MG
AVG, QTY = 1400 / (100 + 300 / 1.2 + 1000 / 1.44), 100 + 300 / 1.2 + 1000 / 1.44


def stop_pct(loss):
    return (AVG + loss * 1400 / QTY - 1) * 100


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
    # ① 3단계까지 간 건: 3단계 뒤 최고가(1단계가 대비) — 10일 창, 익절 전까지
    ups, after = [], []
    for e in evs:
        h, lw, c, n = e["h"], e["lw"], e["c"], e["n"]
        p0 = c[n]
        t3 = next((j for j in range(n + 1, min(len(c), n + 11)) if h[j] >= p0 * 1.44), None)
        if t3 is None:
            continue
        # 3단계 전에 익절됐는지(2단계 평단 기준) — 익절 전 3단계 진입만
        qty2 = 100 / p0 + 300 / (p0 * 1.2)
        tp2 = min(e["half"], 400 / qty2 * 0.995)
        if any(lw[j] <= tp2 for j in range(n + 1, t3)):
            continue
        tp3 = min(e["half"], p0 * AVG * 0.995)
        peak, hit_tp = p0 * 1.44, None
        for j in range(t3, min(len(c), n + 11)):
            peak = max(peak, h[j])
            if j > t3 and lw[j] <= tp3:
                hit_tp = j
                break
        ups.append(peak / p0 - 1)
        after.append((e, t3, peak / p0 - 1, hit_tp is not None))
    ups.sort()
    n3 = len(ups)
    print(f"# 3단계 1,400 진입 뒤 — 3단계까지 간 건 {n3} / 신호 {len(evs)} · 레버 1 · 평단 = 1단계가 × {AVG:.4f}")
    print("\n## ① 3단계 진입(1단계 대비 +44%) 뒤 익절 전까지 최고가 (10일 안)")
    print("| 최고가 (1단계 대비) | 그때 총 증거금 대비 손실 | 건수 | 누적 비율 |\n|---|---|---|---|")
    for lim in (0.47, 0.55, 0.61, 0.74, 0.88, 1.01, 1.5, 9):
        k = sum(1 for u in ups if u < lim)
        loss = (1 + min(lim, 3) - AVG) * QTY / 1400 * 100
        print(f"| +{lim * 100:.0f}% 미만 | −{max(0, loss):.0f}% 까지 | {k} | {k / n3:.0%} |" if lim < 9 else f"| 전부 | | {n3} | 100% |")
    print(f"- 3단계 뒤 결국 익절(급등분 절반 반납·평단 아래) {sum(a[3] for a in after)} / {n3} ({sum(a[3] for a in after) / n3:.0%})")
    # ② 손절선별
    print("\n## ② 손절선 = 총 증거금(1,400) 대비 손실 % — 전체 신호 470 에 적용")
    print("| 손절선 | 손절 가격(1단계 대비) | 합 USDT | 승률 | 앞 → 뒤 | 손절 / 청산 | 손절 1건 | 최대 낙폭 | 손절 뒤 10일 안 익절가 도달(= 손절하고 바로 하락) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for loss in (0.10, 0.20, 0.30, 0.40, 0.50, 0.60):
        s = stop_pct(loss)
        rs = M20.capped(evs, 20, 44, s, 10, None)
        p = [r["pnl"] for r in rs]
        ds = sorted({r["d"] for r in rs})
        mid = ds[len(ds) // 2]
        a = sum(r["pnl"] for r in rs if r["d"] < mid)
        b = sum(r["pnl"] for r in rs if r["d"] >= mid)
        cum = pk = mdd = 0.0
        for r in sorted(rs, key=lambda r: r["d"]):
            cum += r["pnl"]
            pk = max(pk, cum)
            mdd = min(mdd, cum - pk)
        # 손절 뒤 바로 하락: 손절된 건 중 손절 다음 날부터 10일 안에 익절가(평단 −0.5% 또는 급등분 절반)에 닿은 비율
        regret = tot = 0
        for e in evs:
            h, lw, c, n = e["h"], e["lw"], e["c"], e["n"]
            r = M20.run(e, 20, 44, s, 10)
            if not r or r["why"] != "손절":
                continue
            tot += 1
            j0 = n + r["end"]
            tp3 = min(e["half"], c[n] * AVG * 0.995)
            if any(lw[j] <= tp3 for j in range(j0 + 1, min(len(c), j0 + 11))):
                regret += 1
        stops = sum(r["why"] == "손절" for r in rs)
        liq = sum(r["why"] == "청산" for r in rs)
        print(f"| −{loss:.0%} (−{loss * 1400:.0f} USDT) | +{s:.0f}% | {sum(p):+,.0f} | {sum(x > 0 for x in p) / len(p):.0%} | {a:+,.0f} → {b:+,.0f} | "
              f"{stops} / {liq} | −{loss * 1400 + 2:.0f} | {mdd:+,.0f} | {regret}/{tot} ({(regret / tot) if tot else 0:.0%}) |")


if __name__ == "__main__":
    main()
