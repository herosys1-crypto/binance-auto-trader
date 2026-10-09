"""Fix 429 — 볼린저 EMA(일봉) 빠른 백테스트 (거래소 공개 API · 키 없음 · 로컬 실행용).

판정 = 운영과 같은 함수(bb_ema.trend_signal / reversal_signal). 진입 = 신호 봉 종가.
청산 (출처대로):
  추세  — 손절 = 진입 때 중단선(0.3~15% 클램프) · 그 뒤 종가가 그날 중단선 반대편으로 마감하거나 EMA 배열(가격·EMA90 vs EMA200)이 풀리면 종가 청산 · 최대 60봉
  반전  — 손절 = 리버절 밴드 · 익절 = 반대편 2σ 밴드(진입 때 값) · 최대 30봉
비교   — 같은 진입을 「손절 그대로 · 2R 익절 · 최대 30봉」으로도 잰다.
같은 봉 손절·익절 = 손절(보수적). 심볼·규칙당 신호 뒤 1봉 쿨다운. ⚠️ 수수료·펀딩 미반영 · 생존 편향(지금 상위 종목).
사용: python bbema_daily_backtest.py [상위 N]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.services import bb_ema as BE  # noqa: E402

BASE = "https://fapi.binance.com"
TOP = int(sys.argv[1]) if len(sys.argv) > 1 else 60
LIMIT = 1500


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as f:
        return json.loads(f.read())


def clamp_stop(entry, stop, side):
    risk = abs(entry - stop) / entry
    risk = min(max(risk, 0.003), 0.15)
    return (entry * (1 - risk) if side == "LONG" else entry * (1 + risk)), risk


def run_trend(c, h, lo, ind, j, side, stop_raw):
    entry = c[j]
    stop, risk = clamp_stop(entry, stop_raw, side)
    for k in range(j + 1, min(len(c), j + 61)):
        if (lo[k] <= stop) if side == "LONG" else (h[k] >= stop):
            return -1.0, risk, k
        m = ind["mid"][k]
        broke = (c[k] < m or c[k] < ind["e200"][k] or ind["e90"][k] < ind["e200"][k]) if side == "LONG" else \
                (c[k] > m or c[k] > ind["e200"][k] or ind["e90"][k] > ind["e200"][k])
        if broke:
            return ((c[k] - entry) / entry if side == "LONG" else (entry - c[k]) / entry) / risk, risk, k
    k = min(len(c) - 1, j + 60)
    return ((c[k] - entry) / entry if side == "LONG" else (entry - c[k]) / entry) / risk, risk, k


def run_fixed(c, h, lo, j, side, stop_raw, target=None, r_mult=2.0, hold=30):
    entry = c[j]
    stop, risk = clamp_stop(entry, stop_raw, side)
    tgt = target if target is not None else (entry * (1 + r_mult * risk) if side == "LONG" else entry * (1 - r_mult * risk))
    for k in range(j + 1, min(len(c), j + 1 + hold)):
        if (lo[k] <= stop) if side == "LONG" else (h[k] >= stop):
            return -1.0, risk
        if (h[k] >= tgt) if side == "LONG" else (lo[k] <= tgt):
            return (abs(tgt - entry) / entry) / risk, risk
    last = c[min(len(c) - 1, j + hold)]
    return ((last - entry) / entry if side == "LONG" else (entry - last) / entry) / risk, risk


def main():
    coins = {x["symbol"] for x in get("/fapi/v1/exchangeInfo")["symbols"] if x.get("underlyingType") == "COIN"}
    tick = sorted([t for t in get("/fapi/v1/ticker/24hr") if t["symbol"] in coins], key=lambda t: -float(t["quoteVolume"]))
    syms = [t["symbol"] for t in tick[:TOP]]
    p = BE.params_from()
    res: dict[str, list] = {}
    for s in syms:
        kl = get(f"/fapi/v1/klines?symbol={urllib.parse.quote(s)}&interval=1d&limit={LIMIT}")[:-1]
        c = [float(b[4]) for b in kl]
        h = [float(b[2]) for b in kl]
        lo = [float(b[3]) for b in kl]
        if len(c) < BE.min_bars(p):
            continue
        ind = BE.indicators(c)
        nxt: dict[str, int] = {}
        for j in range(BE.min_bars(p) - 5, len(c) - 1):
            for side in ("LONG", "SHORT"):
                ok, d = BE.trend_signal(c, h, lo, j, side, p, ind)
                if ok and j >= nxt.get("T" + side, 0):
                    nxt["T" + side] = j + 1
                    r_, risk_, xk = run_trend(c, h, lo, ind, j, side, d["stop"])
                    res.setdefault(f"추세 {side} (출처 청산: 중단·배열)", []).append((r_, risk_, int(kl[j][0])))
                    if j >= nxt.get("TX" + side, 0):          # 겹침 없음 = 실제 운영(종목당 1회 진입, 청산 뒤에만 재진입)
                        nxt["TX" + side] = xk + 1
                        res.setdefault(f"추세 {side} (출처 청산 · 겹침 없음)", []).append((r_, risk_, int(kl[j][0])))
                    res.setdefault(f"추세 {side} (2R 비교)", []).append((*run_fixed(c, h, lo, j, side, d["stop"]), int(kl[j][0])))
                ok, d = BE.reversal_signal(c, h, lo, j, side, p, ind)
                if ok and j >= nxt.get("R" + side, 0):
                    nxt["R" + side] = j + 1
                    res.setdefault(f"반전 {side} (출처 청산: 반대 밴드)", []).append((*run_fixed(c, h, lo, j, side, d["stop"], target=d["target"]), int(kl[j][0])))
                    res.setdefault(f"반전 {side} (2R 비교)", []).append((*run_fixed(c, h, lo, j, side, d["stop"]), int(kl[j][0])))
    print(f"코인 상위 {len(syms)} · 일봉 최대 {LIMIT}봉 · 수수료 미반영")
    for name in sorted(res):
        rows = res[name]
        n = len(rows)
        avg = sum(r[0] for r in rows) / n
        win = sum(1 for r in rows if r[0] > 0) / n
        by: dict[str, list[float]] = {}
        for r in rows:
            by.setdefault(time.strftime("%Y", time.gmtime(r[2] / 1000)), []).append(r[0])
        yr = " · ".join(f"{y} {len(v)}건 {sum(v) / len(v):+.2f}" for y, v in sorted(by.items()))
        print(f"{name}: {n}건 · 승률 {win:.0%} · 평균 {avg:+.2f}R · 손절폭 {sum(r[1] for r in rows) / n * 100:.1f}% | {yr}")


if __name__ == "__main__":
    main()
