"""Fix 445 — 「통합 이평 전략」(사장님 첨부 integrated_moving_average_strategy.md) vs 기존 3중 이평(Fix 432) 비교 백테스트.

캐시(cache_wave_trima, 코인 상위 30 · 1h/4h 360일)를 그대로 쓴다 — 거래소 요청 없음. LONG 만(통합판은 LONG 전용).
변형:
  기존      = triple_ma.signal(SMA200 10봉 기울기) · 손절 스윙 로우(≤8%) · 청산 종가 < EMA9
  +1봉기울기 = SMA200 > 직전 봉 SMA200 (통합판 슈도코드)
  +횡보차단  = |SMA20 − 5봉 전 SMA20| / SMA20 ≥ f% (통합판 「SMA20 기울기가 평평하면 무시」, f 는 0.3 · 0.6 · 1.0 비교)
  +통합청산  = 손절 3~5% 로 자름 · 종가 < EMA9 에 절반 · 종가 < SMA20 에 나머지 (통합판 2.3)
수수료 왕복 0.08% 뺌 · 겹침 없음 · 생존 편향(지금 상위 종목).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.services import triple_ma as TM  # noqa: E402

CACHE = Path(__file__).resolve().parent / "cache_wave_trima"
FEE = 0.08


def load(iv):
    out = {}
    for fp in sorted(CACHE.glob(f"*_{iv}_360.json")):
        kl = json.loads(fp.read_text())
        if len(kl) > 300:
            out[fp.name.split("_")[0]] = kl
    return out


def run(kl, *, slope, flat_pct, exit_mode):
    h = [float(b[2]) for b in kl]
    lo = [float(b[3]) for b in kl]
    c = [float(b[4]) for b in kl]
    ind = TM.indicators(c)
    e9, s20 = ind["e9"], ind["s20"]
    p = TM.params_from(lambda k: {"trima_slope_bars": str(slope)}.get(k, TM.SETTINGS[k][0]))
    res, j, n = [], TM.min_bars(p), len(c)
    while j < n - 1:
        ok, d = TM.signal(h, lo, c, j, "LONG", p, ind)
        if ok and flat_pct > 0:
            ok = s20[j - 5] is not None and abs(s20[j] - s20[j - 5]) / s20[j] * 100 >= flat_pct
        if not ok:
            j += 1
            continue
        e = c[j]
        risk = (e - d["stop"]) / e * 100
        if exit_mode == "integrated":
            risk = min(max(risk, 3.0), 5.0)
        stop = e * (1 - risk / 100)
        half_done, realized, k_end = False, 0.0, None
        for k in range(j + 1, min(n, j + 201)):
            if lo[k] <= stop:
                realized += (0.5 if half_done else 1.0) * -risk
                k_end = k
                break
            if exit_mode == "classic":
                if c[k] < e9[k]:
                    realized = (c[k] - e) / e * 100
                    k_end = k
                    break
            else:
                if not half_done and c[k] < e9[k]:
                    realized += 0.5 * (c[k] - e) / e * 100
                    half_done = True
                if c[k] < s20[k]:
                    realized += (0.5 if half_done else 1.0) * (c[k] - e) / e * 100
                    k_end = k
                    break
        if k_end is None:
            k_end = min(n - 1, j + 200)
            realized += (0.5 if half_done else 1.0) * (c[k_end] - e) / e * 100
        res.append((int(kl[j][0]), realized - FEE))
        j = k_end + 1
    return res


def summary(name, rows):
    if not rows:
        print(f"  {name:34s} 0건")
        return
    rows.sort()
    mid = rows[len(rows) // 2][0]
    v = [r[1] for r in rows]
    h1 = [r[1] for r in rows if r[0] < mid]
    h2 = [r[1] for r in rows if r[0] >= mid]
    print(f"  {name:34s} {len(v):5d}건 · 평균 {sum(v)/len(v):+6.2f}% · 승률 {sum(1 for x in v if x > 0)/len(v):4.0%}"
          f" · 앞 {sum(h1)/len(h1):+5.2f} 뒤 {sum(h2)/len(h2):+5.2f} · 합 {sum(v):+7.1f}%")


def main():
    for iv in ("1h", "4h"):
        data = load(iv)
        print(f"\n[{iv}] 코인 {len(data)}종목 · 360일 · LONG · 수수료 {FEE}% 뺌")
        variants = [("기존 3중 이평 (Fix 432)", 10, 0.0, "classic"),
                    ("+1봉 기울기", 1, 0.0, "classic"),
                    ("+횡보차단 0.3%", 10, 0.3, "classic"),
                    ("+횡보차단 0.6%", 10, 0.6, "classic"),
                    ("+횡보차단 1.0%", 10, 1.0, "classic"),
                    ("+통합청산", 10, 0.0, "integrated"),
                    ("통합판 전체 (1봉·횡보0.6·통합청산)", 1, 0.6, "integrated"),
                    ("기존 + 횡보0.6 + 통합청산", 10, 0.6, "integrated")]
        for name, slope, flat, ex in variants:
            rows = []
            for kl in data.values():
                rows += run(kl, slope=slope, flat_pct=flat, exit_mode=ex)
            summary(name, rows)


if __name__ == "__main__":
    main()
