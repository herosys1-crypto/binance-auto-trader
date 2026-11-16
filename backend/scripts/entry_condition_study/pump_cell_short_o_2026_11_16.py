"""가설 O — 급등 종목 SHORT 은 타이밍 신호 없이도 장세와 무관하게 버티는가 (2026-11-16 사전 등록 · 읽기 전용).

사장님 11/16 「가상매매의 실적을 바탕으로 어디서 손실인지 … 전략을 다시 개선해서 가상매매를 계속해서 보고서를」.

발견(9/14~11/16 · 64일 · 무작위 기준 거래 baseline_SHORT, live 엔진):
  종목의 24h 변동 ≥ +20% 인 자리의 무작위 SHORT 은 3구간(9/14~ · 10/05~ · 10/26~) 모두 플러스였다
  (+20~30%: 날 평균 +3.70 · +30~50%: +2.62 · ≥+50%: +1.58). 같은 첫 구간에 무작위 SHORT 전체는 −1.99.
  익절선 낮추기·손절 좁히기·눌림 진입은 방향에 따라 부호가 뒤집혀 기각. 트레일링 3%p 만 양쪽에서 +0.12~0.14.
  ⚠️ 10칸 × 2방향을 본 뒤 고른 칸이다(다중 비교) → **발견에 쓴 날은 채점에서 뺀다**.

판정(「Claude가 정함」 — 숫자를 바꾸려면 새 가설로 등록):
  채점 = 진입일(KST) ≥ SCORE_FROM(기본 2026-11-17) 인 baseline_SHORT 마감 행, 순수익 = roi − COST(0.4).
  O20 = 24h ≥ +20% · O30 = 24h ≥ +30%. 날 단위 평균의 평균으로 본다(건수 가중은 한 날 쏠림에 속는다).
  ✅ 통과: 채점 날 ≥ 20 · 날 평균 순수익의 90% 하한 > 0 · 상위 3일 뺀 평균 > 0
  ❌ 기각: 채점 날 ≥ 20 · 90% 상한 < 0  ·  그 밖(채점 날 20 미만 포함) = ⏳ 보류(날 더 쌓기)
  함께 본다: 같은 날 무작위 SHORT 전체와의 차 · 무작위 SHORT 전체가 마이너스였던 날의 성적(장세 무관한지) · 트레일 3%p.
  새 주문·설정 변경 없음. 통과해도 실주문은 그림자 가족 → 사장님 승인 순서.

실행(운영 서버, 읽기만):
  docker compose exec -T scheduler python - < scripts/entry_condition_study/pump_cell_short_o_2026_11_16.py
  발견 구간 재현: docker compose exec -T -e SCORE_FROM=2026-09-14 -e SCORE_TO=2026-11-16 scheduler python - < …
"""
from __future__ import annotations

import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, "/app")
from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402

COST = 0.4
SCORE_FROM = os.environ.get("SCORE_FROM", "2026-11-17")
SCORE_TO = os.environ.get("SCORE_TO", "2099-12-31")
MIN_DAYS = 20
CELLS = (("O20 (24h ≥ +20%)", 20.0), ("O30 (24h ≥ +30%)", 30.0))


def fm(x: float | None) -> str:
    return "—" if x is None else f"{x:+.2f}"


def day_means(rows, val) -> dict[str, float]:
    by: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        v = val(r)
        if v is not None:
            by[str(r.d)].append(v)
    return {k: sum(v) / len(v) for k, v in by.items()}


def boot90(xs: list[float]) -> tuple[float, float]:
    rnd = random.Random(16)
    b = sorted(sum(rnd.choice(xs) for _ in xs) / len(xs) for _ in range(2000))
    return b[100], b[1899]


def verdict(days: int, lo: float, hi: float, top3: float | None) -> str:
    if days < MIN_DAYS:                 # 자료가 모자라면 통과도 기각도 하지 않는다 (교차 검토 지적)
        return "⏳ 보류"
    if hi < 0:
        return "❌ 기각"
    if lo > 0 and top3 is not None and top3 > 0:
        return "✅ 통과"
    return "⏳ 보류"


def main() -> None:
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT (opened_at AT TIME ZONE 'Asia/Seoul')::date AS d, chg_24h::float AS chg,
                   (engines->'live'->>'roi')::float AS roi, (engines->'live_trail3'->>'roi')::float AS trail3,
                   engines->'live'->>'hit' AS hit
            FROM paper_trades
            WHERE source = 'live' AND status = 'CLOSED' AND rule = 'baseline_SHORT'
              AND engines->'live'->>'roi' IS NOT NULL
              AND (opened_at AT TIME ZONE 'Asia/Seoul')::date BETWEEN :a AND :b
        """), {"a": SCORE_FROM, "b": SCORE_TO}).fetchall()
        n_open = db.execute(text("""
            SELECT count(*) FROM paper_trades WHERE source = 'live' AND status = 'OPEN' AND rule = 'baseline_SHORT'
              AND chg_24h >= 20 AND (opened_at AT TIME ZONE 'Asia/Seoul')::date BETWEEN :a AND :b
        """), {"a": SCORE_FROM, "b": SCORE_TO}).scalar()
    finally:
        db.rollback()
        db.close()
    print(f"# 가설 O — 급등 종목 무작위 SHORT (채점 {SCORE_FROM} ~ {SCORE_TO if SCORE_TO < '2099' else '지금'} KST · 순수익 = roi − {COST})")
    print(f"무작위 SHORT 마감 {len(rows):,}건 · 아직 안 끝난 급등 칸 {n_open}건(표에 없음)")
    all_dm = day_means(rows, lambda r: r.roi - COST)
    if all_dm:
        print(f"무작위 SHORT 전체: 날 {len(all_dm)} · 날 평균 {fm(sum(all_dm.values()) / len(all_dm))} · 플러스 날 {sum(1 for v in all_dm.values() if v > 0)}")
    print("| 칸 | 건 | 날 | 날 평균 순수익 | 90% | 상위 3일 뺀 | 플러스 날 | 손절% | 전체 SHORT 대비 | 전체가 − 였던 날 | 트레일 3%p 차 | 판정 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for lab, th in CELLS:
        X = [r for r in rows if r.chg is not None and r.chg >= th]   # 전체 기준선에는 변동률 없는 행도 넣는다
        dm = day_means(X, lambda r: r.roi - COST)
        if len(dm) < 3:
            print(f"| {lab} | {len(X)} | {len(dm)} | — | — | — | — | — | — | — | — | ⏳ 보류(자료 없음) |")
            continue
        xs = list(dm.values())
        lo, hi = boot90(xs)
        top3 = sum(sorted(xs)[:-3]) / (len(xs) - 3) if len(xs) > 5 else None
        diff = [v - all_dm[k] for k, v in dm.items() if k in all_dm]
        bad = [v for k, v in dm.items() if all_dm.get(k, 0.0) < 0]
        t3 = day_means([r for r in X if r.trail3 is not None], lambda r: r.trail3 - r.roi)
        print(f"| {lab} | {len(X):,} | {len(xs)} | {fm(sum(xs) / len(xs))} | {fm(lo)}~{fm(hi)} | {fm(top3)} | {sum(1 for v in xs if v > 0)}/{len(xs)}"
              f" | {100 * sum(1 for r in X if r.hit == 'SL') / len(X):.0f}% | {fm(sum(diff) / len(diff)) if diff else '—'}"
              f" | {fm(sum(bad) / len(bad)) if bad else '—'} ({len(bad)}일) | {fm(sum(t3.values()) / len(t3)) if t3 else '—'} | {verdict(len(xs), lo, hi, top3)} |")
    print("\n읽는 법: 「전체가 − 였던 날」이 플러스면 방향(장세)에 기대지 않는다는 뜻. 가상은 펀딩비·급등 종목 손절 미끄러짐을 넣지 않았다.")


if __name__ == "__main__":
    main()
