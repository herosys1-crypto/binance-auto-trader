"""마틴게일 100 → +20% 300 → +20% 1000 (2026-10-21 사장님 「100 +20% 300 2단계진입 +20% 3단계진입 1000」) — 읽기 전용 · 로컬.

신호·체결·수수료 = martingale_pump_short_2026_10_21.py 그대로 (세력 펌프·덤프 SHORT, 다음 날 음봉 종가 1단계).
해석 2가지: ① 이어서 +20% = 2단계가 대비 +20% → 1단계가 대비 +44% · ② 1단계가 대비 +20% / +40%
손절(사장님 숫자 없음 → 「Claude가 정함」 여러 개): 1단계가 대비 +60 · +75 · +90 · +120% · 손절 없음(10일 / 20일 뒤 종가 정리)
동시 보유 상한: 없음 / 3건 (날짜 순으로 받고, 열린 건이 상한이면 그 신호는 건너뜀)
"""
from __future__ import annotations

import importlib.util
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
_m = importlib.util.spec_from_file_location("mg", HERE / "martingale_pump_short_2026_10_21.py")
MG = importlib.util.module_from_spec(_m)
_m.loader.exec_module(MG)


MM = 0.01            # 유지 증거금률(Claude가 정함 — 바이낸스 소형 코인 1단계 구간 근처)


def run(ev, a, b, s, hold, lev=1):
    """MG.run 과 같되 손절 없음(s=None) 허용 · 끝난 날 인덱스 반환."""
    h, lw, c, n = ev["h"], ev["lw"], ev["c"], ev["n"]
    p0 = c[n]
    legs = [(p0, MG.STAGES[0])]
    trig = [(p0 * (1 + a / 100), MG.STAGES[1]), (p0 * (1 + b / 100), MG.STAGES[2])]
    stop = p0 * (1 + s / 100) if s else None
    exit_px = why = None
    j_end = None
    for j in range(n + 1, min(len(c), n + 1 + hold)):
        while trig and h[j] >= trig[0][0]:
            legs.append(trig.pop(0))
        qty = sum(m * lev / px for px, m in legs)
        avg = sum(m * lev for _px, m in legs) / qty
        margin = sum(m for _px, m in legs)
        liq = avg + (margin - avg * qty * MM) / qty          # 격리 SHORT 청산가(유지 증거금 MM — 소형 코인은 더 클 수 있음)
        if stop and stop < liq and h[j] >= stop:
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
    worst = 0.0                                   # 보유 중 최대 평가 손실(증거금 대비 %)
    for px, m in legs:
        qty = m * lev / px
        pnl += qty * (px - exit_px)
        fee += (m * lev + qty * exit_px) * MG.FEE
    hi = max(h[n + 1:j_end + 1]) if j_end > n else p0
    for px, m in legs:
        worst += m * lev / px * (px - hi)
    used = sum(m for _px, m in legs)
    return {"pnl": pnl - fee, "stages": len(legs), "why": why, "d": ev["d"], "end": j_end - n, "worst": worst, "used": used}


def capped(evs, a, b, s, hold, cap):
    from datetime import date, timedelta
    out, open_until = [], []
    for e in sorted(evs, key=lambda e: e["d"]):
        d = date.fromisoformat(e["d"])
        open_until = [x for x in open_until if x > d]
        if cap and len(open_until) >= cap:
            continue
        r = run(e, a, b, s, hold)
        if r is None:
            continue
        out.append(r)
        open_until.append(d + timedelta(days=r["end"]))
    return out


def line(name, rs):
    if not rs:
        print(f"| {name} | 0 |")
        return
    p = [r["pnl"] for r in rs]
    ds = sorted({r["d"] for r in rs})
    mid = ds[len(ds) // 2]
    a = sum(r["pnl"] for r in rs if r["d"] < mid)
    b = sum(r["pnl"] for r in rs if r["d"] >= mid)
    st3 = defaultdict(int)
    for r in rs:
        st3[r["stages"]] += 1
    cum = peak = mdd = 0.0
    for r in sorted(rs, key=lambda r: r["d"]):
        cum += r["pnl"]
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    yr = defaultdict(float)
    for r in rs:
        yr[r["d"][:4]] += r["pnl"]
    stops = sum(r["why"] == "손절" for r in rs)
    liqs = sum(r["why"] == "청산" for r in rs)
    print(f"| {name} | {len(rs)} | {sum(p):+,.0f} | {sum(p) / len(p):+.1f} | {sum(x > 0 for x in p) / len(p):.0%} | {a:+,.0f} → {b:+,.0f} | "
          f"{st3[1]}/{st3[2]}/{st3[3]} | {stops} / 청산 {liqs} | {min(p):+,.0f} | {min(r['worst'] for r in rs):+,.0f} | {mdd:+,.0f} | "
          + " ".join(f"{y}:{v:+,.0f}" for y, v in sorted(yr.items())) + " |")


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
    hdr = ("| 손절 · 보유 | 거래 | 합 USDT | 건당 | 이긴 비율 | 앞 → 뒤 절반 합 | 1/2/3단계 | 손절 / 청산 | 최악 1건 | 보유 중 최대 평가손실 | 누적 최대 낙폭 | 연도별 합 |\n"
           "|---|---|---|---|---|---|---|---|---|---|---|---|")
    print(f"# 마틴게일 100 → +20% 300 → +20% 1000 · 레버 1 · 세력 펌프·덤프 SHORT 신호 {len(evs)} · 익절 = 급등분 절반 반납 · 수수료 포함 · 펀딩·미끄러짐 미반영")
    for interp, (a, b) in (("① 이어서 +20% (1단계 대비 +20% · +44%)", (20, 44)), ("② 1단계 대비 +20% · +40%", (20, 40))):
        for cap in (None, 3):
            for grp, keep in (("전체", lambda e: True), ("🐋 소형·큰손", lambda e: e["whale"])):
                g = [e for e in evs if keep(e)]
                print(f"\n## {interp} · 동시 상한 {cap or '없음'} · {grp}")
                print(hdr)
                for s, hold in ((60, 10), (75, 10), (90, 10), (120, 10), (None, 10), (None, 20)):   # 손절 없음 = 청산까지
                    line(f"손절 +{s}% · {hold}일" if s else f"손절 없음 · {hold}일 뒤 종가", capped(g, a, b, s, hold, cap))


if __name__ == "__main__":
    main()
