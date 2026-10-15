"""펀딩비 차익(캐리) 측정 (2026-10-16 사장님 「B 진행」) — 읽기 전용 · 공개 시세만(키 없음, 주문 없음).

전략 개념: 무기한 선물 SHORT + 현물 LONG 같은 수량 → 가격 방향은 서로 지워지고, 펀딩비가 + 이면 SHORT 쪽이 8시간(또는 4·1시간)마다 받는다.
측정:
  1) 거래량 상위 N 종목의 최근 30일 펀딩 기록 — 종목별 30일 합계·+ 비율·연 환산
  2) 전진 검증: 7일마다 「직전 7일 펀딩 합 상위 K」 를 골라 다음 7일 보유 → 그 7일 실제 펀딩 합 − 바꿀 때 비용
     비용(가정, Claude가 정함): 한 종목 들어가고 나오는 데 0.30% (선물 0.05%×2 + 현물 0.10%×2, 수수료 기본 등급)
  ※ 현물 보유분만큼 자본이 두 배 필요 · 펀딩이 − 로 바뀌면 오히려 낸다 · 선물 쪽 청산 위험(레버 1~2 권장) · 현물 없는 종목 제외는 하지 않음(확인 필요)
운영(서버 말고 이 PC 에서): py -3.11 scripts/entry_condition_study/funding_carry_2026_10_16.py
"""
from __future__ import annotations

import json
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

BASE = "https://fapi.binance.com"
TOP_N = 40
DAYS = 30
HOLD_DAYS = 7
TOP_K = 5
COST = 0.30          # % — 한 종목 들어가고 나오기(선물·현물 양쪽, 기본 수수료)


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.loads(r.read().decode())


def main():
    tick = get("/fapi/v1/ticker/24hr")
    syms = [t["symbol"] for t in sorted((t for t in tick if t["symbol"].endswith("USDT")),
                                        key=lambda t: -float(t["quoteVolume"]))][:TOP_N]
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=DAYS)
    fund = {}
    for s in syms:
        rows = get(f"/fapi/v1/fundingRate?symbol={s}&startTime={int(start.timestamp() * 1000)}&limit=1000")
        fund[s] = [(datetime.fromtimestamp(r["fundingTime"] / 1000, timezone.utc), float(r["fundingRate"]) * 100) for r in rows]
        time.sleep(0.25)

    print(f"# 펀딩비 차익 측정 — 거래량 상위 {TOP_N} · {start:%m-%d}~{end:%m-%d} UTC · 단위 %(받는 쪽 = 선물 SHORT)")
    print("| 종목 | 30일 합 | 연 환산 | + 비율 | 횟수 |")
    print("|---|---|---|---|---|")
    stats = []
    for s, v in fund.items():
        if not v:
            continue
        tot = sum(x for _, x in v)
        stats.append((tot, s, sum(x > 0 for _, x in v) / len(v), len(v)))
    for tot, s, pos, n in sorted(stats, reverse=True):
        print(f"| {s} | {tot:+.3f} | {tot * 365 / DAYS:+.1f} | {pos:.0%} | {n} |")
    allsum = [t for t, *_ in stats]
    print(f"\n상위 {TOP_N} 평균 30일 합 {sum(allsum) / len(allsum):+.3f}% · 중앙값 {sorted(allsum)[len(allsum) // 2]:+.3f}%")

    # 전진 검증: 직전 7일 상위 K → 다음 7일
    def window_sum(s, a, b):
        return sum(x for t, x in fund[s] if a <= t < b)
    print(f"\n## 전진 검증 — {HOLD_DAYS}일마다 직전 {HOLD_DAYS}일 펀딩 상위 {TOP_K} 를 다음 {HOLD_DAYS}일 보유 (바꾸는 종목마다 비용 {COST}%)")
    t = start + timedelta(days=HOLD_DAYS)
    held: set[str] = set()
    total = 0.0
    while t + timedelta(days=HOLD_DAYS) <= end + timedelta(hours=1):
        prev = sorted(syms, key=lambda s: -window_sum(s, t - timedelta(days=HOLD_DAYS), t))[:TOP_K]
        nxt = {s: window_sum(s, t, t + timedelta(days=HOLD_DAYS)) for s in prev}
        changed = len(set(prev) ^ held) / 2 if held else len(prev)
        gross = sum(nxt.values()) / TOP_K
        cost = COST * changed / TOP_K
        total += gross - cost
        print(f"{t:%m-%d}~ 보유 {', '.join(prev)} · 다음 {HOLD_DAYS}일 펀딩 평균 {gross:+.3f}% · 교체 비용 {cost:.3f}% · 순 {gross - cost:+.3f}%")
        held = set(prev)
        t += timedelta(days=HOLD_DAYS)
    weeks = max(1, (DAYS - HOLD_DAYS) // HOLD_DAYS)
    print(f"합계 순 {total:+.3f}% ({weeks}주) · 연 환산 ≈ {total * 52 / weeks:+.1f}% (현물까지 자본 2배 → 총자본 기준 절반)")


if __name__ == "__main__":
    main()
