"""세력 그림 좁힌 재검증 (2026-10-21 사장님 「랠리 +100%와 당일 +30% 이상 거래대금 10배로 한정해서 검증을 한번더」) — 읽기 전용 · 로컬.

(가) ② 랠리 한정: 상승 추세 눌림(연구 1 정의) 중 랠리 +100%↑ · 랠리 중 최대 거래대금 ≥ 랠리 전 중앙값 ×10
(나) ③ 당일 급등 한정: 그날 종가 ≥ 전날 종가 +30% · 그날 거래대금 ≥ 직전 20일 중앙값 ×10
각각: 결과 비율 · 특징별(다음 날 음봉/양봉, 윗꼬리, 시총·유통) · 롱·숏 후보 R(손절폭 기준, 수수료·펀딩 미반영) · 연도·앞뒤 절반 · 손절폭과 레버 2/1 증거금 손실
+ S4 가상(서버 JSON, 인자로) 중 진입 전날까지 (가)/(나) 문맥인 것
진입은 그날(또는 다음 날) 종가까지 아는 값만. 숫자는 사장님 말씀(+100% · +30% · ×10) 그대로, 나머지 「Claude가 정함」.
사용: python pump_restricted_2026_10_21.py [s4rows.json]
"""
from __future__ import annotations

import bisect
import importlib.util
import json
import statistics as st
import sys
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


def arrays(kl):
    return ([int(k[0]) for k in kl], [float(k[1]) for k in kl], [float(k[2]) for k in kl], [float(k[3]) for k in kl],
            [float(k[4]) for k in kl], [float(k[7]) for k in kl])


def day(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat()


def scan(sym, kl, ci):
    t0, o, h, lw, c, qv = arrays(kl)
    mid, _up, lo = DBB.bands(c)
    whale = (ci.get("mcap") or 9e99) < 2e8 and (ci.get("float") or 9) < 0.6
    A, B = [], []
    used = None
    for t in range(DBB.N + 70, len(c) - 1):
        # (가) ② 랠리 +100%↑ · 거래대금 ×10↑ 눌림
        if (mid[t - 10] is not None and mid[t] > mid[t - 10]
                and sum(1 for j in range(t - 10, t) if c[j] > mid[j]) >= 7 and lw[t] <= mid[t]):
            pk = max(range(t - 30, t), key=lambda j: h[j])
            org = min(range(max(0, pk - 60), pk + 1), key=lambda j: lw[j])
            gain = h[pk] / lw[org] - 1 if lw[org] > 0 else 0
            pre = sorted(qv[max(0, org - 60):org]) or [0]
            med = pre[len(pre) // 2]
            vsp = max(qv[org:pk + 1]) / med if med > 0 else 0
            if gain >= 1.0 and vsp >= 10 and used != pk:
                used = pk
                back = lw[org] + 0.25 * (h[pk] - lw[org])
                res = "횡보"
                for j in range(t + 1, min(len(c), t + 61)):
                    if lw[j] <= back:
                        res = "회귀"
                        break
                    if h[j] > h[pk]:
                        res = "지속"
                        break
                if res == "횡보" and t + 60 >= len(c):
                    res = "진행 중"
                e = c[t]
                dd = 1 - e / h[pk]
                # SHORT A1: 눌림 날 종가 SHORT · 손절 = 그날 고가 +3% (≤20%) · 익절 = back · 30일
                s_stop = min(h[t] * 1.03, e * 1.20)
                rA1 = D3.sim("SHORT", e, s_stop, back, h, lw, c, t + 1, 30) if back < e else None
                # SHORT A2: 눌림 뒤 20일 안 반등이 고점 못 넘고 눌림 날 저가 이탈 마감 → SHORT (연구 S2)
                rA2, d2, risk2 = None, None, None
                reb = h[t]
                for j in range(t + 1, min(len(c) - 1, t + 21)):
                    if h[j] > h[pk]:
                        break
                    reb = max(reb, h[j])
                    if j > t + 1 and c[j] < lw[t]:
                        st_ = min(reb * 1.02, c[j] * 1.20)
                        if back < c[j]:
                            rA2, d2, risk2 = D3.sim("SHORT", c[j], st_, back, h, lw, c, j + 1, 40), day(t0[j]), st_ / c[j] - 1
                        break
                # LONG A3: 눌림 날 종가 LONG · 손절 하단 −3%(3~15%) · 익절 직전 고점 · 40일 (비교용)
                l_stop = max(min(lo[t] * 0.97, e * 0.97), e * 0.85)
                rA3 = D3.sim("LONG", e, l_stop, h[pk], h, lw, c, t + 1, 40)
                A.append({"sym": sym, "d": day(t0[t]), "res": res, "dd": dd, "hold": e >= mid[t], "deep": lw[t] <= lo[t],
                          "whale": whale, "mcap": ci.get("mcap"), "A1": rA1, "A1risk": s_stop / e - 1, "A2": rA2, "A2d": d2, "A2risk": risk2,
                          "A3": rA3, "A3risk": 1 - l_stop / e})
        # (나) ③ 당일 +30%↑ · 그날 거래대금 ×10↑
        if c[t - 1] > 0 and c[t] / c[t - 1] - 1 >= 0.30:
            m20 = sorted(qv[t - 20:t])
            med = m20[len(m20) // 2]
            if med > 0 and qv[t] / med >= 10:
                base = c[t - 1]
                back = base + 0.25 * (c[t] - base)
                lab = "모름"
                for j in range(t + 1, min(len(c), t + 11)):
                    if lw[j] <= back:
                        lab = "바로 하락"
                        break
                    if h[j] > h[t] * 1.05:
                        lab = "더 오름"
                        break
                rng = h[t] - lw[t]
                wick = (h[t] - c[t]) / rng if rng > 0 else 0
                n = t + 1
                half = base + 0.5 * (c[t] - base)
                red = c[n] < c[t]
                rec = {"sym": sym, "d": day(t0[t]), "lab": lab, "red": red, "wick": wick, "whale": whale, "mcap": ci.get("mcap"),
                       "surge": c[t] / base - 1}
                # SHORT B1: 다음 날 음봉 → 그날 종가 SHORT · 손절 = 두 날 최고가 +2%(≤25%) · 익절 = 급등분 절반 반납 · 10일
                if red and half < c[n]:
                    stp = min(max(h[t], h[n]) * 1.02, c[n] * 1.25)
                    rec.update(B1=D3.sim("SHORT", c[n], stp, half, h, lw, c, n + 1, 10), B1risk=stp / c[n] - 1)
                # SHORT B2: 급등 날 윗꼬리 ≥ 40% → 급등 날 종가 SHORT · 같은 손절·익절
                if wick >= 0.4 and half < c[t]:
                    stp = min(h[t] * 1.02, c[t] * 1.25)
                    rec.update(B2=D3.sim("SHORT", c[t], stp, half, h, lw, c, t + 1, 10), B2risk=stp / c[t] - 1)
                # LONG B3: 다음 날 양봉 → 그날 종가 LONG · 손절 = 그날 저가 −1%(3~15%) · 익절 2R · 10일
                if not red:
                    e = c[n]
                    stp = min(max(lw[n] * 0.99, e * 0.85), e * 0.97)
                    rec.update(B3=D3.sim("LONG", e, stp, e + 2 * (e - stp), h, lw, c, n + 1, 10), B3risk=1 - stp / e)
                B.append(rec)
    return A, B


def rtab(title, rows, key, risk_key, date_key="d"):
    g = [x for x in rows if x.get(key) is not None]
    if not g:
        print(f"| {title} | 0 | | | | | |")
        return
    rs = [x[key] for x in g]
    ds = sorted({x[date_key] for x in g})
    m = ds[len(ds) // 2]
    a = [x[key] for x in g if x[date_key] < m]
    b = [x[key] for x in g if x[date_key] >= m]
    yr = defaultdict(list)
    for x in g:
        yr[x[date_key][:4]].append(x[key])
    rk = [x[risk_key] for x in g if x.get(risk_key) is not None]
    print(f"| {title} | {len(g)} ({len(ds)}일) | {sum(rs) / len(rs):+.3f} | {sum(r > 0 for r in rs) / len(rs):.0%} | "
          f"{(sum(a) / len(a)) if a else 0:+.2f} → {(sum(b) / len(b)) if b else 0:+.2f} | "
          + " ".join(f"{y}:{sum(v) / len(v):+.2f}({len(v)})" for y, v in sorted(yr.items()))
          + f" | {st.median(rk):.0%} → 레버2 −{st.median(rk) * 200:.0f}% · 레버1 −{st.median(rk) * 100:.0f}% |")


def main():
    info = D3.coin_info()
    A, B = [], []
    files = sorted(DBB.CACHE.glob("*_1d.json"))
    for p in files:
        sym = p.name[:-8]
        try:
            a, b = scan(sym, json.loads(p.read_text()), info.get(D3.base_of(sym), {}))
            A += a
            B += b
        except Exception:  # noqa: BLE001
            pass
    hdr = "| 규칙 | n (날) | 평균 R | 이긴 비율 | 앞 → 뒤 | 연도별 평균 R(n) | 손절폭 중앙값 → 증거금 손실 |\n|---|---|---|---|---|---|---|"
    print(f"# 세력 그림 좁힌 재검증 — 종목 {len(files)} · 공개 일봉 · 수수료·펀딩 미반영 · 지금 상장 종목만\n")
    # (가)
    done = [x for x in A if x["res"] != "진행 중"]
    print(f"## (가) ② 랠리 +100%↑ · 거래대금 ×10↑ 의 중단·하단 눌림 — {len(A)}개 (결과 난 것 {len(done)})")
    print("| 묶음 | n | 지속(고점 돌파) | 회귀(75% 반납) | 횡보 |\n|---|---|---|---|---|")
    for nm, f in (("전체", lambda x: True), ("눌림 날 중단 위 마감", lambda x: x["hold"]), ("중단 아래 마감", lambda x: not x["hold"]),
                  ("하단까지", lambda x: x["deep"]), ("고점 −10% 이내", lambda x: x["dd"] < 0.10), ("고점 −25%↓", lambda x: x["dd"] >= 0.25),
                  ("🐋 소형·큰손", lambda x: x["whale"]), ("시총 10억$↑", lambda x: (x["mcap"] or 0) >= 1e9)):
        g = [x for x in done if f(x)]
        if g:
            print(f"| {nm} | {len(g)} | {sum(x['res'] == '지속' for x in g) / len(g):.0%} | {sum(x['res'] == '회귀' for x in g) / len(g):.0%} | "
                  f"{sum(x['res'] == '횡보' for x in g) / len(g):.0%} |")
    print("\n" + hdr)
    rtab("A1 SHORT 눌림 날 종가 (손절 그날 고가+3%) · 전체", A, "A1", "A1risk")
    rtab("A1 · 중단 아래 마감만", [x for x in A if not x["hold"]], "A1", "A1risk")
    rtab("A1 · 고점 −25%↓ 만", [x for x in A if x["dd"] >= 0.25], "A1", "A1risk")
    rtab("A1 · 🐋 만", [x for x in A if x["whale"]], "A1", "A1risk")
    rtab("A2 SHORT 반등 실패 + 눌림 저가 이탈", A, "A2", "A2risk", date_key="d")
    rtab("A2 · 🐋 만", [x for x in A if x["whale"]], "A2", "A2risk")
    rtab("A3 LONG 눌림 날 종가(비교)", A, "A3", "A3risk")
    rtab("A3 · 중단 위 마감 + 고점 −10% 이내", [x for x in A if x["hold"] and x["dd"] < 0.10], "A3", "A3risk")
    # (나)
    lab = [x for x in B if x["lab"] != "모름"]
    print(f"\n## (나) ③ 당일 +30%↑ · 그날 거래대금 ×10↑ — {len(B)}개 (결과 난 것 {len(lab)}) · 바로 하락 = 10일 안 급등분 75% 반납이 먼저")
    print("| 묶음 | n | 바로 하락 | 더 오름 |\n|---|---|---|---|")
    for nm, f in (("전체", lambda x: True), ("다음 날 음봉", lambda x: x["red"]), ("다음 날 양봉", lambda x: not x["red"]),
                  ("윗꼬리 ≥40%", lambda x: x["wick"] >= 0.4), ("윗꼬리 <20%", lambda x: x["wick"] < 0.2),
                  ("🐋 소형·큰손", lambda x: x["whale"]), ("🐋 + 다음 날 음봉", lambda x: x["whale"] and x["red"]),
                  ("당일 +50%↑", lambda x: x["surge"] >= 0.5), ("시총 10억$↑", lambda x: (x["mcap"] or 0) >= 1e9)):
        g = [x for x in lab if f(x)]
        if g:
            print(f"| {nm} | {len(g)} | {sum(x['lab'] == '바로 하락' for x in g) / len(g):.0%} | {sum(x['lab'] == '더 오름' for x in g) / len(g):.0%} |")
    print("\n" + hdr)
    rtab("B1 SHORT 다음 날 음봉 · 전체", B, "B1", "B1risk")
    rtab("B1 · 🐋 만", [x for x in B if x["whale"]], "B1", "B1risk")
    rtab("B1 · 윗꼬리 ≥40% 도", [x for x in B if x["wick"] >= 0.4], "B1", "B1risk")
    rtab("B2 SHORT 급등 날 윗꼬리 ≥40% (급등 날 종가)", B, "B2", "B2risk")
    rtab("B3 LONG 다음 날 양봉", B, "B3", "B3risk")
    rtab("B3 · 🐋 제외", [x for x in B if not x["whale"]], "B3", "B3risk")
    # S4 문맥
    if len(sys.argv) > 1:
        s4 = json.loads(Path(sys.argv[1]).read_text())
        kls = {}
        ctx = defaultdict(list)
        for sym, at, chg, roi in s4:
            if chg is None or chg < 10:
                continue
            if sym not in kls:
                p = DBB.CACHE / f"{sym}_1d.json"
                kls[sym] = json.loads(p.read_text()) if p.exists() else None
            kl = kls[sym]
            if not kl:
                continue
            t0, o, h, lw, c, qv = arrays(kl)
            t = bisect.bisect_right(t0, datetime.fromisoformat(at).timestamp() * 1000) - 2
            if t < 100:
                continue
            tag = "그 밖"
            for d in range(t - 2, t + 1):                              # 진입 전 3일 안 (나)
                m20 = sorted(qv[d - 20:d])
                if c[d] / c[d - 1] - 1 >= 0.30 and m20[10] > 0 and qv[d] / m20[10] >= 10:
                    tag = "(나) 당일 +30%·×10 3일 안"
                    break
            if tag == "그 밖":
                pk = max(range(t - 30, t + 1), key=lambda j: h[j])
                org = min(range(max(0, pk - 60), pk + 1), key=lambda j: lw[j])
                pre = sorted(qv[max(0, org - 60):org]) or [0]
                med = pre[len(pre) // 2]
                if lw[org] > 0 and h[pk] / lw[org] - 1 >= 1.0 and med > 0 and max(qv[org:pk + 1]) / med >= 10:
                    tag = "(가) 랠리 +100%·×10"
            ctx[tag].append((at[:10], roi - 0.4))
        print("\n## S4 가상(실주문과 같은 24h +10%↑ 필터 안) × 진입 전날까지 문맥 — 순수익 = roi − 0.4")
        print("| 문맥 | n (날) | 평균 순수익 | 이긴 비율 | 앞 → 뒤 |\n|---|---|---|---|---|")
        for k, v in sorted(ctx.items()):
            ds = sorted({x[0] for x in v})
            m = ds[len(ds) // 2]
            a = [x[1] for x in v if x[0] < m]
            b = [x[1] for x in v if x[0] >= m]
            print(f"| {k} | {len(v)} ({len(ds)}) | {sum(x[1] for x in v) / len(v):+.2f} | {sum(x[1] > 0 for x in v) / len(v):.0%} | "
                  f"{(sum(a) / len(a)) if a else 0:+.2f} → {(sum(b) / len(b)) if b else 0:+.2f} |")


if __name__ == "__main__":
    main()
