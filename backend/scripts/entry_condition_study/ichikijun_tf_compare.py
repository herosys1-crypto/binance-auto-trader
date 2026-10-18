"""일목 기준선 복합 전략 — 판정 봉별 비교 (5m · 15m · 1h · 4h · 1d · 1w). 공개 API · 키 없음 · 로컬 실행용.

같은 규칙(ichikijun_ref.signal · 출처 그대로 기본형)을 봉만 바꿔 돌린다. BTC 장세 = 같은 봉의 BTC 종가 > SMA20.
청산 = 1차 손절(2봉 저점/고점, 0.3~15% 클램프) · 2R 익절 · 기준선 재이탈 종가 청산 · 최대 60봉. 같은 봉 손절·익절 = 손절.
봉마다 기간이 다르다(짧은 봉은 최근 수개월) → 판정은 **같은 봉·같은 시각 무작위 종목 대비 차이**와 **비용 뒤 R** 로 한다.
비용 = 왕복 0.1% 가정(수수료+슬리피지, 실측 아님) → R 로는 0.1% / 손절폭. ⚠️ 생존 편향(지금 상위 종목).
사용: python ichikijun_tf_compare.py [상위 N] [캐시 폴더]
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
TOP = int(sys.argv[1]) if len(sys.argv) > 1 else 40
CACHE = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent / "cache_ichikijun_tf"
COST = 0.001
MAX_HOLD = 60
# 봉 → (받을 봉 수, 봉 길이 ms) — Claude가 정함 (요청 수 ≈ 상위 N × 합계/1500)
TF = {"5m": (26000, 300_000), "15m": (17500, 900_000), "1h": (8800, 3_600_000),
      "4h": (6000, 14_400_000), "1d": (1500, 86_400_000), "1w": (400, 604_800_000)}


def get(path):
    for t in range(5):
        try:
            with urllib.request.urlopen(BASE + path, timeout=30) as f:
                return json.loads(f.read())
        except Exception:  # noqa: BLE001
            time.sleep(2 + 3 * t)
    raise RuntimeError(path)


def klines(sym, iv):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{sym}_{iv}.json"
    if f.exists() and time.time() - f.stat().st_mtime < 20 * 3600:
        return json.loads(f.read_text())
    want, ms = TF[iv]
    out: list = []
    end = None
    while len(out) < want:
        q = f"/fapi/v1/klines?symbol={urllib.parse.quote(sym)}&interval={iv}&limit=1500" + (f"&endTime={end}" if end else "")
        kl = get(q)
        time.sleep(0.35)                     # 무게 10/요청 → 분당 ≈1,700 (한도 2,400 아래)
        if not kl:
            break
        out = kl + out
        end = int(kl[0][0]) - 1
        if len(kl) < 1500:
            break
    out = out[:-1]                           # 마지막 = 진행 중 봉
    f.write_text(json.dumps(out))
    return out


def simulate(S, j, side, stop_raw):
    o, h, lo, c, v, ind = S
    entry = c[j]
    risk = min(max(abs(entry - stop_raw) / entry, 0.003), 0.15)
    up = side == "LONG"
    stop = entry * (1 - risk) if up else entry * (1 + risk)
    tgt = entry * (1 + R.RR * risk) if up else entry * (1 - R.RR * risk)
    for k in range(j + 1, min(len(c), j + 1 + MAX_HOLD)):
        if (lo[k] <= stop) if up else (h[k] >= stop):
            return -1.0, risk, k
        if (h[k] >= tgt) if up else (lo[k] <= tgt):
            return R.RR, risk, k
        if R.kijun_exit(c, ind["kj"], k, side):
            return ((c[k] - entry) / entry if up else (entry - c[k]) / entry) / risk, risk, k
    k = min(len(c) - 1, j + MAX_HOLD)
    return ((c[k] - entry) / entry if up else (entry - c[k]) / entry) / risk, risk, k


def summ(rows):
    n = len(rows)
    if not n:
        return None
    return {"n": n, "win": sum(1 for r in rows if r[0] > 0) / n, "avg": sum(r[0] for r in rows) / n,
            "net": sum(r[0] - COST / r[1] for r in rows) / n, "risk": sum(r[1] for r in rows) / n * 100,
            "days": len({r[2] // 86_400_000 for r in rows})}


def main():
    coins = {x["symbol"] for x in get("/fapi/v1/exchangeInfo")["symbols"]
             if x.get("underlyingType") == "COIN" and x.get("contractType") == "PERPETUAL" and x["symbol"].endswith("USDT")}
    tick = sorted([t for t in get("/fapi/v1/ticker/24hr") if t["symbol"] in coins], key=lambda t: -float(t["quoteVolume"]))
    syms = [t["symbol"] for t in tick[:TOP]]
    if "BTCUSDT" not in syms:
        syms.insert(0, "BTCUSDT")
    p = dict(R.DEFAULTS)
    print(f"코인 상위 {len(syms)} · 출처 그대로 기본형 · 비용 왕복 0.1% 가정 · 같은 시각 무작위 10회 · 생존 편향 있음\n")
    hdr = "봉 | 방향 | 기간 | 건수(날) | 승률 | 평균R | 비용 뒤R | 손절폭 | 무작위 비용 뒤R | 차이"
    print(hdr)
    for iv in TF:
        series = {}
        for s in syms:
            kl = klines(s, iv)
            if len(kl) < R.min_bars(p) + 10:
                continue
            o, h, lo, c, v = ([float(b[i]) for b in kl] for i in (1, 2, 3, 4, 5))
            ts = [int(b[0]) for b in kl]
            series[s] = {"ts": ts, "pos": {t: i for i, t in enumerate(ts)}, "S": (o, h, lo, c, v, R.indicators(o, h, lo, c, v))}
        if "BTCUSDT" not in series:
            continue
        bc = series["BTCUSDT"]["S"][3]
        bs = R.sma(bc, R.BTC_SMA)
        btc_up = {t: (bc[i] > bs[i]) if bs[i] is not None else None for i, t in enumerate(series["BTCUSDT"]["ts"])}
        t0 = min(x["ts"][0] for x in series.values())
        span = (max(x["ts"][-1] for x in series.values()) - t0) / 86_400_000
        for side in ("LONG", "SHORT"):
            rows, rnd = [], []
            rng = random.Random(11)
            for s, X in series.items():
                o, h, lo, c, v, ind = X["S"]
                free = 0
                for j in range(R.min_bars(p), len(c) - 1):
                    if j < free:
                        continue
                    ok, d = R.signal(o, h, lo, c, v, j, side, btc_up.get(X["ts"][j]), p, ind)
                    if not ok:
                        continue
                    r_, rk, xk = simulate(X["S"], j, side, d["stop"])
                    free = xk + 1
                    t = X["ts"][j]
                    rows.append((r_, rk, t))
                    cand = [y for y in series if y != s and t in series[y]["pos"]]
                    for _ in range(10 if cand else 0):
                        Y = series[rng.choice(cand)]
                        jj = Y["pos"][t]
                        if jj < R.min_bars(p):
                            continue
                        yo, yh, yl, yc, yv, yind = Y["S"]
                        st = min(yl[jj], yl[jj - 1]) if side == "LONG" else max(yh[jj], yh[jj - 1])
                        rr, rk2, _ = simulate(Y["S"], jj, side, st)
                        rnd.append((rr, rk2, t))
            a, b = summ(rows), summ(rnd)
            if not a:
                print(f"{iv} | {side} | {span:.0f}일 | 0건")
                continue
            diff = a["net"] - b["net"] if b else float("nan")
            print(f"{iv} | {side} | {span:.0f}일 | {a['n']}({a['days']}) | {a['win']:.0%} | {a['avg']:+.3f} | {a['net']:+.3f} | "
                  f"{a['risk']:.2f}% | {b['net'] if b else float('nan'):+.3f} | {diff:+.3f}")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
