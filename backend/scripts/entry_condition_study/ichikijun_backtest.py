"""일목 기준선 복합 전략(일봉) 사전 백테스트 — 거래소 공개 API · 키 없음 · 로컬 실행용.

판정 = ichikijun_ref.signal (운영 모듈은 이것과 일치해야 함). 진입 = 신호 봉 종가.
청산 (출처대로): 1차 손절 = 진입·직전 봉 저점/고점(0.3~15% 클램프) · 2차 = 종가가 기준선 반대편 마감 → 그 종가
                 · 익절 = 손절폭 × 2 지정가 · 최대 60봉(Claude가 정함). 같은 봉 손절·익절 = 손절(보수적).
겹침 없음 = 종목·방향당 청산 뒤에만 재진입 (실운영과 같음).
비교: ① 같은 날 무작위 종목(같은 청산 규칙, 20회 평균) ② 기준선 청산 없이 2R/손절만 ③ 변형(근접 창·교차 조건·BTC 필터·EMA).
⚠️ 수수료 미반영 줄과 왕복 0.1%(수수료+슬리피지 가정, 실측 아님) 반영 줄을 같이 낸다 · 생존 편향(지금 상위 종목).
사용: python ichikijun_backtest.py [상위 N] [캐시 폴더]
"""
from __future__ import annotations

import json
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ichikijun_ref as R  # noqa: E402

BASE = "https://fapi.binance.com"
TOP = int(sys.argv[1]) if len(sys.argv) > 1 else 80
CACHE = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent / "cache_ichikijun"
LIMIT = 1500
MAX_HOLD = 60
COST = 0.001          # 왕복 0.1% (가정)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as f:
        return json.loads(f.read())


def klines(sym):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{sym}_1d.json"
    if f.exists() and time.time() - f.stat().st_mtime < 20 * 3600:
        return json.loads(f.read_text())
    kl = get(f"/fapi/v1/klines?symbol={urllib.parse.quote(sym)}&interval=1d&limit={LIMIT}")[:-1]   # 마지막 = 진행 중 봉 제외
    f.write_text(json.dumps(kl))
    time.sleep(0.15)
    return kl


def simulate(S, j, side, stop_raw, use_kijun=True):
    o, h, lo, c, v, ind = S
    entry = c[j]
    risk = min(max(abs(entry - stop_raw) / entry, 0.003), 0.15)
    up = side == "LONG"
    stop = entry * (1 - risk) if up else entry * (1 + risk)
    tgt = entry * (1 + R.RR * risk) if up else entry * (1 - R.RR * risk)
    for k in range(j + 1, min(len(c), j + 1 + MAX_HOLD)):
        if (lo[k] <= stop) if up else (h[k] >= stop):
            return -1.0, risk, k, "SL"
        if (h[k] >= tgt) if up else (lo[k] <= tgt):
            return R.RR, risk, k, "TP"
        if use_kijun and R.kijun_exit(c, ind["kj"], k, side):
            return ((c[k] - entry) / entry if up else (entry - c[k]) / entry) / risk, risk, k, "KJ"
    k = min(len(c) - 1, j + MAX_HOLD)
    return ((c[k] - entry) / entry if up else (entry - c[k]) / entry) / risk, risk, k, "TIME"


def stats(rows):
    if not rows:
        return "0건"
    n = len(rows)
    a = sum(r[0] for r in rows) / n
    net = sum(r[0] - COST / r[1] for r in rows) / n
    w = sum(1 for r in rows if r[0] > 0) / n
    rk = sum(r[1] for r in rows) / n * 100
    ex: dict[str, int] = {}
    for r in rows:
        ex[r[3]] = ex.get(r[3], 0) + 1
    exs = " ".join(f"{k}{v}" for k, v in sorted(ex.items()))
    return f"{n}건 승률 {w:.0%} 평균 {a:+.3f}R (비용 뒤 {net:+.3f}R) 손절폭 {rk:.1f}% [{exs}]"


def by_year(rows):
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(time.strftime("%Y", time.gmtime(r[4] / 1000)), []).append(r[0])
    return " · ".join(f"{y} {len(x)}건 {sum(x) / len(x):+.2f}" for y, x in sorted(by.items()))


def main():
    coins = {x["symbol"] for x in get("/fapi/v1/exchangeInfo")["symbols"]
             if x.get("underlyingType") == "COIN" and x.get("contractType") == "PERPETUAL" and x["symbol"].endswith("USDT")}
    tick = sorted([t for t in get("/fapi/v1/ticker/24hr") if t["symbol"] in coins], key=lambda t: -float(t["quoteVolume"]))
    syms = [t["symbol"] for t in tick[:TOP]]
    if "BTCUSDT" not in syms:
        syms.insert(0, "BTCUSDT")
    raw = {s: klines(s) for s in syms}
    btc = raw["BTCUSDT"]
    bc = [float(b[4]) for b in btc]
    bs = R.sma(bc, R.BTC_SMA)
    btc_up = {int(b[0]): (bc[i] > bs[i]) if bs[i] is not None else None for i, b in enumerate(btc)}

    variants = {
        "기본(근접 3봉·교차 필요·BTC·SMA)": {},
        "엄격(같은 날 교차)": {"window": 0},
        "근접 5봉": {"window": 5},
        "교차 없이 상태만(MA·MACD 정배열)": {"need_cross_event": False},
        "BTC 필터 끔": {"btc_filter": False},
        "EMA 이평": {"ma_type": "ema"},
        "거래량·OBV 끔": {"vol_filter": False, "obv_filter": False},
    }
    series = {}
    for s, kl in raw.items():
        o, h, lo, c, v = ([float(b[i]) for b in kl] for i in (1, 2, 3, 4, 5))
        series[s] = {"ts": [int(b[0]) for b in kl], "o": o, "h": h, "lo": lo, "c": c, "v": v,
                     "ind": {mt: R.indicators(o, h, lo, c, v, mt) for mt in ("sma", "ema")}}
    print(f"코인 상위 {len(syms)} · 일봉 최대 {LIMIT}봉 · 진입=신호 봉 종가 · 수수료 미반영(+비용 0.1% 줄) · 생존 편향 있음\n")
    for vname, over in variants.items():
        p = {**R.DEFAULTS, **over}
        for side in ("LONG", "SHORT"):
            rows, rows_nokj, rows_all, sig_days = [], [], [], []
            for s, S0 in series.items():
                ind = S0["ind"][p["ma_type"]]
                S = (S0["o"], S0["h"], S0["lo"], S0["c"], S0["v"], ind)
                free = 0
                for j in range(R.min_bars(p), len(S0["c"]) - 1):
                    ok, d = R.signal(S0["o"], S0["h"], S0["lo"], S0["c"], S0["v"], j, side,
                                     btc_up.get(S0["ts"][j]), p, ind)
                    if not ok:
                        continue
                    r_, rk, xk, why = simulate(S, j, side, d["stop"])
                    rows_all.append((r_, rk, xk, why, S0["ts"][j]))
                    if j >= free:
                        free = xk + 1
                        rows.append((r_, rk, xk, why, S0["ts"][j]))
                        rows_nokj.append((*simulate(S, j, side, d["stop"], use_kijun=False), S0["ts"][j]))
                        sig_days.append((S0["ts"][j], s))
            # 같은 날 무작위 (신호가 난 날마다 다른 종목 하나, 같은 손절 정의·청산)
            rnd = []
            rng = random.Random(7)
            for _ in range(20):
                for ts, s in sig_days:
                    cand = [x for x in series if x != s and ts in series[x]["ts"]]
                    if not cand:
                        continue
                    x = rng.choice(cand)
                    S0 = series[x]
                    j = S0["ts"].index(ts)
                    if j < R.min_bars(p):
                        continue
                    stop = min(S0["lo"][j], S0["lo"][j - 1]) if side == "LONG" else max(S0["h"][j], S0["h"][j - 1])
                    S = (S0["o"], S0["h"], S0["lo"], S0["c"], S0["v"], S0["ind"][p["ma_type"]])
                    rnd.append((*simulate(S, j, side, stop), ts))
            print(f"■ {vname} · {side}")
            print(f"   겹침 없음 : {stats(rows)}")
            print(f"     연도별  : {by_year(rows)}")
            print(f"   기준선 청산 없이(2R·손절만): {stats(rows_nokj)}")
            print(f"   같은 날 무작위(20회): {stats(rnd)}")
            print(f"   (겹침 포함 신호 {len(rows_all)}건)")
        print()


if __name__ == "__main__":
    main()
