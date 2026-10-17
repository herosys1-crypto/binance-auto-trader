"""S4 급반등 꼭대기 SHORT 청산 방식 비교 (2026-10-17 사장님 「1번 진행」) — 읽기 전용.

같은 가상 진입(rule = zone_s4_spike_top_short) 에 가상 엔진이 청산 변형을 함께 기록한다(engines JSON):
  live(지금 실주문과 같은 청산) · house(고정 익절) · live_be10(+10 뒤 본전) · live_sl15(손절 15) · live_lock5 · live_stale24(24h 정체 정리)
  · live_trail3 / live_trail8(트레일링 폭 3·8%p, Fix 453) · live_trend / live_trend0(추세 보유, Fix 447)
비교는 **같은 진입끼리 짝**(변형이 모두 끝난 행만) — 진입 차이를 지우고 청산만 본다.
  변형별 n · 순수익 평균(roi − 0.4) · 이긴 비율 · 이긴 건 평균 · 진 건 평균 · 최악 · live 대비 차(짝) + 부트스트랩 90% 구간 · 앞/뒤 절반 차
  필터 = 실주문과 같은 「24h +10% 이상」 (FILTER=0 이면 전체)
운영:  docker compose exec -T api python - < scripts/entry_condition_study/s4_exit_compare_2026_10_17.py

가설 L (2026-10-17 사전 등록, 판정 ≈ 2026-11-15 · jk 자동 판정에 함께): S4 의 TP1 뒤 트레일링 폭을 3%p 로(live_trail3) 하면 지금(live)보다 낫다.
  대상 = SCORE_FROM(2026-10-17 KST) 이후 진입 · 24h +10% 필터 안 · live·live_trail3 둘 다 끝난 짝
  통과(Claude가 정함) = 짝 ≥ 100 · 차 평균 > 0 · 부트스트랩 90% 구간 아래 끝 > 0 · 앞·뒤 절반 차 모두 > 0 · 기각 = 짝 ≥ 100 인데 차 평균 ≤ 0
  탐색 표본(10/13~16, 36짝): +0.51%p (+0.15~+0.83) · 앞 +0.27 / 뒤 +0.75 — 실주문 반영은 대표님 결정
"""
from __future__ import annotations

import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402

NET = 0.4
RULE = "zone_s4_spike_top_short"
VARIANTS = ("live", "house", "live_be10", "live_sl15", "live_lock5", "live_stale24", "live_trail3", "live_trail8", "live_trend", "live_trend0")
FILTER = os.environ.get("FILTER", "1") != "0"
SCORE_FROM = os.environ.get("SCORE_FROM")             # "YYYY-MM-DD"(KST) — 가설 L 판정 때
KST_OFF = timedelta(hours=9)
SQL = text("""SELECT opened_at, chg_24h, engines FROM paper_trades
  WHERE source='live' AND status='CLOSED' AND rule=:r AND opened_at > :s""")


def roi_of(eng, k):
    v = (eng or {}).get(k)
    if isinstance(v, dict) and v.get("done") and v.get("roi") is not None:
        try:
            return float(v["roi"])
        except (TypeError, ValueError):
            return None
    return None


def boot(diffs, n=2000, seed=7):
    rnd = random.Random(seed)
    ms = sorted(sum(rnd.choice(diffs) for _ in diffs) / len(diffs) for _ in range(n))
    return ms[int(n * 0.05)], ms[int(n * 0.95)]


def main():
    db = SessionLocal()
    try:
        rows = db.execute(SQL, {"r": RULE, "s": datetime.now(timezone.utc) - timedelta(days=60)}).all()
    finally:
        db.close()
    rows = [r for r in rows if not FILTER or (r.chg_24h is not None and float(r.chg_24h) >= 10)]
    if SCORE_FROM:
        rows = [r for r in rows if (r.opened_at + KST_OFF).date().isoformat() >= SCORE_FROM]
    print(f"# S4 SHORT 청산 방식 비교 — 진입 {len(rows)}건 ({'24h +10%↑ 필터 안' if FILTER else '전체'}) · 순수익 = roi − {NET}")

    def table(keys, title):
        both = [r for r in rows if all(roi_of(r.engines, k) is not None for k in keys)]
        if len(both) < 10:
            print(f"\n## {title} — 짝 {len(both)}건, 너무 적어 생략")
            return
        both.sort(key=lambda r: r.opened_at)
        mid = both[len(both) // 2].opened_at
        print(f"\n## {title} — 모두 끝난 같은 진입 {len(both)}건 · {both[0].opened_at:%m-%d}~{both[-1].opened_at:%m-%d}")
        print("| 청산 | 순수익 평균 | 이긴 비율 | 이긴 건 평균 | 진 건 평균 | 최악 | live 대비 차 (90% 구간) | 앞 절반 차 | 뒤 절반 차 |")
        print("|---|---|---|---|---|---|---|---|---|")
        for k in keys:
            v = [roi_of(r.engines, k) - NET for r in both]
            w = [x for x in v if x > 0]
            lo_ = [x for x in v if x <= 0]
            d = [roi_of(r.engines, k) - roi_of(r.engines, "live") for r in both]
            d1 = [x for r, x in zip(both, d) if r.opened_at < mid]
            d2 = [x for r, x in zip(both, d) if r.opened_at >= mid]
            ci = boot(d) if k != "live" else (0.0, 0.0)
            m = lambda x: f"{sum(x) / len(x):+.2f}" if x else "—"   # noqa: E731
            print(f"| {k} | {m(v)} | {len(w) / len(v):.0%} | {m(w)} | {m(lo_)} | {min(v):+.1f} | "
                  f"{m(d)} ({ci[0]:+.2f}~{ci[1]:+.2f}) | {m(d1)} | {m(d2)} |")

    table(("live", "house", "live_be10", "live_sl15", "live_lock5", "live_stale24"), "A. 오래 기록된 변형")
    table(VARIANTS, "B. 전 변형(트레일링 3·8 · 추세 보유는 10/12 부터)")
    # 가설 L 판정
    pair = sorted((r for r in rows if roi_of(r.engines, "live") is not None and roi_of(r.engines, "live_trail3") is not None),
                  key=lambda r: r.opened_at)
    d = [roi_of(r.engines, "live_trail3") - roi_of(r.engines, "live") for r in pair]
    print(f"\n## 가설 L 판정 (SCORE_FROM {SCORE_FROM or '없음 = 탐색 재현'}) — S4 트레일링 3%p vs 지금 · 짝 {len(d)}")
    if len(d) >= 100:
        lo_, hi_ = boot(d)
        h = len(d) // 2
        a1, a2 = sum(d[:h]) / h, sum(d[h:]) / (len(d) - h)
        md = sum(d) / len(d)
        ok = md > 0 and lo_ > 0 and a1 > 0 and a2 > 0
        print(f"L 판정: 차 평균 {md:+.2f}%p (90% {lo_:+.2f}~{hi_:+.2f}) · 앞 {a1:+.2f} / 뒤 {a2:+.2f} → "
              + ("✅ 통과" if ok else ("❌ 기각" if md <= 0 else "⏳ 보류")))
    else:
        print("L 판정: ⏳ 표본 부족 — 판정하지 않음")
    print("\n읽는 법: 「live 대비 차」 90% 구간이 0 을 넘지 않으면(아래 끝 > 0) 그 청산이 더 낫다고 말할 수 있다. 앞·뒤 절반 부호가 같아야 안정.")


if __name__ == "__main__":
    main()
