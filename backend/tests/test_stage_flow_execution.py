"""🚨 단계 흐름 **실행** 테스트 — 기본 방식 / OBV 자동이 진짜로 도는가.

사장님 2026-09-03: **"철저하게 기본 방식과 OBV 자동은 문제없게 해줘야해"**

## 왜 이 파일이 필요한가

정적 검사는 「그 함수가 실제로 불린다」를 증명하지 못한다.
그래서 오늘 세 번 사고가 났다:

  · Fix 318 → 엉뚱한 손절 함수에 붙였다 (정적 검사 13건 전부 통과)
  · Fix 311 → 1단계 진입을 통째로 막았다 (정적 검사 57건 전부 통과)
  · Fix 315 → 마커를 저장 안 해 손절을 다시 잠갔다 (테스트가 없었다)

이 파일은 `ExecutionService.trigger_next_stage` 를 **실제로 실행**하고,
거래소로 나가는 주문을 가로채 **순서와 수량**을 검사한다.

## 사장님 사양 (검증 대상)

    기본 방식 : 트리거 단가 도달 → 10 USDT 남기고 청산 → **그 단가에 다음 단계 진입**
    OBV 자동  : 같은 흐름 (판정만 stage_entry_signal 이 한다)
    1단계 10  : "손절없이 그냥" → 정리 없이 바로 다음 단계
    볼밴 분할 : 물타기가 설계 → **정리하지 않는다**
"""
from decimal import Decimal

import pytest

from app.services import execution_service as E


D = Decimal


# ─────────────────────────────────────────────────────────────────────
# 스텁 — 실제 코드 경로를 그대로 태우되 거래소·DB 만 가짜로
# ─────────────────────────────────────────────────────────────────────

class _Plan:
    def __init__(self, stage_no, capital, trigger_price):
        self.stage_no = stage_no
        self.planned_capital = D(str(capital))
        self.trigger_price = D(str(trigger_price)) if trigger_price else None
        self.planned_qty = D("1")
        self.is_triggered = False
        self.additional_margin_usdt = None


class _Strategy:
    def __init__(self, *, qty, avg, mode="fixed", stage=1, plans=None):
        self.id = 777
        self.symbol = "DOGEUSDT"
        self.side = "SHORT"
        self.status = "STAGE1_OPEN"
        self.current_position_qty = D(str(qty))
        self.avg_entry_price = D(str(avg))
        self.leverage = 2
        self.total_capital = D("910")
        self.realized_pnl = D("0")
        self.unrealized_pnl = D("-10")
        self.capital_management_mode = mode
        self.current_stage = stage
        self.retry_after_liquidation_enabled = False
        self.strategy_template_id = 1
        self.exchange_account_id = 1
        self.cumulative_realized_loss = D("0")
        self.stage_plans = plans or [
            _Plan(1, 10, None), _Plan(2, 300, "0.0505"), _Plan(3, 600, "0.0510"),
        ]


class _Trace:
    """거래소·내부 호출 순서를 그대로 기록한다."""

    def __init__(self):
        self.events = []            # [(what, detail)]

    def add(self, what, detail=None):
        self.events.append((what, detail))

    def names(self):
        return [e[0] for e in self.events]


class _Sym:
    step_size = D("1")
    min_qty = D("1")
    min_notional = D("5")


class _Tpl:
    strategy_type = "auto_bb_break_SAJANGNIM_TOP"
    trigger_mode = "PRICE_DOWN_PCT"
    name = "AUTO_BB_TEST"


class _DB:
    def __init__(self, settings):
        self._s = settings

    def get(self, model, key):
        n = getattr(model, "__name__", "")
        if n == "SystemSetting":
            if key not in self._s:
                return None
            return type("R", (), {"value": self._s[key]})()
        if n == "StrategyTemplate":
            return _Tpl()
        return None

    def execute(self, _stmt):
        class _R:
            def scalar_one_or_none(self_):
                return _Sym()
        return _R()

    def commit(self):
        pass

    def rollback(self):
        pass

    def refresh(self, _o):
        pass


def _make(strategy, settings, *, mark="0.0505"):
    """ExecutionService 를 __init__ 없이 만들고 스텁을 꽂는다."""
    svc = E.ExecutionService.__new__(E.ExecutionService)
    tr = _Trace()
    svc.db = _DB(settings)
    svc.client = object()

    svc._fetch_current_position_qty = lambda _s: abs(D(str(strategy.current_position_qty)))
    svc._fetch_current_mark_price = lambda _sym: D(str(mark))

    def _close(strategy_id, *, quantity, for_stage_transition=False):
        tr.add("CLOSE", (D(str(quantity)), bool(for_stage_transition)))
        return object()

    def _place(strat, plan, *, force_market=False):
        tr.add("ENTER", (plan.stage_no, plan.planned_capital, plan.trigger_price))
        return object()

    svc.emergency_close_position = _close
    svc._place_stage_entry_order = _place
    svc.strategy_repo = type("R", (), {"get_strategy": staticmethod(lambda _i: strategy)})()
    return svc, tr


TRIM_ON = {
    "stage_trim_before_next_enabled": "1",
    "stage_keep_notional_usdt": "10",
}


# ═════════════════════════════════════════════════════════════════════
# 🚨 기본 방식 — 사장님이 급하다고 하신 것
# ═════════════════════════════════════════════════════════════════════

def test_기본방식_정리_먼저_진입_나중():
    """🚨 순서가 뒤바뀌면 평단이 오염된 뒤에 청산하게 된다 = 의미 없음."""
    st = _Strategy(qty=-12000, avg="0.05")      # 명목 600
    svc, tr = _make(st, TRIM_ON)

    svc._trim_before_stage(st, 2)
    svc._place_stage_entry_order(st, st.stage_plans[1])

    assert tr.names() == ["CLOSE", "ENTER"], f"순서가 틀렸다: {tr.names()}"


def test_기본방식_10USDT만_남기고_청산한다():
    st = _Strategy(qty=-12000, avg="0.05")
    svc, tr = _make(st, TRIM_ON, mark="0.05")

    svc._trim_before_stage(st, 2)

    qty, for_stage = tr.events[0][1]
    keep = D("12000") - qty
    assert keep * D("0.05") >= D("10"), f"잔량 명목 부족: {keep * D('0.05')}"
    assert for_stage is True, "for_stage_transition 없으면 다음 단계 LIMIT 이 취소된다"


def test_기본방식_1단계_소액은_정리없이_진입():
    """사장님: "첫진입이 10이라 손절없이 그냥 좋은 포지션에 2단계 300으로 진입"

    🚨 Fix 311 이 여기서 예외를 던져 **2단계가 통째로 막혔던** 곳이다.
    """
    st = _Strategy(qty=-400, avg="0.05")        # 명목 20 = 1단계 10 x 레버2
    svc, tr = _make(st, TRIM_ON)

    svc._trim_before_stage(st, 2)               # 예외가 나면 안 된다
    svc._place_stage_entry_order(st, st.stage_plans[1])

    assert tr.names() == ["ENTER"], f"정리가 나가면 안 된다: {tr.names()}"


def test_기본방식_1단계에는_정리를_적용하지_않는다():
    st = _Strategy(qty=-12000, avg="0.05")
    svc, tr = _make(st, TRIM_ON)
    svc._trim_before_stage(st, 1)               # stage_no = 1
    assert tr.events == [], "1단계는 정리할 기존 포지션이 없다"


def test_기본방식_판정불가면_진입을_중단한다():
    """🚨 fail-open 하면 물타기가 그대로 일어난다 — 고치려던 것이 남는다."""
    st = _Strategy(qty=-12000, avg="0.05")
    svc, tr = _make(st, TRIM_ON)
    svc._fetch_current_mark_price = lambda _s: D("0")   # 시세 결손

    with pytest.raises(ValueError):
        svc._trim_before_stage(st, 2)
    assert tr.events == [], "중단인데 주문이 나갔다"


def test_기본방식_포지션조회_실패면_중단():
    """None 이 falsy 로 흘러 정리를 건너뛰면 물타기로 조용히 복귀한다."""
    st = _Strategy(qty=-12000, avg="0.05")
    svc, tr = _make(st, TRIM_ON)
    svc._fetch_current_position_qty = lambda _s: None

    with pytest.raises(ValueError):
        svc._trim_before_stage(st, 2)
    assert tr.events == []


def test_기본방식_trim_꺼지면_옛_동작():
    """설정이 없으면 정리 없이 그대로 — 기본 동작을 바꾸지 않는다."""
    st = _Strategy(qty=-12000, avg="0.05")
    svc, tr = _make(st, {})
    svc._trim_before_stage(st, 2)
    assert tr.events == []


# ═════════════════════════════════════════════════════════════════════
# 🚨 볼밴 분할 — 물타기가 설계다. 정리하면 안 된다
# ═════════════════════════════════════════════════════════════════════

def test_볼밴분할은_정리하지_않는다():
    """전역 스위치 하나가 다른 전략의 설계를 부수면 안 된다 (Fix 313)."""
    st = _Strategy(qty=-12000, avg="0.05", mode="split_entry")
    svc, tr = _make(st, TRIM_ON)
    svc._trim_before_stage(st, 2)
    assert tr.events == [], "볼밴 분할에 정리가 나갔다 — 설계 파괴"


# ═════════════════════════════════════════════════════════════════════
# 🚨 OBV 자동 — 같은 흐름을 타는가
# ═════════════════════════════════════════════════════════════════════

def test_OBV자동도_같은_정리를_거친다():
    """사장님: "기본전략도 obv 자동도 부분 손절후 좋은 포지션에 진입"

    단계 진입 실행부가 한 곳이므로 OBV 자동도 같은 정리를 탄다.
    """
    st = _Strategy(qty=-12000, avg="0.05")
    st.capital_management_mode = "fixed"
    svc, tr = _make(st, TRIM_ON)

    class _ObvTpl(_Tpl):
        trigger_mode = "OBV_REVERSE"
        strategy_type = "auto_bb_break_OBV_HOLD"

    svc.db.get = lambda m, k: (
        _ObvTpl() if getattr(m, "__name__", "") == "StrategyTemplate"
        else (type("R", (), {"value": TRIM_ON[k]})() if k in TRIM_ON else None)
    )

    svc._trim_before_stage(st, 2)
    assert tr.names() == ["CLOSE"], "OBV 자동에 정리가 안 걸렸다"


# ═════════════════════════════════════════════════════════════════════
# 🚨 단계 진입 경로가 하나인가 (우회로가 생기면 그 경로는 물타기가 된다)
# ═════════════════════════════════════════════════════════════════════

def test_단계_진입은_전부_정리를_거친다():
    """자동(`trigger_next_stage`)·수동(`enter_stage_at_market`) 양쪽."""
    import ast
    from pathlib import Path
    src = Path(E.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for name in ("trigger_next_stage", "enter_stage_at_market"):
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        seg = ast.get_source_segment(src, fn) or ""
        assert "_trim_before_stage" in seg, f"{name} 이 정리를 건너뛴다"


def test_정리_메서드가_하나뿐이다():
    """두 경로가 각자 구현하면 한쪽만 고쳐지는 사고가 난다."""
    from pathlib import Path
    src = Path(E.__file__).read_text(encoding="utf-8")
    assert src.count("def _trim_before_stage") == 1
    assert src.count("self._trim_before_stage(strategy, stage_no)") == 2
