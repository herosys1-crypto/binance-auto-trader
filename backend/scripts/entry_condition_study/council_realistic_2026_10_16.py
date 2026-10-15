"""운영팀 배치 「실주문처럼」 재기 (2026-10-16 사장님 「가상매매 결과로 자동매매 전략 개선」) — 읽기 전용.

질문: 운영팀 전진 검증(D)은 고른 칸의 **모든** 가상 행을 평균한다(하루 수천 건). 실주문은 가족마다 하루 최대 1건이다.
      하루 1건(또는 3건)만 들어가도 운영팀 배치가 지금 실주문 가족 규칙보다 나은가?
방법: 날짜 D 마다 strategy_council 과 같은 규칙으로 칸(rule, side, 시장폭 구간)을 고른다(학습창 [D−13, D−3], n≥30·평균>0·무작위 대비>0).
  정책 A1 / A3 = 그날 고른 칸에 든 가상 행 중 진입 시각이 이른 1건 / 3건 (방향별)
  정책 L  = 지금 실주문 가족과 같은 규칙: LONG bottom_331 · 시장폭<0.4 첫 1건 / SHORT zone_s4_spike_top_short · 24h +10% 이상 첫 1건
  무작위 = baseline 행 중 이른 1건 (방향별)
결과 = live 엔진 roi(%) 와 순수익(roi − 0.4, Fix 452 가정). 끝난 행만.
운영:  docker compose exec -T api python - < scripts/entry_condition_study/council_realistic_2026_10_16.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.services import strategy_council as SC  # noqa: E402

DAYS = 34
NET = 0.4
LIVE_RULES = {"LONG": "bottom_331", "SHORT": "zone_s4_spike_top_short"}

SQL = text("""
    SELECT rule, side, opened_at, (opened_at AT TIME ZONE 'UTC')::date AS d, engines->'live'->>'roi' AS roi,
           snapshot->>'market_breadth' AS mb, chg_24h
    FROM paper_trades
    WHERE source = 'live' AND status = 'CLOSED' AND opened_at > :since AND engines->'live'->>'roi' IS NOT NULL
""")


def num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def main():
    db = SessionLocal()
    rows = []
    try:
        res = db.execute(SQL, {"since": datetime.now(timezone.utc) - timedelta(days=DAYS)},
                         execution_options={"stream_results": True})
        for r in res:
            roi = num(r.roi)
            if roi is None or r.side not in ("LONG", "SHORT"):
                continue
            mb = num(r.mb)
            rows.append((str(r.rule), r.side, r.opened_at, r.d, roi, mb if mb is not None and 0 <= mb <= 1 else None, num(r.chg_24h)))
    finally:
        db.close()
    p = SC.clean_params()
    lo, hi = p["lo"], p["hi"]

    # 날짜·칸별 집계 (학습용) — strategy_council.pick 과 같은 기준
    base_db = defaultdict(lambda: [0, 0.0])
    cell_day = defaultdict(lambda: [0, 0.0])
    by_day_rows = defaultdict(list)
    for rule, side, at, d, roi, mb, chg in rows:
        b = SC.bucket(mb, lo, hi)
        if rule.startswith(SC.BASE_PREFIX):
            x = base_db[(side, d, b)]; x[0] += 1; x[1] += roi   # noqa: E702
        else:
            c = cell_day[(rule, side, b, d)]; c[0] += 1; c[1] += roi   # noqa: E702
        by_day_rows[d].append((at, rule, side, b, roi, mb, chg))
    days = sorted(by_day_rows)

    def pick(D):
        start, end = D - timedelta(days=p["gap"] + p["train_days"] - 1), D - timedelta(days=p["gap"])
        agg = defaultdict(lambda: [0, 0.0, 0, 0.0])
        covered = {d for (_r, _s, _b, d) in cell_day if start <= d <= end}
        for (rule, side, b, d), (n, s) in cell_day.items():
            if start <= d <= end:
                a = agg[(rule, side, b)]; a[0] += n; a[1] += s   # noqa: E702
                bm = base_db.get((side, d, b))
                if bm and bm[0]:
                    a[2] += n; a[3] += s - n * (bm[1] / bm[0])
        sel = {k for k, a in agg.items() if a[0] >= p["min_n"] and a[1] / a[0] > 0 and a[2] and a[3] / a[2] > 0}
        return sel, len(covered) >= (p["train_days"] + 1) // 2

    pol = defaultdict(lambda: defaultdict(list))     # policy → side → [roi...]
    daily = []
    for D in days:
        sel, ok = pick(D)
        if not ok:
            continue
        rs = sorted(by_day_rows[D], key=lambda x: x[0])
        line = {"d": D.isoformat()}
        for side in ("LONG", "SHORT"):
            insel = [x for x in rs if x[2] == side and (x[1], side, x[3]) in sel]
            for k, nm in ((1, "A1"), (3, "A3")):
                for x in insel[:k]:
                    pol[nm][side].append(x[4])
            if insel:
                line[f"A1_{side}"] = round(insel[0][4], 2)
            want = LIVE_RULES[side]
            cond = (lambda x: x[5] is not None and x[5] < 0.4) if side == "LONG" else (lambda x: x[6] is not None and x[6] >= 10)
            liv = [x for x in rs if x[1] == want and x[2] == side and cond(x)]
            if liv:
                pol["L"][side].append(liv[0][4]); line[f"L_{side}"] = round(liv[0][4], 2)   # noqa: E702
            bas = [x for x in rs if x[1].startswith(SC.BASE_PREFIX) and x[2] == side]
            if bas:
                pol["무작위"][side].append(bas[0][4])
        daily.append(line)

    print(f"# 운영팀 배치 「하루 1건」 재기 — 가상 끝난 행 {len(rows):,} · 채점 날 {len(daily)}일 · 순수익 = roi − {NET}")
    print("| 정책 | 방향 | 건 | 평균 roi | 순수익 | 이긴 비율 | 최악 |")
    print("|---|---|---|---|---|---|---|")
    for nm in ("A1", "A3", "L", "무작위"):
        for side in ("LONG", "SHORT"):
            v = pol[nm][side]
            if v:
                m = sum(v) / len(v)
                print(f"| {nm} | {side} | {len(v)} | {m:+.2f} | {m - NET:+.2f} | {sum(x > 0 for x in v) / len(v):.0%} | {min(v):+.1f} |")
    print("\n## 날짜별 (A1 = 운영팀 첫 1건 · L = 지금 실주문 규칙 첫 1건)")
    for x in daily:
        print(x)


main()
