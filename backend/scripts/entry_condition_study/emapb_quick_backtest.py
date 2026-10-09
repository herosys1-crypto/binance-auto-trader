"""Fix 423 EMA 추세 눌림 — 공개 15분봉 빠른 백테스트 (거래소 공개 API · 키 없음 · 로컬 실행용).

진입 = 신호 봉 종가 · 손절 = 신호 상세 stop(0.3~15% 클램프) · 익절 = 2R · 최대 보유 뒤 종가 청산.
같은 봉 안에서 손절·익절이 둘 다 닿으면 손절로 친다(보수적).
사용: python emapb_quick_backtest.py [상위 N] [봉 15m|1d] — 15m = 최대 96봉(24h)·쿨다운 16봉 / 1d(Fix 424) = 최대 30봉(30일)·쿨다운 1봉
⚠️ 수수료·슬리피지 미반영 · 표본 기간 짧음 → 판정이 아니라 「얼마나 자주·대략 어떤지」만 본다.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.services import ema_pullback as EP  # noqa: E402

BASE = "https://fapi.binance.com"
TOP = int(sys.argv[1]) if len(sys.argv) > 1 else 40
IV = sys.argv[2] if len(sys.argv) > 2 else "15m"
LIMIT = 1500
R_TARGET = 2.0
MAX_HOLD, COOL = (30, 1) if IV == "1d" else (96, 16)
BAR_MIN = 1440 if IV == "1d" else 15


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as f:
        return json.loads(f.read())


def run():
    coins = {x["symbol"] for x in get("/fapi/v1/exchangeInfo")["symbols"] if x.get("underlyingType") == "COIN"}   # Fix 425: 코인만
    tick = [t for t in get("/fapi/v1/ticker/24hr") if t["symbol"].endswith("USDT") and t["symbol"] in coins]
    tick.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)
    syms = [t["symbol"] for t in tick[:TOP]]
    res = {"LONG": [], "SHORT": []}
    p = EP.params_from()
    for s in syms:
        kl = get(f"/fapi/v1/klines?symbol={urllib.parse.quote(s)}&interval={IV}&limit={LIMIT}")[:-1]
        c = [float(b[4]) for b in kl]; h = [float(b[2]) for b in kl]; lo = [float(b[3]) for b in kl]; v = [float(b[5]) for b in kl]
        e = EP.emas(c)
        for side in ("LONG", "SHORT"):
            nxt = 0
            for j in range(EP.min_bars(p), len(c) - 1):
                if j < nxt:
                    continue
                ok, d = EP.signal(c, h, lo, v, j, side, p, e)
                if not ok:
                    continue
                nxt = j + COOL
                entry = c[j]
                risk = abs(entry - d["stop"]) / entry
                risk = min(max(risk, 0.003), 0.15)
                stop = entry * (1 - risk) if side == "LONG" else entry * (1 + risk)
                tgt = entry * (1 + R_TARGET * risk) if side == "LONG" else entry * (1 - R_TARGET * risk)
                r_mult = None
                for k in range(j + 1, min(len(c), j + 1 + MAX_HOLD)):
                    hit_s = lo[k] <= stop if side == "LONG" else h[k] >= stop
                    hit_t = h[k] >= tgt if side == "LONG" else lo[k] <= tgt
                    if hit_s:
                        r_mult = -1.0; break
                    if hit_t:
                        r_mult = R_TARGET; break
                if r_mult is None:
                    last = c[min(len(c) - 1, j + MAX_HOLD)]
                    r_mult = ((last - entry) / entry if side == "LONG" else (entry - last) / entry) / risk
                res[side].append((s, r_mult, risk * 100, d["confluence"], int(kl[j][0])))
    days = LIMIT * BAR_MIN / 60 / 24
    print(f"심볼 {len(syms)} · {IV} 최대 {LIMIT}봉 (약 {days:.0f}일, 상장 짧은 종목은 그만큼만)")
    for side, rows in res.items():
        if not rows:
            print(side, "신호 0"); continue
        n = len(rows); wins = sum(1 for r in rows if r[1] > 0); avg = sum(r[1] for r in rows) / n
        conf = [r for r in rows if r[3]]
        ca = (sum(r[1] for r in conf) / len(conf)) if conf else float("nan")
        print(f"{side}: 신호 {n} · 승률 {wins / n:.0%} · 평균 {avg:+.2f}R · 평균 손절폭 {sum(r[2] for r in rows) / n:.2f}% "
              f"· 겹침(증액 후보) {len(conf)}건 평균 {ca:+.2f}R")
        # 연도별 (장세 의존 확인 — 한 장세만 좋으면 채택 근거가 약하다)
        import time as _t
        by: dict[str, list[float]] = {}
        for r in rows:
            by.setdefault(_t.strftime("%Y", _t.gmtime(r[4] / 1000)), []).append(r[1])
        print("   연도별: " + " · ".join(f"{y} {len(v)}건 {sum(v) / len(v):+.2f}R" for y, v in sorted(by.items())))


if __name__ == "__main__":
    run()
