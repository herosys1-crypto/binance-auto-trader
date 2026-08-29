"""🚨 Fix 209 — 볼밴 분할 단계 트리거를 **실체결가** 기준으로 재계산.

사장님 선택 (2026-08-30, 선택지 「b」):
  "1차 체결가 기준으로 재계산 — 1차가 어디서 잡히든 그 아래 -2% / -4% 로 2·3차를 다시"

이 파일이 지키는 계약은 **실제로 돈을 잃은 두 사례**다 (2026-08-29 운영 DB 실측):

  #1639 SKRUSDT  기준선 0.01105670  1차 체결 0.01045 (-5.49%)  2차 0.010503 (-5.01%)
        → 2차가 1차보다 **위**. LONG 인데 가격이 올라가야 2차가 붙는다 = 영원히 미진입.
  #1727 DEXEUSDT 1차 -5.02% / 2차 -5.03% = 간격 0.01%p = 사실상 같은 자리.

  결과: 볼밴 17건 중 3차 체결 **0건**, 12건이 1차 100 USDT 만 물린 채 -10% 손절.

⚠️ 구현 중 실제로 틀렸던 지점 — compounded_trigger_pcts 를 그대로 쓰면 2차 간격이
   **5.00%** 로 나온다 (그건 앵커가 기준선인 값이다). 재앵커는 stage_gap_pcts 를 써야
   하고, 아래 test_1727 이 그 실수를 잡아냈다.
"""
from __future__ import annotations

from decimal import Decimal

from app.workers.pump_split_entry_worker import (
    SPLIT_STEP_PCT,
    reanchor_from_fill,
    stage_gap_pcts,
)

STEPS = SPLIT_STEP_PCT          # 사장님 확정 3 / 5 / 7


class _Plan:
    """StrategyStagePlan 의 이 함수가 실제로 만지는 필드만 흉내낸다."""

    def __init__(self, stage_no, trigger_price, is_triggered=False):
        self.stage_no = stage_no
        self.trigger_price = (
            Decimal(str(trigger_price)) if trigger_price is not None else None
        )
        self.is_triggered = is_triggered


# ═══════════════════════════════════════════════════════════════════════════
# 실제 사고 재현
# ═══════════════════════════════════════════════════════════════════════════
def test_1639_dead_second_stage_is_revived():
    """#1639 — 2차 트리거가 1차 체결가보다 위였다 (LONG 인데 위 = 도달 불가)."""
    fill1 = Decimal("0.01045")
    plans = [
        _Plan(1, fill1, is_triggered=True),
        _Plan(2, "0.010503"),      # 사고 당시 값 — 1차보다 **위**
        _Plan(3, "0.010281"),
    ]
    assert plans[1].trigger_price > fill1, "사고 재현 실패"

    changed, why = reanchor_from_fill(plans, "LONG", STEPS)

    assert changed == 2, why
    assert plans[1].trigger_price < fill1, "2차는 1차 체결가보다 **아래**여야 한다"
    assert plans[2].trigger_price < plans[1].trigger_price, "3차는 2차보다 아래"


def test_1727_overlapping_stages_get_real_spacing():
    """#1727 — 1차와 2차 간격이 0.01%p 였다 (사실상 같은 자리 = 분할이 아님).

    🚨 이 검사가 첫 구현의 버그를 잡았다: compounded_trigger_pcts 를 쓰면 5.00% 가 나온다.
    """
    fill1 = Decimal("2.26123844")
    plans = [
        _Plan(1, fill1, is_triggered=True),
        _Plan(2, "2.26100000"),    # 간격 0.01%p
        _Plan(3, "2.21300000"),
    ]
    reanchor_from_fill(plans, "LONG", STEPS)

    gap2 = (fill1 - plans[1].trigger_price) / fill1 * 100
    gap3 = (plans[1].trigger_price - plans[2].trigger_price) / plans[1].trigger_price * 100
    # 원 설계 간격 (3/5/7 → -2.06% / -2.11%) 이 그대로 유지돼야 한다
    assert Decimal("2.0") < gap2 < Decimal("2.2"), gap2
    assert Decimal("2.0") < gap3 < Decimal("2.2"), gap3


# ═══════════════════════════════════════════════════════════════════════════
# 계약
# ═══════════════════════════════════════════════════════════════════════════
def test_gap_pcts_are_stage_to_stage_not_from_base():
    """stage_gap_pcts 는 **직전 차수 대비**여야 한다 (기준선 대비 5% 가 아니라)."""
    g = stage_gap_pcts("LONG", STEPS)
    assert g[0] is None
    assert Decimal("2.0") < g[1] < Decimal("2.1"), g[1]     # 0.95/0.97
    assert Decimal("2.1") < g[2] < Decimal("2.2"), g[2]     # 0.93/0.95


def test_spacing_matches_original_design_exactly():
    """간격은 **바뀌지 않는다** — 앵커만 옮긴다 (사장님 3/5/7 유지)."""
    fill1 = Decimal("100")
    plans = [_Plan(1, fill1, True), _Plan(2, "97"), _Plan(3, "95")]
    reanchor_from_fill(plans, "LONG", STEPS)
    g = stage_gap_pcts("LONG", STEPS)
    exp2 = fill1 * (Decimal("1") - Decimal(str(g[1])) / 100)
    exp3 = exp2 * (Decimal("1") - Decimal(str(g[2])) / 100)
    assert abs(plans[1].trigger_price - exp2) < Decimal("0.0000001")
    assert abs(plans[2].trigger_price - exp3) < Decimal("0.0000001")


def test_short_goes_up_not_down():
    """SHORT 는 위로 깔린다 — 부호를 뒤집으면 즉시 잡힌다."""
    fill1 = Decimal("100")
    plans = [_Plan(1, fill1, True), _Plan(2, "105"), _Plan(3, "107")]
    reanchor_from_fill(plans, "SHORT", STEPS)
    assert plans[1].trigger_price > fill1
    assert plans[2].trigger_price > plans[1].trigger_price


def test_anchor_moves_to_stage2_once_it_fills():
    """2차가 체결되면 3차는 **2차 체결가**에서 다시 깐다."""
    plans = [
        _Plan(1, "100", True),
        _Plan(2, "90", True),      # 계획보다 훨씬 아래에서 체결됨
        _Plan(3, "95"),
    ]
    changed, _ = reanchor_from_fill(plans, "LONG", STEPS)
    assert changed == 1
    assert plans[2].trigger_price < Decimal("90"), "3차는 2차 체결가 아래여야 한다"


def test_triggered_stages_are_never_modified():
    """체결된 단계는 절대 안 건드린다 (진입 기록 훼손 금지)."""
    plans = [_Plan(1, "100", True), _Plan(2, "97", True), _Plan(3, "95")]
    before = [plans[0].trigger_price, plans[1].trigger_price]
    reanchor_from_fill(plans, "LONG", STEPS)
    assert plans[0].trigger_price == before[0]
    assert plans[1].trigger_price == before[1]


def test_no_fill_means_no_change():
    """1차 미체결 = 앵커 없음 = 아무것도 하지 않는다."""
    plans = [_Plan(1, None), _Plan(2, "97"), _Plan(3, "95")]
    changed, why = reanchor_from_fill(plans, "LONG", STEPS)
    assert changed == 0
    assert plans[1].trigger_price == Decimal("97")
    assert "앵커" in why


def test_idempotent_second_run_writes_nothing():
    """매 15초 도는 자리다 — 두 번째부터는 UPDATE 가 나가면 안 된다 (헌법 148)."""
    plans = [_Plan(1, "100", True), _Plan(2, "97"), _Plan(3, "95")]
    first, _ = reanchor_from_fill(plans, "LONG", STEPS)
    assert first == 2
    second, why = reanchor_from_fill(plans, "LONG", STEPS)
    assert second == 0, why


def test_old_base_anchored_values_really_violate_the_contract():
    """음성 대조군 (헌법 170) — 고치기 **전** 값이 이 계약을 실제로 깨는가.

    검사가 아무것도 안 잡는데 늘 통과하면 그게 제일 위험하다.
    """
    fill1 = Decimal("0.01045")       # 실제 1차 체결 (기준선 -5.49%)
    old2 = Decimal("0.010503")       # 사고 당시 2차 (기준선 -5.01% 로 미리 계산됨)
    assert old2 > fill1, (
        "사고가 재현되지 않는다 = 이 대조군이 무의미해졌다. 숫자 출처를 다시 확인하라."
    )
    plans = [_Plan(1, fill1, True), _Plan(2, old2), _Plan(3, "0.010281")]
    reanchor_from_fill(plans, "LONG", STEPS)
    assert plans[1].trigger_price < fill1
