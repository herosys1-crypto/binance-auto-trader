"""🌟 사장님이 직접 주신 수치를 코드가 재현하는가 (Fix 324).

## 사장님 원문 (2026-09-03, SHORT 레버 2)

    300 USDT 추가 진입 시점 (가격 0.2090 도달 시)
      진입 직전 전체 손실률: **-9.00%** (남겨둔 10 USDT 증거금 기준 평가손실 -0.9 USDT)
      진입 직후 전체 손실률: **-0.29%** (총 증거금이 **310** USDT 로 커지면서 희석)

    600 USDT 추가 진입 시점 (가격 0.2150 도달 시)
      진입 직전 전체 손실률: **-6.04%** (이전 평단가 **0.2087** 대비)
      진입 직후 전체 손실률: **-0.10%** (총 증거금 **610** USDT)

    최종 평균 진입단가 **0.2149**, 총 손실률 약 **-0.10%**

## 이 수치가 확정한 것

1. **「10 USDT」는 증거금이다** (명목 20). 명목 10 이면 -18% 가 나온다.
   내 옛 구현은 명목 기준이라 사장님 의도의 **절반**이었다.
2. **1단계는 정리하지 않는다.** 2단계 총 증거금이 310(=10+300)이므로
   1단계 10 이 그대로 살아 있다 — 사장님 "첫진입이 10이라 손절없이 그냥".
3. **손절선과 단계 트리거는 다른 지점이다.** 손절 raw 2.5%(ROI -5%)가 먼저 오고,
   그 뒤 트리거 단가 raw 4.5% 에서 다음 단계로 간다. 잔량이 살아 있으므로 가능.
   → 「간격이 손절폭보다 크면 2단계 도달 불가」라는 내 옛 결론은 **틀렸다.**
"""
from decimal import Decimal as D

from app.services import stage_trim as T


LEV = 2


class _Sym:
    step_size, min_qty, min_notional = D("0.0001"), D("0.0001"), D("5")


class _DB:
    def __init__(self, settings):
        self._s = settings

    def get(self, _m, k):
        return type("R", (), {"value": self._s[k]})() if k in self._s else None

    def execute(self, _q):
        class _R:
            def scalar_one_or_none(self_):
                return _Sym()
        return _R()


DB = _DB({"stage_trim_before_next_enabled": "1", "stage_keep_notional_usdt": "10"})


def _stage1():
    """1단계: 증거금 10, 진입 0.2000."""
    P1 = D("0.2000")
    return P1, D("10") * LEV / P1


def test_1단계는_정리하지_않는다():
    """사장님: "첫진입이 10이라 **손절없이 그냥** 2단계 300으로 진입"

    🚨 여기서 TRIM(전량)을 돌려주면 1단계가 통째로 잘려 사장님 수치(총 증거금
    310)가 성립하지 않는다.
    """
    P1, qty1 = _stage1()
    _c, _k, _why, act = T.compute_trim(DB, "X", qty1, D("0.2050"), leverage=LEV)
    assert act == T.ACTION_SKIP


def test_2단계_진입후_평단이_사장님_값과_같다():
    P1, qty1 = _stage1()
    P2 = D("0.2090")
    qty2 = qty1 + D("300") * LEV / P2
    avg2 = (qty1 * P1 + D("300") * LEV) / qty2
    assert abs(avg2 - D("0.2087")) < D("0.0002"), f"평단 {avg2} != 0.2087"


def test_2단계_진입직전_손실률이_마이너스9퍼센트():
    """잔량이 **증거금 10**(명목 20)이어야 -9.00% 가 나온다."""
    P1, qty1 = _stage1()
    loss = (D("0.2090") - P1) * qty1
    assert abs(loss - D("0.9")) < D("0.01"), f"손실 {loss} != 0.9"
    assert abs(-loss / D("10") * 100 - D("-9")) < D("0.1")


def test_2단계_손절이_증거금_10을_남긴다():
    """🚨 명목 10 을 남기면 증거금 5 = 사장님 의도의 절반이다."""
    P1, qty1 = _stage1()
    P2 = D("0.2090")
    qty2 = qty1 + D("300") * LEV / P2
    P_sl = D("0.2150")
    c, k, why, act = T.compute_trim(DB, "X", qty2, P_sl, leverage=LEV)
    assert act == T.ACTION_TRIM, why
    assert abs(k * P_sl / LEV - D("10")) < D("0.5"), (
        f"잔여 증거금 {k * P_sl / LEV} != 10")


def test_3단계_진입후_평단과_손실률이_사장님_값과_같다():
    P1, qty1 = _stage1()
    P2 = D("0.2090")
    qty2 = qty1 + D("300") * LEV / P2
    avg2 = (qty1 * P1 + D("300") * LEV) / qty2
    P3 = D("0.2150")
    _c, k2, _w, _a = T.compute_trim(DB, "X", qty2, P3, leverage=LEV)
    qty3 = k2 + D("600") * LEV / P3
    avg3 = (k2 * avg2 + D("600") * LEV) / qty3
    upnl = -(P3 - avg3) * qty3
    assert abs(avg3 - D("0.2149")) < D("0.0003"), f"평단 {avg3} != 0.2149"
    assert abs(upnl / D("610") * 100 - D("-0.10")) < D("0.05")


def test_레버리지가_바뀌면_잔량_명목도_바뀐다():
    """증거금 기준이므로 레버 3 이면 명목 30 을 남긴다."""
    px = D("0.2")
    qty = D("1000")          # 명목 200
    keeps = {}
    for lev in (1, 2, 3):
        _c, k, _w, _a = T.compute_trim(DB, "X", qty, px, leverage=lev)
        keeps[lev] = k * px
    assert keeps[2] > keeps[1] and keeps[3] > keeps[2], keeps
    assert abs(keeps[2] - D("20")) < D("1"), keeps


def test_레버리지를_안_주면_옛_동작():
    """조용히 두 배로 남기는 것보다 옛 동작(명목 기준)이 낫다."""
    _c, k, _w, _a = T.compute_trim(DB, "X", D("1000"), D("0.2"))
    assert abs(k * D("0.2") - D("10")) < D("1")


def test_호출부가_레버리지를_넘긴다():
    """🚨 안 넘기면 증거금의 절반만 남아 사장님 수치가 안 맞는다."""
    import ast
    from pathlib import Path
    from app.services import execution_service as E
    from app.services import tp_sl_orchestrator as O
    for mod in (E, O):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        calls = [
            n for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == "compute_trim"
        ]
        assert calls, f"{mod.__name__}: compute_trim 호출이 없다"
        for c in calls:
            kws = {k.arg for k in c.keywords}
            assert "leverage" in kws, (
                f"{mod.__name__}:{c.lineno} compute_trim 에 leverage 를 안 넘긴다 "
                f"→ 증거금의 절반만 남는다")
