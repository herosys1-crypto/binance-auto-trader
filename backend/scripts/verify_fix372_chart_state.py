"""📐 Fix 372 배포 검사 — 일봉·5분·1분 차트 상태 기록 + 진입 타이밍 채점. **읽기 전용** (DB 쓰기 없음).

VPS:  docker compose exec -T scheduler python scripts/verify_fix372_chart_state.py
로컬:  python scripts/verify_fix372_chart_state.py --code-only
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
CODE_ONLY = "--code-only" in sys.argv
_fails: list[str] = []


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def fail(msg: str) -> None:
    _fails.append(msg)
    print(f"  ❌ {msg}")


def _read(rel: str) -> str:
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
        return f.read()


def check_code() -> None:
    print("① 코드 층")
    pw = _read("app/workers/paper_trading_worker.py")
    i_mb, i_cs = pw.find('t["snapshot"]["market_breadth"] = breadth'), pw.find('t["snapshot"]["chart_state"] = _cs')
    (ok if 0 < i_mb < i_cs else fail)("가상매매: 규칙 발동 진입에 chart_state 기록")
    (ok if '"chart_state": _chart_state_block(client, strategy, klines)' in _read("app/workers/learning_sync_worker.py") else fail)(
        "실거래 학습: entry_context.chart_state 기록")
    (ok if 'guarded_job("chart_timing", 900, _chart_timing)' in _read("app/workers/scheduler_runner.py") else fail)("스케줄: chart_timing 30분")
    (ok if '@router.get("/chart-state.md"' in _read("app/api/v1/paper_trading.py") else fail)("API: /paper-trading/chart-state.md")
    try:
        from app.services import chart_state as CS
        up = [[k * CS.MS["1d"], 100, 101, 99, 100 + (k % 3), 1.0] for k in range(40)] + [[40 * CS.MS["1d"], 102, 121, 101, 120, 1.0]]
        s = CS.bb_state(up, tol_pct=0.5, lookback=5, slope_pct=1.0)
        (ok if s["state"] == "UPPER_BREAKOUT" else fail)(f"판정 모듈 동작 (합성 상단 돌파 → {s['state']})")
    except Exception as e:  # noqa: BLE001
        fail(f"chart_state import/판정 실패: {e!r}")


def check_process() -> None:
    print("② 프로세스 층")
    try:
        with open("/proc/stat") as f:
            btime = int(next(l for l in f if l.startswith("btime")).split()[1])
        with open("/proc/1/stat") as f:
            start_ticks = int(f.read().rsplit(")", 1)[1].split()[19])
        start = btime + start_ticks / os.sysconf(os.sysconf_names["SC_CLK_TCK"])
    except Exception as e:  # noqa: BLE001
        print(f"  ⏭ 확인 불가 (로컬?): {e}")
        return
    newest = max(os.path.getmtime(os.path.join(_ROOT, p)) for p in (
        "app/services/chart_state.py", "app/workers/paper_trading_worker.py", "app/workers/learning_sync_worker.py",
        "app/workers/chart_timing_worker.py", "app/workers/scheduler_runner.py"))
    (ok if start >= newest else fail)(
        f"프로세스 시작 {datetime.fromtimestamp(start, tz=timezone.utc):%m-%d %H:%M} UTC ≥ 파일 수정 "
        f"{datetime.fromtimestamp(newest, tz=timezone.utc):%m-%d %H:%M} UTC (아니면 restart)")


def check_ops() -> None:
    print("③ 운영 층 (읽기 전용)")
    from sqlalchemy import func, select
    from app.core.database import SessionLocal
    from app.models.paper_trade import PaperTrade as P
    from app.models.trade_learning_record import TradeLearningRecord as T
    from app.services import chart_state as CS
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        print(f"  ▸ {CS.S_ENABLED}={CS.setting_on(db, CS.S_ENABLED, True)} · {CS.S_1M}={CS.setting_on(db, CS.S_1M, True)}")
        opened = db.execute(select(func.count()).where(P.source == "live", P.opened_at >= now - timedelta(hours=6))).scalar()
        with_cs = db.execute(select(func.count()).where(P.source == "live", P.opened_at >= now - timedelta(hours=6),
                                                        P.snapshot["chart_state"].isnot(None))).scalar()
        print(f"  ▸ 최근 6시간 가상 진입 {opened}건 중 chart_state 기록 {with_cs}건")
        (ok if opened == 0 or with_cs > 0 else fail)("가상 진입에 차트 상태가 붙는다")
        states = db.execute(
            select(P.snapshot["chart_state"]["d1"]["bb"]["state"].astext, func.count())
            .where(P.opened_at >= now - timedelta(hours=24), P.snapshot["chart_state"].isnot(None))
            .group_by(1).order_by(func.count().desc()).limit(8)
        ).all()
        print(f"  ▸ 24시간 일봉 상태 분포: {', '.join(f'{s}={n}' for s, n in states) or '-'}")
        pl = db.execute(select(func.count()).where(P.snapshot["chart_timing"]["label"].isnot(None),
                                                   P.opened_at >= now - timedelta(days=3))).scalar()
        rl = db.execute(select(func.count()).where(T.insights["chart_timing"].isnot(None))).scalar()
        print(f"  ▸ 타이밍 채점: 가상(3일) {pl}건 · 실거래 {rl}건 (배포 30분 뒤부터 쌓임)")
        real_cs = db.execute(select(func.count()).where(T.entry_context["chart_state"].isnot(None))).scalar()
        print(f"  ▸ 실거래 진입 기록 중 chart_state 있는 것 {real_cs}건 (자동매매 중단 중이라 새 진입이 적다)")
    finally:
        db.close()


if __name__ == "__main__":
    print(f"verify_fix372_chart_state — {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC")
    check_code()
    if not CODE_ONLY:
        check_process()
        check_ops()
    print("─" * 70)
    print(f"결과: {'FAIL ' + str(len(_fails)) + '건' if _fails else 'PASS'}")
    sys.exit(1 if _fails else 0)
