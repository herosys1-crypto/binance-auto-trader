"""전략 계산 엔진 (동적 N단계 지원, 1~10).

stages_config 또는 (호환용) 4-단계 dataclass 둘 다 처리한다.
첫 단계  : IMMEDIATE
중간 단계 : SHORT 면 PRICE_UP_PCT, LONG 이면 PRICE_DOWN_PCT (기본 10%, stage 별 지정 가능)
마지막 단계: SHORT 면 LIQUIDATION_BUFFER 5% (가격 미정, 청산가 기반 후속 산출)
            LONG 이면 PRICE_DOWN_PCT 20%
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Any, Literal

getcontext().prec = 28
Side = Literal["LONG", "SHORT"]

# 기본값 — stages_config 에 명시 안 된 stage 의 trigger_percent
DEFAULT_MIDDLE_TRIGGER_PCT = Decimal("10")
DEFAULT_LAST_LONG_TRIGGER_PCT = Decimal("20")
DEFAULT_LAST_SHORT_TRIGGER_PCT = Decimal("5")
DEFAULT_LAST_TRIGGER_MODE_SHORT = "LIQUIDATION_BUFFER"
DEFAULT_LAST_TRIGGER_MODE_LONG = "PRICE_DOWN_PCT"

MAX_STAGES = 10
MIN_STAGES = 1


@dataclass(frozen=True)
class SymbolRule:
    symbol: str
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    price_precision: int
    quantity_precision: int


@dataclass(frozen=True)
class StrategyTemplate:
    """기존 4단계 호환용 dataclass. 단위 테스트 등에서 직접 만들 때 사용."""
    name: str
    side: Side
    leverage: int
    total_capital: Decimal
    stage1_capital: Decimal
    stage2_capital: Decimal
    stage3_capital: Decimal
    stage4_capital: Decimal
    stage2_trigger_percent: Decimal
    stage3_trigger_percent: Decimal
    stage4_trigger_mode: str
    stage4_trigger_percent: Decimal | None
    tp1_percent: Decimal
    tp2_percent: Decimal
    tp3_percent: Decimal
    tp1_qty_ratio: Decimal
    tp2_qty_ratio: Decimal
    tp3_qty_ratio: Decimal
    stop_loss_percent_of_capital: Decimal
    reentry_policy: str = "manual_ready"


@dataclass(frozen=True)
class StagePlan:
    stage_no: int
    trigger_mode: str
    planned_capital: Decimal
    trigger_percent: Decimal | None = None
    trigger_price: Decimal | None = None
    planned_qty: Decimal | None = None


@dataclass(frozen=True)
class StrategyPreview:
    symbol: str
    side: Side
    leverage: int
    stages: list[StagePlan]
    tp1_percent: Decimal
    tp2_percent: Decimal
    tp3_percent: Decimal
    stop_loss_amount: Decimal


# =============================================================================
# stages_config 정규화
# =============================================================================
def _decimal_or_none(v: Any) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(v))


def _normalize_stages_config(stages_config: dict[str, Any] | None, side: Side, total_capital: Decimal) -> dict[str, Any]:
    """stages_config 에서 capitals / trigger_percents / last_stage_* 를 추출 + 검증."""
    if not stages_config:
        raise ValueError("stages_config is required for V2 calculator")

    capitals_raw = stages_config.get("capitals")
    if not capitals_raw:
        raise ValueError("stages_config.capitals is empty")
    capitals = [Decimal(str(c)) for c in capitals_raw]
    n = len(capitals)
    if n < MIN_STAGES or n > MAX_STAGES:
        raise ValueError(f"stages count must be {MIN_STAGES}..{MAX_STAGES}, got {n}")
    for i, c in enumerate(capitals, 1):
        if c <= 0:
            raise ValueError(f"capital for stage {i} must be > 0, got {c}")

    trigger_percents_raw = stages_config.get("trigger_percents") or [None] * n
    if len(trigger_percents_raw) != n:
        # 길이 안 맞으면 None 으로 padding
        trigger_percents_raw = (list(trigger_percents_raw) + [None] * n)[:n]
    trigger_percents = [_decimal_or_none(p) for p in trigger_percents_raw]

    last_mode = stages_config.get("last_stage_trigger_mode") or (
        DEFAULT_LAST_TRIGGER_MODE_SHORT if side == "SHORT" else DEFAULT_LAST_TRIGGER_MODE_LONG
    )
    last_pct = _decimal_or_none(stages_config.get("last_stage_trigger_percent"))
    if last_pct is None:
        last_pct = DEFAULT_LAST_SHORT_TRIGGER_PCT if side == "SHORT" else DEFAULT_LAST_LONG_TRIGGER_PCT

    return {
        "capitals": capitals,
        "trigger_percents": trigger_percents,
        "last_mode": last_mode,
        "last_pct": last_pct,
    }


def _legacy_template_to_stages_config(t: StrategyTemplate) -> dict[str, Any]:
    """구 4-단계 dataclass → stages_config 변환. 단위 테스트 호환용."""
    return {
        "capitals": [t.stage1_capital, t.stage2_capital, t.stage3_capital, t.stage4_capital],
        "trigger_percents": [None, t.stage2_trigger_percent, t.stage3_trigger_percent, None],
        "last_stage_trigger_mode": t.stage4_trigger_mode,
        "last_stage_trigger_percent": t.stage4_trigger_percent,
    }


# =============================================================================
# Calculator
# =============================================================================
class StrategyCalculator:
    def __init__(self, symbol_rule: SymbolRule) -> None:
        self.symbol_rule = symbol_rule

    # ---------- public API ----------
    def calculate_preview(
        self,
        *,
        symbol: str,
        side: Side,
        start_price: Decimal,
        template: StrategyTemplate | None = None,
        stages_config: dict[str, Any] | None = None,
        leverage: int | None = None,
        total_capital: Decimal | None = None,
        tp1_percent: Decimal | None = None,
        tp2_percent: Decimal | None = None,
        tp3_percent: Decimal | None = None,
        stop_loss_percent_of_capital: Decimal | None = None,
    ) -> StrategyPreview:
        """동적 N단계 + 호환용 template 모두 지원."""
        # template 이 제공되면 그걸로 대체값 채움
        if template is not None:
            stages_config = stages_config or _legacy_template_to_stages_config(template)
            leverage = leverage if leverage is not None else template.leverage
            total_capital = total_capital if total_capital is not None else template.total_capital
            tp1_percent = tp1_percent if tp1_percent is not None else template.tp1_percent
            tp2_percent = tp2_percent if tp2_percent is not None else template.tp2_percent
            tp3_percent = tp3_percent if tp3_percent is not None else template.tp3_percent
            stop_loss_percent_of_capital = (
                stop_loss_percent_of_capital
                if stop_loss_percent_of_capital is not None
                else template.stop_loss_percent_of_capital
            )

        if leverage is None or total_capital is None:
            raise ValueError("leverage and total_capital are required")
        if any(v is None for v in (tp1_percent, tp2_percent, tp3_percent, stop_loss_percent_of_capital)):
            raise ValueError("tp1/tp2/tp3 percent and stop_loss_percent_of_capital are required")

        cfg = _normalize_stages_config(stages_config, side, total_capital)
        capitals: list[Decimal] = cfg["capitals"]
        trigger_percents: list[Decimal | None] = cfg["trigger_percents"]
        last_mode: str = cfg["last_mode"]
        last_pct: Decimal = cfg["last_pct"]
        n = len(capitals)

        stages: list[StagePlan] = []
        prev_anchor_price: Decimal = self._quantize_price(start_price)

        for i, capital in enumerate(capitals):
            stage_no = i + 1
            is_first = i == 0
            is_last = i == n - 1

            if is_first:
                price = prev_anchor_price
                qty = self.compute_qty_from_capital(capital=capital, price=price)
                stages.append(
                    StagePlan(
                        stage_no=stage_no,
                        trigger_mode="IMMEDIATE",
                        trigger_price=price,
                        planned_capital=capital,
                        planned_qty=qty,
                    )
                )
                prev_anchor_price = price
                continue

            if is_last:
                # 마지막 단계: SHORT 의 경우 청산가 기반이라 trigger_price 는 후속 산출 (None).
                # LONG 또는 last_mode == PRICE_DOWN_PCT/UP_PCT 면 가격을 미리 산출.
                pct = last_pct
                mode = last_mode
                if mode == "LIQUIDATION_BUFFER":
                    stages.append(
                        StagePlan(
                            stage_no=stage_no,
                            trigger_mode=mode,
                            trigger_percent=pct,
                            trigger_price=None,  # 청산가 산출 시점에 채움
                            planned_capital=capital,
                            planned_qty=None,
                        )
                    )
                else:
                    multiplier = self._multiplier(side, pct)
                    price = self._quantize_price(prev_anchor_price * multiplier)
                    qty = self.compute_qty_from_capital(capital=capital, price=price)
                    stages.append(
                        StagePlan(
                            stage_no=stage_no,
                            trigger_mode=mode,
                            trigger_percent=pct,
                            trigger_price=price,
                            planned_capital=capital,
                            planned_qty=qty,
                        )
                    )
                continue

            # 중간 단계
            pct = trigger_percents[i] if trigger_percents[i] is not None else DEFAULT_MIDDLE_TRIGGER_PCT
            mode = "PRICE_UP_PCT" if side == "SHORT" else "PRICE_DOWN_PCT"
            multiplier = self._multiplier(side, pct)
            price = self._quantize_price(prev_anchor_price * multiplier)
            qty = self.compute_qty_from_capital(capital=capital, price=price)
            stages.append(
                StagePlan(
                    stage_no=stage_no,
                    trigger_mode=mode,
                    trigger_percent=pct,
                    trigger_price=price,
                    planned_capital=capital,
                    planned_qty=qty,
                )
            )
            prev_anchor_price = price

        stop_loss_amount = self._quantize_price(
            total_capital * (stop_loss_percent_of_capital / Decimal("100"))
        )
        return StrategyPreview(
            symbol=symbol,
            side=side,
            leverage=leverage,
            stages=stages,
            tp1_percent=tp1_percent,
            tp2_percent=tp2_percent,
            tp3_percent=tp3_percent,
            stop_loss_amount=stop_loss_amount,
        )

    def compute_short_last_stage_trigger_from_liquidation(self, liquidation_price: Decimal) -> Decimal:
        """SHORT 마지막 단계의 trigger_price 를 청산가의 95% 로 산출."""
        return self._quantize_price(liquidation_price * Decimal("0.95"))

    # 호환용 alias (구 이름)
    compute_short_stage4_trigger_from_liquidation = compute_short_last_stage_trigger_from_liquidation

    def compute_tp_prices(self, *, side: Side, avg_entry_price: Decimal) -> dict[str, Decimal]:
        if side == "LONG":
            vals = [
                avg_entry_price * Decimal("1.10"),
                avg_entry_price * Decimal("1.20"),
                avg_entry_price * Decimal("1.30"),
            ]
        else:
            vals = [
                avg_entry_price * Decimal("0.90"),
                avg_entry_price * Decimal("0.80"),
                avg_entry_price * Decimal("0.70"),
            ]
        return {
            "tp1": self._quantize_price(vals[0]),
            "tp2": self._quantize_price(vals[1]),
            "tp3": self._quantize_price(vals[2]),
        }

    def compute_qty_from_capital(self, *, capital: Decimal, price: Decimal) -> Decimal:
        qty = self._quantize_qty(capital / price)
        if qty < self.symbol_rule.min_qty:
            raise ValueError(
                f"calculated quantity {qty} below min_qty {self.symbol_rule.min_qty} "
                f"(capital={capital}, price={price})"
            )
        return qty

    # ---------- helpers ----------
    @staticmethod
    def _multiplier(side: Side, pct: Decimal) -> Decimal:
        if side == "SHORT":
            return Decimal("1") + (pct / Decimal("100"))
        return Decimal("1") - (pct / Decimal("100"))

    def _quantize_price(self, value: Decimal) -> Decimal:
        if self.symbol_rule.tick_size == 0:
            return value
        return (value // self.symbol_rule.tick_size) * self.symbol_rule.tick_size

    def _quantize_qty(self, value: Decimal) -> Decimal:
        if self.symbol_rule.step_size == 0:
            return value
        return (value // self.symbol_rule.step_size) * self.symbol_rule.step_size
