"""Fix 423 EMA 추세 눌림 — 공개 15분봉 빠른 백테스트 (거래소 공개 API · 키 없음 · 로컬 실행용).

진입 = 신호 봉 종가 · 손절 = 신호 상세 stop(0.3~15% 클램프) · 익절 = 2R · 최대 96봉(24h) 뒤 종가 청산.
같은 봉 안에서 손절·익절이 둘 다 닿으면 손절로 친다(보수적). 심볼당 신호 뒤 16봉(4h) 쿨다운 = 운영 설정과 같음.
⚠️ 수수료·슬리피지 미반영 · 표본 기간 짧음 → 판정이 아니라 「얼마나 자주·대략 어떤지」만 본다.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.services import ema_pullback as EP  # noqa: E402

BASE = "https://fapi.binance.com"
TOP = int(sys.argv[1]) if len(sys.argv) > 1 else 40
LIMIT = 1500
R_TARGET, MAX_HOLD, COOL = 2.0, 96, 16


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as f:
        return json.loads(f.read())


def run():
    tick = [t for t in get("/fapi/v1/ticker/24hr") if t["symbol"].endswith("USDT")]
    tick.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)
    syms = [t["symbol"] for t in tick[:TOP]]
    res = {"LONG": [], "SHORT": []}
    p = EP.params_from()
    for s in syms:
        kl = get(f"/fapi/v1/klines?symbol={s}&interval=15m&limit={LIMIT}")[:-1]
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
                res[side].append((s, r_mult, risk * 100, d["confluence"]))
    days = LIMIT * 15 / 60 / 24
    print(f"심볼 {len(syms)} · 15분봉 {LIMIT} (약 {days:.1f}일)")
    for side, rows in res.items():
        if not rows:
            print(side, "신호 0"); continue
        n = len(rows); wins = sum(1 for r in rows if r[1] > 0); avg = sum(r[1] for r in rows) / n
        conf = [r for r in rows if r[3]]
        ca = (sum(r[1] for r in conf) / len(conf)) if conf else float("nan")
        print(f"{side}: 신호 {n} (하루 {n / days:.1f}) · 승률 {wins / n:.0%} · 평균 {avg:+.2f}R · 평균 손절폭 {sum(r[2] for r in rows) / n:.2f}% "
              f"· 겹침(증액 후보) {len(conf)}건 평균 {ca:+.2f}R")


if __name__ == "__main__":
    run()
