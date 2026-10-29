"""A1~D5: 돈 계산과 가짜 Redis 리더 잠금의 불변식을 검사한다.

대상 구현을 수정하거나 반례를 xfail로 숨기지 않는다.
네트워크, DB 세션, 실제 Redis는 사용하지 않는다.
"""

import math
from dataclasses import replace
from decimal import Decimal, InvalidOperation

import pytest

hypothesis = pytest.importorskip("hypothesis")

from hypothesis import event, example, given, strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    rule,
)

from app.services import capital_calculator as CC
from app.services import pump_dump_short as PDS
from app.workers import paper_retention_worker as PR
from app.workers import position_retention_worker as POS
from app.workers.distributed_scheduler_guard import DistributedSchedulerGuard


ZERO = Decimal("0")
HUNDRED = Decimal("100")
TICK = Decimal("0.0001")
LEADER_KEY = "sched:leader"


def money_strategy(lo, hi):
    return st.decimals(
        min_value=lo,
        max_value=hi,
        allow_nan=False,
        allow_infinity=False,
        places=4,
    )


MONEY = money_strategy(-(10**6), 10**7)
NONPOSITIVE_MONEY = money_strategy(-(10**6), 0)
POSITIVE_MONEY = money_strategy(TICK, 10**7)
NONNEGATIVE_MONEY = money_strategy(0, 10**7)


@given(w=NONPOSITIVE_MONEY, p=NONNEGATIVE_MONEY)
@example(w=ZERO, p=ZERO)
def test_A1_nonpositive_wallet_has_zero_limit(w, p):
    """A1: 양수가 아닌 지갑의 한도는 0이다: w≤0 ∧ p≥0 ⇒ L(w,p)=0."""
    assert CC.calc_wallet_limit(w, p) == ZERO


@given(
    w1=POSITIVE_MONEY,
    w2=POSITIVE_MONEY,
    p1=NONNEGATIVE_MONEY,
    p2=NONNEGATIVE_MONEY,
)
def test_A2_formula_and_monotonicity(w1, w2, p1, p2):
    """A2: 한도는 곱의 공식과 순서를 보존한다: L(w,p)=wp/100 ∧ wp≤vq⇒L(w,p)≤L(v,q)."""
    first = CC.calc_wallet_limit(w1, p1)
    second = CC.calc_wallet_limit(w2, p2)
    assert first == w1 * p1 / HUNDRED
    assert second == w2 * p2 / HUNDRED

    low_w, high_w = sorted((w1, w2))
    low_p, high_p = sorted((p1, p2))
    assert (
        CC.calc_wallet_limit(low_w, p1)
        <= CC.calc_wallet_limit(high_w, p1)
    )
    assert (
        CC.calc_wallet_limit(w1, low_p)
        <= CC.calc_wallet_limit(w1, high_p)
    )
    if w1 * p1 <= w2 * p2:
        assert first <= second
    else:
        assert first >= second


@given(w=POSITIVE_MONEY, p=NONNEGATIVE_MONEY)
@example(w=Decimal("1"), p=ZERO)
def test_A2_environment_ratio_is_fresh_and_preserves_zero(w, p):
    """A2: 환경 비율은 캐시나 0 대체 없이 반영된다: env=p ⇒ L(w)=L(w,p)."""
    with pytest.MonkeyPatch.context() as patch:
        for pct in (Decimal("130"), p, ZERO, Decimal("300")):
            patch.setenv("WALLET_LIMIT_PCT", str(pct))
            assert CC.get_wallet_limit_ratio() == pct / HUNDRED
            assert CC.calc_wallet_limit(w) == CC.calc_wallet_limit(w, pct)


@given(w=MONEY, r=MONEY, p=NONNEGATIVE_MONEY)
def test_A3_available_is_clamped_difference(w, r, p):
    """A3: 가용 자본은 음수가 아닌 한도 차액이다: A(w,r)=max(L(w)−r,0)≥0."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("WALLET_LIMIT_PCT", str(p))
        limit = CC.calc_wallet_limit(w)
        assert limit == CC.calc_wallet_limit(w, p)
        available = CC.calc_new_strategy_available(w, r)
        assert available >= ZERO
        assert available == max(limit - r, ZERO)


@given(w=MONEY, r=MONEY, p=NONNEGATIVE_MONEY)
def test_A4_exceeded_is_strict_comparison(w, r, p):
    """A4: 초과는 양수 지갑에서만 엄격 비교한다: E(w,r)=(r>L(w)) if w>0 else False."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("WALLET_LIMIT_PCT", str(p))
        limit = CC.calc_wallet_limit(w)
        expected = r > limit if w > ZERO else False
        assert CC.is_wallet_limit_exceeded(w, r) == expected
        if w > ZERO:
            assert not CC.is_wallet_limit_exceeded(w, limit)
            assert CC.is_wallet_limit_exceeded(w, limit + TICK)


@given(w=POSITIVE_MONEY, r=NONNEGATIVE_MONEY, p=NONNEGATIVE_MONEY)
def test_A5_exceeded_implies_zero_available(w, r, p):
    """A5: 초과 상태에서는 가용 자본이 0이다: w>0 ∧ r≥0 ∧ E(w,r) ⇒ A(w,r)=0."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("WALLET_LIMIT_PCT", str(p))
        if CC.is_wallet_limit_exceeded(w, r):
            assert CC.calc_new_strategy_available(w, r) == ZERO

        over = CC.calc_wallet_limit(w) + r + TICK
        assert CC.is_wallet_limit_exceeded(w, over)
        assert CC.calc_new_strategy_available(w, over) == ZERO


def finite_float(lo, hi):
    return st.floats(
        min_value=lo,
        max_value=hi,
        allow_nan=False,
        allow_infinity=False,
        allow_subnormal=False,
    )


@st.composite
def plans(draw):
    return PDS.Plan(
        key="pbt",
        label="속성 테스트",
        margins=tuple(
            draw(
                st.lists(
                    finite_float(1.0, 5000.0),
                    min_size=2,
                    max_size=5,
                )
            )
        ),
        gap_pct=draw(finite_float(1.0, 60.0)),
        loss_frac=draw(finite_float(0.05, 0.9)),
    )


SCALES = finite_float(0.1, 5.0)


def independent_legs(plan, scale):
    """입력에서 단계별 증거금과 가격을 구한다: mᵢ=Mᵢs, μᵢ=(1+g/100)ⁱ."""
    growth = 1.0 + plan.gap_pct / 100.0
    return [
        (margin * scale, growth**index)
        for index, margin in enumerate(plan.margins)
    ]


@given(plan=plans())
def test_B1_multipliers_start_at_one_and_increase(plan):
    """B1: 단계 배수는 1에서 시작해 엄격히 증가한다: μ₀=1 ∧ μᵢ<μᵢ₊₁."""
    mults = plan.mults()
    assert len(mults) == len(plan.margins)
    assert mults[0] == 1.0
    assert all(a < b for a, b in zip(mults, mults[1:]))


@given(plan=plans(), scale=SCALES)
def test_B2_price_bounds_and_total(plan, scale):
    """B2: 평단과 손절·청산 및 합계가 유효하다: 1≤avg≤μ끝 ∧ stop,liq>avg ∧ total=Σmᵢ."""
    nums = plan.numbers(scale)
    assert 1.0 <= nums["avg"] <= nums["mults"][-1]
    assert nums["stop"] > nums["avg"]
    assert nums["liq"] > nums["avg"]
    assert nums["total"] == sum(m * scale for m in plan.margins)
    assert nums["margins"] == [m * scale for m in plan.margins]


@given(plan=plans(), scale=SCALES)
def test_B3_stop_conserves_independent_short_loss(plan, scale):
    """B3: 손절 시 단계별 숏 손실이 설정 손실과 같다: Σ(mᵢ/μᵢ)(stop−μᵢ)=fΣmᵢ."""
    nums = plan.numbers(scale)
    legs = independent_legs(plan, scale)
    total = sum(m for m, _ in legs)
    qty = sum(m / px for m, px in legs)
    expected = plan.loss_frac * total

    independent_loss = math.fsum(
        (m / px) * (nums["stop"] - px)
        for m, px in legs
    )
    assert independent_loss == pytest.approx(expected, rel=1e-9, abs=0.0)
    assert qty * (nums["stop"] - nums["avg"]) == pytest.approx(
        expected, rel=1e-9, abs=0.0
    )
    assert nums["stop_loss_usdt"] == expected


def check_B4(plan, scale, lev):
    """B4: 손절·청산 순서는 가격 비교를 따른다: stop<liq ⇔ f<1/lev−MM."""
    nums = plan.numbers(scale)
    legs = independent_legs(plan, scale)
    total = sum(m for m, _ in legs)
    qty = sum(m / px for m, px in legs)

    liquidation_loss = math.fsum(
        (m / px) * (nums["liq"] - px)
        for m, px in legs
    )
    assert liquidation_loss == pytest.approx(
        total * (1.0 - PDS.MM), rel=1e-9, abs=0.0
    )

    threshold = 1.0 - PDS.MM * nums["avg"] * qty / total
    # 정확한 경계 부근은 별도 명시 예제로 분리하여
    # 비교식의 반올림 차이를 결함으로 오인하지 않는다.
    assert abs(plan.loss_frac - threshold) > 1e-6
    assert (nums["stop"] < nums["liq"]) == (
        plan.loss_frac < threshold
    )

    leveraged_qty = sum(m * lev / px for m, px in legs)
    entry_notional = sum(m * lev for m, _ in legs)
    leveraged_avg = entry_notional / leveraged_qty
    leveraged_liq = (
        leveraged_avg
        + (total - leveraged_avg * leveraged_qty * PDS.MM)
        / leveraged_qty
    )
    assert math.fsum(
        (m * lev / px) * (leveraged_liq - px)
        for m, px in legs
    ) == pytest.approx(
        total - PDS.MM * entry_notional,
        rel=1e-9,
        abs=0.0,
    )

    stop_first = nums["stop"] < leveraged_liq
    high = max(px for _, px in legs)
    high = max(high, nums["stop"], leveraged_liq) * 1.01
    result = PDS.simulate(
        h=[1.0, high],
        lw=[1.0, 1.0],
        c=[1.0, 1.0],
        n=0,
        half=0.5,
        plan=plan,
        hold=1,
        lev=lev,
        fee=0.0005,
        scale=scale,
    )
    assert result is not None
    assert result["stages"] == len(plan.margins)
    assert result["days"] == 1
    assert result["why"] == ("손절" if stop_first else "청산")


@given(plan=plans(), scale=SCALES, lev=st.integers(1, 3))
def test_B4_stop_liquidation_order(plan, scale, lev):
    """B4: 같은 봉에서 두 가격을 넘으면 먼저인 위험 가격으로 종료한다: why=손절 if stop<liq else 청산."""
    check_B4(plan, scale, lev)


BOUNDARY_LOSS = st.one_of(
    finite_float(0.9, 0.989),
    finite_float(0.991, 1.3),
)


@given(plan=plans(), scale=SCALES, loss_frac=BOUNDARY_LOSS)
@example(
    plan=PDS.Plan("boundary", "경계", (100.0, 100.0), 10.0, 0.5),
    scale=1.0,
    loss_frac=0.989,
)
@example(
    plan=PDS.Plan("boundary", "경계", (100.0, 100.0), 10.0, 0.5),
    scale=1.0,
    loss_frac=0.991,
)
def test_B4_additional_loss_boundary(plan, scale, loss_frac):
    """B4: 추가 경계 전략에서 손절 우선 여부가 양쪽으로 바뀐다: f<0.99⇒손절, f>0.99⇒청산."""
    check_B4(replace(plan, loss_frac=loss_frac), scale, 1)


@st.composite
def simulation_cases(draw, below_entry=False):
    plan = draw(plans())
    scale = draw(SCALES)
    n = draw(st.integers(0, 5))
    hold = draw(st.integers(1, 15))
    size = n + hold + 1 + draw(st.integers(0, 3))
    p0 = draw(finite_float(0.01, 100000.0))

    factors = draw(
        st.lists(
            st.tuples(
                finite_float(0.05, 1.0 if below_entry else 10.0),
                finite_float(0.01, 1.0),
                finite_float(0.0, 1.0),
            ),
            min_size=size,
            max_size=size,
        )
    )
    h, lw, c = [], [], []
    for high_factor, low_factor, position in factors:
        high = p0 * high_factor
        low = high * low_factor
        close = min(max(low + (high - low) * position, low), high)
        h.append(high)
        lw.append(low)
        c.append(close)

    h[n] = lw[n] = c[n] = p0
    assert all(
        0.0 < low <= close <= high
        for high, low, close in zip(h, lw, c)
    )
    if below_entry:
        assert all(high <= p0 for high in h[n + 1 :])

    return {
        "h": h,
        "lw": lw,
        "c": c,
        "n": n,
        "half": p0 * draw(finite_float(0.3, 1.0)),
        "plan": plan,
        "hold": hold,
        "lev": draw(st.integers(1, 3)),
        "fee": 0.0005,
        "scale": scale,
    }


def forced_case(kind, lev):
    """強制例でも正のOHLC条件を保つ: 0<lw≤c≤h."""
    plan = PDS.Plan(
        "forced",
        "分岐を保証",
        (100.0, 100.0),
        10.0,
        0.3,
    )
    if kind == "익절":
        high, low, close, half = 1.0, 0.8, 0.9, 0.9
    elif kind == "시간":
        high, low, close, half = 1.0, 1.0, 1.0, 0.5
    else:
        high, low, close, half = 10.0, 1.0, 1.0, 0.5
    return {
        "h": [1.0, high],
        "lw": [1.0, low],
        "c": [1.0, close],
        "n": 0,
        "half": half,
        "plan": plan,
        "hold": 1,
        "lev": lev,
        "fee": 0.0005,
        "scale": 1.0,
    }


def validate_result(case, result):
    """B5: 完全区間では結果の範囲を満たす: why∈許容値 ∧ 1≤stages≤K ∧ 1≤days≤hold."""
    assert result is not None
    event(f"why={result['why']}")
    event(f"stages={result['stages']}")
    event(f"lev={case['lev']}")
    assert result["why"] in {"손절", "청산", "익절", "시간"}
    assert type(result["stages"]) is int
    assert type(result["days"]) is int
    assert 1 <= result["stages"] <= len(case["plan"].margins)
    assert 1 <= result["days"] <= case["hold"]
    assert math.isfinite(result["pnl"])


@given(case=simulation_cases())
@example(case=forced_case("익절", 3))
@example(case=forced_case("손절", 1))
@example(case=forced_case("청산", 3))
@example(case=forced_case("시간", 1))
def test_B5_B6_B7_simulation_invariants(case):
    """B5·B6·B7: 결과 범위와 손실 상한 및 익절 이익을 지킨다: valid ∧ pnl≥−bound ∧ (익절⇒gross≥0)."""
    result = PDS.simulate(**case)
    validate_result(case, result)

    count = result["stages"]
    margins = [
        margin * case["scale"]
        for margin in case["plan"].margins[:count]
    ]
    used = sum(margins)
    fee_bound = used * 2.0 * case["fee"] * case["lev"]

    # B6: 요구된 상한을 그대로 검사한다.
    bound = used * (1.0 + 2.0 * case["fee"] * case["lev"])
    assert result["pnl"] >= -(bound + 1e-9), "B6"

    if result["why"] == "익절":
        # B7: 입력과 진입 단계 수로 익절 가격·수수료를 독립 계산한다.
        p0 = case["c"][case["n"]]
        growth = 1.0 + case["plan"].gap_pct / 100.0
        entries = [
            (p0 * growth**index, margin)
            for index, margin in enumerate(margins)
        ]
        qty = sum(
            margin * case["lev"] / px
            for px, margin in entries
        )
        notional = sum(margin * case["lev"] for margin in margins)
        avg = notional / qty
        exit_px = min(case["half"], avg * 0.995)
        exact_fee = sum(
            (
                margin * case["lev"]
                + (margin * case["lev"] / px) * exit_px
            )
            * case["fee"]
            for px, margin in entries
        )
        independent_gross = math.fsum(
            (margin * case["lev"] / px) * (px - exit_px)
            for px, margin in entries
        )
        assert result["pnl"] >= -(fee_bound + 1e-9), "B7"
        assert result["pnl"] + exact_fee >= -1e-9, "B7"
        assert independent_gross >= -1e-9, "B7"
        assert result["pnl"] + exact_fee == pytest.approx(
            independent_gross, rel=1e-9, abs=1e-9
        ), "B7"


@given(case=simulation_cases(below_entry=True))
def test_B8_prices_below_entry_never_add_stages(case):
    """B8: 이후 고가가 진입가 이하이면 추가 진입하지 않는다: ∀j>n,hⱼ≤cₙ ⇒ stages=1."""
    p0 = case["c"][case["n"]]
    assert all(high <= p0 for high in case["h"][case["n"] + 1 :])
    result = PDS.simulate(**case)
    validate_result(case, result)
    assert result["stages"] == 1


RETENTION_MODULES = (
    pytest.param(PR, id="paper"),
    pytest.param(POS, id="position"),
)

NUMERIC_TEXT = st.from_regex(
    r"[+-]?[0-9]{0,3}\.?[0-9]{0,3}([eE][+-]?[0-9]{1,4})?",
    fullmatch=True,
)

RETENTION_INPUTS = st.one_of(
    st.integers(-(10**30), 10**30),
    st.integers(-(10**30), 10**30).map(str),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(max_size=80),
    NUMERIC_TEXT,
    st.none(),
    st.sampled_from(
        [
            0,
            0.0,
            -0.0,
            "0",
            " 0 ",
            "+0",
            "-0",
            "0.0",
            "0e10",
            "1e-400",
            "-1e-999",
            "nan",
            "inf",
            "-inf",
            "1.5",
            "",
            " ",
        ]
    ),
)


def is_exact_zero(raw):
    """정확한 0만 끔의 입력이다: zero(x) ⇔ 유효한 유한 수 x=0."""
    if raw is None or isinstance(raw, bool):
        return False
    if isinstance(raw, int):
        return raw == 0
    if isinstance(raw, float):
        return math.isfinite(raw) and raw == 0.0
    if isinstance(raw, str):
        text = raw.strip()
        # Decimal이 허용하더라도 float 문법상 읽을 수 없는 문자열은 제외한다.
        try:
            float(text)
            number = Decimal(text)
        except (InvalidOperation, ValueError, OverflowError):
            return False
        # 알려진 경계(2026-10-29 리드 결정): 코드는 float 로 읽으므로 "1e-400" 처럼 float 로 0 이 되는 값도 「끔」이다.
        # 끔 = 지우지 않음(안전 쪽)이라 코드는 그대로 두고, 오라클을 코드의 정의(float 로 정확히 0)에 맞춘다.
        return number.is_finite() and float(text) == 0.0
    return False


@pytest.mark.parametrize("module", RETENTION_MODULES)
@given(raw=RETENTION_INPUTS)
def test_C1_retention_result_is_bounded_integer_or_none(module, raw):
    """C1: 결과는 끔 또는 범위 내 정수다: R(x)=None ∨ (type(R(x))=int ∧ MIN≤R(x)≤MAX)."""
    result = module.retention_days(raw)
    assert result is None or (
        type(result) is int
        and module.MIN_DAYS <= result <= module.MAX_DAYS
    )


@pytest.mark.parametrize("module", RETENTION_MODULES)
@given(raw=RETENTION_INPUTS)
@example(raw=0)
@example(raw=0.0)
@example(raw=-0.0)
@example(raw="0")
@example(raw=" 0 ")
@example(raw="1e-400")
@example(raw="-1e-999")
def test_C2_only_exact_zero_disables_retention(module, raw):
    """C2: 수학적으로 정확한 0만 보관을 끈다: R(x)=None ⇔ exact_zero(x)."""
    assert (module.retention_days(raw) is None) == is_exact_zero(raw)


@pytest.mark.parametrize("module", RETENTION_MODULES)
@given(data=st.data())
def test_C3_in_range_integer_and_string_are_preserved(module, data):
    """C3: 범위 내 정수는 문자열 표현에서도 보존된다: MIN≤d≤MAX ⇒ R(d)=R(str(d))=d."""
    days = data.draw(
        st.integers(module.MIN_DAYS, module.MAX_DAYS),
        label="보관 일수",
    )
    assert module.retention_days(days) == days
    assert module.retention_days(str(days)) == days


@pytest.mark.parametrize("module", RETENTION_MODULES)
@given(raw=RETENTION_INPUTS)
def test_C4_retention_is_idempotent(module, raw):
    """C4: 끔이 아닌 결과를 재해석해도 같다: r=R(x)≠None ⇒ R(r)=r."""
    result = module.retention_days(raw)
    if result is not None:
        assert module.retention_days(result) == result


class FakeRedis:
    """지정된 가짜 Redis: 유효한 키는 exp>now인 동안 값을 유지한다."""

    def __init__(self):
        self.now = 0.0
        self.data = {}

    def get(self, k):
        v, exp = self.data.get(k, (None, None))
        if exp is not None and exp <= self.now:
            self.data.pop(k, None)
            return None
        return v

    def set(self, k, v, nx=False, ex=None):
        if nx and self.get(k) is not None:
            return False
        self.data[k] = (
            v.encode() if isinstance(v, str) else v,
            self.now + ex if ex else None,
        )
        return True

    def expire(self, k, sec):
        v = self.get(k)
        if v is None:
            return False
        self.data[k] = (v, self.now + sec)
        return True

    def delete(self, *ks):
        return sum(self.data.pop(k, None) is not None for k in ks)

    def eval(self, script, numkeys, key, owner, *rest):
        if "expire" in script:
            ttl, stopping = rest
            cur = self.get(key)
            if cur is not None and cur.decode() == owner:
                return int(self.expire(key, int(ttl)))
            if cur is None and stopping == "0":          # 실제 코드는 문자열 "0"/"1" 을 넘긴다(요구사항 가짜 Redis 그대로)
                return (
                    2
                    if self.set(key, owner, nx=True, ex=int(ttl))
                    else 0
                )
            return 0
        cur = self.get(key)
        if cur is not None and cur.decode() == owner:
            return self.delete(key)
        return 0


class SchedulerLeaderMachine(RuleBasedStateMachine):
    """D1~D5: 任意の命令列で所有・隔離・終了・再取得を保つ: ∀sequence,D1∧D2∧D3∧D4∧D5."""

    def __init__(self):
        super().__init__()
        self.redis = FakeRedis()
        self.all_nodes = []
        for index in range(3):
            node = DistributedSchedulerGuard(
                self.redis,
                leader_ttl_seconds=30,
            )
            node.node_id = f"pbt-node-{index}"
            self.all_nodes.append(node)
        self.nodes = self.all_nodes[:2]

    @initialize(node_count=st.integers(2, 3))
    def select_active_nodes(self, node_count):
        self.nodes = self.all_nodes[:node_count]

    def refresh_and_check(self, index):
        """D2~D5: 갱신은 소유권과 종료 상태를 지킨다: success⇒owner=id ∧ empty∧¬stop⇒success."""
        node = self.nodes[index % len(self.nodes)]
        before = self.redis.get(LEADER_KEY)
        before_record = self.redis.data.get(LEADER_KEY)
        was_stopping = bool(node.stopping)

        result = node.refresh_leader()
        after = self.redis.get(LEADER_KEY)

        if result:
            assert after == node.node_id.encode(), "D2"

        if before is not None and before != node.node_id.encode():
            assert after == before, "D3"
            assert self.redis.data.get(LEADER_KEY) == before_record, "D3"

        if before is None and was_stopping:
            assert not result, "D4"
            assert after is None, "D4"
            assert LEADER_KEY not in self.redis.data, "D4"

        if before is None and not was_stopping:
            assert result, "D5: 활성 노드는 빈 리더 잠금을 복구해야 한다"
            assert after == node.node_id.encode(), "D5"

    @rule(index=st.integers(0, 2))
    def try_become(self, index):
        self.nodes[index % len(self.nodes)].try_become_leader()

    @rule(index=st.integers(0, 2))
    def refresh(self, index):
        """D2~D5: 임의 노드 갱신도 잠금 불변식을 지킨다: refresh⇒D2∧D3∧D4∧D5."""
        self.refresh_and_check(index)

    @rule(index=st.integers(0, 2))
    def release(self, index):
        """D4: 해제는 종료를 표시하고 자기 키만 지운다: release(i)⇒stoppingᵢ ∧ 타인기록불변."""
        node = self.nodes[index % len(self.nodes)]
        before = self.redis.get(LEADER_KEY)
        before_record = self.redis.data.get(LEADER_KEY)
        node.release_leader()
        assert node.stopping, "D4"

        if before == node.node_id.encode():
            assert self.redis.get(LEADER_KEY) is None
        else:
            assert self.redis.get(LEADER_KEY) == before
            assert self.redis.data.get(LEADER_KEY) == before_record

    @rule(seconds=st.integers(0, 40))
    def advance_time(self, seconds):
        self.redis.now += seconds

    @rule()
    def external_delete(self):
        self.redis.delete(LEADER_KEY)

    @rule(index=st.integers(0, 2))
    def delete_then_refresh(self, index):
        """D4·D5: 외부 삭제 뒤 활성 노드만 복구한다: empty⇒(success⇔¬stopping)."""
        self.redis.delete(LEADER_KEY)
        self.refresh_and_check(index)

    @invariant()
    def D1_owner_is_none_or_known_node(self):
        """D1: 리더 값은 비었거나 활성 노드 중 하나다: owner∈{None,id₀,…,idₖ}."""
        owners = {node.node_id.encode() for node in self.nodes}
        assert self.redis.get(LEADER_KEY) in owners | {None}, "D1"


TestSchedulerLeaderMachine = SchedulerLeaderMachine.TestCase
TestSchedulerLeaderMachine.__doc__ = (
    "D1~D5: 임의 명령열에서 잠금 불변식을 지킨다: "
    "∀sequence,D1∧D2∧D3∧D4∧D5."
)
