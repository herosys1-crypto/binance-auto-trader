"""세력 그림 종목 롱·숏 전략 후보 시험 (2026-10-21 사장님 「이런 코인에 롱과 숏으로 진입해서 수익은 높이고 손실은 최소하는 전략을 구상해줘」) — 읽기 전용 · 로컬.

데이터 = cache_daily_bb(공개 일봉) + CoinGecko(받은 날 값). 진입은 그날 종가까지 아는 값만 · 그날 종가 진입. R = 손절폭 기준 · 수수료·펀딩 미반영.
후보(숫자 「Claude가 정함」 — 연구 근거에서 바로 옮김):
  L3  ③ 급등(3일 안 +30%) 다음 날 양봉(종가 > 급등 날 종가) → 그날 종가 LONG · 손절 = 그날 저가 −1%(3~15%) · 익절 2R · 10일
  L3b L3 + 다음 날 종가 > 급등 날 고가(돌파 마감)
  S3x ③ 급등 다음 날 음봉 + 🐋(시총<2억$·유통<60%) + 급등 날 거래대금 ×10↑ → SHORT · 손절 = 급등 이후 고가 +2%(≤25%) · 익절 = 급등분 절반 반납 · 10일
  S3y ③ 급등 다음 날 음봉 + 다음 날 종가 < 급등 날 (시가+종가)/2 (급등 몸통 절반 아래) → SHORT · 같은 손절·익절
  S2d ② 급등 랠리(하루 ≥3% 또는 거래대금 ×30↑) 눌림 날이 고점 −25%↓ · 중단 아래 마감 → SHORT · 손절 = 그날 고가 +3%(≤20%) · 익절 = origin+25% · 30일
  L1b ① 정상 추세 눌림(연구 L1) · 시총 10억$↑  (참고 — Fix 475 그대로)
각 후보 × 레버리지 청산 거리: 손절폭 중앙값·최대를 보여 준다(사장님: 청산 위험이면 SHORT 1배).
"""
from __future__ import annotations

import importlib.util
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
_a = importlib.util.spec_from_file_location("dbb", HERE / "daily_bb_pullback_study_2026_10_21.py")
DBB = importlib.util.module_from_spec(_a)
_a.loader.exec_module(DBB)
_b = importlib.util.spec_from_file_location("d3", HERE / "daily_three_patterns_2026_10_21.py")
D3 = importlib.util.module_from_spec(_b)
_b.loader.exec_module(D3)


def scan(sym, kl, ci):
    o = [float(k[1]) for k in kl]
    h = [float(k[2]) for k in kl]
    lw = [float(k[3]) for k in kl]
    c = [float(k[4]) for k in kl]
    qv = [float(k[7]) for k in kl]
    from datetime import datetime, timezone
    day = lambda i: datetime.fromtimestamp(int(kl[i][0]) / 1000, timezone.utc).date().isoformat()   # noqa: E731
    mid, _up, lo = DBB.bands(c)
    whale = (ci.get("mcap") or 9e99) < 2e8 and (ci.get("float") or 9) < 0.6
    big = (ci.get("mcap") or 0) >= 1e9
    out = []
    last3, used = -99, None
    for t in range(DBB.N + 70, len(c) - 1):
        base = min(lw[t - 3:t + 1])
        if base > 0 and c[t] / base - 1 >= 0.30 and t - last3 >= 10:
            last3 = t
            vsp = qv[t] / (st.median(qv[t - 20:t]) or 1)
            n = t + 1
            if c[n] > c[t]:                                              # 다음 날 양봉 → LONG
                e = c[n]
                stop = min(max(lw[n] * 0.99, e * 0.85), e * 0.97)
                for rule, cond in (("L3", True), ("L3b", c[n] > h[t])):
                    if cond:
                        out.append((rule, sym, day(n), D3.sim("LONG", e, stop, e + 2 * (e - stop), h, lw, c, n + 1, 10), 1 - stop / e))
            else:                                                        # 다음 날 음봉 → SHORT 후보
                e = c[n]
                stop = min(max(h[t], h[n]) * 1.02, e * 1.25)
                half = base + 0.5 * (c[t] - base)
                if half < e:
                    r = D3.sim("SHORT", e, stop, half, h, lw, c, n + 1, 10)
                    if whale and vsp >= 10:
                        out.append(("S3x", sym, day(n), r, stop / e - 1))
                    if c[n] < (o[t] + c[t]) / 2:
                        out.append(("S3y", sym, day(n), r, stop / e - 1))
        ok_trend = mid[t] is not None and mid[t - 10] is not None and mid[t] > mid[t - 10]
        if ok_trend and lw[t] <= mid[t]:
            pk = max(range(t - 30, t), key=lambda j: h[j])
            org = min(range(max(0, pk - 60), pk + 1), key=lambda j: lw[j])
            gain = h[pk] / lw[org] - 1 if lw[org] > 0 else 0
            if gain >= 0.30 and used != pk:
                used = pk
                speed = gain / max(1, pk - org)
                pre = sorted(qv[max(0, org - 60):org]) or [0]
                med = pre[len(pre) // 2]
                vsp = max(qv[org:pk + 1]) / med if med > 0 else 0
                dd = 1 - c[t] / h[pk]
                if (speed >= 0.03 or vsp >= 30) and dd >= 0.25 and c[t] < mid[t]:
                    e = c[t]
                    stop = min(h[t] * 1.03, e * 1.20)
                    tgt = lw[org] + 0.25 * (h[pk] - lw[org])
                    if tgt < e:
                        out.append(("S2d", sym, day(t), D3.sim("SHORT", e, stop, tgt, h, lw, c, t + 1, 30), stop / e - 1))
                if speed < 0.01 and big:
                    e = c[t]
                    stop = max(min(lo[t] * 0.97, e * 0.97), e * 0.85)
                    out.append(("L1b", sym, day(t), D3.sim("LONG", e, stop, h[pk], h, lw, c, t + 1, 40), 1 - stop / e))
    return out


def main():
    info = D3.coin_info()
    rows = []
    for p in sorted(DBB.CACHE.glob("*_1d.json")):
        sym = p.name[:-8]
        try:
            rows += scan(sym, json.loads(p.read_text()), info.get(D3.base_of(sym), {}))
        except Exception:  # noqa: BLE001
            pass
    print("# 세력 그림 종목 롱·숏 후보 — 일봉 종가 진입 · R(손절폭 기준) · 수수료·펀딩 미반영 · 지금 상장 종목만")
    print("| 후보 | n (날) | 평균 R | 이긴 비율 | 앞 → 뒤 절반 | 연도별 평균 R(n) | 손절폭 중앙값 / 최대 | 레버 2 손절 때 증거금 |")
    print("|---|---|---|---|---|---|---|---|")
    names = {"L3": "L3 급등 다음 날 양봉 LONG", "L3b": "L3b + 급등 고가 돌파 마감", "S3x": "S3x 급등 다음 날 음봉 + 🐋 + 거래대금×10 SHORT",
             "S3y": "S3y 급등 다음 날 음봉 + 몸통 절반 아래 SHORT", "S2d": "S2d 세력 랠리 깊은 눌림(−25%↓·중단 아래) SHORT",
             "L1b": "L1b 정상 추세 눌림 LONG(대형, Fix 475)"}
    for rule, nm in names.items():
        g = [x for x in rows if x[0] == rule and x[3] is not None]
        if not g:
            print(f"| {nm} | 0 | | | | | | |")
            continue
        rs = [x[3] for x in g]
        ds = sorted({x[2] for x in g})
        midd = ds[len(ds) // 2]
        a = [x[3] for x in g if x[2] < midd]
        b = [x[3] for x in g if x[2] >= midd]
        yr = defaultdict(list)
        for x in g:
            yr[x[2][:4]].append(x[3])
        risk = [x[4] for x in g]
        print(f"| {nm} | {len(g)} ({len(ds)}) | {sum(rs) / len(rs):+.3f} | {sum(r > 0 for r in rs) / len(rs):.0%} | "
              f"{sum(a) / len(a):+.2f} → {sum(b) / len(b):+.2f} | " + " ".join(f"{y}:{sum(v) / len(v):+.2f}({len(v)})" for y, v in sorted(yr.items()))
              + f" | {st.median(risk):.0%} / {max(risk):.0%} | −{st.median(risk) * 200:.0f}% (최대 −{max(risk) * 200:.0f}%) |")


if __name__ == "__main__":
    main()
