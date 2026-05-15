"""TP3+ 발동 + stage<3 시 단축 익절 (잔량 100%) 검증 — 사용자 기획 v7 (2026-05-14).

배경:
사용자 기획 v5 (trailing): TP3+ AND current_stage>=3 + peak-5% → 잔량 100%.
사용자 기획 v7 (단축 익절): stage<3 인데 TP3+ 발동 시 → 즉시 잔량 100% 청산.

이유:
- stage<3 면 trailing 자격 미달 → trailing 영원히 미발동 (잔량 영구 보유 위험)
- TP3 (+20% threshold) 까지 갔다 = 충분한 수익 = 잔량 빠르게 정리하는 게 안전

적용 조건:
- level == TPx (x >= 3)
- current_stage < 3
- 크라이시스 모드 X (크라이시스는 별도 ratio)
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.risk_service import TRAILING_MIN_TP_INDEX, TRAILING_MIN_STAGE


def _make_template(tp_percents: dict, tp_ratios: dict | None = None):
    tpl = SimpleNamespace(strategy_template_id=1, crisis_qty_ratios=None)
    for n in range(1, 11):
        setattr(tpl, f"tp{n}_percent", tp_percents.get(n))
        setattr(tpl, f"tp{n}_qty_ratio", (tp_ratios or {}).get(n))
    return tpl


def _resolve_close_ratio_v7(level, tpl, current_stage, crisis_mode=False):
    """tp_sl_orchestrator._execute_take_profit close_ratio 결정 로직 v7 simulation."""
    ratio_attr = {f"TP{n}": f"tp{n}_qty_ratio" for n in range(1, 11)}
    default_ratio = {f"TP{n}": Decimal("25") for n in range(1, 10)}
    default_ratio["TP10"] = Decimal("100")
    crisis_qty_ratio = {
        "TP1": Decimal("25"), "TP2": Decimal("25"),
        "TP3": Decimal("50"), "TP4": Decimal("100"),
    }

    # v7: stage<3 + TP3+ → 100%
    v7_short_exit = False
    if level.startswith("TP") and level[2:].isdigit() and not crisis_mode:
        try:
            tp_n = int(level[2:])
            if tp_n >= TRAILING_MIN_TP_INDEX and current_stage < TRAILING_MIN_STAGE:
                v7_short_exit = True
        except ValueError:
            pass

    if level == "TRAILING_TP":
        return Decimal("1.00")
    if v7_short_exit:
        return Decimal("1.00")
    if crisis_mode and level in crisis_qty_ratio:
        return crisis_qty_ratio[level] / Decimal("100")
    attr = ratio_attr.get(level)
    tpl_val = getattr(tpl, attr, None) if tpl and attr else None
    ratio_pct = Decimal(str(tpl_val)) if tpl_val is not None else default_ratio.get(level, Decimal("25"))
    return ratio_pct / Decimal("100")


class TestV7ShortExitPartialStage:
    """사용자 기획 v7: stage<3 + TP3+ → 잔량 100% 즉시 청산."""

    def test_stage1_tp3_triggers_full_close(self):
        """1단계 진입 + TP3 발동 → 100% 청산 (v7 신규)."""
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25, 5: 30})
        ratio = _resolve_close_ratio_v7("TP3", tpl, current_stage=1)
        assert ratio == Decimal("1.00"), (
            "v7: stage 1 + TP3 발동 → trailing 자격 미달 → 잔량 100% 청산"
        )

    def test_stage2_tp3_triggers_full_close(self):
        """2단계 진입 + TP3 발동 → 100% 청산 (v7 신규)."""
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25})
        ratio = _resolve_close_ratio_v7("TP3", tpl, current_stage=2)
        assert ratio == Decimal("1.00")

    def test_stage1_tp4_tp5_also_full_close(self):
        """stage<3 + 임의의 TP3+ (TP4/TP5/TP6 등) → 100%."""
        tpl = _make_template({n: 5 + n * 5 for n in range(1, 11)})
        for tp in ["TP3", "TP4", "TP5", "TP6", "TP7", "TP8", "TP9", "TP10"]:
            ratio = _resolve_close_ratio_v7(tp, tpl, current_stage=1)
            assert ratio == Decimal("1.00"), f"{tp} at stage 1 → 100% (v7)"

    def test_stage1_tp1_tp2_normal_ratio(self):
        """stage<3 라도 TP1/TP2 는 정상 ratio (v7 적용 X)."""
        tpl = _make_template({1: 10, 2: 15, 3: 20})
        # TP1 default 25%
        assert _resolve_close_ratio_v7("TP1", tpl, current_stage=1) == Decimal("0.25")
        # TP2 default 25% (잔량의)
        assert _resolve_close_ratio_v7("TP2", tpl, current_stage=1) == Decimal("0.25")

    def test_stage3_tp3_normal_ratio(self):
        """stage>=3 + TP3 → 정상 ratio (v7 적용 X — trailing 자격 있어 잔량 보유)."""
        tpl = _make_template({1: 10, 2: 15, 3: 20})
        # stage 3 + TP3 → default 25% (v6) — trailing 대기
        assert _resolve_close_ratio_v7("TP3", tpl, current_stage=3) == Decimal("0.25"), (
            "stage>=3 면 trailing 자격 있음 → TP3 도 25% (잔량 보유 → trailing 기회)"
        )

    def test_stage3_tp4_normal_ratio(self):
        """stage>=3 + TP4 → 정상 ratio (v7 적용 X)."""
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25})
        assert _resolve_close_ratio_v7("TP4", tpl, current_stage=3) == Decimal("0.25")

    def test_user_template_ratio_overrides_v7_default(self):
        """사용자가 명시적 ratio 설정해도 v7 100% 가 우선.

        이유: v7 의 의도는 잔량 정리. 사용자 ratio (예 TP3=50%) 가 있어도
        stage 미달 = trailing 자격 없음 → 잔량 영구 보유 위험 → 안전 우선.
        """
        tpl = _make_template({1: 10, 2: 15, 3: 20}, tp_ratios={3: 50})
        ratio = _resolve_close_ratio_v7("TP3", tpl, current_stage=1)
        assert ratio == Decimal("1.00"), "v7 가 사용자 ratio 보다 우선 (잔량 정리)"

    def test_crisis_mode_uses_crisis_ratio_not_v7(self):
        """크라이시스 모드면 v7 적용 X — 크라이시스 ratio 사용."""
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25})
        # stage 1 + TP3 + crisis → crisis ratio TP3 = 50%
        ratio = _resolve_close_ratio_v7("TP3", tpl, current_stage=1, crisis_mode=True)
        assert ratio == Decimal("0.50"), (
            "크라이시스 모드면 v7 우회 — crisis ratio 그대로"
        )

    def test_trailing_tp_always_full_close(self):
        """TRAILING_TP 는 항상 100% (v7 무관)."""
        tpl = _make_template({1: 10, 2: 15, 3: 20})
        for stage in [1, 2, 3, 5, 7]:
            ratio = _resolve_close_ratio_v7("TRAILING_TP", tpl, current_stage=stage)
            assert ratio == Decimal("1.00")
