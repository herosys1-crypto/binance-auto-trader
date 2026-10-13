"""📉 급락장 LONG 진입 분석 (2026-10-14 사장님 「1번 진행해줘」) — 읽기 전용.

질문: 「시장폭 < 0.4 일 때 LONG」(Fix 439 두 줄 법칙)이 **계속 빠지는 중**에도 들어가 떨어지는 칼을 잡는가?
방법: 가상매매(source=live) LONG 행을 진입 봉의 시장폭 흐름으로 나눈다.
  시장폭 흐름 = 그 봉의 시장폭 − 1시간(4봉) 전 시장폭 (같은 봉에 들어간 모든 행의 시장폭 중앙값으로 봉별 시계열을 만든다)
  ↓ 하락 중 = −0.05 미만 · → 멈춤 = −0.05 ~ +0.05 · ↑ 반등 = +0.05 초과   (경계는 Claude가 정함)
대상: 시장폭 < 0.4 진입만 (필터 안). 결과 = live 엔진 roi (끝난 행 = 확정, 진행 중 = 지금 평가).
비교: 같은 흐름 구간의 무작위 LONG(baseline_LONG) 평균.
운영:  docker compose exec -T api python - < scripts/entry_condition_study/crash_long_study_2026_10_14.py
"""
from __future__ import annotations

import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")

BAR_MS = 900_000
LOOKBACK_BARS = 4
FALL, RISE = -0.05, 0.05


def trend_of(delta: float | None) -> str:
    if delta is None:
        return "?"
    return "↓하락중" if delta < FALL else ("↑반등" if delta > RISE else "→멈춤")


def breadth_series(rows: list[dict]) -> dict[int, float]:
    by: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        if r["mb"] is not None:
            by[int(r["ts"])].append(r["mb"])
    return {ts: statistics.median(v) for ts, v in by.items()}


def delta_at(series: dict[int, float], ts: int) -> float | None:
    prev = series.get(ts - LOOKBACK_BARS * BAR_MS)
    cur = series.get(ts)
    return None if prev is None or cur is None else cur - prev


def summarize(xs: list[float]) -> str:
    if not xs:
        return "— | — | —"
    return f"{len(xs)} | {sum(xs) / len(xs):+.2f} | {sum(1 for x in xs if x > 0) / len(xs):.0%}"


def main() -> None:  # pragma: no cover — 운영 DB 필요
    from sqlalchemy import text
    from app.core.database import SessionLocal

    days = int(os.environ.get("STUDY_DAYS", "30"))
    db = SessionLocal()
    try:
        rows = []
        for r in db.execute(text("""select rule, side, status, entry_bar_ts ts, opened_at, (snapshot->>'market_breadth')::float mb,
                                           (engines->'live'->>'roi')::float roi
                                    from paper_trades where source='live' and opened_at > now() - make_interval(days => :d)
                                      and engines->'live'->>'roi' is not null"""), {"d": days}):
            rows.append(dict(r._mapping))
    finally:
        db.close()
    ser = breadth_series(rows)
    longs = [r for r in rows if r["side"] == "LONG" and r["mb"] is not None and r["mb"] < 0.4]
    for r in longs:
        r["trend"] = trend_of(delta_at(ser, int(r["ts"])))
    crash_from = datetime(2026, 10, 12, tzinfo=timezone.utc)
    print(f"# 📉 급락장 LONG 분석 — 최근 {days}일 · 시장폭 < 0.4 LONG 진입 {len(longs)}건\n")
    print("흐름 = 진입 봉 시장폭 − 1시간 전 (↓ < −0.05 · ↑ > +0.05) · roi = live 엔진(진행 중은 지금 평가)\n")

    def table(title: str, sub: list[dict]) -> None:
        print(f"## {title}\n| 규칙 | 흐름 | n | 평균 roi | 이긴 비율 |\n|---|---|---|---|---|")
        groups: dict = defaultdict(list)
        for r in sub:
            key = "baseline_LONG(무작위)" if r["rule"].startswith("baseline_") else ("consensus_long" if r["rule"] == "consensus_long" else "규칙 LONG 전체")
            groups[(key, r["trend"])].append(r["roi"])
            if not r["rule"].startswith("baseline_") and r["rule"] != "consensus_long":
                groups[(r["rule"], r["trend"])].append(r["roi"])
        order = ["consensus_long", "규칙 LONG 전체", "baseline_LONG(무작위)"]
        keys = sorted({k for k, _t in groups}, key=lambda k: (order.index(k) if k in order else 9, k))
        for k in keys:
            for t in ("↓하락중", "→멈춤", "↑반등", "?"):
                if (k, t) in groups:
                    print(f"| {k} | {t} | {summarize(groups[(k, t)])} |")
        print()

    table("A. 10/12~ 급락 구간 (끝난 + 진행 중)", [r for r in longs if r["opened_at"] >= crash_from])
    table("B. 그 전 (끝난 행만 = 확정 결과)", [r for r in longs if r["opened_at"] < crash_from and r["status"] == "CLOSED"])

    print("## C. 날짜별 — 시장폭 < 0.4 규칙 LONG (무작위 제외)\n| 날짜 | n | ↓하락중 평균 | →멈춤 평균 | ↑반등 평균 |\n|---|---|---|---|---|")
    by_d: dict = defaultdict(lambda: defaultdict(list))
    for r in longs:
        if not r["rule"].startswith("baseline_"):
            by_d[r["opened_at"].date()][r["trend"]].append(r["roi"])
    for d in sorted(by_d):
        g = by_d[d]
        f = lambda t: f"{sum(g[t]) / len(g[t]):+.2f} ({len(g[t])})" if g[t] else "—"  # noqa: E731
        print(f"| {d} | {sum(len(v) for v in g.values())} | {f('↓하락중')} | {f('→멈춤')} | {f('↑반등')} |")


if __name__ == "__main__":
    main()
