"""⛔ Fix 371 (2026-09-14 사장님) — 자동매매 전면 중단 · 사람이 만든 전략과 사람이 누른 버튼만 실주문.

"새전략 기본방식과 새전략 obv 자동만 가능하게 수동으로 전략을 만들수 있게 남기고 모든 자동매매 중단하고 가상으로만 매매하고 학습"
"""
import ast
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app.services import auto_trading_halt as H

APP = Path(__file__).resolve().parents[1] / "app"
ROOT = APP.parent


@pytest.fixture(autouse=True)
def _read_real_setting():
    """conftest 는 다른 가드 테스트를 위해 중단을 강제로 끈다 — 이 파일은 실제 판정을 본다."""
    prev = H.FORCE_HALT
    H.FORCE_HALT = None
    yield
    H.FORCE_HALT = prev


class _DB:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, _m, key):
        return type("R", (), {"value": self.kv[key]})() if key in self.kv else None


class _BrokenDB:
    def get(self, *_a):
        raise RuntimeError("db down")


MANUAL = NS(id=1, symbol="KOMAUSDT", entry_origin="manual_modal")
CLONE = NS(id=2, symbol="XUSDT", entry_origin=None, entry_profile="obv_auto")   # 관리 재진입 복제 = OBV 템플릿이라 obv_auto 표식이 붙는다


# ── 판정 ────────────────────────────────────────────────────────────────
def test_halt_default_is_on_and_fail_closed():
    assert H.halt_enabled(_DB()) is True                          # 행 없음 = 중단
    assert H.halt_enabled(_DB(auto_trading_halt="")) is True
    assert H.halt_enabled(_DB(auto_trading_halt="1")) is True
    assert H.halt_enabled(_BrokenDB()) is True                    # 읽기 실패 = 중단 (헌법 118)
    for off in ("0", "off", "FALSE", " no "):
        assert H.halt_enabled(_DB(auto_trading_halt=off)) is False


def test_automatic_stage_orders_only_for_manual_strategies():
    db = _DB()
    for action in ("stage1", "stage2"):
        H.check_order(db, MANUAL, action=action)                  # 사람 전략 = 모달 설정대로 자동 단계 진행
        with pytest.raises(ValueError) as e:
            H.check_order(db, CLONE, action=action)               # obv_auto 표식이 있어도 사람 생성이 아니면 차단
        assert "kill-switch" in str(e.value) and H.is_halt_error(e.value)


def test_automatic_add_and_market_stage_always_blocked():
    db = _DB()
    for strategy in (MANUAL, CLONE):
        with pytest.raises(ValueError):
            H.check_order(db, strategy, action="포지션 추가", manual_only=True)   # 자동 수익 추가 (9/13 KOMA·哈基米 손실 원인)
        with pytest.raises(ValueError):
            H.check_order(db, strategy, action="시장가 단계2", manual_only=True)  # 반전 워커 등


def test_human_buttons_allowed_regardless_of_origin():
    # 반박 검증 A/B: 배포 전에 만든 사람 전략(entry_origin NULL)·손절 없는 기존 방식 포지션을 사람이 방어할 길을 막지 않는다
    db = _DB()
    for strategy in (MANUAL, CLONE):
        H.check_order(db, strategy, action="포지션 추가", manual_action=True, manual_only=True)
        H.check_order(db, strategy, action="시장가 단계2", manual_action=True, manual_only=True)
        H.check_order(db, strategy, action="stage1", manual_action=True)
    assert H.is_manual_action("manual") and H.is_manual_action(" MANUAL ") and not H.is_manual_action("auto")
    assert not H.is_manual_action(None)


def test_create_only_manual_modal_of_the_two_families():
    H.check_create(_DB(), entry_origin="manual_modal", entry_profile="legacy_manual")
    H.check_create(_DB(), entry_origin="manual_modal", entry_profile="obv_auto")
    for origin, profile in ((None, "obv_auto"), ("", "legacy_manual"), ("manual_modal", None), ("manual_modal", "split")):
        with pytest.raises(ValueError):
            H.check_create(_DB(), entry_origin=origin, entry_profile=profile)


def test_resume_restores_old_behavior():
    db = _DB(auto_trading_halt="0")
    H.check_order(db, CLONE, action="stage2")
    H.check_order(db, CLONE, action="포지션 추가", manual_only=True)
    H.check_create(db, entry_origin=None, entry_profile=None)


def test_constants_match_sources():
    ss = (APP / "services" / "strategy_service.py").read_text(encoding="utf-8")
    assert f'ENTRY_ORIGIN_MANUAL = "{H.MANUAL_ORIGIN}"' in ss
    rc = (APP / "core" / "risk_constants.py").read_text(encoding="utf-8")
    for fam in H.CREATE_FAMILIES:
        assert f'= "{fam}"' in rc


def test_realtime_reentry_treats_block_message_as_kill_switch():
    src = (APP / "workers" / "realtime_reentry_worker.py").read_text(encoding="utf-8")
    assert '"kill-switch" in _low' in src
    assert "kill-switch" in H.BLOCK_PREFIX.lower()


def test_conftest_forces_halt_off_for_other_tests():
    src = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "_h.FORCE_HALT = False" in src


# ── 배선 (AST) ───────────────────────────────────────────────────────────
def _fn(path: Path, name: str) -> tuple[str, ast.FunctionDef]:
    src = path.read_text(encoding="utf-8")
    node = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(src, node), node


@pytest.mark.parametrize("name, first_order_call, manual_only", [
    ("start_stage1", "self._place_stage_entry_order(", False),
    ("trigger_next_stage", "self._trim_before_stage(", False),
    ("enter_stage_at_market", "self._place_market_entry(", True),
    ("add_position_now", "self._place_market_entry(", True),
])
def test_every_entry_function_checks_halt_before_ordering(name, first_order_call, manual_only):
    body, node = _fn(APP / "services" / "execution_service.py", name)
    i_ks = body.find("AccountKillSwitchService(self.db).is_enabled(")
    i_halt = body.find("_halt371.check_order(")
    i_order = body.find(first_order_call)
    assert 0 < i_ks < i_halt < i_order, name
    assert body.count("_halt371.check_order(") == 1
    call = body[i_halt:body.find(")   # ⛔ Fix 371", i_halt)]
    assert ("manual_only=True" in call) is manual_only, name
    kw = {a.arg: d for a, d in zip(node.args.kwonlyargs, node.args.kw_defaults)}
    assert "origin" in kw and ast.literal_eval(kw["origin"]) == "auto", name     # 기본 = 자동


def test_only_human_endpoints_pass_origin_manual():
    found = {}
    for p in APP.rglob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) in (
                    "add_position_now", "start_stage1", "trigger_next_stage", "enter_stage_at_market"):
                for k in n.keywords:
                    if k.arg == "origin" and isinstance(k.value, ast.Constant) and k.value.value == "manual":
                        found.setdefault(n.func.attr, []).append(p.relative_to(APP).as_posix())
    assert found == {
        "add_position_now": ["api/v1/strategies/lifecycle.py"],
        "start_stage1": ["api/v1/strategies/control.py"],
        "enter_stage_at_market": ["api/v1/strategies/control.py"],
    }


def test_strategy_creation_checks_halt_with_family_before_instance_and_stores_origin():
    body, _ = _fn(APP / "services" / "strategy_service.py", "create_strategy_instance")
    i_profile = body.find("_entry_profile369 = (")
    i_halt = body.find("_halt_create371(self.db, entry_origin=entry_origin, entry_profile=_entry_profile369)")
    i_inst = body.find("instance = StrategyInstance(")
    assert 0 < i_profile < i_halt < i_inst
    assert body.count("_halt_create371(") == 1
    assert "entry_origin=(entry_origin or None)" in body[i_inst:]


def test_worker_side_effects_are_suppressed():
    ms = (APP / "workers" / "managed_symbol_worker.py").read_text(encoding="utf-8")
    i_ks = ms.find('"error": "kill_switch_check"')
    i_halt = ms.find('"error": "auto_trading_halt"')
    i_budget = ms.find("bump_daily(")
    assert 0 < i_ks < i_halt < i_budget                           # 일일 한도·쿨다운 소비 전에 멈춘다
    st = (APP / "workers" / "stage_trigger_worker.py").read_text(encoding="utf-8")
    i_exc = st.find("if _is_halt371(e):")
    i_alert = st.find('title="[시스템 오류] Stage 자동 진입 실패"')
    assert 0 < i_exc < i_alert                                    # 「시스템 오류」 알림 전에 continue
    ar = (APP / "workers" / "auto_reentry_worker.py").read_text(encoding="utf-8")
    i_h = ar.find("_is_halt371(e)")
    i_failed = ar.find('_refetched.status = "REENTRY_FAILED"')
    assert 0 < i_h < i_failed                                     # 중단이면 REENTRY_FAILED 로 영구 마킹하지 않는다


def test_model_and_migration():
    from app.models.strategy_instance import StrategyInstance
    assert "entry_origin" in StrategyInstance.__table__.columns
    mig = (ROOT / "alembic" / "versions" / "0040_strategy_instances_entry_origin.py").read_text(encoding="utf-8")
    tree = ast.parse(mig)
    vals = {t.targets[0].id: t.value.value for t in tree.body
            if isinstance(t, ast.Assign) and isinstance(t.targets[0], ast.Name) and isinstance(t.value, ast.Constant)}
    assert vals["revision"] == "0040_si_entry_origin" and len(vals["revision"]) <= 32
    assert vals["down_revision"] == "0039_si_entry_profile"
    assert "WHERE entry_profile = 'legacy_manual'" in mig          # 소급은 모달 생성 표식만 (obv_auto 는 복제본에도 찍힌다)
