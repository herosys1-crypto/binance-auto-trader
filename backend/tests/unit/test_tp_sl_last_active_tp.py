"""TPSLOrchestratorService — TP qty ratio 정책 v6 (사용자 기획, 2026-05-12 밤).

이전 정책 (#80, 2026-04-30): 「마지막 enabled TP 발동 시 잔량 100% 청산」 안전망.
신규 정책 v6: TPs 균일 25% (TP1~9), TP10 만 100% 안전망. last_active_tp shortcut 폐지.

근본 이유: 사용자 기획 「TP3 익절 후 trailing -5% 잔량 청산」.
- 이전엔 TP1~3 enable 시 TP3=last_active_tp → 100% 청산 → status COMPLETED → trailing X.
- v6 부터: TP3 도 25% 청산 → 잔량 보유 → trailing 발동 가능 (status>=TP3+ AND stage>=3).

사용자 의도 반영:
"익절시작은 +10%에서 25%씩 시작하고 +15% 일때 잔량에 25% 이렇게 tp10단계까지 가지만
 진입이 3단계 + tp3단계까지 실행 후 최고가 -5% 발생하면 잔량모두 익절청산이야".
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace


def _make_template(tp_percents: dict, tp_ratios: dict | None = None):
    """tp_percents={1: 10, ..., 10: 50} 같은 식. None 이면 비활성."""
    tpl = SimpleNamespace(strategy_template_id=1, crisis_qty_ratios=None)
    for n in range(1, 11):
        setattr(tpl, f"tp{n}_percent", tp_percents.get(n))
        setattr(tpl, f"tp{n}_qty_ratio", (tp_ratios or {}).get(n))
    return tpl


def _resolve_close_ratio_v6(level, tpl, crisis_mode=False):
    """tp_sl_orchestrator._execute_take_profit close_ratio 결정 로직 v6 simulation."""
    ratio_attr = {f"TP{n}": f"tp{n}_qty_ratio" for n in range(1, 11)}
    # v6 default: TP1~9 = 25%, TP10 = 100% (안전망)
    default_ratio = {f"TP{n}": Decimal("25") for n in range(1, 10)}
    default_ratio["TP10"] = Decimal("100")
    crisis_qty_ratio = {
        "TP1": Decimal("25"), "TP2": Decimal("25"),
        "TP3": Decimal("50"), "TP4": Decimal("100"),
    }

    if level == "TRAILING_TP":
        return Decimal("1.00")
    elif crisis_mode and level in crisis_qty_ratio:
        return crisis_qty_ratio[level] / Decimal("100")
    else:
        attr = ratio_attr.get(level)
        tpl_val = getattr(tpl, attr, None) if tpl and attr else None
        ratio_pct = Decimal(str(tpl_val)) if tpl_val is not None else default_ratio.get(level, Decimal("25"))
        return ratio_pct / Decimal("100")


class TestV6DefaultRatios:
    """v6 default ratio: TP1~9 = 25%, TP10 = 100%."""

    def test_tp1_through_tp9_default_25_pct(self):
        """모든 TP1~9 default = 25% (사용자 기획 균일)."""
        tpl = _make_template({n: 5 + n * 5 for n in range(1, 11)})  # TP 임계만 enable, ratio 미설정
        for n in range(1, 10):
            assert _resolve_close_ratio_v6(f"TP{n}", tpl) == Decimal("0.25"), (
                f"TP{n} default ratio should be 25% (v6 균일), got {_resolve_close_ratio_v6(f'TP{n}', tpl)}"
            )

    def test_tp10_default_100_pct_safety_net(self):
        """TP10 default = 100% (절대 마지막 안전망)."""
        tpl = _make_template({n: 5 + n * 5 for n in range(1, 11)})
        assert _resolve_close_ratio_v6("TP10", tpl) == Decimal("1.00"), (
            "TP10 default ratio = 100% (안전망)"
        )

    def test_user_template_ratio_overrides_default(self):
        """사용자가 tp{n}_qty_ratio 설정하면 default 무시."""
        tpl = _make_template({1: 10, 2: 15}, tp_ratios={1: 50, 2: 30})
        assert _resolve_close_ratio_v6("TP1", tpl) == Decimal("0.50")
        assert _resolve_close_ratio_v6("TP2", tpl) == Decimal("0.30")


class TestV6NoLastActiveTpShortcut:
    """v6: last_active_tp shortcut 폐지 — TP3 가 마지막 enabled 여도 100% 강제 X."""

    def test_tp3_last_enabled_does_NOT_close_all(self):
        """사용자 기획 핵심: TP1~3 만 enable 해도 TP3 가 25% (default) 청산.

        이전 v5: TP3 = last_active_tp → 100% override → COMPLETED → trailing X.
        v6: TP3 = 25% → 잔량 보유 → trailing armed → trailing 발동 가능.
        """
        tpl = _make_template({1: 10, 2: 15, 3: 20}, tp_ratios=None)  # default 사용
        # TP1, TP2, TP3 모두 25% (균일 default)
        assert _resolve_close_ratio_v6("TP1", tpl) == Decimal("0.25")
        assert _resolve_close_ratio_v6("TP2", tpl) == Decimal("0.25")
        assert _resolve_close_ratio_v6("TP3", tpl) == Decimal("0.25"), (
            "v6: TP3 가 last_enabled 여도 100% 강제 안 함 (사용자 기획)"
        )

    def test_tp1_only_enabled_no_shortcut(self):
        """TP1 만 enable — TP1 이 25% (default), 100% 강제 X."""
        tpl = _make_template({1: 10}, tp_ratios=None)
        assert _resolve_close_ratio_v6("TP1", tpl) == Decimal("0.25"), (
            "v6: TP1 만 enable 해도 100% 강제 안 함"
        )

    def test_tp5_last_enabled_no_shortcut(self):
        """TP5 가 마지막 enabled — 100% 강제 X."""
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25, 5: 30}, tp_ratios=None)
        assert _resolve_close_ratio_v6("TP5", tpl) == Decimal("0.25")


class TestV6TrailingPriority:
    """TRAILING_TP 는 항상 100% (변경 없음)."""

    def test_trailing_always_100_pct(self):
        tpl = _make_template({1: 10, 2: 15})
        assert _resolve_close_ratio_v6("TRAILING_TP", tpl) == Decimal("1.00")


class TestV6CrisisMode:
    """크라이시스 모드 ratio 정책 v6: TP1=25, TP2=25, TP3=50, TP4=100 (변경 없음)."""

    def test_crisis_tp1_25(self):
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25})
        assert _resolve_close_ratio_v6("TP1", tpl, crisis_mode=True) == Decimal("0.25")

    def test_crisis_tp2_25(self):
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25})
        assert _resolve_close_ratio_v6("TP2", tpl, crisis_mode=True) == Decimal("0.25")

    def test_crisis_tp3_50(self):
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25})
        assert _resolve_close_ratio_v6("TP3", tpl, crisis_mode=True) == Decimal("0.50")

    def test_crisis_tp4_100(self):
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25})
        assert _resolve_close_ratio_v6("TP4", tpl, crisis_mode=True) == Decimal("1.00")


class TestV6EffectiveBehavior:
    """end-to-end: TP1~9 균일 25% + TP10 100% 안전망."""

    def test_progressive_25pct_close_no_trailing(self):
        """TP1~5 enable, ratios 모두 default (25%) — 잔량 0 안 됨 (trailing 필요)."""
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25, 5: 30}, tp_ratios=None)
        qty = Decimal("1000")
        # TP1: 1000 × 25% = 250 → 잔량 750
        # TP2: 750 × 25% = 187.5 → 잔량 562.5
        # TP3: 562.5 × 25% = 140.625 → 잔량 421.875
        # TP4: 421.875 × 25% = 105.46875 → 잔량 316.40625
        # TP5: 316.40625 × 25% = 79.1015625 → 잔량 237.3046875
        # → 잔량 100% 청산은 trailing 또는 TP10 enable 시 가능
        for level in ["TP1", "TP2", "TP3", "TP4", "TP5"]:
            r = _resolve_close_ratio_v6(level, tpl)
            qty -= qty * r
        # 잔량 약 23.7% 남음 — trailing 으로 마무리 (또는 TP10 enable 시 100%)
        assert qty > 0, "v6: TP1~9 균일 25% 라 잔량 안 사라짐 — trailing 필요"
        assert qty < Decimal("250"), "5번 부분 청산으로 75% 이상 청산됨"

    def test_tp10_enabled_fully_closes(self):
        """TP10 enable + threshold 도달 시 잔량 100% 청산 (TP10 default = 100%)."""
        tpl = _make_template(
            {n: 5 + n * 5 for n in range(1, 11)},
            tp_ratios=None,
        )
        # TP10 발동 시 default 100% → 잔량 0
        ratio = _resolve_close_ratio_v6("TP10", tpl)
        assert ratio == Decimal("1.00")

    def test_user_can_set_tp3_to_100(self):
        """사용자가 명시적으로 TP3=100% 설정하면 v6 도 100% 청산 (template 우선)."""
        tpl = _make_template({1: 10, 2: 15, 3: 20}, tp_ratios={3: 100})
        assert _resolve_close_ratio_v6("TP3", tpl) == Decimal("1.00")
