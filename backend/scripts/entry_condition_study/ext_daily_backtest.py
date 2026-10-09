"""Fix 427 — 후지모토·마하세븐 일봉 빠른 백테스트 (거래소 공개 API · 키 없음 · 로컬 실행용).

판정 = 운영과 같은 함수(external_strategies.fujimoto_stages / mach7_signal / swing_stop).
진입 = 신호 봉 종가 · 손절 = 후지모토 최근 20봉 스윙 · 마하세븐 최근 3봉 극값 (0.3~15% 클램프) · 익절 2R · 최대 30봉 뒤 종가 청산.
같은 봉에 손절·익절 둘 다 닿으면 손절(보수적). 심볼·규칙당 신호 뒤 1봉 쿨다운. ⚠️ 수수료·펀딩·슬리피지 미반영 · 생존 편향(지금 상위 종목).
사용: python ext_daily_backtest.py [상위 N]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.services import external_strategies as ES  # noqa: E402

BASE = "https://fapi.binance.com"
TOP = int(sys.argv[1]) if len(sys.argv) > 1 else 60
LIMIT, R_TARGET, MAX_HOLD = 1500, 2.0, 30


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as f:
        return json.loads(f.read())


def outcome(c, h, lo, j, side, stop_price):
    entry = c[j]
    risk = abs(entry - stop_price) / entry
    risk = min(max(risk, 0.003), 0.15)
    stop = entry * (1 - risk) if side == "LONG" else entry * (1 + risk)
    tgt = entry * (1 + R_TARGET * risk) if side == "LONG" else entry * (1 - R_TARGET * risk)
    for k in range(j + 1, min(len(c), j + 1 + MAX_HOLD)):
        if (lo[k] <= stop) if side == "LONG" else (h[k] >= stop):
            return -1.0, risk
        if (h[k] >= tgt) if side == "LONG" else (lo[k] <= tgt):
            return R_TARGET, risk
    last = c[min(len(c) - 1, j + MAX_HOLD)]
    return ((last - entry) / entry if side == "LONG" else (entry - last) / entry) / risk, risk


def run():
    coins = {x["symbol"] for x in get("/fapi/v1/exchangeInfo")["symbols"] if x.get("underlyingType") == "COIN"}
    tick = [t for t in get("/fapi/v1/ticker/24hr") if t["symbol"] in coins]
    tick.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)
    syms = [t["symbol"] for t in tick[:TOP]]
    swing = int(ES.SETTINGS["fujimoto_swing_lookback"][0])
    div_lb = int(ES.SETTINGS["fujimoto_div_lookback"][0])
    slope = float(ES.SETTINGS["mach7_min_slope_pct"][0])
    res: dict[str, list] = {}
    for s in syms:
        kl = get(f"/fapi/v1/klines?symbol={urllib.parse.quote(s)}&interval=1d&limit={LIMIT}")[:-1]
        c = [float(b[4]) for b in kl]
        h = [float(b[2]) for b in kl]
        lo = [float(b[3]) for b in kl]
        ind = ES.compute(c, h, lo)
        nxt: dict[str, int] = {}
        for j in range(60, len(c) - 1):
            for side in ("LONG", "SHORT"):
                st = ES.fujimoto_stages(ind, j, side, div_lookback=div_lb)
                for name, hit in ((f"후지모토 1차 {side}", st[1]), (f"후지모토 3차 단독 {side}", st[3])):
                    if hit and j >= nxt.get(name + s, 0):
                        nxt[name + s] = j + 1
                        r, risk = outcome(c, h, lo, j, side, ES.swing_stop(ind, j, side, swing))
                        res.setdefault(name, []).append((r, risk, int(kl[j][0])))
                ok, d = ES.mach7_signal(ind, j, side, min_slope_pct=slope)
                name = f"마하세븐 {side}"
                if ok and j >= nxt.get(name + s, 0):
                    nxt[name + s] = j + 1
                    r, risk = outcome(c, h, lo, j, side, float(d["stop"]))
                    res.setdefault(name, []).append((r, risk, int(kl[j][0])))
    print(f"코인 상위 {len(syms)} · 일봉 최대 {LIMIT}봉 · 2R · 수수료 미반영")
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
    run()
