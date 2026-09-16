"""🎛 Fix 374 배포 검사 — 자동매매 관제실. **읽기 전용** (설정을 만들지도 고치지도 않는다).

VPS:  docker compose exec -T api python scripts/verify_fix374_auto_control.py
로컬:  python scripts/verify_fix374_auto_control.py --code-only

3층으로 본다 (CLAUDE.md 6): ① 코드 ② 프로세스(파일 수정 시각 vs 프로세스 시작 시각) ③ 운영(실제 설정값·건수).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

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


WATCH = ("app/services/auto_control.py", "app/services/auto_control_state.py", "app/services/worker_switch.py",
         "app/api/v1/auto_control.py", "app/api/router.py", "app/workers/auto_short_at_top_worker.py",
         "app/workers/auto_long_at_bottom_worker.py", "app/workers/realtime_reentry_worker.py",
         "app/workers/resistance_reversal_worker.py", "app/workers/peak_break_reversal_worker.py",
         "app/workers/ladder_restart_worker.py")

SWITCH_PINS = (
    ("app/workers/auto_short_at_top_worker.py", "sajangnim_top_short_enabled"),
    ("app/workers/auto_long_at_bottom_worker.py", "sajangnim_bottom_long_enabled"),
    ("app/workers/realtime_reentry_worker.py", "realtime_reentry_enabled"),
    ("app/workers/resistance_reversal_worker.py", "resistance_reversal_enabled"),
    ("app/workers/peak_break_reversal_worker.py", "peak_break_reversal_enabled"),
    ("app/workers/ladder_restart_worker.py", "ladder_restart_enabled"),
)


def check_code() -> None:
    print("① 코드 층")
    (ok if "auto_control_router" in _read("app/api/router.py") else fail)("API 등록: /api/v1/auto-control/*")
    page = _read("app/static/auto-control.html")
    (ok if "/static/js/auto-control.js" in page else fail)("화면: auto-control.html → auto-control.js")
    (ok if "openAutoControl" in _read("app/static/index.html") else fail)("입구: 운영 대시보드 상단 「🎛 자동매매」")
    for rel, key in SWITCH_PINS:
        src = _read(rel)
        (ok if f'"{key}"' in src and "worker_switch" in src else fail)(f"워커 스위치: {os.path.basename(rel)} → {key}")
    try:
        from app.services import auto_control as AC
        ps = AC.panels()
        rule = [p for p in ps if p.group == AC.G_RULE]
        (ok if len(rule) == 12 else fail)(f"규칙 가족 12종 등록 (지금 {len(rule)}종)")
        (ok if not [p for p in ps if p.gate is None] else fail)("모든 가족에 켜기/끄기 칸이 있다")
        print(f"  ▸ 가족 {len(ps)}종 · 다룰 수 있는 설정 {len(AC.whitelist())}칸")
    except Exception as e:  # noqa: BLE001
        fail(f"레지스트리 import 실패: {e!r}")


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
    from app.core.database import SessionLocal
    from app.services.auto_control_state import build
    db = SessionLocal()
    try:
        s = build(db)
        c = s["summary"]
        print(f"  ▸ 전면 중단 = {s['halted']}" + (f" ({s['halt_reason']})" if s["halt_reason"] else ""))
        print(f"  ▸ 실주문 on {c['on']}종 · 그림자 {c['shadow']}종 · 끔 {c['off']}종 (합 {c['total']})")
        print(f"  ▸ 오늘(KST) 자동 진입 {c['entered_today']}건 · 지금 보유 {c['live_now']}건")
        if s["kill_switches"]:
            print(f"  ▸ 🛑 Kill-Switch 작동 계정: {[k['account_id'] for k in s['kill_switches']]}")
        (ok if not s["count_error"] else fail)(f"건수 집계 정상{'' if not s['count_error'] else ': ' + s['count_error']}")
        on = [p["label"] for p in s["panels"] if p["state"] == "on"]
        print(f"  ▸ on 인 가족: {', '.join(on) if on else '없음'}")
        if not s["halted"] and on:
            print("  ⚠ 중단이 풀려 있고 on 인 가족이 있다 = 조건이 맞으면 실주문이 나간다 (사장님 의도인지 확인)")
        miss = [g["key"] for g in s["globals"] if g["is_default"]]
        print(f"  ▸ 행이 없어 기본값으로 도는 전체 설정: {', '.join(miss) if miss else '없음'}")
    finally:
        db.close()


if __name__ == "__main__":
    print(f"verify_fix374_auto_control — {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC")
    check_code()
    if not CODE_ONLY:
        check_process()
        check_ops()
    print("─" * 70)
    print(f"결과: {'FAIL ' + str(len(_fails)) + '건' if _fails else 'PASS'}")
    sys.exit(1 if _fails else 0)
