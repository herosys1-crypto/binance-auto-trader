"""사장님 일봉 세 가지 그림 → 미리 알아볼 근거 + LONG·SHORT 규칙 시험 (2026-10-21) — 읽기 전용 · 로컬 실행.

사장님(verbatim 요지):
  1. 일봉이 지속 상승하며 볼밴 중단을 지지하고 다시 상승, 심하면 하단까지 왔다가 다시 지속 상승
  2. 며칠·몇 주 급상승 → 중단(심하면 하단)까지 조정 → 다시 상승 → 최종적으로 원점 회귀 (세력의 장난·조작)
  3. 며칠 또는 당일 급상승 후 바로 하락
  「이것을 파악할 수 있는 근거를 찾고 롱과 숏으로 매매할 수 있는 전략을 만들고 싶어」

데이터 = daily_bb_pullback_study_2026_10_21.py 의 캐시(cache_daily_bb/ · 공개 API · COIN 무기한 전부 · 일봉 ≤1500).
모든 진입은 **그날 종가까지 알 수 있는 값**으로만 판정하고 그날 종가에 들어간다. 숫자는 모두 「Claude가 정함」.

규칙 후보
  L1  (1번 LONG)  상승 추세 눌림(연구 1 정의) 중 완만 랠리(하루 상승률 < 1%) — 눌림 날 종가 LONG · 손절 = 그날 하단 −3%(최대 −15%) · 익절 = 직전 고점 · 최대 40일
  S2  (2번 SHORT) 급등 랠리(하루 ≥ 3%) 의 첫 눌림 뒤 20일 안: 반등이 직전 고점을 못 넘고(낮은 고점) 종가가 눌림 날 저가 아래로 마감 → 그날 종가 SHORT
                  · 손절 = 그 사이 반등 고점 +2%(최대 +20%) · 익절 = origin + 25%(랠리 75% 반납) · 최대 40일
  S3  (3번 SHORT) 급등 날 = 종가가 3일 전 최저가 대비 +30% 이상 · 다음 날(t+1) 종가 < 급등 날 종가(이어 가지 못함) → t+1 종가 SHORT
                  · 손절 = 급등 이후 최고가 +2%(최대 +25%) · 익절 = 급등 시작가 + 50%(급등분 절반 반납) · 최대 20일
  S3w (3번 SHORT, 꼬리) 급등 날 윗꼬리 ≥ 40%(고가−종가 ÷ 고가−저가) → 급등 날 종가 SHORT · 손절·익절 S3 와 같음
결과 = R(손절폭 기준) · 같은 날 손절·익절 둘 다 = 손절(보수적) · 수수료·펀딩 미반영 · 지금 상장 종목만(상폐 빠짐)
안정성 = 연도별 · 앞/뒤 절반(날짜 기준) · 날 평균 R(같은 날 진입을 한 표본으로)
사용: python daily_three_patterns_2026_10_21.py   (먼저 연구 1 을 한 번 돌려 캐시를 만든다)
"""
from __future__ import annotations

import importlib.util
import json
import random
import statistics as st
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
_s = importlib.util.spec_from_file_location("dbb", HERE / "daily_bb_pullback_study_2026_10_21.py")
DBB = importlib.util.module_from_spec(_s)
_s.loader.exec_module(DBB)


def sim(side, e, stop, tgt, h, lw, c, j0, hold):
    """j0 = 진입 다음 봉. → R 또는 None(데이터 부족)."""
    risk = abs(e - stop)
    if risk <= 0:
        return None
    for j in range(j0, min(len(c), j0 + hold)):
        if side == "LONG":
            if lw[j] <= stop:
                return -1.0
            if h[j] >= tgt:
                return (tgt - e) / risk
        else:
            if h[j] >= stop:
                return -1.0
            if lw[j] <= tgt:
                return (e - tgt) / risk
    if j0 + hold <= len(c):
        x = c[j0 + hold - 1]
        return ((x - e) if side == "LONG" else (e - x)) / risk
    return None


def scan(sym, kl):
    t0 = [int(k[0]) for k in kl]
    o = [float(k[1]) for k in kl]
    h = [float(k[2]) for k in kl]
    lw = [float(k[3]) for k in kl]
    c = [float(k[4]) for k in kl]
    qv = [float(k[7]) for k in kl]
    mid, up, lo = DBB.bands(c)
    day = lambda i: datetime.fromtimestamp(t0[i] / 1000, timezone.utc).date().isoformat()   # noqa: E731
    out = []
    used_peak = None
    last_s3 = -99
    for t in range(DBB.N + 70, len(c) - 1):
        # ---------- 연구 1 의 눌림 (L1 · S2) ----------
        ok_trend = (mid[t] is not None and mid[t - 10] is not None and mid[t] > mid[t - 10]
                    and sum(1 for j in range(t - 10, t) if mid[j] is not None and c[j] > mid[j]) >= 7)
        if ok_trend and lw[t] <= mid[t]:
            pk_i = max(range(t - 30, t), key=lambda j: h[j])
            peak = h[pk_i]
            or_i = min(range(max(0, pk_i - 60), pk_i + 1), key=lambda j: lw[j])
            origin = lw[or_i]
            if origin > 0 and peak / origin - 1 >= DBB.MIN_GAIN and used_peak != pk_i:
                used_peak = pk_i
                speed = (peak / origin - 1) / max(1, pk_i - or_i)
                if speed < 0.01:                                    # L1 완만 랠리 LONG
                    e = c[t]
                    stop = max(min(lo[t] * 0.97, e * 0.97), e * 0.85)
                    out.append({"rule": "L1", "sym": sym, "date": day(t), "side": "LONG",
                                "r": sim("LONG", e, stop, peak, h, lw, c, t + 1, 40), "risk": 1 - stop / e})
                if speed >= 0.03:                                   # S2 급등 랠리의 실패 뒤 SHORT
                    reb = h[t]
                    for j in range(t + 1, min(len(c) - 1, t + 21)):
                        if h[j] > peak:
                            break                                   # 고점 돌파 = 1번처럼 됨 → 안 함
                        reb = max(reb, h[j])
                        if j > t + 1 and c[j] < lw[t]:
                            e = c[j]
                            stop = min(reb * 1.02, e * 1.20)
                            tgt = origin + 0.25 * (peak - origin)
                            if tgt < e:
                                out.append({"rule": "S2", "sym": sym, "date": day(j), "side": "SHORT",
                                            "r": sim("SHORT", e, stop, tgt, h, lw, c, j + 1, 40), "risk": stop / e - 1})
                            break
        # ---------- 3번: 급등 날 ----------
        base = min(lw[t - 3:t + 1])
        if base > 0 and c[t] / base - 1 >= 0.30 and t - last_s3 >= 10:
            last_s3 = t
            rng = h[t] - lw[t]
            wick = (h[t] - c[t]) / rng if rng > 0 else 0
            vsp = qv[t] / (st.median(qv[t - 20:t]) or 1)
            half = base + 0.5 * (c[t] - base)
            feat = {"wick": wick, "vspike": vsp, "surge": c[t] / base - 1,
                    "above_up": (c[t] / up[t] - 1) if up[t] else None, "qv20": sum(qv[t - 20:t]) / 20}
            if wick >= 0.4:                                         # S3w 꼬리 SHORT(급등 날 종가)
                e = c[t]
                stop = min(h[t] * 1.02, e * 1.25)
                out.append({"rule": "S3w", "sym": sym, "date": day(t), "side": "SHORT",
                            "r": sim("SHORT", e, stop, half, h, lw, c, t + 1, 20), "risk": stop / e - 1, **feat})
            if c[t + 1] < c[t]:                                     # S3 다음 날 못 이어 감
                e = c[t + 1]
                stop = min(max(h[t], h[t + 1]) * 1.02, e * 1.25)
                if half < e:
                    out.append({"rule": "S3", "sym": sym, "date": day(t + 1), "side": "SHORT",
                                "r": sim("SHORT", e, stop, half, h, lw, c, t + 2, 20), "risk": stop / e - 1, **feat})
            # 3번 「바로 하락」 결과 라벨(근거 찾기용) — 10일 안에 급등분 75% 반납이 먼저 vs 급등 고점 돌파가 먼저
            back = base + 0.25 * (c[t] - base)
            lab = "모름"
            for j in range(t + 1, min(len(c), t + 11)):
                if lw[j] <= back:
                    lab = "바로 하락"
                    break
                if h[j] > h[t] * 1.05:
                    lab = "더 오름"
                    break
            out.append({"rule": "lab3", "sym": sym, "date": day(t), "lab": lab, "next_red": c[t + 1] < c[t], **feat})
    return out


def summarize(name, g):
    g = [x for x in g if x["r"] is not None]
    if not g:
        print(f"| {name} | 0 | | | | | | |")
        return
    rs = [x["r"] for x in g]
    ds = sorted({x["date"] for x in g})
    mid = ds[len(ds) // 2]
    a = [x["r"] for x in g if x["date"] < mid]
    b = [x["r"] for x in g if x["date"] >= mid]
    by_day = defaultdict(list)
    for x in g:
        by_day[x["date"]].append(x["r"])
    dm = [sum(v) / len(v) for v in by_day.values()]
    risk = st.median(x["risk"] for x in g)
    yrs = defaultdict(list)
    for x in g:
        yrs[x["date"][:4]].append(x["r"])
    ytxt = " ".join(f"{y}:{sum(v) / len(v):+.2f}({len(v)})" for y, v in sorted(yrs.items()))
    print(f"| {name} | {len(g)} ({len(ds)}일) | {sum(rs) / len(rs):+.3f} | {sum(r > 0 for r in rs) / len(rs):.0%} | "
          f"{sum(a) / len(a):+.2f} → {sum(b) / len(b):+.2f} | {sum(dm) / len(dm):+.3f} | {risk:.1%} | {ytxt} |")


def coin_info():
    """CoinGecko 공개 자료(키 없음, 받은 날 기준 — 사건 당시 값 아님) → 기호 → {mcap, float}. float = 시총 ÷ 완전 희석 시총(유통 비율)."""
    p = DBB.CACHE / "_coingecko_markets.json"
    if not p.exists():
        return {}
    out = {}
    for k, v in json.loads(p.read_text())["coins"].items():
        mc, fdv = v.get("mcap") or 0, v.get("fdv") or 0
        out[k] = {"mcap": mc or None, "float": (mc / fdv) if mc and fdv else None}
    return out


def base_of(sym):
    b = sym[:-4] if sym.endswith("USDT") else sym
    for pre in ("1000000", "1000", "1M"):
        if b.startswith(pre) and len(b) > len(pre):
            return b[len(pre):]
    return b


MCAP = (("시총 < 5천만$", 0, 5e7), ("5천만~2억$", 5e7, 2e8), ("2억~10억$", 2e8, 1e9), ("10억$↑", 1e9, 1e30))
FLOAT = (("유통 < 30%", 0, 0.3), ("30~60%", 0.3, 0.6), ("60~90%", 0.6, 0.9), ("90%↑", 0.9, 9))


def main():
    files = sorted(DBB.CACHE.glob("*_1d.json"))
    info = coin_info()
    rows = []
    for p in files:
        try:
            sym = p.name[:-8]
            ci = info.get(base_of(sym), {})
            for x in scan(sym, json.loads(p.read_text())):
                x["mcap"], x["float"] = ci.get("mcap"), ci.get("float")
                rows.append(x)
        except Exception:  # noqa: BLE001
            pass
    matched = len({x["sym"] for x in rows if x.get("mcap")})
    print(f"(시총 짝 맞춘 종목 {matched} / {len({x['sym'] for x in rows})} — CoinGecko 기호 기준 · 받은 날 값)")
    print(f"# 일봉 세 가지 그림 — 종목 {len(files)} · 진입은 그날 종가까지 아는 값만 · R = 손절폭 기준 · 수수료·펀딩 미반영")
    print("\n## 규칙 시험 (R 평균 > 0 이면 기대값 플러스)")
    print("| 규칙 | 진입 n (날) | 평균 R | 이긴 비율 | 앞 → 뒤 절반 | 날 평균 R | 손절폭 중앙값 | 연도별 평균 R(n) |\n|---|---|---|---|---|---|---|---|")
    for rule, name in (("L1", "L1 1번 LONG · 완만 추세 중단·하단 눌림"), ("S2", "S2 2번 SHORT · 급등 랠리 눌림 뒤 낮은 고점 + 눌림 저가 이탈"),
                       ("S3", "S3 3번 SHORT · 급등 다음 날 못 이어 감"), ("S3w", "S3w 3번 SHORT · 급등 날 윗꼬리 ≥40%")):
        summarize(name, [x for x in rows if x.get("rule") == rule])
    for key, bks, ttl in (("mcap", MCAP, "시총별"), ("float", FLOAT, "유통 비율별(낮을수록 큰손 몇이 물량 쥠)")):
        print(f"\n### 규칙 × {ttl}")
        print("| 규칙 · 구간 | 진입 n (날) | 평균 R | 이긴 비율 | 앞 → 뒤 절반 | 날 평균 R | 손절폭 중앙값 | 연도별 평균 R(n) |\n|---|---|---|---|---|---|---|---|")
        for rule in ("L1", "S2", "S3", "S3w"):
            for nm, a, b in bks:
                summarize(f"{rule} · {nm}", [x for x in rows if x.get("rule") == rule and x.get(key) is not None and a <= x[key] < b])
    # 3번 근거: 급등 날 특징별 「바로 하락」 비율
    lab = [x for x in rows if x.get("rule") == "lab3" and x["lab"] != "모름"]
    print(f"\n## 3번 근거 — 급등 날(3일 안 +30%) {len([x for x in rows if x.get('rule') == 'lab3'])}개 중 결과 난 것 {len(lab)} · 「바로 하락」 = 10일 안 급등분 75% 반납이 먼저")
    print("| 급등 날 특징 | n | 바로 하락 | 더 오름 |\n|---|---|---|---|")

    def line(nm, f):
        g = [x for x in lab if f(x)]
        if g:
            print(f"| {nm} | {len(g)} | {sum(x['lab'] == '바로 하락' for x in g) / len(g):.0%} | {sum(x['lab'] == '더 오름' for x in g) / len(g):.0%} |")
    line("전체", lambda x: True)
    for lo_, hi_ in ((0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 1.01)):
        line(f"윗꼬리 {lo_:.0%}~{hi_:.0%}", lambda x, a=lo_, b=hi_: a <= x["wick"] < b)
    line("다음 날 음봉(종가 < 급등 날 종가)", lambda x: x["next_red"])
    line("다음 날 양봉", lambda x: not x["next_red"])
    for lo_, hi_ in ((0, 3), (3, 10), (10, 1e9)):
        line(f"급등 날 거래대금 ×{lo_}~{hi_ if hi_ < 1e9 else '∞'}", lambda x, a=lo_, b=hi_: a <= x["vspike"] < b)
    for lo_, hi_ in ((0.3, 0.5), (0.5, 1.0), (1.0, 99)):
        line(f"3일 상승 +{lo_:.0%}~{'∞' if hi_ > 9 else f'{hi_:.0%}'}", lambda x, a=lo_, b=hi_: a <= x["surge"] < b)
    line("20일 평균 거래대금 < 2천만$", lambda x: x["qv20"] < 2e7)
    line("20일 평균 거래대금 ≥ 2천만$", lambda x: x["qv20"] >= 2e7)
    for nm, a, b in MCAP:
        line(nm, lambda x, a=a, b=b: x.get("mcap") is not None and a <= x["mcap"] < b)
    for nm, a, b in FLOAT:
        line(nm, lambda x, a=a, b=b: x.get("float") is not None and a <= x["float"] < b)
    line("시총 < 2억$ + 유통 < 60% + 급등 날 거래대금 ×10↑", lambda x: (x.get("mcap") or 9e99) < 2e8 and (x.get("float") or 9) < 0.6 and x["vspike"] >= 10)


if __name__ == "__main__":
    main()
