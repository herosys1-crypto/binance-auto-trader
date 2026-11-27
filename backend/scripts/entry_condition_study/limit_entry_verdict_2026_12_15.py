"""지정가 진입 그림자 판정 (사전등록 2026-11-27 · 판정일 2026-12-15 · D-119 · D-139) — 운영 DB 읽기 전용.

질문: Fix 488 `live_lmt`(종가 지정가 · 1봉 유효)가 실제 가상매매에서 시장가(`live`)보다 나은가.
대상: 기준선 행 baseline_LONG/SHORT · status CLOSED · engines 에 live_lmt 있음 · 진입 FROM ~ UNTIL(UTC).
순수익: 시장가 = live.roi − 0.40 · 지정가 = live_lmt.roi − 0.24 (체결된 행만, 미체결 = 0 = 거래 없음).
단위: 「칸」 = 같은 진입봉(entry_bar_ts) 묶음 (기준선은 3시간마다 한 봉) — 날짜는 봉 수가 들쭉날쭉해서(11/22 = 봉 1개) 칸 단위로 본다.

사전등록 통과 기준 (Claude가 정함 · 11/27 — 판정일에 바꾸지 않는다):
  P1 체결률 ≥ 90%
  P2 신호당 (지정가 − 시장가) 평균 > 0, 칸 단위 부트스트랩(2,000회) 90% 하한 > 0
  P3 지정가가 나은 칸 ≥ 60%
  P4 꼬리: 체결률 하위 5% 칸들의 신호당 (지정가 − 시장가) 평균 ≥ −3.0  (11/22 21:00 급등 봉 LONG −2.50 을 기준으로 그보다 크게 나쁘면 실패)
  네 개 모두 통과 = 「채택 후보」(실주문 진입 방식을 지정가로 · 켜기는 사장님) · 하나라도 실패 = 「기각」(그림자 끄기).
  어느 쪽이든 자동매매 재가동 근거는 아니다 — 지정가는 비용 절감이지 방향 우위가 아니다(D-139).

실행 (서버, 읽기만):
  ssh … "cd ~/binance-auto-trader/backend && docker compose exec -T api python -" < scripts/entry_condition_study/limit_entry_verdict_2026_12_15.py
"""
from __future__ import annotations

import random
import statistics as st
from collections import defaultdict

from sqlalchemy import text

from app.core.database import SessionLocal

FROM, UNTIL = "2026-11-09", "2026-12-15"
COST_MKT, COST_LMT = 0.40, 0.24
P1_FILL, P3_SHARE, P4_TAIL, TAIL_Q, BOOT = 90.0, 60.0, -3.0, 0.05, 2000

Q = text("""
SELECT side, entry_bar_ts b, engines->'live'->>'roi' lr,
       engines->'live_lmt'->>'filled' f, engines->'live_lmt'->>'roi' mr
FROM paper_trades
WHERE rule IN ('baseline_LONG','baseline_SHORT') AND status='CLOSED' AND engines ? 'live_lmt'
  AND opened_at >= :a AND opened_at < :z
""")


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def summarize(rows):
    """rows = (side, bar, live_roi, filled, lmt_roi). 반환 = 판정 dict (순수 함수 — 시험용)."""
    cells = defaultdict(lambda: [0, 0, 0.0, 0.0])        # bar → [n, filled, mkt_sum, lmt_sum]
    n = nf = 0
    for side, bar, lr, f, mr in rows:
        m = _num(lr)
        if m is None:
            continue
        filled = f in (True, "true")
        lv = _num(mr) if filled else None
        if filled and lv is None:
            continue
        c = cells[bar]
        c[0] += 1
        c[2] += m - COST_MKT
        if filled:
            c[1] += 1
            c[3] += lv - COST_LMT
        n += 1
        nf += filled
    if not n:
        return {"n": 0, "verdict": "자료 없음"}
    diffs = {b: (c[3] - c[2]) / c[0] for b, c in cells.items()}
    fills = {b: c[1] / c[0] for b, c in cells.items()}
    tot_m = sum(c[2] for c in cells.values()) / n
    tot_l = sum(c[3] for c in cells.values()) / n
    keys = list(cells)
    rnd = random.Random(20261215)
    boots = []
    for _ in range(BOOT):
        pick = [rnd.choice(keys) for _ in keys]
        s_n = sum(cells[k][0] for k in pick)
        boots.append(sum(cells[k][3] - cells[k][2] for k in pick) / s_n)
    boots.sort()
    lo90 = boots[int(0.05 * BOOT)]
    k_tail = max(1, int(round(TAIL_Q * len(keys))))
    tail = sorted(keys, key=lambda k: fills[k])[:k_tail]
    tail_diff = sum(cells[k][3] - cells[k][2] for k in tail) / sum(cells[k][0] for k in tail)
    share = 100.0 * sum(1 for d in diffs.values() if d > 0) / len(diffs)
    fill_pct = 100.0 * nf / n
    checks = {
        "P1 체결률≥90%": fill_pct >= P1_FILL,
        "P2 평균>0·90%하한>0": (tot_l - tot_m) > 0 and lo90 > 0,
        "P3 나은 칸≥60%": share >= P3_SHARE,
        "P4 하위5% 칸≥−3.0": tail_diff >= P4_TAIL,
    }
    return {
        "n": n, "cells": len(keys), "fill_pct": round(fill_pct, 2),
        "mkt_per_signal": round(tot_m, 4), "lmt_per_signal": round(tot_l, 4),
        "diff": round(tot_l - tot_m, 4), "diff_lo90": round(lo90, 4),
        "better_cells_pct": round(share, 1), "tail_cells": k_tail, "tail_diff": round(tail_diff, 4),
        "checks": checks, "verdict": "채택 후보" if all(checks.values()) else "기각",
    }


def main():
    with SessionLocal() as s:
        s.execute(text("SET statement_timeout='180s'"))
        rows = [(r.side, r.b, r.lr, r.f, r.mr) for r in s.execute(Q, {"a": FROM, "z": UNTIL})]
    for side in ("LONG", "SHORT", None):
        R = [r for r in rows if side is None or r[0] == side]
        out = summarize(R)
        print(f"[{side or '전체'}]", {k: v for k, v in out.items() if k != "checks"})
        if side is None:
            for k, v in out.get("checks", {}).items():
                print("  ", "✅" if v else "❌", k)
            print("판정(전체 기준):", out["verdict"])


if __name__ == "__main__":
    main()
