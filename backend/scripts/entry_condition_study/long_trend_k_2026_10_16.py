"""가설 K — LONG 전면 수정안 (2026-10-16 사전 등록, 판정 ≈ 2026-11-15) — 읽기 전용.

배경(전 전략 검토 2026-10-16): LONG 5규칙(bottom_331·pullback_331·l1_hist_turn_up·multiday_rebound_352·wick_rev_long_v220)은
  두 줄 법칙(시장폭<0.4) 안에서 앞 절반 +2.7~+4.0% → 뒤 절반 −0.2~−1.4%, 무작위 LONG 도 뒤 절반 마이너스 = 시장 방향 탓.
  4가지 변형 중 「진입 전 24시간 시장폭 평균 < 0.45」 만 두 기간 모두 플러스(앞 +4.86 · 뒤 +0.21, 무작위 +0.48) —
  4개 중 고른 것이라 과적합 위험 → **2026-10-17 KST 이후 진입만으로** 다시 잰다(하루 = KST, 실주문 하루 최대와 같은 경계).
수정안 K: LONG 5규칙 진입 = 지금 시장폭 < 0.4 **그리고** 진입 전 24시간(15분 봉 시장폭 중앙값) 평균 < 0.45
  · 24시간 평균은 진입 시점에 이미 알 수 있는 값(미래 참조 없음) — 봉별 시장폭은 같은 봉 가상 행들의 중앙값으로 다시 만든다
통과(Claude가 정함): ① K 안 n ≥ 300 · 날 ≥ 10 ② K 안 순수익 > 0 ③ K 안 순수익 − 같은 기간 두 줄 법칙만 순수익 ≥ +0.5%p
  ④ K 안 순수익 > 같은 조건 무작위 LONG 순수익 ⑤ 하루 1건(그날 첫 진입) 순수익 > 0 (n ≥ 10)
  기각 = ② 실패 · 그 밖은 보류. 통과해도 실주문 반영은 대표님 결정.
운영:  docker compose exec -T -e SCORE_FROM=2026-10-17 api python - < scripts/entry_condition_study/long_trend_k_2026_10_16.py
       (SCORE_FROM 없으면 지난 46일 전체 = 탐색 표본 재현)
"""
from __future__ import annotations

import bisect
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402

NET = 0.4
KST_OFF = timedelta(hours=9)                         # 하루 = KST(실주문 「하루 최대」 와 같은 경계, auto_family_registry)
BAR = 900
LONG5 = {"bottom_331", "pullback_331", "l1_hist_turn_up", "multiday_rebound_352", "wick_rev_long_v220"}
K_AVG24 = 0.45
SCORE_FROM = os.environ.get("SCORE_FROM")
SQL = text("""SELECT opened_at, side, rule, (engines->'live'->>'roi')::float AS r, (snapshot->>'market_breadth')::float AS mb
  FROM paper_trades WHERE source='live' AND status='CLOSED' AND opened_at > :s AND engines->'live'->>'roi' IS NOT NULL""")


def main():
    db = SessionLocal()
    try:
        rows = db.execute(SQL, {"s": datetime.now(timezone.utc) - timedelta(days=int(os.environ.get("DAYS") or 46))}).all()
    finally:
        db.close()
    bars = defaultdict(list)
    for at, _side, _rule, _r, mb in rows:
        if mb is not None:
            bars[int(at.timestamp()) // BAR].append(mb)
    series = {k: st.median(v) for k, v in bars.items()}
    keys = sorted(series)

    def avg24(t):
        b = int(t.timestamp()) // BAR
        i, j = bisect.bisect_left(keys, b - 96), bisect.bisect_left(keys, b)
        v = [series[k] for k in keys[i:j]]
        return sum(v) / len(v) if len(v) >= 48 else None

    grp = defaultdict(list)            # 이름 → [(at, roi)]
    for at, side, rule, r, mb in rows:
        if side != "LONG" or mb is None or mb >= 0.4 or r is None:
            continue
        if SCORE_FROM and (at + KST_OFF).date().isoformat() < SCORE_FROM:
            continue
        who = "무작위" if rule.startswith("baseline_") else ("규칙5" if rule in LONG5 else None)
        if who is None:
            continue
        a = avg24(at)
        grp[f"{who}·두줄"].append((at, r))
        if a is not None and a < K_AVG24:
            grp[f"{who}·K"].append((at, r))

    def net(v):
        return sum(x[1] for x in v) / len(v) - NET if v else None

    print(f"# 가설 K — LONG 5규칙 · 시장폭<0.4 & 24h 평균<{K_AVG24} (SCORE_FROM {SCORE_FROM or '없음(탐색 재현)'}) · 순수익")
    for k in ("규칙5·K", "규칙5·두줄", "무작위·K", "무작위·두줄"):
        v = grp[k]
        if v:
            print(f"{k}: n {len(v)} · 날 {len({(x[0] + KST_OFF).date() for x in v})} · 순수익 {net(v):+.2f}")
    k, two, bk = grp["규칙5·K"], grp["규칙5·두줄"], grp["무작위·K"]
    first = {}
    for at, r in sorted(k):
        first.setdefault((at + KST_OFF).date(), r)
    one = (sum(first.values()) / len(first) - NET) if first else None
    print(f"하루 1건(그날 첫 진입) 순수익 {'—' if one is None else f'{one:+.2f}'} (n {len(first)})")
    nd = len({(x[0] + KST_OFF).date() for x in k})
    if len(k) >= 300 and nd >= 10 and len(first) >= 10:
        ok = (net(k) > 0 and net(k) - net(two) >= 0.5 and (not bk or net(k) > net(bk)) and one > 0)
        print("판정:", "✅ 통과" if ok else ("❌ 기각" if net(k) <= 0 else "⏳ 보류"))
    else:
        print("판정: ⏳ 표본 부족")


if __name__ == "__main__":
    main()
