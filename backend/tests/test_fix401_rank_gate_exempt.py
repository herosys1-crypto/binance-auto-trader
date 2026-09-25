"""🚨 Fix 401 — LONG 반전 규칙은 「상승50 ∪ 하락50 = 100종목」 게이트에서 면제 (2026-09-25).

사장님 「100종목 안/밖 갈라서 재봐줘」 → 가상 마감 **12,297건**을 신호 시점 태그(UP/DOWN)로
갈라 같은 청산으로 비교했다. **방향에 따라 부호가 반대다**:

    규칙                    안쪽 ROI(손절률)     밖 ROI(손절률)    안쪽이 나은 날
    bottom_331            +1.35 (14%)        **+4.23 (4%)**      5/16
    wick_rev_long_v220    +0.59 (11%)        **+3.56 (3%)**      4/16
    multiday_rebound_352  +0.67 (16%)        **+3.57 (4%)**      4/16
    fujimoto_l1_rsi       +2.40 (13%)        **+5.07 (3%)**      0/13
    ────────────────────────────────────────────────────────────────────
    zone_s4 (SHORT)     **+3.56 (27%)**       −5.36 (50%)        4/6
    off8_267 (SHORT)    **+0.00 (31%)**       −5.81 (30%)       14/16

상승·하락 50위 = 그날 가장 크게 움직인 종목 = 변동성 극단.
  · SHORT(급등 꼭대기 되돌림)는 그 극단에서만 먹힌다 → 게이트 유지.
  · LONG(저점·아래꼬리 반전)은 조용한 종목에서 훨씬 안전하다(손절률 3배 차이) → 게이트가 해롭다.

실제로 LONG 2종을 켠 첫날 시도 8건 중 6건이 이 게이트에 막혔고(BLESS +5.04% · SUI +5.38% ·
TRUMP +7.01% · STABLE +0.11% 등), **막힌 쪽이 더 좋은 쪽**이었다.

되돌리기: 설정 `entry_rank_gate_exempt_prefixes` 를 `none` 으로.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from app.services import chg24_entry_gate as G


class _DB:
    """system_settings 만 흉내 — get(Model, key) 로 값 하나."""

    def __init__(self, kv: dict | None = None) -> None:
        self.kv = dict(kv or {})

    def get(self, _model, key):
        v = self.kv.get(key)
        return None if v is None else NS(value=v)


@pytest.mark.parametrize(
    "template_name",
    [
        "RF_BOTTOM_ARXUSDT_LONG_20260924_231722_A1",
        "RF_WICKLONG_FLOCKUSDT_LONG_20260925_001822_A1",
        "RF_MULTIDAY_XUSDT_LONG_20260925_010000_A1",
        "rf_bottom_lowercase_also_matches",
    ],
)
def test_long_reversal_families_are_exempt(template_name: str) -> None:
    ok, why = G._is_rank_exempt(_DB(), template_name)
    assert ok, why
    assert "Fix 401" in why


@pytest.mark.parametrize(
    "template_name",
    [
        "RF_ZONES4_AGTUSDT_SHORT_20260922_160220_A1",     # S4 = 안쪽이 좋다 → 게이트 유지
        "RF_OFF8_XUSDT_SHORT_1",                          # off8 = 안쪽이 좋다
        "RF_SURGESTART_XUSDT_LONG_1",                     # 안 재본 LONG = 면제하지 않는다
        "auto_bb_break_SAJANGNIM_BOTTOM",
        "",
        None,
    ],
)
def test_others_still_gated(template_name: object) -> None:
    ok, _ = G._is_rank_exempt(_DB(), template_name)
    assert not ok


def test_exempt_list_is_a_setting() -> None:
    """사장님이 한 줄로 되돌릴 수 있어야 한다."""
    assert G.SETTING_EXEMPT == "entry_rank_gate_exempt_prefixes"
    assert G.exempt_prefixes(_DB()) == ("RF_BOTTOM", "RF_WICKLONG", "RF_MULTIDAY")
    assert G.exempt_prefixes(_DB({G.SETTING_EXEMPT: "none"})) == ()   # 끄기 = 명시 토큰
    assert G.exempt_prefixes(_DB({G.SETTING_EXEMPT: "RF_X , rf_y"})) == ("RF_X", "RF_Y")
    # `none` 으로 되돌리면 면제가 사라진다
    ok, _ = G._is_rank_exempt(_DB({G.SETTING_EXEMPT: "none"}), "RF_BOTTOM_ARXUSDT_LONG_1")
    assert not ok


def test_exempt_checked_before_ticker_fetch() -> None:
    """면제면 시세 조회 없이 통과한다 (거래소 호출 낭비 금지 · IP 차단 추적과 연결)."""
    src = (G.__file__).replace(".pyc", ".py")
    import pathlib
    text = pathlib.Path(src).read_text(encoding="utf-8")
    body = text[text.index("def passes(db, bc, symbol"):]
    assert body.index("_is_rank_exempt(db, template_name)") < body.index("bc.get_24hr_ticker()")


def test_manual_exception_untouched() -> None:
    """수동(`_quick_`) 면제는 그대로."""
    assert G._is_manual("_quick_20260924_1") is True
    assert G._is_manual("RF_BOTTOM_X") is False
