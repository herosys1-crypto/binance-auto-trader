"""Fix 414 — CRITICAL 오탐 2종.

① 마틴게일 게이트 검사기(Fix 58): 통과 표식을 쓰는 코드가 없었고(companion change 누락), Fix 232 이후 가격 모드는 게이트 자체가 없다
   → 운영 #4570 PONSUSDT(수동, 가격 모드) 3단계 진입이 CRITICAL. 게이트 미적용 모드는 건너뛰고, 적용 모드는 단계 워커가 표식을 쓴다.
② TP 청산 감사: 최소 주문 명목가(Fix 187) 때문에 의도적으로 전량 청산한 것을 「25% 의도 vs 100% 실제」 CRITICAL 로 알림
   → 운영 #4625 AINUSDT(10 USDT 단일 = 명목 20U, TP1 25% = 5U). 의도된 조정은 INFO + 사유.
"""
from __future__ import annotations

import pathlib
from types import SimpleNamespace as NS

import pytest

from app.workers import martingale_gate_validator_worker as V

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


class FakeDB:
    def __init__(self, strategies, templates):
        self.s, self.t = strategies, templates

    def get(self, model, key):
        name = getattr(model, "__name__", "")
        return (self.t if name == "StrategyTemplate" else self.s).get(key)


def db_with(mode, cmm=None, tid=7):
    return FakeDB({1: NS(id=1, capital_management_mode=cmm, strategy_template_id=tid)},
                  {7: NS(trigger_mode=mode)} if mode is not None else {})


@pytest.mark.parametrize("mode, cmm, na", [
    ("PRICE_DOWN_PCT", None, True), ("PRICE_UP_PCT", None, True), ("OBV_REVERSE", None, True),
    ("PRICE_DOWN_PCT", "split_entry", True), ("SOME_INDICATOR_MODE", None, False), ("SOME_INDICATOR_MODE", "SPLIT_ENTRY", True),
    (None, None, True),          # 템플릿 없음 = 단계 워커 기본값 PRICE_DOWN_PCT = 게이트 미적용
])
def test_gate_not_applicable_mirrors_stage_trigger(mode, cmm, na):
    assert bool(V._gate_not_applicable(db_with(mode, cmm), 1)) is na


def test_gate_not_applicable_unknown_strategy_or_error_falls_back_to_marker_check():
    assert V._gate_not_applicable(FakeDB({}, {}), 999) is None

    class Boom:
        def get(self, *_a):
            raise RuntimeError("db down")
    assert V._gate_not_applicable(Boom(), 1) is None


def test_validator_loop_skips_not_applicable_before_marker(monkeypatch):
    plans = [NS(strategy_instance_id=1, stage_no=3, triggered_at=None)]
    monkeypatch.setattr(V, "_get_recent_martingale_entries", lambda db: plans)
    monkeypatch.setattr(V, "SessionLocal", lambda: NS(close=lambda: None, get=db_with("PRICE_DOWN_PCT").get))
    monkeypatch.setattr(V, "_check_indicator_log_exists", lambda *a: pytest.fail("가격 모드는 표식 검사까지 가면 안 된다"))
    monkeypatch.setattr(V, "_send_silent_bug_alert", lambda *a: pytest.fail("알림 금지"))
    import app.core.redis_client as RC
    monkeypatch.setattr(RC, "get_redis_client", lambda: None)
    res = V.run_martingale_gate_validator()
    assert res["gate_not_applicable"] == 1 and res["gate_missing"] == 0 and res["alerts_sent"] == 0


def test_stage_trigger_writes_pass_marker_without_risking_entry():
    src = (APP / "workers" / "stage_trigger_worker.py").read_text(encoding="utf-8")
    i = src.index('"[Fix55] ✅ 지표 반전 통과!')
    blk = src[i:i + 1200]
    assert 'f"stage_trigger:fix55_gate_passed:sid:{strategy.id}:stage:{next_stage_no}"' in blk
    assert V._FIX55_PASS_MARKER_KEY == "stage_trigger:fix55_gate_passed:sid:{sid}:stage:{stage_no}"   # 같은 키
    # 표식 기록은 자기 try 안 — 실패가 바깥 except(「검증 예외 → skip 진입」)로 번지지 않는다
    j, n = blk.index("_redis.setex("), blk.index("if _redis is not None:")
    t = blk.index("try:")
    assert t < n < j and "except Exception as _mk55" in blk[j:]                    # 참조·쓰기 모두 자기 try 안


def test_tp_audit_intended_full_close_is_info_with_reason():
    src = (APP / "services" / "tp_sl_orchestrator.py").read_text(encoding="utf-8")
    f = src[src.index("def _execute_take_profit("):]
    f = f[:f.index("\n    def ", 10)]
    assert "_qty_adjust_reason: str | None = None" in f[:f.index("current_qty = abs(")]   # 함수 앞에서 초기화 (NameError 없음)
    i187 = f.index("if _close_nom < MIN_CLOSE_NOTIONAL or _rest_nom < MIN_CLOSE_NOTIONAL:")
    assert "_qty_adjust_reason = (" in f[i187:i187 + 400] and "close_qty = current_qty" in f[i187:i187 + 900]
    assert '_qty_adjust_reason = f"계산 수량이 step' in f
    k = f.index("pct_diff = abs(expected_close_pct - actual_close_pct)")
    sev = f[k:k + 900]
    assert sev.index("if _qty_adjust_reason:") < sev.index('_severity = "INFO"') < sev.index("elif pct_diff > 20:")
    assert "의도된 조정: " in f
    # 교차 감사: 조정 수량과 실제 청산 수량이 다르면 면제하지 않는다 (사이에 수량이 또 바뀌는 결함을 묻지 않게)
    assert "_qty_adjust_close = current_qty" in f and "_qty_adjust_close = step" in f
    assert "close_qty != _qty_adjust_close" in f[:f.index("if _qty_adjust_reason:")]


def test_result_has_key_even_without_entries(monkeypatch):
    monkeypatch.setattr(V, "_get_recent_martingale_entries", lambda db: [])
    monkeypatch.setattr(V, "SessionLocal", lambda: NS(close=lambda: None))
    import app.core.redis_client as RC
    monkeypatch.setattr(RC, "get_redis_client", lambda: None)
    assert V.run_martingale_gate_validator()["gate_not_applicable"] == 0


def test_db_error_rolls_back():
    calls = []

    class Boom:
        def get(self, *_a):
            raise RuntimeError("db down")

        def rollback(self):
            calls.append("rb")
    assert V._gate_not_applicable(Boom(), 1) is None and calls == ["rb"]
