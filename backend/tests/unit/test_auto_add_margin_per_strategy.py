"""🛡️ Fix 238 — 자동 증거금은 **그 전략의 초기금액**으로 넣는다 (사장님 선택 「B」).

## 사장님 verbatim (2026-08-22 v220)

    "전체손실이 30% 넘어가면 **초기금액으로** 증거금을 추가해줘
     3단계 진입전에 청산가를 높이고"

당시 초기금액은 **300** 이었다 (v219 마틴게일 300/600/1800) — 코드의 300 은 맞았다.
그런데 **2026-08-26 Fix 133** 이 사다리를 `10/300/600` 으로 바꿔 초기금액이 **10** 이
된 뒤에도 이 300 만 따라가지 않고 얼어붙었다 = 사장님 문장과 **30배 차이**.

12초마다 도는 LIVE 워커라 손실 -30% 인 모든 자동진입 전략에 일괄 300 이 들어갔다.

## 사장님 결정 (2026-08-31): 「B」

    「초기금액」 = **그 전략 자신의 1단계 자본**

10 으로 시작한 전략은 10, 500 으로 시작한 전략은 500 을 받는다.
전역 상수는 없앴다 — 모르면 **넣지 않는다** (Fix 237 과 같은 fail-closed 원칙).

`auto_add_margin_usdt` 에 양수를 넣으면 그 값으로 고정된다(옛 동작 복원 = 300).
0 은 여전히 기능 OFF (Fix 165 / 헌법 83).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.workers.auto_add_margin_worker import (
    _resolve_add_margin_mode,
    _stage1_capital_of,
)

APP = Path(__file__).resolve().parents[2] / "app"
WORKER = APP / "workers" / "auto_add_margin_worker.py"


def _db_with_setting(value):
    """SystemSetting row 를 흉내낸다. value=None 이면 미설정."""
    db = MagicMock()
    db.get.return_value = (
        None if value is None else SimpleNamespace(value=value)
    )
    return db


def _db_with_plan(planned_capital, tpl=None):
    db = MagicMock()
    plan = (
        None if planned_capital is None
        else SimpleNamespace(planned_capital=planned_capital)
    )
    db.query.return_value.filter.return_value.one_or_none.return_value = plan
    db.get.return_value = tpl
    return db


_SI = SimpleNamespace(id=1, symbol="SKRUSDT", strategy_template_id=7)


# ───────────────────────────────── 금액 방식

def test_unset_means_per_strategy():
    """🚨 미설정 = 사장님 「초기금액으로」 = 전략별. 옛 300 일괄이 아니다."""
    mode, amount = _resolve_add_margin_mode(_db_with_setting(None))
    assert mode == "per_strategy" and amount is None


def test_explicit_zero_is_still_off():
    """헌법 83 — 0 은 끄기다 (네 번째 재발 방지)."""
    mode, amount = _resolve_add_margin_mode(_db_with_setting("0"))
    assert mode == "off" and amount is None


def test_explicit_amount_pins_it():
    """사장님이 숫자를 넣으면 그 값으로 고정 (옛 동작 복원 경로)."""
    mode, amount = _resolve_add_margin_mode(_db_with_setting("300"))
    assert mode == "fixed" and amount == Decimal("300")


def test_broken_setting_falls_back_to_per_strategy_not_300():
    """파싱 실패해도 300 으로 떨어지면 안 된다 — 그게 원래 사고였다."""
    mode, amount = _resolve_add_margin_mode(_db_with_setting("삼백"))
    assert mode == "per_strategy" and amount is None


# ───────────────────────────────── 전략별 초기금액

def test_uses_stage1_plan_capital():
    db = _db_with_plan(Decimal("10"))
    assert _stage1_capital_of(db, _SI) == Decimal("10")


def test_large_stage1_is_respected():
    """500 으로 시작한 전략은 500 을 받는다 — 일괄 300 이 아니다."""
    db = _db_with_plan(Decimal("500"))
    assert _stage1_capital_of(db, _SI) == Decimal("500")


def test_falls_back_to_template_capitals():
    tpl = SimpleNamespace(stages_config={"capitals": ["250", "500"]}, stage1_capital=None)
    db = _db_with_plan(None, tpl=tpl)
    assert _stage1_capital_of(db, _SI) == Decimal("250")


def test_falls_back_to_legacy_column():
    tpl = SimpleNamespace(stages_config=None, stage1_capital=Decimal("77"))
    db = _db_with_plan(None, tpl=tpl)
    assert _stage1_capital_of(db, _SI) == Decimal("77")


def test_unknown_capital_returns_none_not_a_number():
    """🚨 모르면 **넣지 않는다**. 금액을 지어내면 Fix 237 사고가 재발한다."""
    tpl = SimpleNamespace(stages_config={}, stage1_capital=None)
    db = _db_with_plan(None, tpl=tpl)
    assert _stage1_capital_of(db, _SI) is None


def test_zero_or_negative_is_treated_as_unknown():
    assert _stage1_capital_of(_db_with_plan(Decimal("0")), _SI) is None


def test_db_error_does_not_crash_the_worker():
    db = MagicMock()
    db.query.side_effect = RuntimeError("boom")
    assert _stage1_capital_of(db, _SI) is None


# ───────────────────────────────── 소스 가드

def test_global_300_constant_is_gone():
    """🚨 전역 300 상수가 되살아나면 사장님 「초기금액으로」가 다시 깨진다."""
    code = "\n".join(
        ln for ln in WORKER.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )
    assert "DEFAULT_ADD_MARGIN_USDT" not in code, (
        "전역 증거금 상수가 코드에 다시 생겼다 — 전략별 초기금액을 덮어쓴다"
    )
    assert "_stage1_capital_of(db, si)" in code, (
        "루프가 전략별 1단계 자본을 읽지 않는다"
    )
