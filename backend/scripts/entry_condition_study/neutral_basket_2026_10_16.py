"""방향 중립 바구니 모의 (2026-10-16 사장님 「A 진행」) — 읽기 전용.

질문: 결과가 거의 시장 방향으로 정해진다(같은 날 LONG·SHORT 상관 −0.97). SHORT 한 건마다 **같은 15분 봉의 다른 종목 LONG 바구니** 를
      같은 금액으로 함께 잡아 방향을 지우면, 고른 SHORT 의 실력만 남는가?
비교(모두 SHORT 1 + 같은 봉 무작위 LONG 평균 1 의 반반, 순수익 = 각 다리 roi − 0.4 의 평균):
  S4      = zone_s4_spike_top_short · 24h +10%↑ (지금 실주문 규칙)
  SHORT전체 = 규칙 SHORT 전부 · 24h +10%↑
  무작위  = baseline_SHORT (기준선 — 0 근처여야 정상)
하루 1건(KST 하루 첫 짝) · 전부 평균 · 하루 손익 흔들림 · 최악의 날 · 앞/뒤 절반.
LONG 바구니 = 같은 봉에 들어간 **다른 종목** 가상 LONG(규칙·무작위 모두) 5건 이상의 평균 — 같은 종목끼리 짝지으면
  한쪽 손절(−25)·다른 쪽 트레일링 조기 익절이라 늘 손해(10/16 첫 실행에서 발견) → 같은 종목은 뺀다.
운영:  docker compose exec -T api python - < scripts/entry_condition_study/neutral_basket_2026_10_16.py
"""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402

DAYS = 45
NET = 0.4
BAR = 900
KST_OFF = timedelta(hours=9)
MIN_BASKET = 5
SQL = text("""SELECT opened_at, side, rule, (engines->'live'->>'roi')::float AS r, chg_24h, symbol
  FROM paper_trades WHERE source='live' AND status='CLOSED' AND opened_at > :s AND engines->'live'->>'roi' IS NOT NULL
  ORDER BY opened_at, md5(symbol)""")   # 같은 봉 동점을 늘 같은 순서로(10/17 반박 감사)


def main():
    db = SessionLocal()
    try:
        rows = db.execute(SQL, {"s": datetime.now(timezone.utc) - timedelta(days=DAYS)}).all()
    finally:
        db.close()
    long_bar = defaultdict(list)                       # 봉 → [(종목, LONG roi)] — 규칙·무작위 모두
    for at, side, rule, r, chg, sym in rows:
        if side == "LONG" and r is not None:
            long_bar[int(at.timestamp()) // BAR].append((sym, r))
    groups = {"S4": lambda rule, chg: rule == "zone_s4_spike_top_short" and chg is not None and float(chg) >= 10,
              "SHORT전체": lambda rule, chg: not rule.startswith("baseline_") and chg is not None and float(chg) >= 10,
              "무작위": lambda rule, chg: rule.startswith("baseline_")}
    days = sorted({(at + KST_OFF).date() for at, *_rest in rows})
    mid = days[len(days) // 2]
    print(f"# 방향 중립 바구니 — SHORT 1 + 같은 봉 무작위 LONG 1 (반반) · {days[0]}~{days[-1]} · 순수익 = roi − {NET}")
    print("| 묶음 | 짝 수 | 짝 평균 | SHORT 만 | 앞 절반 | 뒤 절반 | 하루 1건 평균(날) | 하루 1건 흔들림 | 최악의 날 | 플러스 날 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for name, ok in groups.items():
        pairs = []
        for at, side, rule, r, chg, sym in rows:
            if side != "SHORT" or r is None or not ok(rule, chg):
                continue
            lv = [x for s_, x in long_bar.get(int(at.timestamp()) // BAR, ()) if s_ != sym]
            if len(lv) < MIN_BASKET:
                continue
            pairs.append((at, ((r - NET) + (sum(lv) / len(lv) - NET)) / 2, r - NET))
        if not pairs:
            continue
        first = {}
        for at, h, _s in sorted(pairs, key=lambda x: x[0]):   # 시각만으로 — 예전 sorted(pairs) 는 동점에서 값이 가장 낮은 짝을 골라 「하루 1건」 이 늘 −13 이었다(10/18)
            first.setdefault((at + KST_OFF).date(), h)
        v = list(first.values())
        h1 = [h for at, h, _ in pairs if (at + KST_OFF).date() < mid]
        h2 = [h for at, h, _ in pairs if (at + KST_OFF).date() >= mid]
        m = lambda x: f"{sum(x) / len(x):+.2f}" if x else "—"   # noqa: E731
        print(f"| {name} | {len(pairs)} | {m([h for _, h, _ in pairs])} | {m([s for *_, s in pairs])} | {m(h1)} | {m(h2)} | "
              f"{m(v)} ({len(v)}) | {st.pstdev(v):.2f} | {min(v):+.2f} | {sum(x > 0 for x in v)}/{len(v)} |")
    print("\n읽는 법: 「짝 평균」 이 무작위보다 확실히 크고 앞·뒤 절반 모두 + 이면 방향을 지워도 남는 실력이 있다.")


if __name__ == "__main__":
    main()
