"""🗓 2026-09-15 자동매매 준비 — 가족 레지스트리 · 가족별 하루 최대 · 분할 10/100/200 실행기 · 화면 라벨 (docs/spec/AUTO_ENTRY_READY_2026-09-15.md)."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app.services import auto_family_registry as AF
from app.services import split_entry_executor as SX

APP = Path(__file__).resolve().parents[2] / "app"


class _DB:
    def __init__(self, **kv):
        self.kv = kv
        self.rolled = 0

    def get(self, _m, key):
        return type("Row", (), {"value": self.kv[key]})() if key in self.kv else None

    def rollback(self):
        self.rolled += 1


def _fn_src(path: Path, name: str) -> str:
    src = path.read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(src, fn)


# ── 가족 판정 ────────────────────────────────────────────────────────────
OLD = datetime(2026, 9, 10, tzinfo=timezone.utc)      # 출처 기록(alembic 0040) 이전 행


@pytest.mark.parametrize("stype,tname,origin,created,key", [
    ("DYNAMIC_LONG", "BASE", "manual_modal", None, None),                      # 사람 (출처가 단일 진실)
    ("DYNAMIC_SHORT", "_quick_123_SHORT", "manual_modal", None, None),
    ("DYNAMIC_SHORT", "_quick_123_SHORT", None, OLD, None),                    # 옛 행 = 옛 표식으로 사람
    ("DYNAMIC_SHORT", None, None, OLD, None),
    ("DYNAMIC_SHORT", "_quick_123_SHORT", None, None, "human_template_auto"),  # 사람 템플릿을 워커가 다시 엶 = 자동 (#3)
    ("DYNAMIC_LONG", "_quick_m1789_LONG", None, None, "managed_reentry"),      # 관리 재진입 복제 = 자동
    ("DYNAMIC_LONG", "_quick_m1789_LONG", None, OLD, "managed_reentry"),
    ("auto_bb_break_SAJANGNIM_TOP", "X", None, None, "top_short"),
    ("auto_bb_break_SAJANGNIM_BOTTOM", "X", None, None, "bottom_long"),
    ("auto_bb_break_UNIFIED_15M", "X", None, None, "unified_15m"),              # #1 같은 접두사 다른 워커
    ("auto_bb_break_PENDING_HC_FAST", "X", None, None, "pending_hc"),
    ("auto_bb_break_success", "X", None, None, "success_reentry"),
    ("auto_bb_break_lastchance", "X", None, None, "rt_lastchance"),
    ("auto_bb_break", "AUTO_BB_X_reentry1", None, None, "bb_reentry"),
    ("auto_bb_break_reentry2", "X", None, None, "bb_reentry"),
    ("auto_bb_break", "X", None, None, "bb_break"),
    ("realtime_reentry", "X", None, None, "rt_reentry"),
    ("pump_split", "PUMPSPLIT_X", None, None, "pump_split"),
    ("bb_swing", "BBSWING_X", None, None, "bb_swing"),
    ("bb_mid_line", "BB_MIDLINE_X", None, None, "bb_mid_line"),
    ("fujimoto_3stage", "FUJIMOTO_X", None, None, "fujimoto"),
    ("mach7_ma_trap", "MACH7_X", None, None, "mach7"),
    ("rf_off8_267", "RF_OFF8_X", None, None, "rf_off8"),
    ("something_new", "Y", None, None, "other_something_new"),                  # 분류 안 됨 = 종류별 (한 칸에 몰지 않음)
    ("", None, None, None, "auto_other"),
])
def test_family_for(stype, tname, origin, created, key):
    fam = AF.family_for(strategy_type=stype, template_name=tname, entry_origin=origin, created_at=created)
    assert (fam.key if fam else None) == key


def test_counts_toward_today_includes_waiting_and_archived_entered():
    assert AF.counts_toward_today(stage=0, status="WAITING", archived=False) is True     # 곧 진입 = 동시 생성 경쟁 방지
    assert AF.counts_toward_today(stage=2, status="STOPPED", archived=False) is True
    assert AF.counts_toward_today(stage=1, status="STOPPED", archived=True) is True      # 사람이 보관해도 그날 건수 유지 (#6)
    assert AF.counts_toward_today(stage=0, status="STOPPED", archived=True) is False     # 주문 전 취소·1차 실패 보관
    assert AF.counts_toward_today(stage=0, status="STOPPED", archived=False) is False


def test_every_family_key_is_unique_and_labeled():
    fams = AF.known_families()
    keys = [f.key for f in fams]
    assert len(keys) == len(set(keys))
    assert all(f.label and f.short for f in fams)


# ── 하루 최대 ────────────────────────────────────────────────────────────
def test_daily_max_parsing_and_switch():
    assert AF.daily_max(_DB(), "bb_swing") == 1                          # 사장님 「모두 일최대 1개」
    assert AF.daily_max(_DB(daily_max_bb_swing="3"), "bb_swing") == 3
    assert AF.daily_max(_DB(daily_max_bb_swing="0"), "bb_swing") == 0     # 0 = 그 가족 새 진입 없음
    assert AF.daily_max(_DB(daily_max_bb_swing="abc"), "bb_swing") == 1
    assert AF.daily_max(_DB(daily_max_bb_swing="-2"), "bb_swing") == 1
    assert AF.enabled(_DB()) is True and AF.enabled(_DB(auto_daily_limit_enabled="0")) is False


def test_kst_day_start():
    assert AF.kst_day_start(datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc)) == datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)
    assert AF.kst_day_start(datetime(2026, 9, 15, 14, 59, tzinfo=timezone.utc)) == datetime(2026, 9, 14, 15, 0, tzinfo=timezone.utc)


def test_check_blocks_at_cap_and_skips_manual(monkeypatch):
    used = {"n": 0}
    monkeypatch.setattr(AF, "count_today", lambda db, key, exclude_id=None, now=None: used["n"])
    kw = dict(strategy_type="bb_swing", template_name="BBSWING_X", entry_origin=None)
    assert AF.check(_DB(), **kw).key == "bb_swing"
    used["n"] = 1
    with pytest.raises(ValueError) as e:
        AF.check(_DB(), **kw)
    assert AF.is_limit_error(e.value) and "daily_max_bb_swing" in str(e.value)
    assert AF.check(_DB(daily_max_bb_swing="2"), **kw).key == "bb_swing"
    assert AF.check(_DB(auto_daily_limit_enabled="0"), **kw).key == "bb_swing"
    assert AF.check(_DB(), strategy_type="DYNAMIC_LONG", template_name="T", entry_origin="manual_modal") is None
    monkeypatch.setattr(AF, "count_today", lambda db, key, exclude_id=None, now=None: AF.COUNT_FAILED)
    with pytest.raises(ValueError) as e2:
        AF.check(_DB(daily_max_bb_swing="5"), **kw)
    assert "조회 실패" in str(e2.value)


def test_count_today_fail_closed_and_rolls_back():
    db = _DB()
    assert AF.count_today(db, "bb_swing") == AF.COUNT_FAILED            # _DB 에 execute 없음 = 조회 실패
    assert db.rolled == 1


def test_reentry_and_managed_workers_respect_daily_limit():
    ar = (APP / "workers" / "auto_reentry_worker.py").read_text(encoding="utf-8")
    assert "_is_halt371(e) or _is_daily_limit(e)" in ar                  # 막혀도 REENTRY_FAILED 로 영구 마킹하지 않는다 (#2)
    ms = (APP / "workers" / "managed_symbol_worker.py").read_text(encoding="utf-8")
    assert ms.find("family_daily_max") < ms.find("MS.bump_daily(now)")    # 막힐 시도는 워커 한도·쿨다운 소비 안 함 (#4)
    ss = _fn_src(APP / "services" / "strategy_service.py", "create_strategy_instance")
    assert 'where="전략 생성", lock=True' in ss                          # 같은 가족 동시 생성 잠금 (#5)


# ── 배선 (생성 · 1차 주문 · 화면) ─────────────────────────────────────────
def test_gate_wiring_create_and_stage1():
    ss = _fn_src(APP / "services" / "strategy_service.py", "create_strategy_instance")
    assert 0 < ss.find("_halt_create371(") < ss.find("_daily_check(") < ss.find("instance = StrategyInstance(")
    ex = _fn_src(APP / "services" / "execution_service.py", "start_stage1")
    i_halt = ex.find('_halt371.check_order(self.db, strategy, action="stage1"')
    i_daily = ex.find("_daily_check_si(self.db, strategy")
    i_plan = ex.find("stage_plan = next(")
    assert 0 < i_halt < i_daily < i_plan
    assert "if not _halt371.is_manual_action(origin):" in ex[i_halt:i_daily]   # 사람 버튼은 막지 않는다


def test_ui_labels_wired():
    from app.schemas.strategy import StrategyDetailResponse
    assert {"auto_family", "auto_label"} <= set(StrategyDetailResponse.model_fields)
    ls = _fn_src(APP / "api" / "v1" / "strategies" / "crud.py", "list_strategies")
    assert "resp.auto_family, resp.auto_label" in ls
    js = (APP / "static" / "js" / "strategies-list.js").read_text(encoding="utf-8")
    assert "s.auto_label" in js and "escapeHtml(s.auto_label)" in js
    from app.api.v1.terminal import _badge_for
    assert _badge_for("rf_off8_267")[1] == "정점 대비 −8% SHORT"
    assert _badge_for("bb_swing")[0] == "🤖 볼밴스윙"


def test_single_entry_guard_includes_all_rule_families():
    from app.services.rule_families import RF_STRATEGY_TYPES, RF_TEMPLATE_PREFIXES
    from app.services.single_entry_guard import SINGLE_ENTRY_STRATEGY_TYPES, SINGLE_ENTRY_TEMPLATE_PREFIXES
    assert RF_STRATEGY_TYPES <= SINGLE_ENTRY_STRATEGY_TYPES and set(RF_TEMPLATE_PREFIXES) <= set(SINGLE_ENTRY_TEMPLATE_PREFIXES)


# ── 분할 실행기 ──────────────────────────────────────────────────────────
def test_executor_config_defaults_and_dead_stage_fallback():
    caps, steps, sl, note = SX.parse_config(None, None, None)
    assert [float(c) for c in caps] == [10, 100, 200] and [float(s) for s in steps] == [3, 5, 7] and float(sl) == 10 and note == "설정 OK"
    caps2, steps2, sl2, note2 = SX.parse_config("10,100,200", "3,5,7", "1")      # 손절 1% = 2차보다 먼저 = 죽은 단계
    assert float(sl2) == 10 and "정합성" in note2
    assert SX.anchor_base(97.0, "LONG", steps) == pytest.approx(Decimal("100"))
    assert SX.tp_percents(5) == [5, 10, 15, 20]


def test_executor_create_blocked_returns_without_orders(monkeypatch):
    monkeypatch.setattr(SX, "build_template", lambda db, **k: NS(id=1))

    class _SS:
        def __init__(self, db):
            pass

        def create_strategy_instance(self, **k):
            raise ValueError("⛔ [가족별 일 최대 진입] 볼밴 스윙 오늘(KST) 1/1건")
    monkeypatch.setattr("app.services.strategy_service.StrategyService", _SS)
    monkeypatch.setattr(SX, "_exec", lambda db, acc: pytest.fail("주문 경로에 들어가면 안 된다"))
    db = _DB()
    caps, steps, sl, _ = SX.parse_config(None, None, None)
    si, code, why = SX.open_split_position(db, NS(id=1), symbol="XUSDT", side="LONG", price=1.0, strategy_type="bb_swing",
                                           name_prefix="BBSWING_", label="볼밴 스윙", caps=caps, steps=steps, sl_roi=sl, tp1=5, trail=3)
    assert si is None and code == "create_blocked" and AF.is_limit_error(why) and db.rolled == 1


def test_split_total_cap_fail_closed_and_setting():
    full, why = SX.split_total_full(_DB())                               # 조회 실패 = 막음
    assert full is True and "조회 실패" in why
    assert SX.split_total_cap(_DB()) == 3 and SX.split_total_cap(_DB(auto_split_max_concurrent_total="5")) == 5
    assert SX.split_total_cap(_DB(auto_split_max_concurrent_total="x")) == 3
    assert SX.uses_executor("rf_off8_267") and SX.uses_executor("bb_swing") and not SX.uses_executor("pump_split")


class _Res:
    def __init__(self, one=None, many=()):
        self.one, self.many = one, many

    def scalar_one_or_none(self):
        return self.one

    def scalars(self):
        return self

    def all(self):
        return list(self.many)


class _ExecDB(_DB):
    def __init__(self, **kv):
        super().__init__(**kv)
        self.commits = 0

    def execute(self, *_a, **_k):
        return _Res(None, ())

    def commit(self):
        self.commits += 1


def _patch_open(monkeypatch, *, order_sent):
    si = NS(id=77, status="WAITING", is_archived=False, last_error_code=None, last_error_message=None)
    monkeypatch.setattr(SX, "build_template", lambda db, **k: NS(id=1))

    class _SS:
        def __init__(self, db):
            pass

        def create_strategy_instance(self, **k):
            return si
    monkeypatch.setattr("app.services.strategy_service.StrategyService", _SS)
    monkeypatch.setattr("app.workers.pump_split_entry_worker.verify_stage_plans", lambda *a, **k: (True, "ok"))

    class _Ex:
        def start_stage1(self, sid):
            raise RuntimeError("commit failed after order")
    monkeypatch.setattr(SX, "_exec", lambda db, acc: _Ex())
    monkeypatch.setattr(SX, "_order_sent", lambda db, sid: order_sent)
    return si


def test_executor_does_not_archive_when_order_already_sent(monkeypatch):
    caps, steps, sl, _ = SX.parse_config(None, None, None)
    kw = dict(symbol="XUSDT", side="LONG", price=1.0, strategy_type="rf_off8_267", name_prefix="RF_OFF8_", label="L",
              caps=caps, steps=steps, sl_roi=sl, tp1=5, trail=3)
    si = _patch_open(monkeypatch, order_sent=True)
    got, code, _ = SX.open_split_position(_ExecDB(), NS(id=1), **kw)
    assert got is None and code == "start_unconfirmed" and si.is_archived is False     # 살아 있을 수 있는 포지션을 숨기지 않는다 (L1)
    si2 = _patch_open(monkeypatch, order_sent=False)
    got2, code2, _ = SX.open_split_position(_ExecDB(), NS(id=1), **kw)
    assert got2 is None and code2 == "start_failed" and si2.is_archived is True and si2.last_error_code == "SPLIT_START_FAILED"


def test_workers_check_total_cap_and_config_before_opening():
    rf = _fn_src(APP / "workers" / "rule_family_worker.py", "_enter_split")
    assert 0 < rf.find('note != "설정 OK"') < rf.find("split_total_full(db)") < rf.find("open_split_position(")
    bb = _fn_src(APP / "workers" / "bb_swing_worker.py", "_enter")
    assert 0 < bb.find("split_total_full(db)") < bb.find("open_split_position(")
    run = _fn_src(APP / "workers" / "bb_swing_worker.py", "run_bb_swing_once")
    assert 'return {"note": f"설정 오류: {cfg}", **stat}' in run


def test_executor_order_pins():
    op = _fn_src(APP / "services" / "split_entry_executor.py", "open_split_position")
    assert 0 < op.find("create_strategy_instance(") < op.find("verify_stage_plans(plans") < op.find(".start_stage1(")
    assert "capital_management_mode=SPLIT_ENTRY_MODE" in op and "SPLIT_START_FAILED" in op
    bt = _fn_src(APP / "services" / "split_entry_executor.py", "build_template")
    assert '"family_label": label' in bt and '"steps":' in bt
