"""🎯 Fix 375·376 배포 검사 — 차트 자리 진입 게이트 (규칙 가족 + 실매매 워커). **읽기 전용**.

VPS:  docker compose exec -T scheduler python scripts/verify_fix375_entry_gate.py
로컬:  python scripts/verify_fix375_entry_gate.py --code-only
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
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


WATCH = ("app/services/chart_state.py", "app/services/entry_conditions.py", "app/services/rule_families.py",
         "app/services/chart_gate_live.py", "app/services/strategy_service.py", "app/workers/managed_symbol_worker.py",
         "app/workers/rule_family_worker.py", "app/workers/paper_trading_worker.py", "app/services/paper_report_v3.py")


def check_code() -> None:
    print("① 코드 층")
    (ok if "hilo_position(bars, HILO_BARS" in _read("app/services/chart_state.py") else fail)("chart_state: from_hi_pct 기록")
    w = _read("app/workers/rule_family_worker.py")
    (ok if 'blocks.append("chart_gate")' in w and '"chart_gate": gate' in w else fail)("규칙 가족 워커: 게이트 판정·그림자 기록")
    (ok if "P5_short_near_high_not_d1_up" in _read("app/services/paper_report_v3.py") else fail)("보고서: P5·P6 사전등록 필터")
    ss = _read("app/services/strategy_service.py")
    (ok if ss.index("_chart_gate376(self.db") < ss.index("acct = client.get_account()") < ss.index("_daily_check(self.db") else fail)(
        "Fix 376 실매매: 전략 생성 지점 게이트 (계좌 조회·하루 최대 앞)")
    try:
        from app.services import chart_gate_live as CG
        (ok if CG.FORCE_MODE is None else fail)(f"Fix 376 테스트 훅 FORCE_MODE 비어 있음 (지금 {CG.FORCE_MODE!r})")
    except Exception as e:  # noqa: BLE001
        fail(f"chart_gate_live import 실패: {e!r}")
    try:
        from app.services import entry_conditions as EC
        from app.services import rule_families as RF
        s = {"chart_state": {"h1": {"from_hi_pct": -1}, "m5": {"from_hi_pct": 0}, "d1": {"bb": {"trend": "DOWN"}}}}
        (ok if EC.evaluate("SHORT", s)["verdict"] == "pass" and EC.evaluate("LONG", s, chg_24h=1)["verdict"] == "fail" else fail)(
            "판정 모듈 동작")
        (ok if all(RF.SETTINGS[f"{f.key}_chart_gate"][0] == "on" for f in RF.FAMILIES) else fail)("규칙 가족 12종 게이트 기본 on")
    except Exception as e:  # noqa: BLE001
        fail(f"import 실패: {e!r}")


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
    newest = max(os.path.getmtime(os.path.join(_ROOT, p)) for p in WATCH)
    (ok if start >= newest else fail)(
        f"프로세스 시작 {datetime.fromtimestamp(start, tz=timezone.utc):%m-%d %H:%M} UTC ≥ 파일 수정 "
        f"{datetime.fromtimestamp(newest, tz=timezone.utc):%m-%d %H:%M} UTC (아니면 restart api scheduler)")


def check_ops() -> None:
    print("③ 운영 층 (읽기 전용)")
    from sqlalchemy import func, select
    from app.core.database import SessionLocal
    from app.core.redis_client import get_redis_client
    from app.models.paper_trade import PaperTrade as P
    db = SessionLocal()
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=3)
        n = db.execute(select(func.count()).where(P.source == "live", P.opened_at >= since)).scalar()
        g = db.execute(select(func.count()).where(P.source == "live", P.opened_at >= since,
                                                  P.snapshot["chart_state"]["h1"]["from_hi_pct"].isnot(None))).scalar()
        print(f"  ▸ 최근 3시간 가상 진입 {n}건 중 from_hi_pct 기록 {g}건")
        (ok if n == 0 or g > 0 else fail)("가상 진입에 게이트 값이 붙는다 (배포 뒤 15분 이상 지나야 한다)")
    finally:
        db.close()
    try:
        r = get_redis_client()
        cnt: Counter = Counter()
        for i, k in enumerate(r.scan_iter(match="rf:shadow:*", count=1000)):
            if i > 5000:
                break
            raw = r.get(k)
            if not raw:
                continue
            p = json.loads(raw)
            gate = p.get("chart_gate")
            if gate:
                cnt[(p.get("side"), gate.get("verdict", gate.get("mode")))] += 1
        print(f"  ▸ 규칙 가족 그림자 기록의 게이트 판정: {dict(cnt) or '아직 없음 (새 신호가 와야 쌓인다)'}")
        live: Counter = Counter()
        for i, k in enumerate(r.scan_iter(match="chart_gate:live:*", count=500)):
            if i > 2000:
                break
            raw = r.get(k)
            if raw:
                live[json.loads(raw).get("verdict")] += 1
        print(f"  ▸ 실매매 차트 게이트 최근 5분 판정 캐시: {dict(live) or '없음 (자동매매 중단 중이면 생성 시도 자체가 없다)'}")
        from app.core.database import SessionLocal as _SL
        from app.services import auto_control as _AC
        from app.services.chart_gate_live import mode_for
        _db = _SL()
        try:
            modes = {p.fam: mode_for(_db, p.fam) for p in _AC.panels() if p.fam and not p.fam.startswith("rf_")}
        finally:
            _db.close()
        print(f"  ▸ 실매매 가족 게이트 모드: {modes}")
    except Exception as e:  # noqa: BLE001
        print(f"  ⏭ Redis 확인 생략: {e}")


if __name__ == "__main__":
    print(f"verify_fix375_entry_gate — {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC")
    check_code()
    if not CODE_ONLY:
        check_process()
        check_ops()
    print("─" * 70)
    print(f"결과: {'FAIL ' + str(len(_fails)) + '건' if _fails else 'PASS'}")
    sys.exit(1 if _fails else 0)
