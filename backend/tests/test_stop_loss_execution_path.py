"""🚨 손절 **실행 경로** 통합 테스트 — 「진짜로 부분 손절이 나가는가」.

사장님 2026-09-03: **"이렇게 하고도 안되면 어떻게 할꺼야"**

## 왜 이 파일이 필요한가

지금까지 내 테스트는 전부 **정적 검사**였다 — "소스에 이 문자열이 있나".
그건 **「그 함수가 실제로 불린다」를 증명하지 못한다.**

실제로 그래서 사고가 났다 (Fix 318 → 319):

    if evaluate_force_stop_loss(...):
        self._execute_force_stop_loss(strategy)   # 사장님 -5%/-10% 는 여기로 온다
    if evaluate_stop_loss(...):
        self._execute_stop_loss(strategy)          # Fix 318 이 붙었던 곳 (-80~90%)

같은 이름의 손절 함수가 둘인데 아래쪽을 고쳤다. 정적 검사 13건이 **전부 통과**했고
배포까지 됐는데, 사장님 손절은 여전히 전량으로 나가 #2046 이 전량 청산됐다.

## 이 테스트가 하는 것

`TPSLOrchestratorService` 를 **실제로 실행**하고, 거래소로 나가는
`emergency_close_position(quantity=...)` 호출을 가로채 **수량을 검사**한다.

  · 손절이 어느 함수를 타든 상관없다 — **주문이 부분인지만 본다**
  · 함수를 잘못 고르면 이 테스트가 **즉시 실패**한다
  · 잔량을 남겼는데 STOPPING 을 찍으면 실패한다
  · 부분인데 미체결 주문을 취소하면 실패한다

= **배포 전에 「진짜로 되는가」를 확인하는 유일한 방법.**
"""
from decimal import Decimal

import pytest

from app.services import tp_sl_orchestrator as O


D = Decimal


# ─────────────────────────────────────────────────────────────────────
# 최소 스텁 — 실제 코드 경로를 그대로 태우되 거래소·DB 만 가짜로
# ─────────────────────────────────────────────────────────────────────

class _Strategy:
    def __init__(self, qty, avg, *, mode="fixed", stage=1):
        self.id = 999
        self.symbol = "DOGEUSDT"
        self.side = "SHORT"
        self.status = "STAGE1_OPEN"
        self.current_position_qty = D(str(qty))
        self.avg_entry_price = D(str(avg))
        self.leverage = 2
        self.total_capital = D("300")
        self.realized_pnl = D("0")
        self.unrealized_pnl = D("-15")
        self.capital_management_mode = mode
        self.current_stage = stage
        self.retry_after_liquidation_enabled = False
        self.strategy_template_id = None


class _Calls:
    """거래소로 나간 호출을 전부 기록한다."""

    def __init__(self):
        self.closes = []        # [(quantity, for_stage_transition)]
        self.cancels = []       # [symbol]


class _ExecStub:
    def __init__(self, calls, mark):
        self._calls = calls
        self._mark = D(str(mark))
        self.client = self

    # execution_service.client.cancel_all_orders
    def cancel_all_orders(self, symbol):
        self._calls.cancels.append(symbol)

    def _fetch_current_mark_price(self, symbol):
        return self._mark

    def emergency_close_position(self, strategy_id, *, quantity,
                                 for_stage_transition=False):
        self._calls.closes.append((D(str(quantity)), bool(for_stage_transition)))
        return object()


class _NotifyStub:
    def send_stop_loss_alert(self, **_kw):
        pass

    def send_system_alert(self, **_kw):
        pass


class _RiskStub:
    def mark_reentry_ready(self, _sid):
        pass


class _Sym:
    """symbols 테이블 한 행."""
    step_size = D("1")
    min_qty = D("1")
    min_notional = D("5")


class _DB:
    """SystemSetting + Symbol 조회만 흉내낸다."""

    def __init__(self, settings):
        self._s = settings

    def get(self, model, key):
        if getattr(model, "__name__", "") == "SystemSetting":
            if key not in self._s:
                return None
            return type("R", (), {"value": self._s[key]})()
        return None

    def execute(self, _stmt):
        class _R:
            def scalar_one_or_none(self_inner):
                return _Sym()
        return _R()

    def commit(self):
        pass

    def rollback(self):
        pass


def _make(strategy, mark, settings):
    """orchestrator 를 __init__ 없이 만들고 스텁을 꽂는다."""
    svc = O.TPSLOrchestratorService.__new__(O.TPSLOrchestratorService)
    calls = _Calls()
    svc.db = _DB(settings)
    svc.execution_service = _ExecStub(calls, mark)
    svc.notification_service = _NotifyStub()
    svc.risk_service = _RiskStub()
    svc.strategy_repo = None
    return svc, calls


TRIM_ON = {
    "stage_trim_before_next_enabled": "1",
    "stage_keep_notional_usdt": "10",
}


# ─────────────────────────────────────────────────────────────────────
# 🚨 핵심 — 사장님이 실제로 쓰는 손절 (force SL) 이 부분으로 나가는가
# ─────────────────────────────────────────────────────────────────────

def test_force_SL이_부분_주문을_보낸다():
    """사장님 force_sl_roi_override(-5%/-10%) 가 타는 경로.

    보유 12,000 x 0.05 = 명목 600 → 10 USDT 만 남기고 청산해야 한다.
    """
    st = _Strategy(qty=-12000, avg="0.05")
    svc, calls = _make(st, mark="0.05", settings=TRIM_ON)

    svc._execute_force_stop_loss(st)

    assert len(calls.closes) == 1, "청산 주문이 정확히 한 번 나가야 한다"
    qty, for_stage = calls.closes[0]
    assert qty < D("12000"), f"전량({qty})이 나갔다 — 부분 손절이 아니다"
    keep = D("12000") - qty
    assert keep * D("0.05") >= D("10"), f"잔량 명목이 10 미만: {keep * D('0.05')}"
    assert for_stage is True, "for_stage_transition 을 안 넘기면 주문이 취소된다"


def test_force_SL_부분이면_전략을_종료하지_않는다():
    st = _Strategy(qty=-12000, avg="0.05")
    svc, _c = _make(st, mark="0.05", settings=TRIM_ON)
    svc._execute_force_stop_loss(st)
    assert st.status != "STOPPING", "STOPPING 을 찍으면 전략이 죽어 다음 단계가 없다"


def test_force_SL_부분이면_미체결_주문을_취소하지_않는다():
    """🚨 취소하면 다음 단계 트리거 LIMIT 이 사라져 사다리가 끊긴다."""
    st = _Strategy(qty=-12000, avg="0.05")
    svc, calls = _make(st, mark="0.05", settings=TRIM_ON)
    svc._execute_force_stop_loss(st)
    assert calls.cancels == [], f"취소가 나갔다: {calls.cancels}"


# ─────────────────────────────────────────────────────────────────────
# 전량이어야 하는 경우
# ─────────────────────────────────────────────────────────────────────

def test_1단계_소액은_전량_손절된다():
    """1단계 10 USDT x 레버2 = 명목 20 → 10 을 남기면 절반뿐이라 의미가 없다.
    손절은 반드시 나가야 하므로 전량이 맞다."""
    st = _Strategy(qty=-400, avg="0.05")     # 명목 20
    svc, calls = _make(st, mark="0.05", settings=TRIM_ON)
    svc._execute_force_stop_loss(st)
    assert calls.closes[0][0] == D("400"), "전량이어야 한다"
    assert st.status == "STOPPING"


def test_trim이_꺼져있으면_전량_손절():
    st = _Strategy(qty=-12000, avg="0.05")
    svc, calls = _make(st, mark="0.05", settings={})
    svc._execute_force_stop_loss(st)
    assert calls.closes[0][0] == D("12000")
    assert st.status == "STOPPING"


def test_볼밴분할은_전량_손절():
    """물타기가 설계인 전략을 단계마다 자르면 안 된다."""
    st = _Strategy(qty=-12000, avg="0.05", mode="split_entry")
    svc, calls = _make(st, mark="0.05", settings=TRIM_ON)
    svc._execute_force_stop_loss(st)
    assert calls.closes[0][0] == D("12000")


def test_시세_조회_실패해도_손절은_나간다():
    """🚨 손절을 건너뛰면 손실이 무한정 커진다 — 반드시 전량으로라도 나가야 한다."""
    st = _Strategy(qty=-12000, avg="0.05")
    svc, calls = _make(st, mark="0.05", settings=TRIM_ON)

    def _boom(_sym):
        raise RuntimeError("api down")

    svc.execution_service._fetch_current_mark_price = _boom
    svc._execute_force_stop_loss(st)
    assert calls.closes, "손절 주문이 아예 안 나갔다 — 가장 위험한 실패"
    assert calls.closes[0][0] == D("12000")


# ─────────────────────────────────────────────────────────────────────
# 일반 SL(-80~90%) 도 같은 규칙인지
# ─────────────────────────────────────────────────────────────────────

def test_일반_SL도_부분_주문을_보낸다():
    st = _Strategy(qty=-12000, avg="0.05")
    svc, calls = _make(st, mark="0.05", settings=TRIM_ON)
    svc._execute_stop_loss(st)
    assert calls.closes
    assert calls.closes[0][0] < D("12000"), "일반 SL 도 부분이어야 한다"


# ─────────────────────────────────────────────────────────────────────
# 🚨 함수를 잘못 고르는 사고를 구조적으로 막는다
# ─────────────────────────────────────────────────────────────────────

def test_손절_실행_함수가_둘_뿐인지_확인():
    """새 손절 경로가 생기면 이 테스트가 실패해 **부분 손절 적용을 강제**한다.

    Fix 318 사고: `_execute_stop_loss` 만 고치고 `_execute_force_stop_loss` 를
    놓쳐서 사장님 손절이 전량으로 나갔다.
    """
    import ast
    from pathlib import Path
    src = Path(O.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    执 = {
        n.name for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
        and n.name.startswith("_execute_")
        and "stop_loss" in n.name
    }
    assert 执 == {"_execute_stop_loss", "_execute_force_stop_loss"}, (
        f"손절 실행 함수가 바뀌었다: {sorted(执)} — "
        "새 경로에도 compute_trim 을 적용했는지 확인하라"
    )


@pytest.mark.parametrize("fn_name", ["_execute_stop_loss", "_execute_force_stop_loss"])
def test_모든_손절_경로가_실제로_부분_주문을_낸다(fn_name):
    """정적 검사가 아니라 **실행**으로 확인한다."""
    st = _Strategy(qty=-12000, avg="0.05")
    svc, calls = _make(st, mark="0.05", settings=TRIM_ON)
    getattr(svc, fn_name)(st)
    assert calls.closes, f"{fn_name}: 주문이 안 나갔다"
    assert calls.closes[0][0] < D("12000"), f"{fn_name}: 전량이 나갔다"
