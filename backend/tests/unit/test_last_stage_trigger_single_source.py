"""🛡️ Fix 234 — 마지막 단계 트리거의 **단일 진실** (헌법 6).

## 실측 사고 (#1873 SKRUSDT SHORT, 2026-08-31)

사장님이 수정 모달에 2단계 트리거를 **30** 으로 넣으셨고, 화면의 단계 표도
2단계 진입가를 **0.14919** (= 0.11476 x 1.30) 로 보여줬다.
그런데 DB 의 단계 계획은 **0.252472** (= 0.11476 x 2.20) 였다.

원인: 같은 칸의 값이 **두 곳에** 저장된다.

    stages_config["trigger_percents"][last]      <- 화면이 읽고 쓰는 곳
    stages_config["last_stage_trigger_percent"]  <- 엔진이 읽던 곳

`strategy_calculator` 의 `if is_last: pct = last_pct` 가 배열을 **아예 안 봤다**.
게다가 `_collectDirectInputs` 는 배열의 마지막 칸을 null 로 지웠고,
`PATCH /settings` 는 last_stage_trigger_percent 가 null 이면 전송조차 하지 않아
(cm-preview.js) backend 도 갱신하지 않았다(control.py) —
**한 번 잘못 들어간 값이 지워지지 않고 영구히 진입가를 지배했다.**

🚨 이건 화면을 봐서는 절대 안 보인다. 화면은 30 이라고 말하고 있었다.
   그래서 검사를 매번 도는 자리에 둔다 (헌법 169).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.services.strategy_calculator import StrategyCalculator, SymbolRule

APP = Path(__file__).resolve().parents[2] / "app"


def _skr_rule() -> SymbolRule:
    return SymbolRule(
        symbol="SKRUSDT",
        tick_size=Decimal("0.00001"),
        step_size=Decimal("1"),
        min_qty=Decimal("1"),
        price_precision=5,
        quantity_precision=0,
    )


def _kwargs(side="SHORT", start="0.11476"):
    return {
        "symbol": "SKRUSDT",
        "side": side,
        "start_price": Decimal(start),
        "leverage": 2,
        "total_capital": Decimal("1500"),
        "tp1_percent": Decimal("10"),
        "tp2_percent": Decimal("15"),
        "tp3_percent": Decimal("20"),
        "stop_loss_percent_of_capital": Decimal("90"),
    }


def _preview(**cfg):
    return StrategyCalculator(_skr_rule()).calculate_preview(
        **_kwargs(), stages_config=cfg
    )


# ---------------------------------------------------------------- 핵심 계약

def test_explicit_array_value_wins_over_stale_last_field():
    """🚨 #1873 재현 — 화면이 보여준 30% 가 적용되어야 한다 (120% 가 아니라)."""
    p = _preview(
        capitals=["500", "1000"],
        trigger_percents=[None, "30"],
        last_stage_trigger_percent="120",   # 지워지지 않던 옛 잔재
        last_stage_trigger_mode="PRICE_UP_PCT",
    )
    last = p.stages[-1]
    assert last.trigger_percent == Decimal("30"), (
        f"마지막 단계가 화면값 30% 를 안 쓴다: {last.trigger_percent}"
    )
    # 0.11476 x 1.30 = 0.149188 -> tick 0.00001
    assert Decimal("0.1491") < last.trigger_price < Decimal("0.1492"), last.trigger_price


def test_falls_back_to_last_field_when_array_empty():
    """구 저장 형식 호환 — 배열이 비어 있으면 last_stage_trigger_percent 를 쓴다."""
    p = _preview(
        capitals=["500", "1000"],
        trigger_percents=[None, None],
        last_stage_trigger_percent="20",
        last_stage_trigger_mode="PRICE_UP_PCT",
    )
    assert p.stages[-1].trigger_percent == Decimal("20")


def test_middle_stages_unaffected():
    """중간 단계는 예전 그대로 배열을 쓴다 (회귀 방지)."""
    p = _preview(
        capitals=["500", "1000", "1500"],
        trigger_percents=[None, "10", "40"],
        last_stage_trigger_percent="99",
        last_stage_trigger_mode="PRICE_UP_PCT",
    )
    assert p.stages[1].trigger_percent == Decimal("10")
    assert p.stages[2].trigger_percent == Decimal("40"), "마지막도 배열값이어야 한다"


def test_long_side_too():
    """LONG 도 같은 계약 — 방향만 다르다."""
    p = StrategyCalculator(_skr_rule()).calculate_preview(
        **_kwargs(side="LONG"),
        stages_config={
            "capitals": ["500", "1000"],
            "trigger_percents": [None, "30"],
            "last_stage_trigger_percent": "120",
            "last_stage_trigger_mode": "PRICE_DOWN_PCT",
        },
    )
    assert p.stages[-1].trigger_percent == Decimal("30")
    assert p.stages[-1].trigger_price < Decimal("0.11476"), "LONG 은 아래로"


def test_old_behaviour_really_differed():
    """음성 대조군 (헌법 170) — 두 값이 실제로 다른 가격을 만드는가.

    이게 성립하지 않으면 Fix 234 는 고칠 게 없었다는 뜻이다.
    """
    start = Decimal("0.11476")
    screen = start * (Decimal("1") + Decimal("30") / 100)     # 0.149188
    engine = start * (Decimal("1") + Decimal("120") / 100)    # 0.2524720
    assert engine > screen * Decimal("1.5"), (screen, engine)


# ---------------------------------------------------------------- 소스 가드

def _code(path: Path) -> str:
    src = path.read_text(encoding="utf-8")
    return chr(10).join(
        ln for ln in src.splitlines()
        if not ln.lstrip().startswith(("#", "//", "*", "/*"))
    )


def test_engine_reads_the_array_for_last_stage():
    """`pct = last_pct` 한 줄로 되돌아가면 사고가 그대로 재발한다."""
    code = _code(APP / "services" / "strategy_calculator.py")
    assert "_explicit if _explicit is not None else last_pct" in code, (
        "strategy_calculator 의 is_last 가 다시 last_pct 만 읽는다"
    )


def test_collector_does_not_erase_last_trigger():
    """JS 가 배열의 마지막 칸을 다시 null 로 지우면 저장이 화면과 갈라진다."""
    code = _code(APP / "static" / "js" / "cm-collectors.js")
    assert "triggers[triggers.length - 1] = null" not in code, (
        "cm-collectors 가 마지막 트리거를 지운다 = #1873 재발 경로"
    )


def test_settings_patch_syncs_stale_field():
    """PATCH 가 잔재를 안 지우면 옛 값이 계속 DB 에 남는다."""
    code = _code(APP / "api" / "v1" / "strategies" / "control.py")
    assert "new_triggers[-1] is not None" in code, (
        "control.py 가 last_stage_trigger_percent 잔재를 동기화하지 않는다"
    )
