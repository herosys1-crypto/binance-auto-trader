"""방향 계층 측정 (2026-11-11 사장님 「문제되는 전략을 모두 수정하고 수익이 날수 있는 구조로 전면 개선해줘」) — 읽기 전용.

63일(9/9~11/10) 측정 결론: 진입 규칙·청산 방식(10가지) 어느 조합도 앞·뒤 기간 모두에서
같은 방향 무작위를 이기지 못했다(0개). 손익은 「그날 LONG 이냐 SHORT 냐」가 거의 전부(매일 정답 방향 +4.05).
그래서 규칙 손질이 아니라 **방향 계층**을 측정한다.

사전 등록 가설 N (D-113): D 일 진입 방향 = 직전 24시간에 **이미 마감된** 무작위 거래(baseline_*)가
더 나빴던 쪽 (역방향, 미래 참조 없음). 진입 = 그 방향 무작위, 청산 = live 엔진, 비용 0.4%p.
채택 기준(전진 구간만): 순수익/건 > 항상 SHORT·항상 LONG 둘 다 · 날 평균 90% 하한 > 0 · 상위 3일 빼도 > 0.

실행: docker compose exec -T api python - < scripts/entry_condition_study/direction_contrarian_2026_11_11.py
      FORWARD_FROM=2026-11-11 (기본) 이후 진입일만 따로 채점한다.
"""
import bisect
import datetime as dt
import math
import os
import statistics as st
from collections import defaultdict

from sqlalchemy import text

from app.core.database import SessionLocal

COST = 0.4
HOURS = (6, 12, 24, 48, 72)      # 24 = 사전 등록값, 나머지는 주변 안정성 확인용
FORWARD_FROM = dt.date.fromisoformat(os.environ.get("FORWARD_FROM", "2026-11-11"))

SQL = text("""
    SELECT side, opened_at, closed_at, (engines->'live'->>'roi')::float AS roi
    FROM paper_trades
    WHERE source = 'live' AND status = 'CLOSED' AND rule LIKE 'baseline_%'
      AND engines->'live'->>'roi' IS NOT NULL AND closed_at IS NOT NULL
""")


def score(res):
    if len(res) < 3:
        return f"날 {len(res)} (부족)"
    vv = [v for _, v, _ in res]
    mu = sum(vv) / len(vv)
    lo = mu - 1.645 * st.stdev(vv) / math.sqrt(len(vv))
    dd = sorted(vv)[:-3]
    return (f"{mu:+.2f}/건 · 90%하한 {lo:+.2f} · 상위3일빼면 {sum(dd) / max(len(dd), 1):+.2f} · "
            f"+일 {sum(1 for v in vv if v > 0)}/{len(vv)} · LONG일 {sum(1 for *_, s in res if s == 'LONG')}")


def main():
    db = SessionLocal()
    try:
        rows = db.execute(SQL).fetchall()
    finally:
        db.rollback()
        db.close()
    ent = defaultdict(lambda: [0, 0.0])
    closed = {"LONG": [], "SHORT": []}
    for s, o, c, r in rows:
        x = ent[(s, o.date())]
        x[0] += 1
        x[1] += r
        closed[s].append((c, r))
    for s in closed:
        closed[s].sort()
    keys = {s: [c for c, _ in closed[s]] for s in closed}
    days = sorted({d for _, d in ent})
    print(f"무작위 {len(rows):,}행 · {days[0]} ~ {days[-1]} · 전진 구간 {FORWARD_FROM}~")

    for hours in HOURS:
        res = []
        for D in days:
            t0 = dt.datetime.combine(D, dt.time(0), tzinfo=dt.timezone.utc)
            t1 = t0 - dt.timedelta(hours=hours)
            m = {}
            for s in closed:
                seg = [r for _, r in closed[s][bisect.bisect_left(keys[s], t1):bisect.bisect_left(keys[s], t0)]]
                if len(seg) >= 20:
                    m[s] = sum(seg) / len(seg)
            if len(m) < 2:
                continue
            side = "SHORT" if m["LONG"] > m["SHORT"] else "LONG"     # 역방향
            if (side, D) in ent:
                x = ent[(side, D)]
                res.append((D, x[1] / x[0] - COST, side))
        tag = " ← 사전 등록" if hours == 24 else ""
        print(f"[{hours:>2}h{tag}] 전체 {score(res)}")
        print(f"        전진 {score([x for x in res if x[0] >= FORWARD_FROM])}")

    for s in ("LONG", "SHORT"):
        for lab, cond in (("전체", lambda d: True), ("전진", lambda d: d >= FORWARD_FROM)):
            v = [ent[(s, D)][1] / ent[(s, D)][0] - COST for D in days if (s, D) in ent and cond(D)]
            if v:
                print(f"항상 {s} {lab} {sum(v) / len(v):+.2f}/건 (날 {len(v)})")


if __name__ == "__main__":
    main()
