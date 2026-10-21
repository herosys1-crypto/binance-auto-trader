"""🎰 Fix 477 세력 펌프·덤프 SHORT 마틴게일 — 그림자 사후 채점 · 사전 등록 판정 (2026-10-21) — 읽기 전용.

Redis pds:shadow:* (매일 KST 09:15 잡이 기록한 신호) 를 읽어, 신호 심볼의 공개 일봉으로 두 안(A 4단계 · B 3단계)을
백테스트와 같은 규칙(app/services/pump_dump_short.simulate · 레버 1 · 10일)으로 채점한다.

## 사전 등록 판정 기준 (2026-10-21 고정 — 결과를 보고 바꾸지 않는다. 「Claude가 정함」)
  안마다: 끝난 신호 n ≥ 30 · 날(신호일) ≥ 20 · 합 USDT > 0 · 앞·뒤 절반(신호일 기준) 합 모두 > 0 · 청산 0건
    → ✅ 통과(실주문 후보 — 켜기는 사장님) / n·날 미달 → ⏳ 보류 / 합 ≤ 0 또는 청산 ≥ 1 → ❌ 기각 / 그 밖 ⏳
  참고(판정 아님): 🐋 소형·큰손만 · 백테스트 기대(건당 A +41.9 · B +24.4 USDT)와 비교
운영:  docker compose exec -T api python - < scripts/entry_condition_study/pds_shadow_verdict.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "/app")

BT = {"a": 19689 / 470, "b": 11447 / 470}


def main():  # pragma: no cover — 운영 Redis·거래소 필요
    from app.core.redis_client import get_redis_client
    from app.integrations.binance.client import BinanceClient
    from app.services import pump_dump_short as P
    r = get_redis_client()
    recs = []
    for k in r.scan_iter("pds:shadow:*", count=500):
        try:
            recs.append(json.loads(r.get(k)))
        except Exception:  # noqa: BLE001
            pass
    recs.sort(key=lambda x: (x["day"], x["symbol"]))
    print(f"# 🎰 세력 펌프·덤프 SHORT 그림자 채점 — 신호 {len(recs)}건 · 기준 2026-10-21 사전 등록 · 레버 1 · 10일\n")
    if not recs:
        print("신호 없음")
        return
    bc = BinanceClient(api_key="", api_secret="")
    now_ms = int(time.time() * 1000)
    res = {k: [] for k in P.PLANS}
    for x in recs:
        try:
            kl = [k for k in bc.get_klines(symbol=x["symbol"], interval="1d", limit=99) if int(k[6]) < now_ms]
        except Exception:  # noqa: BLE001
            continue
        time.sleep(0.2)
        opens = [int(k[0]) for k in kl]
        if x["entry_day"] not in opens:
            continue
        n = opens.index(x["entry_day"])
        h = [float(k[2]) for k in kl]
        lw = [float(k[3]) for k in kl]
        c = [float(k[4]) for k in kl]
        for key, plan in P.PLANS.items():
            sim = P.simulate(h, lw, c, n, x["half"], plan)
            if sim:
                res[key].append({**sim, "day": x["day"], "symbol": x["symbol"], "whale": bool(x.get("whale"))})
    for key, plan in P.PLANS.items():
        g = res[key]
        print(f"## {plan.label}")
        if not g:
            print("끝난 신호 없음 → ⏳ 보류\n")
            continue
        days = sorted({y["day"] for y in g})
        mid = days[len(days) // 2]
        a = sum(y["pnl"] for y in g if y["day"] < mid)
        b = sum(y["pnl"] for y in g if y["day"] >= mid)
        tot = sum(y["pnl"] for y in g)
        liq = sum(y["why"] == "청산" for y in g)
        if len(g) < 30 or len(days) < 20:
            v = f"⏳ 보류 (n {len(g)}/30 · 날 {len(days)}/20)"
        elif tot <= 0 or liq >= 1:
            v = "❌ 기각"
        elif a > 0 and b > 0:
            v = "✅ 통과 (실주문 후보 — 켜기는 사장님)"
        else:
            v = "⏳ 보류 (앞·뒤 절반 중 하나 ≤ 0)"
        wh = [y["pnl"] for y in g if y["whale"]]
        print(f"끝난 {len(g)} · 날 {len(days)} · 합 {tot:+,.0f} USDT (건당 {tot / len(g):+.1f} · 백테스트 {BT[key]:+.1f}) · 앞 {a:+,.0f} / 뒤 {b:+,.0f} · "
              f"손절 {sum(y['why'] == '손절' for y in g)} · 청산 {liq} · 🐋 {len(wh)}건 {sum(wh):+,.0f}")
        print(f"판정: {v}\n")
    print(f"(채점 시각 {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)")


if __name__ == "__main__":
    main()
