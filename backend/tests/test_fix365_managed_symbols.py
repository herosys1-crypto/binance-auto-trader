"""🧭 Fix 365 — 심볼 관리 재진입 (사장님 2026-09-09 저녁 verbatim: "첫 진입에 실패하면 청산하고 재진입 모니터링으로 특별 관리 …
다시 10usdt로 진입해서 성공하면 포지션추가 … 10번까지 반복 … 롱이든 숏이든 … 한번 선택한 종목을 지속적으로 분석하면서 관리 재진입")."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS

from app.services import managed_symbols as MS

ROOT = Path(__file__).resolve().parents[1] / "app"


class _DB:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, _m, key):
        return type("R", (), {"value": self.kv[key]})() if key in self.kv else None


def _ms(**kw):
    base = dict(symbol="XUSDT", status=MS.STATUS_WATCHING, attempts=0, max_attempts=10, successes=0, total_entries=0,
                origin_instance_id=None, last_instance_id=None, last_side=None, last_pnl=None, last_exit_at=None,
                user_id=None, exchange_account_id=None, strategy_template_id=None, templates=None, counted_ids=None,
                released_at=None)
    base.update(kw)
    return NS(**base)


def _si(i, pnl, side="SHORT", avg=Decimal("1")):
    return NS(id=i, symbol="XUSDT", side=side, realized_pnl=pnl, avg_entry_price=avg, stopped_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
              updated_at=None, user_id=1, exchange_account_id=1, strategy_template_id=77)


def test_settings_defaults_and_probe_mode():
    db = _DB()
    assert MS.probe_mode(db) is True and MS.loss_ladder_mode(db) == "probe"
    assert MS.probe_mode(_DB(obv_loss_ladder_mode="ladder")) is False
    assert MS.probe_mode(_DB(obv_loss_ladder_mode="garbage")) is True                    # 모르는 값 = 기본
    assert MS.get_bool(db, MS.S_ENABLED) is True and MS.get_bool(db, MS.S_ENTRY) is True
    assert MS.get_bool(_DB(managed_symbol_entry_enabled="0"), MS.S_ENTRY) is False
    assert MS.get_int(db, MS.S_MAX_ATTEMPTS, 1, 100) == 10                             # 사장님 「10번까지」
    assert MS.get_int(_DB(managed_symbol_max_attempts="999"), MS.S_MAX_ATTEMPTS, 1, 100) == 10   # 범위 밖 = 기본
    assert MS.get_int(db, MS.S_DAILY, 0, 1000) == 10 and MS.get_int(db, MS.S_MAX_SYMBOLS, 1, 200) == 20
    # 프로브 술어: OBV 인스턴스 + probe 모드 → (True, why); 가격 트리거 인스턴스 → False; ladder 모드 → False
    obv = NS(strategy_template=NS(trigger_mode="OBV_REVERSE"), strategy_template_id=1)
    px = NS(strategy_template=NS(trigger_mode="PRICE_DOWN_PCT"), strategy_template_id=2)
    assert MS.loss_ladder_disabled(db, obv)[0] is True and "전량 청산" in MS.loss_ladder_disabled(db, obv)[1]
    assert MS.loss_ladder_disabled(db, px) == (False, "")
    assert MS.loss_ladder_disabled(_DB(obv_loss_ladder_mode="ladder"), obv) == (False, "")


def test_classify_close_by_reason():
    c = MS.classify_close
    assert c("FORCE_SL", "STOPPED") == "fail" and c("SL", "REENTRY_READY") == "fail" and c("ZOMBIE_FORCE_STOP", "STOPPED") == "fail"
    assert c("EXTERNAL_CLOSE", "STOPPED", probe_marker=True) == "fail"            # 프로브 전량 청산 마커가 있으면 실패
    assert c("TP_TP1", "COMPLETED") == "success" and c("TRAILING_TP", "COMPLETED") == "success" and c("MANUAL_TP", "STOPPED") == "success"
    assert c("CLOSED_UNKNOWN", "COMPLETED") == "success"                            # COMPLETED = 익절 종료
    for r in ("EXTERNAL_CLOSE", "CLOSED_UNKNOWN", "STOPPING_CLEANUP", "FLAT_CLEANUP", "UNKNOWN", "AFTER_TP1", None):
        assert c(r, "STOPPED") == "skip", r                                         # 사장님 ⏸정지·외부 청산·불명 = 세지 않음


def test_registry_counting_fail_success_exhaust_and_dup():
    ms = _ms(counted_ids=None)
    ap = lambda si, o: MS.apply_closed_instance(ms, si, max_attempts=10, outcome=o)
    assert ap(_si(1, Decimal("-2.5")), "fail") == "fail"
    assert ms.attempts == 1 and ms.status == MS.STATUS_WATCHING and ms.origin_instance_id == 1 and ms.last_instance_id == 1
    assert ms.templates == {"SHORT": 77} and ms.user_id == 1 and ms.last_pnl == Decimal("-2.5") and ms.last_side == "SHORT"
    assert ap(_si(1, Decimal("-2.5")), "fail") == "dup" and ms.attempts == 1        # 같은 인스턴스 두 번 안 셈
    for i in range(2, 12):                                                          # 재진입 10회 실패까지
        ap(_si(i, Decimal("-1")), "fail")
    assert ms.attempts == 11 and ms.status == MS.STATUS_EXHAUSTED                   # 첫 실패 + 재진입 10회 = 소진
    assert ap(_si(20, Decimal("+8"), side="LONG"), "success") == "success"
    assert ms.attempts == 0 and ms.successes == 1 and ms.status == MS.STATUS_WATCHING and ms.templates == {"SHORT": 77, "LONG": 77}
    # 워터마크가 아니라 집합: 늦게 닫힌 옛 id(15) 도 센다 (C4/C8)
    assert ap(_si(15, Decimal("-1")), "fail") == "fail" and ms.attempts == 1 and ms.last_instance_id == 20
    # 진입 자체가 없던 종료는 세지 않는다 / 수동·외부(skip 힌트)도 세지 않는다
    assert ap(_si(22, None, avg=None), "fail") == "skip" and ms.attempts == 1 and 22 in ms.counted_ids
    assert ap(_si(23, Decimal("-3"), avg=Decimal("1")), "skip") == "skip" and ms.attempts == 1
    # RELEASED 는 끈적인다 (C2/C9/C14): 카운터는 갱신, 상태는 그대로
    ms.status = MS.STATUS_RELEASED
    assert ap(_si(30, Decimal("-1")), "fail") == "fail" and ms.attempts == 2 and ms.status == MS.STATUS_RELEASED
    assert ap(_si(31, Decimal("+1")), "success") == "success" and ms.status == MS.STATUS_RELEASED
    assert len(ms.counted_ids) <= MS.COUNTED_IDS_CAP


def test_decide_entry_table():
    d = MS.decide_entry
    assert d(long_ok=False, short_ok=False, active_sides=set(), allow_hedge=False, attempts=0, max_attempts=10) == (None, "신호 없음")
    assert d(long_ok=True, short_ok=False, active_sides=set(), allow_hedge=False, attempts=3, max_attempts=10)[0] == "LONG"
    assert d(long_ok=False, short_ok=True, active_sides=set(), allow_hedge=False, attempts=10, max_attempts=10)[0] == "SHORT"   # 10번째 재진입 허용
    assert d(long_ok=False, short_ok=True, active_sides=set(), allow_hedge=False, attempts=11, max_attempts=10)[0] is None      # 소진
    assert d(long_ok=True, short_ok=True, active_sides=set(), allow_hedge=False, attempts=0, max_attempts=10) == (None, "롱·숏 동시 신호 — 보류")
    assert d(long_ok=True, short_ok=False, active_sides={"SHORT"}, allow_hedge=False, attempts=0, max_attempts=10)[0] is None   # 반대 포지션 보유 = 대기
    assert d(long_ok=True, short_ok=False, active_sides={"SHORT"}, allow_hedge=True, attempts=0, max_attempts=10)[0] == "LONG"  # 헤지 허용이면 진입
    assert d(long_ok=True, short_ok=False, active_sides={"LONG"}, allow_hedge=True, attempts=0, max_attempts=10)[0] is None     # 같은 방향 보유 = 대기


def test_daily_key_is_kst():
    assert MS.daily_key(datetime(2026, 9, 9, 15, 30, tzinfo=timezone.utc)).endswith("20260910")   # 00:30 KST = 다음 날
    assert MS.daily_key(datetime(2026, 9, 9, 14, 30, tzinfo=timezone.utc)).endswith("20260909")


def test_wiring_pins():
    orch = (ROOT / "services" / "tp_sl_orchestrator.py").read_text(encoding="utf-8")
    assert orch.count("_probe365, _probe_why365 = self._loss_ladder_disabled(strategy)") == 3, "손절 실행 2곳 + _has_next_stage"
    assert orch.count("self._record_probe_full_close(strategy, _probe_why365)") == 2 and 'event_type="FORCE_SL_FULL_CLOSE"' in orch
    cc = (ROOT / "services" / "capital_calculator.py").read_text(encoding="utf-8")
    i_lr = cc.find("def ladder_reserves_untriggered(")
    assert "loss_ladder_disabled as _lld365" in cc[i_lr:i_lr + 1500], "프로브 인스턴스의 죽은 단계는 예약 아님 (C3)"
    assert orch.count("elif trim_enabled(self.db, strategy):") == 2, "프로브면 부분손절 생략 = 전량"
    i_def = orch.find("def _has_next_stage(")
    assert "if _probe365:\n            return False, _probe_why365" in orch[i_def:i_def + 2500]
    st = (ROOT / "workers" / "stage_trigger_worker.py").read_text(encoding="utf-8")
    i_obv = st.find("_stopped_ok364, _stopped_why364 = _obv_prev_stage_stopped(")
    blk = st[i_obv:i_obv + 1500]
    assert "if _probe365:" in blk and "elif _obv_stage_cooldown_active(_redis, strategy.id):" in blk, "프로브가 OBV 분기 첫 조건"
    assert "_record_block_reason" not in blk[blk.find("if _probe365:"):blk.find("elif _obv_stage_cooldown_active")], "프로브는 배지 아님(로그)"
    lr = (ROOT / "workers" / "ladder_restart_worker.py").read_text(encoding="utf-8")
    assert "probe_mode as _probe365" in lr and '_skip("probe_mode")' in lr
    sch = (ROOT / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    assert 'id="managed_symbols"' in sch and "IntervalTrigger(seconds=60)" in sch[sch.find('guarded_job("managed_symbols"'):sch.find('guarded_job("managed_symbols"') + 300]
    init = (ROOT / "models" / "__init__.py").read_text(encoding="utf-8")
    assert "from app.models.managed_symbol import ManagedSymbol" in init
    mig = (ROOT.parent / "alembic" / "versions" / "0037_managed_symbols.py").read_text(encoding="utf-8")
    assert "revision = '0037_managed_symbols'" in mig and "down_revision = '0036_paper_trades'" in mig
    svc = (ROOT / "services" / "managed_symbols.py").read_text(encoding="utf-8")
    assert svc.count(".start_stage1(") == 1, "주문이 나가는 지점은 enter_symbol 하나"
    wk = (ROOT / "workers" / "managed_symbol_worker.py").read_text(encoding="utf-8")
    for pin in ("MS.register_closed_instances(db, now=now)", 'check_stage_entry_signal(bc, db, ms.symbol, "LONG")',
                'check_stage_entry_signal(bc, db, ms.symbol, "SHORT")', "MS.decide_entry(", "check_position_slot(db, \"managed_symbols\")",
                "MS.daily_used(now)", "MS.enter_symbol(db, ms, side, account=account, decrypt_text=decrypt_text, now=now)",
                "AccountKillSwitchService(db).is_enabled(account.id)", "probe = MS.probe_mode(db)", "if not probe:",
                "MS.entry_cooldown_active(ms.symbol)", "MS.set_entry_cooldown(ms.symbol, cooldown_sec)",
                "ManagedSymbol.last_check_at.asc().nulls_first()"):
        assert pin in wk, pin
    # C5: 시도 = 일일 카운트·쿨다운 소비가 주문 **앞**
    i_enter = wk.find("MS.enter_symbol(")
    assert 0 < wk.find("n = MS.bump_daily(now)") < i_enter and 0 < wk.find("MS.set_entry_cooldown(ms.symbol, cooldown_sec)") < i_enter
    # C10/C18: 자동 해제는 전체 WATCHING 대상, 판정은 회전
    assert wk.find("all_watching = db.execute(") < wk.find("ManagedSymbol.last_check_at.asc().nulls_first()")
    assert "is_excluded(db, ms.symbol)" in wk and wk.find("is_excluded(db, ms.symbol)") < wk.find("MS.active_sides_for(db, ms.symbol)"), "제외 심볼은 판정 전에 건너뜀"
    i_start = svc.find(".start_stage1(")
    assert 'new_si.status = "STOPPED"' in svc[i_start:i_start + 900], "주문 실패 = WAITING 고아 대신 STOPPED (control.py 와 동일)"
    # 순서: 일일 한도 → 슬롯 → 진입
    assert wk.find("MS.daily_used(now)") < wk.find('check_position_slot(db, "managed_symbols")') < wk.find("MS.enter_symbol(")
