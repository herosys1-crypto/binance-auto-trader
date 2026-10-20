"""일봉 상승 중 볼밴 중단·하단 눌림 → 「계속 상승」 vs 「원점 회귀(세력 장난)」 구별 연구 (2026-10-21 사장님) — 읽기 전용 · 로컬 실행.

사장님 말씀(verbatim 요지):
  1. 일봉이 지속적으로 상승하면서 볼밴 중단을 지지하고 다시 상승, 좀더 심하면 볼밴 하단까지 왔다가 다시 지속 상승
  2. 단기 며칠 또는 몇 주 급상승 → 상승 중 볼밴 중단, 심하면 하단까지 조정 후 다시 상승 → 최종적으로 원점 회귀 (세력의 장난·조작)
→ 눌림이 나온 그 날(그날 종가까지 알 수 있는 값만)로 1과 2를 미리 가를 수 있는가?

데이터: 거래소 공개 API(키 없음) · USDⓈ-M 무기한 중 COIN 종목 전부 · 일봉 최대 1500개 · 캐시 cache_daily_bb/
정의(숫자는 모두 「Claude가 정함」):
  볼밴 = 20일 · 2σ (중단 = 20일 평균)
  상승 추세(눌림 날 t 기준) = 중단이 10일 전보다 높음 · 직전 10일 중 7일 이상 종가 > 중단
  랠리 = 직전 30일 최고가(peak) · peak 전 60일 최저가(origin) · 상승폭 peak/origin − 1 ≥ 30%
  눌림 = 그날 저가 ≤ 중단 (하단까지 = 저가 ≤ 하단) · 같은 랠리에서 첫 눌림만(새 고점이 나야 다음 눌림을 다시 셈)
  결과(다음 60일): 지속 = peak 를 먼저 넘음 · 회귀 = 먼저 origin + 25%(랠리의 75% 반납) 아래로 · 그 밖 = 횡보
  모의 LONG(참고): 눌림 날 종가 진입 · 손절 −15% · 익절 = peak · 최대 40일 → R(손절폭 기준)
⚠️ 지금 상장된 종목만(상폐 종목 빠짐 = 회귀 쪽이 덜 잡힘) · 수수료·펀딩 미반영 · 같은 시기 종목끼리 독립 아님(날짜별로도 봄)
사용: python daily_bb_pullback_study_2026_10_21.py
"""
from __future__ import annotations

import json
import statistics as st
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://fapi.binance.com"
CACHE = Path(__file__).resolve().parent / "cache_daily_bb"
LIMIT = 1500
N, K = 20, 2.0
MIN_GAIN = 0.30
FWD = 60


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as f:
        return json.loads(f.read())


def klines(sym):
    CACHE.mkdir(exist_ok=True)
    p = CACHE / f"{sym}_1d.json"
    if p.exists() and time.time() - p.stat().st_mtime < 20 * 3600:
        return json.loads(p.read_text())
    kl = get(f"/fapi/v1/klines?symbol={sym}&interval=1d&limit={LIMIT}".replace(sym, urllib.parse.quote(sym)))[:-1]   # 마감 안 된 오늘 봉 제외
    p.write_text(json.dumps(kl))
    time.sleep(0.35)                                                           # 무게 10/회 → 분당 ≈1,700 아래
    return kl


def bands(c):
    mid, up, lo = [None] * len(c), [None] * len(c), [None] * len(c)
    for i in range(N - 1, len(c)):
        w = c[i - N + 1:i + 1]
        m = sum(w) / N
        sd = (sum((x - m) ** 2 for x in w) / N) ** 0.5
        mid[i], up[i], lo[i] = m, m + K * sd, m - K * sd
    return mid, up, lo


def events(sym, kl):
    t0 = [int(k[0]) for k in kl]
    h = [float(k[2]) for k in kl]
    lw = [float(k[3]) for k in kl]
    c = [float(k[4]) for k in kl]
    qv = [float(k[7]) for k in kl]
    mid, up, lo = bands(c)
    out = []
    last_peak_used = None
    for t in range(N + 70, len(c)):
        if mid[t] is None or mid[t - 10] is None or not mid[t] > mid[t - 10]:
            continue
        if sum(1 for j in range(t - 10, t) if mid[j] is not None and c[j] > mid[j]) < 7:
            continue
        pk_i = max(range(t - 30, t), key=lambda j: h[j])
        peak = h[pk_i]
        o_from = max(0, pk_i - 60)
        or_i = min(range(o_from, pk_i + 1), key=lambda j: lw[j])
        origin = lw[or_i]
        if origin <= 0 or peak / origin - 1 < MIN_GAIN:
            continue
        if not lw[t] <= mid[t]:
            continue
        if last_peak_used == pk_i:
            continue
        last_peak_used = pk_i
        kind = "하단" if lw[t] <= lo[t] else "중단"
        # 결과(t+1 ~ t+FWD) — 미래 구간은 「결과」에만 쓴다
        end = min(len(c), t + 1 + FWD)
        complete = t + FWD < len(c)
        back = origin + 0.25 * (peak - origin)
        res = "횡보"
        for j in range(t + 1, end):
            if lw[j] <= back:
                res = "회귀"
                break
            if h[j] > peak:
                res = "지속"
                break
        if res == "횡보" and not complete:
            res = "진행 중"
        # 모의 LONG
        e = c[t]
        stop, tgt = e * 0.85, peak
        r = None
        for j in range(t + 1, min(len(c), t + 41)):
            if lw[j] <= stop:
                r = -1.0
                break
            if h[j] >= tgt:
                r = (tgt - e) / (e - stop)
                break
        if r is None and t + 40 < len(c):
            r = (c[t + 40] - e) / (e - stop)
        pre = qv[max(0, or_i - 60):or_i] or qv[:1]
        rally_qv = qv[or_i:pk_i + 1]
        out.append({
            "sym": sym, "date": datetime.fromtimestamp(t0[t] / 1000, timezone.utc).date().isoformat(),
            "kind": kind, "res": res, "r": r,
            "gain": peak / origin - 1, "rally_days": max(1, pk_i - or_i), "dd": 1 - c[t] / peak,
            "hold_mid": c[t] >= mid[t], "width": (up[t] - lo[t]) / mid[t],
            "qv30": sum(qv[t - 30:t]) / 30, "vspike": (max(rally_qv) / st.median(pre)) if pre and st.median(pre) > 0 else None,
            "age": t, "days_since_peak": t - pk_i, "fwd20": (c[t + 20] / e - 1) if t + 20 < len(c) else None,
        })
    return out


def table(rows, key, buckets, title):
    print(f"\n### {title}")
    print("| 구간 | 눌림 수 | 지속 | 회귀 | 횡보 | 지속−회귀 | 모의 LONG 평균 R | 20일 뒤 중앙값 |")
    print("|---|---|---|---|---|---|---|---|")
    for name, f in buckets:
        g = [x for x in rows if f(key(x))]
        if not g:
            continue
        n = len(g)
        a = sum(x["res"] == "지속" for x in g) / n
        b = sum(x["res"] == "회귀" for x in g) / n
        s = sum(x["res"] == "횡보" for x in g) / n
        rs = [x["r"] for x in g if x["r"] is not None]
        f20 = [x["fwd20"] for x in g if x["fwd20"] is not None]
        print(f"| {name} | {n} | {a:.0%} | {b:.0%} | {s:.0%} | {a - b:+.0%} | "
              f"{(sum(rs) / len(rs)) if rs else float('nan'):+.2f} | {(st.median(f20) * 100) if f20 else float('nan'):+.1f}% |")


def main():
    info = get("/fapi/v1/exchangeInfo")["symbols"]
    syms = sorted(x["symbol"] for x in info if x.get("underlyingType") == "COIN" and x.get("contractType") == "PERPETUAL"
                  and x.get("quoteAsset") == "USDT" and x.get("status") == "TRADING")
    allr = []
    for i, s in enumerate(syms):
        try:
            allr += events(s, klines(s))
        except Exception as e:  # noqa: BLE001
            print(f"  {s} 건너뜀: {type(e).__name__}", file=sys.stderr)
        if i % 100 == 0:
            print(f"  … {i}/{len(syms)}", file=sys.stderr)
    done = [x for x in allr if x["res"] != "진행 중"]
    print(f"# 일봉 상승 중 볼밴 중단·하단 눌림 — 종목 {len(syms)} · 눌림 {len(allr)} (결과 난 것 {len(done)}, 진행 중 {len(allr) - len(done)})")
    print("결과: 지속 = 60일 안에 직전 고점 돌파가 먼저 · 회귀 = 랠리의 75% 반납(원점 근처)이 먼저 · 모의 LONG = 종가 진입 · 손절 −15% · 익절 직전 고점 · 40일")
    table(done, lambda x: 0, [("전체", lambda v: True)], "전체")
    table(done, lambda x: x["kind"], [("중단까지", lambda v: v == "중단"), ("하단까지", lambda v: v == "하단")], "눌림 깊이")
    table(done, lambda x: x["gain"], [("+30~60%", lambda v: v < 0.6), ("+60~100%", lambda v: 0.6 <= v < 1.0),
                                      ("+100~200%", lambda v: 1.0 <= v < 2.0), ("+200%↑", lambda v: v >= 2.0)], "랠리 크기(origin→peak)")
    table(done, lambda x: x["gain"] / x["rally_days"], [("하루 +1% 미만(완만)", lambda v: v < 0.01), ("+1~3%", lambda v: 0.01 <= v < 0.03),
                                                       ("+3~6%", lambda v: 0.03 <= v < 0.06), ("+6%↑(급등)", lambda v: v >= 0.06)], "랠리 속도(상승폭 ÷ 일수)")
    table(done, lambda x: x["vspike"] or 0, [("거래대금 폭증 ×3 미만", lambda v: v < 3), ("×3~10", lambda v: 3 <= v < 10),
                                             ("×10~30", lambda v: 10 <= v < 30), ("×30↑", lambda v: v >= 30)], "랠리 중 최대 거래대금 ÷ 랠리 전 중앙값")
    table(done, lambda x: x["qv30"], [("30일 평균 거래대금 <1천만$", lambda v: v < 1e7), ("1천만~5천만$", lambda v: 1e7 <= v < 5e7),
                                      ("5천만~2억$", lambda v: 5e7 <= v < 2e8), ("2억$↑", lambda v: v >= 2e8)], "유동성")
    table(done, lambda x: x["hold_mid"], [("중단 위 마감(지지)", lambda v: v), ("중단 아래 마감", lambda v: not v)], "눌림 날 종가")
    table(done, lambda x: x["dd"], [("고점 −10% 이내", lambda v: v < 0.1), ("−10~25%", lambda v: 0.1 <= v < 0.25),
                                    ("−25~40%", lambda v: 0.25 <= v < 0.4), ("−40%↓", lambda v: v >= 0.4)], "눌림 날 고점 대비 하락")
    # 1번(완만 추세) vs 2번(급등) 대표 묶음
    slow = lambda x: x["gain"] / x["rally_days"] < 0.01 and (x["vspike"] or 0) < 10        # noqa: E731
    fast = lambda x: x["gain"] / x["rally_days"] >= 0.03 and (x["vspike"] or 0) >= 10       # noqa: E731
    table(done, lambda x: x, [("① 완만 추세(하루 <1% · 거래대금 ×10 미만)", slow), ("② 급등(하루 ≥3% · 거래대금 ×10↑)", fast),
                              ("그 사이", lambda x: not slow(x) and not fast(x))], "사장님 1번 vs 2번 묶음")
    for nm, f in (("① 완만 추세", slow), ("② 급등", fast)):
        g = [x for x in done if f(x)]
        yrs = defaultdict(list)
        for x in g:
            yrs[x["date"][:4]].append(x["res"] == "지속")
        print(f"- {nm} 연도별 지속 비율: " + " · ".join(f"{y} {sum(v) / len(v):.0%}({len(v)})" for y, v in sorted(yrs.items())))
    live = [x for x in allr if x["res"] == "진행 중"]
    print(f"\n진행 중 눌림 {len(live)}개 (최근 60일, 결과 미정 — 참고): " + ", ".join(f"{x['sym']} {x['date']} {x['kind']}" for x in live[-15:]))


if __name__ == "__main__":
    main()
