"""v7 단축 익절 폐지 → v8 TP 균일 25% ratio 검증 (2026-06-09 BEATUSDT).

배경 (옛 v7, 2026-05-14):
사용자 기획 v5 (trailing): TP3+ AND current_stage>=3 + peak-5% → 잔량 100%.
사용자 기획 v7 (단축 익절): stage<3 인데 TP3+ 발동 시 → 즉시 잔량 100% 청산.

🚨 테스트 stale fix (commit 044b17b, 2026-06-09 사장님 BEATUSDT):
"tp3 정상 익절후 계속 유지하고 tp4를 못가고 최고가 대비 -15%가 빠져야 익절청산"
= v7 의 "TP3+ 이면 stage 미달이라도 잔량 100% 즉시 청산"이 사장님 의도와
정반대였다 (TP3 익절 후에도 잔량을 **유지**해야 TP4·트레일링을 볼 수 있다).
그래서 v7 단축 익절 로직 자체가 **영구 비활성화**됐다
(app/services/tp_sl_orchestrator.py:158-163 `v7_short_exit = False` 하드코딩).

v8 신 동작 = TP1~20 균일 25% ratio (템플릿 값 우선, 없으면 기본 25%,
app/services/tp_sl_orchestrator.py:143 `default_ratio` 참조 — TP20 도 예외 없이 25%).
v7 분기 자체를 시뮬레이션에서 제거한다.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace


def _make_template(tp_percents: dict, tp_ratios: dict | None = None):
    tpl = SimpleNamespace(strategy_template_id=1, crisis_qty_ratios=None)
    for n in range(1, 11):
        setattr(tpl, f"tp{n}_percent", tp_percents.get(n))
        setattr(tpl, f"tp{n}_qty_ratio", (tp_ratios or {}).get(n))
    return tpl


def _resolve_close_ratio_v8(level, tpl, current_stage, crisis_mode=False):
    """tp_sl_orchestrator._execute_take_profit close_ratio 결정 로직 v8 simulation.

    v7(2026-05-14, stage<3 + TP3+ → 잔량 100% 즉시 청산)은 commit 044b17b
    (2026-06-09 사장님 BEATUSDT)로 영구 비활성화됐다 — `current_stage` 인자는
    이제 호출 시그니처 호환을 위해서만 남아 있고 ratio 계산에 관여하지 않는다.
    """
    ratio_attr = {f"TP{n}": f"tp{n}_qty_ratio" for n in range(1, 11)}
    default_ratio = {f"TP{n}": Decimal("25") for n in range(1, 21)}
    crisis_qty_ratio = {
        "TP1": Decimal("25"), "TP2": Decimal("25"),
        "TP3": Decimal("50"), "TP4": Decimal("100"),
    }

    if level == "TRAILING_TP":
        return Decimal("1.00")
    if crisis_mode and level in crisis_qty_ratio:
        return crisis_qty_ratio[level] / Decimal("100")
    attr = ratio_attr.get(level)
    tpl_val = getattr(tpl, attr, None) if tpl and attr else None
    ratio_pct = Decimal(str(tpl_val)) if tpl_val is not None else default_ratio.get(level, Decimal("25"))
    return ratio_pct / Decimal("100")


class TestV7ShortExitPartialStage:
    """v7(stage<3 + TP3+ → 잔량 100% 즉시 청산)은 폐기 — v8 균일 25% 검증으로 대체.

    🚨 테스트 stale fix (commit 044b17b, 2026-06-09 사장님 BEATUSDT):
    "tp3 정상 익절후 계속 유지하고 tp4를 못가고 최고가 대비 -15%가 빠져야 익절청산"
    production app/services/tp_sl_orchestrator.py:163 `v7_short_exit = False` 로
    영구 하드코딩됐다. 클래스명은 과거 파일/이력 추적을 위해 유지한다.
    """

    def test_stage1_tp3_normal_ratio_no_full_close(self):
        """1단계 진입 + TP3 발동 → v7 폐기로 25% 정상 청산 (100% 아님)."""
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25, 5: 30})
        ratio = _resolve_close_ratio_v8("TP3", tpl, current_stage=1)
        assert ratio == Decimal("0.25"), (
            "v8: stage 무관 TP3 는 25% 청산 + 잔량 유지 (v7 단축 익절 폐기)"
        )

    def test_stage2_tp3_normal_ratio_no_full_close(self):
        """2단계 진입 + TP3 발동 → 25% 청산 (v7 폐기)."""
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25})
        ratio = _resolve_close_ratio_v8("TP3", tpl, current_stage=2)
        assert ratio == Decimal("0.25")

    def test_stage1_tp3_to_tp10_all_25pct(self):
        """stage 무관 TP3~TP10 전부 25% (v7 100% 청산 없음)."""
        tpl = _make_template({n: 5 + n * 5 for n in range(1, 11)})
        for tp in ["TP3", "TP4", "TP5", "TP6", "TP7", "TP8", "TP9", "TP10"]:
            ratio = _resolve_close_ratio_v8(tp, tpl, current_stage=1)
            assert ratio == Decimal("0.25"), f"{tp} at stage 1 → 25% (v8, v7 폐기)"

    def test_stage1_tp1_tp2_normal_ratio(self):
        """stage<3 라도 TP1/TP2 는 정상 ratio (v7/v8 모두 동일)."""
        tpl = _make_template({1: 10, 2: 15, 3: 20})
        # TP1 default 25%
        assert _resolve_close_ratio_v8("TP1", tpl, current_stage=1) == Decimal("0.25")
        # TP2 default 25% (잔량의)
        assert _resolve_close_ratio_v8("TP2", tpl, current_stage=1) == Decimal("0.25")

    def test_stage3_tp3_normal_ratio(self):
        """stage>=3 + TP3 → 정상 ratio (v7 이전에도, v8 에서도 동일)."""
        tpl = _make_template({1: 10, 2: 15, 3: 20})
        # stage 3 + TP3 → default 25% — trailing 대기
        assert _resolve_close_ratio_v8("TP3", tpl, current_stage=3) == Decimal("0.25"), (
            "stage>=3 이든 아니든 TP3 는 25% (잔량 보유 → trailing 기회, v7 폐기)"
        )

    def test_stage3_tp4_normal_ratio(self):
        """stage>=3 + TP4 → 정상 ratio."""
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25})
        assert _resolve_close_ratio_v8("TP4", tpl, current_stage=3) == Decimal("0.25")

    def test_user_template_ratio_is_respected(self):
        """사용자가 명시적 ratio 설정하면 그 값 그대로 적용 (v7 강제 100% 없음).

        🚨 테스트 stale fix: 옛 v7 은 사용자 ratio(TP3=50%) 를 무시하고 100%로
        강제했다. v7 이 폐기됐으므로 이제는 사용자 ratio 가 그대로 존중된다.
        """
        tpl = _make_template({1: 10, 2: 15, 3: 20}, tp_ratios={3: 50})
        ratio = _resolve_close_ratio_v8("TP3", tpl, current_stage=1)
        assert ratio == Decimal("0.50"), "v7 폐기 후 사용자 ratio 가 그대로 존중된다"

    def test_crisis_mode_uses_crisis_ratio(self):
        """크라이시스 모드면 크라이시스 ratio 사용 (v7 무관, 이전부터 동일)."""
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25})
        # stage 1 + TP3 + crisis → crisis ratio TP3 = 50%
        ratio = _resolve_close_ratio_v8("TP3", tpl, current_stage=1, crisis_mode=True)
        assert ratio == Decimal("0.50"), (
            "크라이시스 모드는 v7/v8 과 무관하게 crisis ratio 그대로"
        )

    def test_trailing_tp_always_full_close(self):
        """TRAILING_TP 는 항상 100% (v7/v8 무관)."""
        tpl = _make_template({1: 10, 2: 15, 3: 20})
        for stage in [1, 2, 3, 5, 7]:
            ratio = _resolve_close_ratio_v8("TRAILING_TP", tpl, current_stage=stage)
            assert ratio == Decimal("1.00")
