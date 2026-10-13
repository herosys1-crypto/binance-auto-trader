"""🩺 10/17 중간 점검 (2026-10-13 사장님 「1번 진행해줘」) — 10/25 통합 판정(verdict_2026_10_25.py)까지 표본이 찰지 미리 본다. 읽기 전용.

운영 서버에서:  docker compose exec -T api python - < scripts/entry_condition_study/midcheck_2026_10_17.py
            (판정일을 바꿔 보려면 환경변수 VERDICT_DATE=2026-11-01)
일봉 캐시(Fix 446) 무게는 DB 밖(로그)이라 서버 셸에서:
    docker compose logs --since 3h scheduler | grep 'Fix361.*가상매매:' | grep ' 00:'

## 내용
  1 시장폭 — 날짜별 평균·최저·0.4 미만 비율 (LONG 장세 필터 = 시장폭 < 0.4)
  2 표본 진행 — 판정 대상마다 지금 (끝난 n · 일수 · 진행 중) → 판정일 예상 n · 일수 → 충분/부족 예상
  3 청산 방식 비교(Fix 447) 짝 수
  4 합의 LONG 진입 목록 (결과)
  5 일봉 캐시(Fix 446) Redis 키 수
예상은 「지금까지 진입 속도가 그대로」라는 가정 — 장세가 바뀌면(특히 LONG) 크게 달라진다.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, "/app")

CLOSE_LAG_DAYS = 2.0          # 가상 포지션 최대 48h — 판정일 직전 이틀 진입분은 아직 안 끝난다
VERDICT_DATE_DEFAULT = "2026-10-25"


def _load_verdict():
    cands = [Path("/app/scripts/entry_condition_study/verdict_2026_10_25.py")]       # stdin 실행(<stdin>) = 서버 경로
    if "__file__" in globals() and not str(__file__).startswith("<"):
        cands.insert(0, Path(__file__).resolve().parent / "verdict_2026_10_25.py")
    p = next((c for c in cands if c.exists()), cands[-1])
    spec = importlib.util.spec_from_file_location("verdict_2026_10_25_mid", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def project(n_opened: int, elapsed_days: float, to_verdict_days: float) -> float:
    """지금까지 진입 속도로 판정일까지 「끝난」 n 예상 (마지막 이틀 진입분은 아직 진행 중으로 뺀다)."""
    if elapsed_days <= 0:
        return 0.0
    usable = max(0.0, to_verdict_days - CLOSE_LAG_DAYS)
    return n_opened / elapsed_days * usable


def project_days(entry_days: int, elapsed_days: float, to_verdict_days: float, calendar_days: int) -> int:
    """판정일까지 「진입이 있었던 날」 수 예상 — 장세 의존 규칙(LONG)은 몰린 날만 들어오므로 달력 일수보다 작다."""
    if elapsed_days <= 0 or entry_days <= 0:
        return 0
    rate = min(1.0, entry_days / max(1.0, elapsed_days))
    return min(calendar_days, int(round(rate * max(0.0, to_verdict_days - CLOSE_LAG_DAYS))))


def status(n_closed: int, n_opened: int, proj_n: float, proj_days: int, min_n: int, min_days: int) -> str:
    if n_opened == 0:
        return "— 진입 0 (장세 대기)"
    if n_closed >= min_n and proj_days >= min_days:
        return "✅ 충분"
    if proj_n >= min_n and proj_days >= min_days:
        return "✅ 충분 예상"
    return "⚠️ 부족 예상"


def main() -> None:  # pragma: no cover — 운영 DB 필요
    from sqlalchemy import text
    from app.core.database import SessionLocal
    from app.core.redis_client import get_redis_client
    from app.services import rule_families as RF

    V = _load_verdict()
    now = datetime.now(timezone.utc)
    vd = date.fromisoformat(os.environ.get("VERDICT_DATE", VERDICT_DATE_DEFAULT))
    vdt = datetime(vd.year, vd.month, vd.day, tzinfo=timezone.utc)
    earliest = min(datetime.fromisoformat(v) for v in V.CUTOFFS.values())
    db = SessionLocal()
    try:
        rows = [dict(r._mapping) for r in db.execute(text(
            """select rule, side, status, opened_at, opened_at::date d, chg_24h, snapshot->>'market_breadth' mb,
                      (engines->'live'->>'roi')::float roi
               from paper_trades where source='live' and opened_at >= :since"""), {"since": earliest})]
        print(f"# 🩺 중간 점검 — {now:%Y-%m-%d %H:%M} UTC · 판정일 {vd} (남은 {(vdt - now).total_seconds() / 86400:.1f}일)\n")

        print("## 1. 시장폭 (LONG 장세 필터 = 0.4 미만)\n| 날짜 | 평균 | 최저 | 0.4 미만 진입 비율 | 진입 수 |\n|---|---|---|---|---|")
        by_d: dict = defaultdict(list)
        for r in rows:
            b = V._f(r["mb"])
            if b is not None:
                by_d[r["d"]].append(b)
        for d in sorted(by_d):
            xs = by_d[d]
            print(f"| {d} | {sum(xs) / len(xs):.3f} | {min(xs):.3f} | {sum(1 for x in xs if x < 0.4) / len(xs):.0%} | {len(xs)} |")

        print("\n## 2. 표본 진행 — 판정 기준 끝난 n ≥ 30 · 7일 이상 (장세 필터 안 기준)\n"
              "| 대상 | 끝난 n | 일수 | 진행 중 | 진입한 날 | 판정일 예상 끝난 n | 판정일 예상 일수 | 상태 |\n|---|---|---|---|---|---|---|---|")
        targets: list[tuple[str, str, str, bool]] = []                 # (이름, rule, cutoff 키, 필터 적용)
        targets += [(r_, r_, ck, False) for r_, ck in V.NEW_RULES.items()]
        targets += [(f"{f.key} · 필터 안", f.rule, "regime", True) for f in RF.FAMILIES if f.rule not in V.NEW_RULES]
        ext_rules = sorted({r["rule"] for r in rows if any(r["rule"].startswith(p) for p in V.EXT_PREFIX)})
        targets += [(f"{r_} · 필터 안", r_, next(v for p, v in V.EXT_PREFIX.items() if r_.startswith(p)), True) for r_ in ext_rules]
        summary = defaultdict(int)
        for name, rule, ck, filt in targets:
            cut = datetime.fromisoformat(V.CUTOFFS[ck])
            xs = [r for r in rows if r["rule"] == rule and r["opened_at"] >= cut
                  and (not filt or V.regime_ok(r["side"], r["mb"], r["chg_24h"]) is True)]
            closed = [r for r in xs if r["status"] == "CLOSED" and r["roi"] is not None]
            n_open = sum(1 for r in xs if r["status"] == "OPEN")
            elapsed = (now - cut).total_seconds() / 86400
            proj = project(len(xs), elapsed, (vdt - cut).total_seconds() / 86400)
            entry_days = len({r["d"] for r in xs})
            proj_days = project_days(entry_days, elapsed, (vdt - cut).total_seconds() / 86400, (vd - cut.date()).days)
            st = status(len(closed), len(xs), proj, proj_days, V.CRIT["min_n"], V.CRIT["min_days"])
            summary[st.split(" ")[0]] += 1
            print(f"| {name} | {len(closed)} | {len({r['d'] for r in closed})} | {n_open} | {entry_days} | {proj:.0f} | {proj_days} | {st} |")
        print("\n요약: " + " · ".join(f"{k} {v}" for k, v in summary.items()))

        print("\n## 3. 청산 방식 비교(Fix 447) — 끝난 짝 수 (판정 기준 짝 n ≥ 30)")
        for eng in V.EXIT_ENGINES:
            n = db.execute(text(f"""select count(*) from paper_trades where source='live' and status='CLOSED'
                                    and engines->'{eng}'->>'roi' is not null and engines->'live_trend' is not null""")).scalar()
            print(f"- {eng}: {n}")

        print("\n## 4. 🤝 합의 LONG 진입\n| 진입(UTC) | 상태 | live roi | 시장폭 |\n|---|---|---|---|")
        con = [r for r in rows if r["rule"] == "consensus_long"]
        for r in sorted(con, key=lambda r: r["opened_at"]):
            print(f"| {r['opened_at']:%m-%d %H:%M} | {r['status']} | {V._fmt(r['roi'])} | {r['mb']} |")
        closed_c = [r["roi"] for r in con if r["status"] == "CLOSED" and r["roi"] is not None]
        if closed_c:
            print(f"\n끝난 {len(closed_c)}건 평균 {sum(closed_c) / len(closed_c):+.2f}% · 이긴 비율 {sum(1 for x in closed_c if x > 0) / len(closed_c):.0%}")

        print("\n## 5. 일봉 캐시 (Fix 446)")
        try:
            r = get_redis_client()
            cnt = defaultdict(int)
            for k in r.scan_iter("kc:*", count=1000):
                cnt[str(k).split(":")[1]] += 1
            print("Redis 키: " + (" · ".join(f"{p} {n}" for p, n in sorted(cnt.items())) or "없음"))
        except Exception as e:  # noqa: BLE001
            print(f"Redis 조회 실패: {e}")
        print("일봉 마감 사이클 무게 = 서버 셸에서 (파일 머리 명령) — 00:0x 사이클 「봉 무게」 가 ≈1,821 이하면 효과(전 2,428)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
