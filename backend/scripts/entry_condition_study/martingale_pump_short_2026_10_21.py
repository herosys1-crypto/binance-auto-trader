"""세력 펌프·덤프 SHORT 에 100 · 300 · 1000 USDT 3단계 마틴게일 (2026-10-21 사장님 「100 300 1000 이렇게 3단계 마틴게일 진입을 했을때 어떻게 되는지」) — 읽기 전용 · 로컬.

진입 신호(세 조건 함께 재검증의 B1): 하루 +30%↑ · 그날 거래대금 ×10↑ · 60일 최저 대비 +100%↑ 랠리 안 · 다음 날 음봉 → 다음 날 종가 1단계 SHORT
  묶음: 전체 / 🐋(시총 <2억$ · 유통 <60%)
마틴게일(증거금 USDT, 사장님 숫자 그대로): 1단계 100 → 가격이 1단계가 대비 +a% 오르면 300 → +b% 면 1000 (합 1,400)
  손절 = 1단계가 대비 +s% (전량) · 익절 = 평단 대비 −tp% 또는 급등분 절반 반납 가격 중 먼저 닿는 쪽(설정) · 최대 보유 H 일 뒤 종가 정리
  일봉 안 순서 모름 → 보수적: 같은 날 추가·손절 둘 다 닿으면 추가 뒤 손절, 익절과 손절 둘 다 닿으면 손절
  수수료 = 명목 × 0.05% × 2 (시장가 가정) · 펀딩 미반영 · 레버 1 / 2 (레버 2 청산 ≈ 평단 +50% 근처 — 손절 s 가 그보다 가까운지 표시)
간격 조합(a, b, s)은 「Claude가 정함」 — 여러 개를 나란히 본다.
"""
from __future__ import annotations

import importlib.util
import json
import statistics as st
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

STAGES = (100.0, 300.0, 1000.0)
FEE = 0.0005
GRID = ((10, 20, 30), (10, 25, 40), (15, 30, 45), (20, 40, 60), (25, 50, 75))   # (2단계 +a%, 3단계 +b%, 손절 +s%)
SINGLE = (None, None, 25)                                                       # 비교: 1단계 100 만 · 손절 +25%


def events(kl, whale):
    t0 = [int(k[0]) for k in kl]
    h = [float(k[2]) for k in kl]
    lw = [float(k[3]) for k in kl]
    c = [float(k[4]) for k in kl]
    qv = [float(k[7]) for k in kl]
    out = []
    for t in range(90, len(c) - 2):
        if not (c[t - 1] > 0 and c[t] / c[t - 1] - 1 >= 0.30):
            continue
        w = sorted(qv[t - 20:t])
        med = w[len(w) // 2]
        lo60 = min(lw[max(0, t - 60):t + 1])
        if med <= 0 or qv[t] / med < 10 or lo60 <= 0 or h[t] / lo60 - 1 < 1.0:
            continue
        n = t + 1
        if c[n] >= c[t]:
            continue
        half = c[t - 1] + 0.5 * (c[t] - c[t - 1])
        out.append({"n": n, "half": half, "whale": whale,
                    "d": datetime.fromtimestamp(t0[n] / 1000, timezone.utc).date().isoformat(), "h": h, "lw": lw, "c": c})
    return out


def run(ev, a, b, s, tp_mode, tp_pct, hold, lev):
    h, lw, c, n = ev["h"], ev["lw"], ev["c"], ev["n"]
    p0 = c[n]
    legs = [(p0, STAGES[0])]                                    # (가격, 증거금)
    trig = [] if a is None else [(p0 * (1 + a / 100), STAGES[1]), (p0 * (1 + b / 100), STAGES[2])]
    stop = p0 * (1 + s / 100)
    exit_px, why, j_end = None, None, None
    for j in range(n + 1, min(len(c), n + 1 + hold)):
        while trig and h[j] >= trig[0][0]:                      # 추가 진입(그 가격에 체결 가정)
            legs.append(trig.pop(0))
        if h[j] >= stop:
            exit_px, why, j_end = stop, "손절", j
            break
        notional = sum(m * lev / px for px, m in legs)          # 수량
        avg = sum(m * lev for _px, m in legs) / notional
        tp = avg * (1 - tp_pct / 100) if tp_mode == "avg" else min(ev["half"], avg * 0.995)
        if lw[j] <= tp:
            exit_px, why, j_end = tp, "익절", j
            break
    if exit_px is None:
        j_end = min(len(c) - 1, n + hold)
        if j_end >= len(c) - 1 and n + hold > len(c) - 1:
            return None                                          # 아직 안 끝남
        exit_px, why = c[j_end], "시간"
    pnl = 0.0
    fee = 0.0
    for px, m in legs:
        qty = m * lev / px
        pnl += qty * (px - exit_px)
        fee += (m * lev + qty * exit_px) * FEE
    used = sum(m for _px, m in legs)
    return {"pnl": pnl - fee, "used": used, "stages": len(legs), "why": why, "d": ev["d"]}


def summarize(name, rs):
    rs = [r for r in rs if r]
    if not rs:
        print(f"| {name} | 0 |")
        return
    p = [r["pnl"] for r in rs]
    ds = sorted({r["d"] for r in rs})
    mid = ds[len(ds) // 2]
    a = [r["pnl"] for r in rs if r["d"] < mid]
    b = [r["pnl"] for r in rs if r["d"] >= mid]
    st3 = defaultdict(int)
    for r in rs:
        st3[r["stages"]] += 1
    stops = [r["pnl"] for r in rs if r["why"] == "손절"]
    yr = defaultdict(float)
    for r in rs:
        yr[r["d"][:4]] += r["pnl"]
    # 누적 최대 낙폭(날짜 순)
    cum, peak, mdd = 0.0, 0.0, 0.0
    for r in sorted(rs, key=lambda r: r["d"]):
        cum += r["pnl"]
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    print(f"| {name} | {len(rs)} | {sum(p):+,.0f} | {sum(p) / len(p):+.1f} | {sum(x > 0 for x in p) / len(p):.0%} | "
          f"{sum(a):+,.0f} → {sum(b):+,.0f} | {st3[1]}/{st3[2]}/{st3[3]} | {len(stops)}건 {min(p):+,.0f} | {mdd:+,.0f} | "
          + " ".join(f"{y}:{v:+,.0f}" for y, v in sorted(yr.items())) + " |")


def main():
    info = D3.coin_info()
    evs = []
    for p in sorted(DBB.CACHE.glob("*_1d.json")):
        sym = p.name[:-8]
        ci = info.get(D3.base_of(sym), {})
        whale = (ci.get("mcap") or 9e99) < 2e8 and (ci.get("float") or 9) < 0.6
        try:
            evs += events(json.loads(p.read_text()), whale)
        except Exception:  # noqa: BLE001
            pass
    print(f"# 세력 펌프·덤프 SHORT × 마틴게일 100·300·1000 — 신호 {len(evs)} (🐋 {sum(e['whale'] for e in evs)}) · 일봉 · 수수료 0.05%×2 · 펀딩 미반영")
    hdr = ("| 방식 | 거래 | 합 USDT | 건당 | 이긴 비율 | 앞 → 뒤 절반 합 | 1/2/3단계까지 간 수 | 손절 수 · 최악 1건 | 누적 최대 낙폭 | 연도별 합 |\n"
           "|---|---|---|---|---|---|---|---|---|---|")
    for lev in (1, 2):
        for grp, keep in (("전체", lambda e: True), ("🐋 소형·큰손", lambda e: e["whale"])):
            g = [e for e in evs if keep(e)]
            print(f"\n## 레버 {lev} · {grp} ({len(g)}건) — 익절 = 급등분 절반 반납 가격 · 최대 10일")
            print(hdr)
            summarize(f"비교: 1단계 100 만 · 손절 +{SINGLE[2]}%", [run(e, None, None, SINGLE[2], "half", 0, 10, lev) for e in g])
            for a, b, s in GRID:
                liq = " ⚠️청산 먼저" if lev == 2 and s >= 50 else ""
                summarize(f"100 → +{a}% 300 → +{b}% 1000 · 손절 +{s}%{liq}", [run(e, a, b, s, "half", 0, 10, lev) for e in g])
            print(f"\n### 레버 {lev} · {grp} — 익절 = 평단 −10% · 최대 10일")
            print(hdr)
            for a, b, s in GRID:
                liq = " ⚠️청산 먼저" if lev == 2 and s >= 50 else ""
                summarize(f"100 → +{a}% 300 → +{b}% 1000 · 손절 +{s}%{liq}", [run(e, a, b, s, "avg", 10, 10, lev) for e in g])


if __name__ == "__main__":
    main()
