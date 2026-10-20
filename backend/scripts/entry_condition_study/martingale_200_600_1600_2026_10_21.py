"""마틴게일 200 → +40% 600 → +40% 1600 · 다 들어간 뒤 총 증거금 −30% 손절 (2026-10-21 사장님) — 읽기 전용 · 로컬.

사장님: 「1단계 200  2단계 +40% 600 3단계 +40% 1600  진입후 -30% 손절일 경우를 검증해줘」
해석 ① 이어서 +40% → 3단계 = 1단계가 × 1.4 × 1.4 = +96% · ② 1단계 대비 +40% / +80%
비교 = 지난번 100 → +20% 300 → +20% 1000 · 손절 총 증거금 −40%
손절 가격 = 3단계까지 다 들어간 평단 + 손실 한도 ÷ 수량 (3단계 진입가보다 위 — 그 전에는 손절 없음) · 그 밖(신호·익절·수수료·청산 모델) = martingale_20_20 그대로
보유 10일 / 20일 · 레버 1 · 동시 상한 없음 / 3
"""
from __future__ import annotations

import importlib.util
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
_m = importlib.util.spec_from_file_location("m20", HERE / "martingale_20_20_2026_10_21.py")
M20 = importlib.util.module_from_spec(_m)
_m.loader.exec_module(M20)
MG = M20.MG
MM = M20.MM


def plan(margins, mults, loss):
    qty = sum(m / x for m, x in zip(margins, mults))
    tot = sum(margins)
    avg = tot / qty
    stop = avg + loss * tot / qty
    loss_at3 = sum(m / x * (mults[-1] - x) for m, x in zip(margins[:-1], mults[:-1]))
    liq = avg + (tot - avg * qty * MM) / qty
    return {"avg": avg, "stop": stop, "liq": liq, "loss_at3": loss_at3, "tot": tot}


def run(ev, margins, mults, stop_mult, hold):
    h, lw, c, n = ev["h"], ev["lw"], ev["c"], ev["n"]
    p0 = c[n]
    legs = [(p0 * mults[0], margins[0])]
    trig = [(p0 * x, m) for m, x in zip(margins[1:], mults[1:])]
    stop = p0 * stop_mult
    exit_px = why = None
    j_end = None
    for j in range(n + 1, min(len(c), n + 1 + hold)):
        while trig and h[j] >= trig[0][0]:
            legs.append(trig.pop(0))
        qty = sum(m / px for px, m in legs)
        avg = sum(m for _px, m in legs) / qty
        margin = sum(m for _px, m in legs)
        liq = avg + (margin - avg * qty * MM) / qty
        if not trig and stop < liq and h[j] >= stop:
            exit_px, why, j_end = stop, "손절", j
            break
        if h[j] >= liq:
            exit_px, why, j_end = liq, "청산", j
            break
        tp = min(ev["half"], avg * 0.995)
        if lw[j] <= tp:
            exit_px, why, j_end = tp, "익절", j
            break
    if exit_px is None:
        if n + hold > len(c) - 1:
            return None
        j_end = n + hold
        exit_px, why = c[j_end], "시간"
    pnl = fee = 0.0
    for px, m in legs:
        q = m / px
        pnl += q * (px - exit_px)
        fee += (m + q * exit_px) * MG.FEE
    return {"pnl": pnl - fee, "stages": len(legs), "why": why, "d": ev["d"], "end": j_end - n, "used": sum(m for _p, m in legs),
            "j_end": j_end, "tp3": None}


def table(name, evs, margins, mults, loss, hold, cap=None):
    pl = plan(margins, mults, loss)
    out, open_until = [], []
    regret = stops = 0
    for e in sorted(evs, key=lambda e: e["d"]):
        d = date.fromisoformat(e["d"])
        open_until = [x for x in open_until if x > d]
        if cap and len(open_until) >= cap:
            continue
        r = run(e, margins, mults, pl["stop"], hold)
        if r is None:
            continue
        out.append(r)
        open_until.append(d + timedelta(days=r["end"]))
        if r["why"] == "손절":
            stops += 1
            h, lw, c, n = e["h"], e["lw"], e["c"], e["n"]
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
    liq = sum(r["why"] == "청산" for r in out)
    yr = defaultdict(float)
    for r in out:
        yr[r["d"][:4]] += r["pnl"]
    roi = sum(p) / (pl["tot"] * (cap or 1))
    print(f"| {name} | {len(out)} | {sum(p):+,.0f} | {sum(x > 0 for x in p) / len(p):.0%} | {a:+,.0f} → {b:+,.0f} | {st[1]}/{st[2]}/{st[3]} | "
          f"{stops} / {liq} | {min(p):+,.0f} | {mdd:+,.0f} | {regret}/{stops} | " + " ".join(f"{y}:{v:+,.0f}" for y, v in sorted(yr.items())) + " |")


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
    cases = (
        ("새안 ① 200 → +40% 600 → +40%(+96%) 1600 · 손절 −30%", (200, 600, 1600), (1.0, 1.4, 1.96), 0.30),
        ("새안 ② 200 → +40% 600 → +80% 1600 · 손절 −30%", (200, 600, 1600), (1.0, 1.4, 1.8), 0.30),
        ("지난안 100 → +20% 300 → +20%(+44%) 1000 · 손절 −40%", (100, 300, 1000), (1.0, 1.2, 1.44), 0.40),
    )
    print(f"# 마틴게일 비교 — 세력 펌프·덤프 SHORT 신호 {len(evs)} · 레버 1 · 익절 = 급등분 절반 반납/평단 아래 · 수수료 포함 · 펀딩·미끄러짐 미반영\n")
    print("| 안 | 총 증거금 | 3단계 진입 때 손실(총 대비) | 평단 (1단계 대비) | 손절 가격 | 손절 1건 | 청산가 |\n|---|---|---|---|---|---|---|")
    for nm, mg, mu, loss in cases:
        pl = plan(mg, mu, loss)
        print(f"| {nm} | {pl['tot']:,} | −{pl['loss_at3']:.0f} ({pl['loss_at3'] / pl['tot']:.1%}) | {(pl['avg'] - 1) * 100:+.0f}% | "
              f"+{(pl['stop'] - 1) * 100:.0f}% | −{loss * pl['tot']:.0f} | +{(pl['liq'] - 1) * 100:.0f}% |")
    hdr = ("| 안 | 거래 | 합 USDT | 승률 | 앞 → 뒤 | 1/2/3단계 | 손절 / 청산 | 최악 1건 | 최대 낙폭 | 손절 뒤 바로 하락 | 연도별 |\n"
           "|---|---|---|---|---|---|---|---|---|---|---|")
    for hold in (10, 20):
        for cap in (None, 3):
            for grp, keep in (("전체", lambda e: True), ("🐋 소형·큰손", lambda e: e["whale"])):
                g = [e for e in evs if keep(e)]
                print(f"\n## 보유 {hold}일 · 동시 상한 {cap or '없음'} · {grp} ({len(g)})\n" + hdr)
                for nm, mg, mu, loss in cases:
                    table(nm, g, mg, mu, loss, hold, cap)


if __name__ == "__main__":
    main()
