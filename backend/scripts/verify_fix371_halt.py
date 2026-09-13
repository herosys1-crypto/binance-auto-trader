"""⛔📉 Fix 371 배포 검사 — 자동매매 중단 게이트 + 손실 원인 학습. **읽기 전용** (DB 쓰기 없음).

VPS:  docker compose exec -T api python scripts/verify_fix371_halt.py            (코드·프로세스·운영)
      docker compose exec -T scheduler python scripts/verify_fix371_halt.py      (워커 쪽 프로세스 시각)
로컬:  python scripts/verify_fix371_halt.py --code-only
"""
from __future__ import annotations

import ast
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


def _fn_src(src: str, name: str) -> str:
    node = next((n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == name), None)
    return ast.get_source_segment(src, node) if node else ""


def check_code() -> None:
    print("① 코드 층")
    es = _read("app/services/execution_service.py")
    for name, order_call in (("start_stage1", "self._place_stage_entry_order("), ("trigger_next_stage", "self._trim_before_stage("),
                             ("enter_stage_at_market", "self._place_market_entry("), ("add_position_now", "self._place_market_entry(")):
        b = _fn_src(es, name)
        i_ks, i_h, i_o = b.find("AccountKillSwitchService(self.db).is_enabled("), b.find("_halt371.check_order("), b.find(order_call)
        (ok if 0 < i_ks < i_h < i_o else fail)(f"execution_service.{name}: Kill-Switch → 중단 게이트 → 주문")
    lc = _read("app/api/v1/strategies/lifecycle.py")
    (ok if 'origin="manual"' in _fn_src(lc, "add_position_to_strategy") else fail)("💉 포지션 추가 엔드포인트 origin=manual")
    ss = _fn_src(_read("app/services/strategy_service.py"), "create_strategy_instance")
    (ok if 0 < ss.find("_halt_create371(") < ss.find("instance = StrategyInstance(") and "entry_origin=(entry_origin or None)" in ss else fail)(
        "전략 생성: 중단 게이트 → 인스턴스 · entry_origin 저장")
    (ok if 'guarded_job("loss_cause", 600, _loss_cause)' in _read("app/workers/scheduler_runner.py") else fail)("스케줄: loss_cause 매시간")
    (ok if '@router.get("/loss-causes")' in _read("app/api/v1/trade_learning.py") else fail)("API: GET /trade-learning/loss-causes")
    try:
        from app.services import auto_trading_halt as H
        from types import SimpleNamespace as NS

        class _Empty:
            def get(self, *_a):
                return None
        blocked = False
        try:
            H.check_order(_Empty(), NS(id=0, symbol="X", entry_origin=None, entry_profile="obv_auto"), action="stage2")
        except ValueError:
            blocked = True
        (ok if H.halt_enabled(_Empty()) and blocked else fail)("설정 행 없음 = 중단 · obv_auto 복제본 차단")
    except Exception as e:  # noqa: BLE001
        fail(f"게이트 모듈 import 실패: {e!r}")


def check_process() -> None:
    print("② 프로세스 층 (이 컨테이너가 새 코드로 떠 있나)")
    try:
        with open("/proc/stat") as f:
            btime = int(next(l for l in f if l.startswith("btime")).split()[1])
        with open("/proc/1/stat") as f:
            start_ticks = int(f.read().rsplit(")", 1)[1].split()[19])
        start = btime + start_ticks / os.sysconf(os.sysconf_names["SC_CLK_TCK"])
    except Exception as e:  # noqa: BLE001
        print(f"  ⏭ 프로세스 시각 확인 불가 (로컬?): {e}")
        return
    newest = max(os.path.getmtime(os.path.join(_ROOT, p)) for p in (
        "app/services/auto_trading_halt.py", "app/services/execution_service.py", "app/services/strategy_service.py",
        "app/services/loss_cause.py", "app/workers/scheduler_runner.py"))
    s = datetime.fromtimestamp(start, tz=timezone.utc)
    m = datetime.fromtimestamp(newest, tz=timezone.utc)
    (ok if start >= newest else fail)(f"프로세스 시작 {s:%m-%d %H:%M:%S} UTC ≥ 파일 수정 {m:%m-%d %H:%M:%S} UTC (아니면 restart 필요)")


def check_ops() -> None:
    print("③ 운영 층 (읽기 전용)")
    from sqlalchemy import inspect, select
    from app.core.database import SessionLocal, engine
    from app.core.strategy_status import TERMINAL_STATUSES
    from app.models.account_kill_switch import AccountKillSwitch
    from app.models.strategy_instance import StrategyInstance
    from app.models.system_setting import SystemSetting
    from app.services import auto_trading_halt as H
    from app.services import loss_cause as LC
    cols = {c["name"] for c in inspect(engine).get_columns("strategy_instances")}
    (ok if "entry_origin" in cols else fail)("alembic 0040: strategy_instances.entry_origin 컬럼")
    db = SessionLocal()
    try:
        from sqlalchemy import text
        ver = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        (ok if ver == "0040_si_entry_origin" else fail)(f"alembic_version = {ver}")
        row = db.get(SystemSetting, H.HALT_KEY)
        print(f"  ▸ {H.HALT_KEY} = {None if row is None else row.value!r} → {'중단' if H.halt_enabled(db) else '⚠️ 자동매매 재개 상태'}")
        for ks in db.execute(select(AccountKillSwitch)).scalars().all():
            print(f"  ▸ Kill-Switch 계정 #{ks.exchange_account_id}: {'켜짐' if ks.is_enabled else '꺼짐'} ({ks.reason_code})")
        if "entry_origin" in cols:
            rows = db.execute(
                select(StrategyInstance).where(StrategyInstance.status.not_in(sorted(TERMINAL_STATUSES)),
                                               StrategyInstance.is_archived.is_(False)).order_by(StrategyInstance.id)
            ).scalars().all()
            print(f"  ▸ 종료 안 된 전략 {len(rows)}건 (중단 중 자동 단계 허용 = entry_origin manual_modal · 사람 버튼은 모두 허용)")
            for si in rows:
                allowed = H.is_manual_strategy(si)
                tpl = getattr(si, "strategy_template", None)
                print(f"     #{si.id:<5} {si.symbol:<14} {si.side:<5} {si.status:<22} profile={si.entry_profile or '-':<13} "
                      f"origin={si.entry_origin or '-':<12} 템플릿={getattr(tpl, 'name', '-')!s:<28} "
                      f"유형={getattr(tpl, 'strategy_type', '-')!s:<16} {'✅ 자동 단계 허용' if allowed else '⛔ 자동 단계 차단'}")
            from app.models.order import Order
            pending = db.execute(
                select(Order, StrategyInstance).join(StrategyInstance, StrategyInstance.id == Order.strategy_instance_id)
                .where(Order.purpose == "ENTRY", Order.status.in_(("NEW", "PARTIALLY_FILLED")))
            ).all()
            print(f"  ▸ 거래소에 걸려 있는 진입 주문 (DB 기준) {len(pending)}건 — 게이트는 새 주문만 막는다, 원치 않으면 사장님이 취소")
            for o, si in pending:
                print(f"     주문 #{o.id} 전략 #{si.id} {si.symbol} {o.order_type} {o.price} qty={o.orig_qty} 단계={o.stage_no} "
                      f"origin={si.entry_origin or '-'} {o.client_order_id}")
        rep = db.get(SystemSetting, LC.REPORT_KEY)
        print(f"  ▸ {LC.REPORT_KEY}: {'아직 없음 (워커 첫 사이클 전)' if rep is None else str(rep.value)[:160] + '…'}")
    finally:
        db.close()


if __name__ == "__main__":
    print(f"verify_fix371_halt — {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC")
    check_code()
    if not CODE_ONLY:
        check_process()
        check_ops()
    print("─" * 70)
    print(f"결과: {'FAIL ' + str(len(_fails)) + '건' if _fails else 'PASS'}")
    sys.exit(1 if _fails else 0)
