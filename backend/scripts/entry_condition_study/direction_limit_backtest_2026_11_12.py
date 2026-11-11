"""개편 v1 지정가 진입 백테스트 (2026-11-12 사장님 「다음으로 진행해줘」 · D-118) — 로컬, 공개 15분봉.

질문: 진입을 지정가(메이커 0.02%)로 바꾸면 비용 0.40 → ≈0.24 %p 인데,
  ① 얼마나 체결되나(미체결 = 진입 놓침) ② 체결된 거래가 불리한 쪽으로 쏠리지 않나(역선택).
모형: direction_backtest_2026_11_11.py 와 같은 종목·시각·청산(run_live_like). 방향 = 가설 N(직전 24h 마감 시장가 거래가 나빴던 쪽).
  지정가 = 진입 시점 종가 대비 off% 유리한 가격, valid 봉 안에 그 가격을 **뚫고 지나가야** 체결(같은 값 닿기만은 미체결, 보수적).
  체결 봉 다음 봉부터 청산 계산. 비용: 시장가 0.40 · 지정가 0.24 (진입 0.02 + 청산 0.05 + 슬리피지 0.05, ×레버리지 2).
실행: py -3.14 -X utf8 scripts/entry_condition_study/direction_limit_backtest_2026_11_12.py
"""
from __future__ import annotations

import bisect
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import direction_backtest_2026_11_11 as DB  # noqa: E402
from app.services import paper_trading as PT  # noqa: E402

COST_MKT, COST_LMT = 0.40, 0.24
VARIANTS = [(0.0, 1), (0.0, 4), (0.1, 4), (0.3, 4), (0.3, 16)]     # (off %, 유효 봉 수)
MS_DAY = DB.MS_DAY
H = PT.LIVE_HORIZON


def run():
    mkt = []                                     # (side, entry_ms, close_ms, roi) — 방향 신호용
    lmt = defaultdict(list)                      # var → [(side, day, filled, roi)]
    for k, sym in enumerate(DB.SYMBOLS):
        bars = sorted((b for y, m in DB.MONTHS for b in DB.month_bars(sym, y, m)), key=lambda b: b[0])
        for j in range(len(bars) - 1):
            if (bars[j][0] // 900_000) % DB.STEP != DB.STEP - 1:
                continue
            if j + 1 + 16 + H > len(bars):
                break
            c = bars[j][4]
            day = (bars[j][0] + 900_000) // MS_DAY
            for side in ("LONG", "SHORT"):
                after = bars[j + 1:j + 1 + H]
                r = PT.run_live_like(side, c, after, tp1_pct=PT.TP1_FLAT, variants=())
                eb = int(r.get("exit_bar") if r.get("exit_bar") is not None else H - 1)
                mkt.append((side, bars[j][0] + 900_000, after[min(eb, H - 1)][0] + 900_000, float(r["roi"])))
                for off, valid in VARIANTS:
                    px = c * (1 - off / 100) if side == "LONG" else c * (1 + off / 100)
                    fill = None
                    for i in range(valid):
                        b = bars[j + 1 + i]
                        if (side == "LONG" and b[3] < px) or (side == "SHORT" and b[2] > px):
                            fill = j + 1 + i
                            break
                    if fill is None:
                        lmt[(off, valid)].append((side, day, False, 0.0))
                        continue
                    rr = PT.run_live_like(side, px, bars[fill + 1:fill + 1 + H], tp1_pct=PT.TP1_FLAT, variants=())
                    lmt[(off, valid)].append((side, day, True, float(rr["roi"])))
        print(f"  [{k + 1}/{len(DB.SYMBOLS)}] {sym}")
    return mkt, lmt


def main():
    mkt, lmt = run()
    closed = {"LONG": [], "SHORT": []}
    mday = defaultdict(list)
    for s, e, c, r in mkt:
        closed[s].append((c, r))
        mday[(s, e // MS_DAY)].append(r)
    for s in closed:
        closed[s].sort()
    keys = {s: [c for c, _ in closed[s]] for s in closed}
    sig = {}
    for d in sorted({d for _, d in mday}):
        t0 = d * MS_DAY
        m = {}
        for s in closed:
            seg = closed[s][bisect.bisect_left(keys[s], t0 - MS_DAY):bisect.bisect_left(keys[s], t0)]
            if len(seg) >= 20:
                m[s] = sum(r for _, r in seg) / len(seg)
        if len(m) == 2:
            sig[d] = "SHORT" if m["LONG"] > m["SHORT"] else "LONG"

    def day_stats(vals_by_day):
        dm = [sum(v) / len(v) for v in vals_by_day.values() if v]
        mu = sum(dm) / len(dm)
        lo = mu - 1.645 * st.stdev(dm) / math.sqrt(len(dm))
        return mu, lo, sum(1 for x in dm if x > 0), len(dm)

    base = defaultdict(list)
    for (s, d), v in mday.items():
        if sig.get(d) == s:
            base[d] += [r - COST_MKT for r in v]
    mu, lo, pos, n = day_stats(base)
    allm = [x for v in base.values() for x in v]
    print(f"\n[시장가] 방향 N: 건당 {sum(allm) / len(allm):+.2f} · 날평균 {mu:+.2f} 90%하한 {lo:+.2f} · +일 {pos}/{n}")
    for (off, valid), rows in lmt.items():
        per_day = defaultdict(list)          # 기회당(미체결 = 0)
        filled, fill_roi_gross, n_opp = 0, [], 0
        mkt_same = []
        for s, d, ok, r in rows:
            if sig.get(d) != s:
                continue
            n_opp += 1
            if ok:
                filled += 1
                fill_roi_gross.append(r)
                per_day[d].append(r - COST_LMT)
            else:
                per_day[d].append(0.0)
        mu, lo, pos, n = day_stats(per_day)
        fr = filled / max(n_opp, 1)
        per_fill = sum(fill_roi_gross) / max(len(fill_roi_gross), 1) - COST_LMT
        print(f"[지정가 {off:.1f}% · {valid}봉] 체결률 {fr:.0%} · 체결 건당 {per_fill:+.2f} · 기회당(미체결 0) 날평균 {mu:+.2f} 90%하한 {lo:+.2f} · +일 {pos}/{n}")
    # 역선택: 시장가 거래 중 '지정가 0.3%·4봉이 체결됐을 기회' vs 아닌 기회의 시장가 수익
    print("\n(역선택 확인은 체결 건당 값을 시장가 건당 값과 비교: 체결 건당 − 시장가 건당 이 비용 차 0.16 보다 작으면 역선택이 비용 이득을 먹는다)")


if __name__ == "__main__":
    main()
