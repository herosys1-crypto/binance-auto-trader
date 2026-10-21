"""급등 다음 날 15분봉 꺾임 SHORT 연구 (2026-10-22, 일정 2번) — 읽기 전용 · 로컬(공개 API).

배경: 세력 펌프·덤프(하루 +30% · 거래대금 ×10 · 랠리 +100%) 뒤 일봉 종가 SHORT 은 손절 25% 라 R ≈ 0.
→ 다음 날(n) 장중에 「꺾임」을 15분봉으로 잡아 손절을 좁히면?
급등 날 t = 일봉(마감) 조건 · 다음 날 n 의 15분봉 96개(UTC 00:00~24:00)를 받아:
  K1 「급등 종가 이탈」: n 날 15분봉 종가가 처음으로 급등 날 종가(c[t]) 아래 → 그 봉 종가 SHORT · 손절 = 그때까지 n 날 최고가 × 1.01
  K2 「시가 아래 재이탈」: n 날 시가 위로 올라갔다가(고가 > 시가 × 1.03) 15분봉 종가가 시가 아래로 → SHORT · 손절 = n 날 최고가 × 1.01
  K3 「고점 −8% 꺾임」: n 날 최고가에서 15분봉 종가가 −8% 이상 내려옴 → SHORT · 손절 = 최고가 × 1.01
  (한 사건에 규칙마다 첫 신호 1번 · n 날 안에만 진입)
청산: 익절 = 급등분 절반 반납 가격(c[t−1] + (c[t]−c[t−1])/2) · n 날 남은 15분봉 → 그 뒤 일봉(n+1~n+9) · 같은 봉 손절·익절 = 손절 · 10일째 종가 정리
결과 = R(손절폭 기준) · 수수료 0.05%×2 를 R 로 환산해 뺌 · 손절폭 분포 · 레버 1/2 증거금 손실 · 연도·앞뒤 절반 · 🐋(시총<2억$·유통<60%)
비교 = 같은 사건 일봉 종가 SHORT(B1: 다음 날 음봉일 때 n 종가 · 손절 = 두 날 최고 +2% · ≤25%)
⚠️ 지금 상장 종목만 · 펀딩·미끄러짐 미반영 · 15분봉 안 순서는 모름(보수적: 손절 먼저). 숫자 「Claude가 정함」.
사용: python pump_15m_short_2026_10_22.py   (daily_bb_pullback_study 캐시 필요)
"""
from __future__ import annotations

import importlib.util
import json
import statistics as st
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
_a = importlib.util.spec_from_file_location("dbb", HERE / "daily_bb_pullback_study_2026_10_21.py")
DBB = importlib.util.module_from_spec(_a)
_a.loader.exec_module(DBB)
_b = importlib.util.spec_from_file_location("d3", HERE / "daily_three_patterns_2026_10_21.py")
D3 = importlib.util.module_from_spec(_b)
_b.loader.exec_module(D3)
C15 = HERE / "cache_15m_pds"
FEE = 0.001        # 왕복 0.1% (가격 대비)
DAY = 86_400_000


def k15(sym, day_ms):
    C15.mkdir(exist_ok=True)
    p = C15 / f"{sym}_{day_ms}.json"
    if p.exists():
        return json.loads(p.read_text())
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={urllib.parse.quote(sym)}&interval=15m&startTime={day_ms}&endTime={day_ms + DAY - 1}&limit=96"
    with urllib.request.urlopen(url, timeout=30) as f:
        kl = json.loads(f.read())
    p.write_text(json.dumps(kl))
    time.sleep(0.12)
    return kl


def events(sym, kl, whale):
    t0 = [int(k[0]) for k in kl]
    h = [float(k[2]) for k in kl]
    lw = [float(k[3]) for k in kl]
    c = [float(k[4]) for k in kl]
    qv = [float(k[7]) for k in kl]
    out = []
    for t in range(90, len(c) - 11):
        if not (c[t - 1] > 0 and c[t] / c[t - 1] - 1 >= 0.30):
            continue
        w = sorted(qv[t - 20:t])
        med = w[len(w) // 2]
        lo60 = min(lw[max(0, t - 60):t + 1])
        if med <= 0 or qv[t] / med < 10 or lo60 <= 0 or h[t] / lo60 - 1 < 1.0:
            continue
        out.append({"sym": sym, "t": t, "n_ms": t0[t + 1], "half": c[t - 1] + 0.5 * (c[t] - c[t - 1]), "ct": c[t], "ht": h[t],
                    "h": h, "lw": lw, "c": c, "whale": whale, "d": datetime.fromtimestamp(t0[t + 1] / 1000, timezone.utc).date().isoformat()})
    return out


def finish(e, side_entry, stop, j15, bars15):
    """SHORT 진입가 side_entry · 15분봉 j15 다음부터 · 그 뒤 일봉 n+1.. → R (수수료 뺀)."""
    risk = stop - side_entry
    if risk <= 0:
        return None
    tgt = e["half"]
    if tgt >= side_entry:
        return None
    for b in bars15[j15 + 1:]:
        hi, lo = float(b[2]), float(b[3])
        if hi >= stop:
            return -1.0 - FEE * side_entry / risk
        if lo <= tgt:
            return (side_entry - tgt) / risk - FEE * side_entry / risk
    h, lw, c, n = e["h"], e["lw"], e["c"], e["t"] + 1
    for j in range(n + 1, min(len(c), n + 10)):
        if h[j] >= stop:
            return -1.0 - FEE * side_entry / risk
        if lw[j] <= tgt:
            return (side_entry - tgt) / risk - FEE * side_entry / risk
    j = min(len(c) - 1, n + 9)
    return (side_entry - c[j]) / risk - FEE * side_entry / risk


def rules(e, bars):
    """→ {규칙: (R, 손절폭)}"""
    out = {}
    if not bars:
        return out
    o0 = float(bars[0][1])
    hi = 0.0
    seen_up = False
    for j, b in enumerate(bars):
        hi = max(hi, float(b[2]))
        cl = float(b[4])
        if hi > o0 * 1.03:
            seen_up = True
        cands = []
        if "K1" not in out and cl < e["ct"]:
            cands.append("K1")
        if "K2" not in out and seen_up and cl < o0:
            cands.append("K2")
        if "K3" not in out and cl <= hi * 0.92:
            cands.append("K3")
        for k in cands:
            stop = hi * 1.01
            r = finish(e, cl, stop, j, bars)
            if r is not None:
                out[k] = (r, stop / cl - 1)
    # B1 비교: 다음 날 음봉이면 n 종가
    h, c, n = e["h"], e["c"], e["t"] + 1
    if c[n] < c[e["t"]]:
        stop = min(max(h[e["t"]], h[n]) * 1.02, c[n] * 1.25)
        r = finish(e, c[n], stop, len(bars), bars)   # n 날 15분봉 다 지난 뒤 = 일봉 n+1 부터
        if r is not None:
            out["B1"] = (r, stop / c[n] - 1)
    return out


def summarize(name, g):
    if not g:
        print(f"| {name} | 0 |")
        return
    rs = [x[0] for x in g]
    ds = sorted({x[2] for x in g})
    mid = ds[len(ds) // 2]
    a = [x[0] for x in g if x[2] < mid]
    b = [x[0] for x in g if x[2] >= mid]
    yr = defaultdict(list)
    for x in g:
        yr[x[2][:4]].append(x[0])
    sl = [x[1] for x in g]
    print(f"| {name} | {len(g)} | {sum(rs) / len(rs):+.3f} | {sum(r > 0 for r in rs) / len(rs):.0%} | {sum(a) / len(a):+.2f} → {sum(b) / len(b):+.2f} | "
          f"{st.median(sl):.1%} / {max(sl):.0%} | −{st.median(sl) * 100:.0f}% · −{st.median(sl) * 200:.0f}% | "
          + " ".join(f"{y}:{sum(v) / len(v):+.2f}({len(v)})" for y, v in sorted(yr.items())) + " |")


def main():
    info = D3.coin_info()
    evs = []
    for p in sorted(DBB.CACHE.glob("*_1d.json")):
        sym = p.name[:-8]
        ci = info.get(D3.base_of(sym), {})
        whale = (ci.get("mcap") or 9e99) < 2e8 and (ci.get("float") or 9) < 0.6
        try:
            evs += events(sym, json.loads(p.read_text()), whale)
        except Exception:  # noqa: BLE001
            pass
    res = defaultdict(list)
    miss = 0
    for i, e in enumerate(evs):
        try:
            bars = k15(e["sym"], e["n_ms"])
        except Exception:  # noqa: BLE001
            miss += 1
            continue
        for k, (r, slp) in rules(e, bars).items():
            res[k].append((r, slp, e["d"], e["whale"]))
    print(f"# 급등 다음 날 15분봉 꺾임 SHORT — 사건 {len(evs)} (15분봉 못 받음 {miss}) · R 은 수수료 0.1% 왕복 뺌 · 펀딩·미끄러짐 미반영\n")
    print("| 규칙 | n | 평균 R | 이긴 비율 | 앞 → 뒤 | 손절폭 중앙/최대 | 손절 때 증거금(레버1·2) | 연도별 평균 R(n) |\n|---|---|---|---|---|---|---|---|")
    names = {"K1": "K1 급등 종가 이탈", "K2": "K2 시가 위 갔다가 시가 아래", "K3": "K3 그날 고점 −8% 꺾임", "B1": "비교 B1 일봉 종가(다음 날 음봉)"}
    for k in ("K1", "K2", "K3", "B1"):
        summarize(names[k], res[k])
    print("\n🐋 소형·큰손만")
    print("| 규칙 | n | 평균 R | 이긴 비율 | 앞 → 뒤 | 손절폭 중앙/최대 | 손절 때 증거금(레버1·2) | 연도별 평균 R(n) |\n|---|---|---|---|---|---|---|---|")
    for k in ("K1", "K2", "K3", "B1"):
        summarize(names[k], [x for x in res[k] if x[3]])


if __name__ == "__main__":
    main()
