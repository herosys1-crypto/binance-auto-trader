"""Fix 431·432 — 볼린저 중심선 파동(bb_wave) · 3중 이평(triple_ma) 사전 백테스트 (공개 API · 키 없음 · 로컬 실행용).

판정 = 운영과 같은 함수(bb_wave.signal · triple_ma.signal). 진입 = 신호 봉 종가. 종목당·규칙당 한 번에 한 포지션(겹침 없음).
청산 (출처대로):
  bb_wave  — 손절 = signal 의 stop(돌파 봉 시가, 3~5% 로 자름) · 종가가 중심선을 다시 깨면 종가 청산 · 최대 100봉
  triple_ma — 손절 = 스윙 로우/하이 · 종가가 EMA9 를 깨면 종가 청산 · 최대 200봉
수수료 왕복 0.08%(테이커 0.04%×2) 를 뺀 % 와 R 을 같이 낸다. 같은 봉 손절·청산 = 손절. ⚠️ 생존 편향(지금 상위 종목) · 펀딩 미반영.
사용: python wave_trima_backtest.py [상위 N] [일수]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.services import bb_wave as BW  # noqa: E402
from app.services import triple_ma as TM  # noqa: E402

BASE = "https://fapi.binance.com"
TOP = int(sys.argv[1]) if len(sys.argv) > 1 else 30
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 120
FEE = 0.08
CACHE = Path(__file__).resolve().parent / "cache_wave_trima"
IV_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as f:
        return json.loads(f.read())


def klines(sym, iv, days):
    CACHE.mkdir(exist_ok=True)
    fp = CACHE / f"{sym}_{iv}_{days}.json"
    if fp.exists():
        return json.loads(fp.read_text())
    end = int(time.time() * 1000)
    start = end - days * 86_400_000
    out = []
    t = start
    while t < end:
        kl = get(f"/fapi/v1/klines?symbol={sym}&interval={iv}&startTime={t}&limit=1500")
        if not kl:
            break
        out += kl
        t = int(kl[-1][0]) + IV_MS[iv]
        time.sleep(0.12)
    out = out[:-1]                                   # 진행 중 봉 버림
    fp.write_text(json.dumps(out))
    return out


def run_bw(o, h, lo, c, v, side, p, mid):
    res, j, nb = [], BW.min_bars(p), len(c)
    while j < nb - 1:
        ok, d = BW.signal(o, h, lo, c, v, j, side, p, (mid, None))
        if not ok:
            j += 1
            continue
        e, st, up = c[j], d["stop"], side == "LONG"
        risk = abs(e - st) / e * 100
        x = None
        for k in range(j + 1, min(nb, j + 101)):
            if (lo[k] <= st) if up else (h[k] >= st):
                x = (-risk, k); break
            if (c[k] < mid[k]) if up else (c[k] > mid[k]):
                x = (((c[k] - e) if up else (e - c[k])) / e * 100, k); break
        if x is None:
            k = min(nb - 1, j + 100)
            x = (((c[k] - e) if up else (e - c[k])) / e * 100, k)
        res.append((x[0] - FEE, x[0] / risk))
        j = x[1] + 1
    return res


def run_tm(h, lo, c, side, p, ind):
    res, j, nb = [], TM.min_bars(p), len(c)
    e9 = ind["e9"]
    while j < nb - 1:
        ok, d = TM.signal(h, lo, c, j, side, p, ind)
        if not ok:
            j += 1
            continue
        e, st, up = c[j], d["stop"], side == "LONG"
        risk = abs(e - st) / e * 100
        x = None
        for k in range(j + 1, min(nb, j + 201)):
            if (lo[k] <= st) if up else (h[k] >= st):
                x = (-risk, k); break
            if (c[k] < e9[k]) if up else (c[k] > e9[k]):
                x = (((c[k] - e) if up else (e - c[k])) / e * 100, k); break
        if x is None:
            k = min(nb - 1, j + 200)
            x = (((c[k] - e) if up else (e - c[k])) / e * 100, k)
        res.append((x[0] - FEE, x[0] / risk))
        j = x[1] + 1
    return res


def summary(name, rows):
    if not rows:
        print(f"{name}: 0건"); return
    n = len(rows)
    pct = sum(r[0] for r in rows) / n
    rr = sum(r[1] for r in rows) / n
    win = sum(1 for r in rows if r[0] > 0) / n
    print(f"{name}: {n}건 · 승률 {win:.0%} · 수수료 뺀 평균 {pct:+.3f}% · 평균 {rr:+.2f}R (수수료 전)")


def main():
    coins = {x["symbol"] for x in get("/fapi/v1/exchangeInfo")["symbols"] if x.get("underlyingType") == "COIN"}
    tick = sorted([t for t in get("/fapi/v1/ticker/24hr") if t["symbol"] in coins], key=lambda t: -float(t["quoteVolume"]))
    syms = [t["symbol"] for t in tick if t["symbol"].isascii()][:TOP]
    pb, pt = BW.params_from(), TM.params_from()
    acc: dict[str, list] = {}
    for s in syms:
        for iv in ("5m", "15m"):
            kl = klines(s, iv, min(DAYS, 60) if iv == "5m" else DAYS)
            o, h, lo, c, v = ([float(b[i]) for b in kl] for i in (1, 2, 3, 4, 5))
            mid, _ = BW.bands(c)
            for side in ("LONG", "SHORT"):
                acc.setdefault(f"파동 {iv} {side}", []).extend(run_bw(o, h, lo, c, v, side, pb, mid))
        for iv in ("15m", "1h", "4h"):
            kl = klines(s, iv, DAYS if iv == "15m" else DAYS * 3)
            h, lo, c = ([float(b[i]) for b in kl] for i in (2, 3, 4))
            ind = TM.indicators(c)
            for side in ("LONG", "SHORT"):
                acc.setdefault(f"3중이평 {iv} {side}", []).extend(run_tm(h, lo, c, side, pt, ind))
    print(f"코인 상위 {len(syms)} · 5m {min(DAYS, 60)}일 · 15m {DAYS}일 · 1h/4h {DAYS * 3}일 · 수수료 왕복 {FEE}%")
    for k in sorted(acc):
        summary(k, acc[k])


if __name__ == "__main__":
    main()
