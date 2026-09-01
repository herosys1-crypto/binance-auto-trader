"""📈 Fix 274 — LONG 은 「급등 중」에만.

## 사장님 사상 (2026-08-31 정정)

  "급등중에 조정은 **다시 급등**으로 간다고 했어 ...
   급락한건 언제 어떤 심볼이 급등하는 찾는게 **힘들다**고 헀어"

LONG 의 주력은 「급등 중 조정」이지 「아무 종목의 저점」이 아니다.
그런데 코드는 24h 변동을 제한하지 않았고, 평범한 종목의 저점 LONG 이
손실의 거의 전부였다.

## 실측 (LONG 130건 / 12일, Fix 270 이 켜진 위에)

    Fix270 만               30건 승률 43.3%   +12.15  건당 +0.40
    **Fix270 + 24h>=15%**   20건 승률 65.0%  **+80.07**  건당 **+4.00**  <- 채택

    차단: 24h<15%    85건 승률 **8.2%**  -803.25
          4H hist<=0 37건 승률   2.7%   -665.22

    과적합 검사 — 15% 만 양쪽 절반 모두 양수:
        10%  최근 -54.82 / 이전 +71.18
        15%  최근  +8.89 / 이전 +71.18   <- 채택
        20%  최근  -3.00 / 이전 +77.93

    현행 전체 130건 -947.45  ->  게이트 적용 20건 **+80.07**

## ⚠️ 더 조이면 나빠진다

레인지 위치·15m 조정 조건을 **더하면** -3.02 -> -12.85 로 악화.
효과크기가 있어도(레인지 0.49 / 15m -0.56) 손익은 다르다.
조건은 **24h 급등 하나만**.
"""
from __future__ import annotations

from pathlib import Path

from app.services.long_surge_gate import (
    MIN_CHG_24H,
    SETTING_KEY,
    check_long_surge,
    long_surge_gate_enabled,
)

BACKEND = Path(__file__).resolve().parents[2]
FUNNEL = BACKEND / "app" / "workers" / "auto_bb_breakdown_worker.py"
SVC = BACKEND / "app" / "services" / "long_surge_gate.py"


class _BC:
    def __init__(self, chg=None, boom=False, as_list=False, empty=False):
        self.chg, self.boom, self.as_list, self.empty = chg, boom, as_list, empty

    def get_24hr_ticker(self, symbol=None):
        if self.boom:
            raise RuntimeError("API")
        if self.empty:
            return [] if self.as_list else None
        t = {"symbol": symbol, "priceChangePercent": str(self.chg)}
        return [t] if self.as_list else t


def test_threshold_is_fifteen():
    """🚨 10%·20% 는 표본 절반 중 한쪽이 음수였다. 15% 만 양쪽 다 양수."""
    assert MIN_CHG_24H == 15.0


def test_long_blocked_below_threshold():
    """차단될 85건은 승률 8.2%, -803.25 였다."""
    ok, why, d = check_long_surge(_BC(chg=2.28), "X", "LONG")
    assert not ok
    assert d["chg_24h"] == 2.28 and "급등 중 아님" in why


def test_long_passes_when_surging():
    ok, why, d = check_long_surge(_BC(chg=21.46), "X", "LONG")
    assert ok and d["chg_24h"] == 21.46


def test_boundary_is_inclusive():
    assert check_long_surge(_BC(chg=15.0), "X", "LONG")[0] is True
    assert check_long_surge(_BC(chg=14.99), "X", "LONG")[0] is False


def test_short_is_not_affected():
    """🚨 이 게이트는 LONG 전용이다 — SHORT 은 급등 종목을 파는 게 본업이다."""
    ok, why, _d = check_long_surge(_BC(chg=-30.0), "X", "SHORT")
    assert ok and "대상 아님" in why


def test_accepts_list_or_dict_ticker():
    """get_24hr_ticker 는 symbol 유무에 따라 dict/list 를 준다."""
    assert check_long_surge(_BC(chg=20.0, as_list=True), "X", "LONG")[0] is True
    assert check_long_surge(_BC(chg=20.0), "X", "LONG")[0] is True


def test_fail_open_on_error_or_empty():
    """티커를 못 받았다고 매매를 멈추면 안 된다 (필터이지 안전장치가 아니다)."""
    for bc in (_BC(boom=True), _BC(empty=True), _BC(empty=True, as_list=True)):
        ok, why, _d = check_long_surge(bc, "X", "LONG")
        assert ok, why


def test_default_off():
    """LONG 진입을 1/6.5 로 줄이는 변화라 기본 OFF (헌법 161)."""
    class _Row:
        def __init__(self, v):
            self.value = v

    class _DB:
        def __init__(self, v=None):
            self._v = v

        def get(self, m, k):
            return _Row(self._v) if self._v is not None else None

    class _Boom:
        def get(self, m, k):
            raise RuntimeError("DB")

    assert SETTING_KEY == "long_surge_gate_enabled"
    assert long_surge_gate_enabled(_DB(None)) is False
    assert long_surge_gate_enabled(_DB("1")) is True
    assert long_surge_gate_enabled(_Boom()) is False


# ───────────────────────── 배선

def _code(p: Path) -> str:
    return "\n".join(
        ln for ln in p.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_wired_before_creation_and_only_for_long():
    code = _code(FUNNEL)
    assert "check_long_surge" in code
    assert code.index("check_long_surge") < code.index("svc.create_strategy_instance(")
    i = code.index("long_surge_gate_enabled")
    assert 'str(side).upper() == "LONG"' in code[i - 200: i + 200]


def test_no_extra_conditions_were_added():
    """🚨 레인지 위치·15m 조정을 더하면 -3.02 -> -12.85 로 나빠진다.

    조건은 24h 급등 하나만이어야 한다.

    ⚠️ 문서(docstring)에는 「왜 뺐는지」가 적혀 있으므로 **실행되는 코드**만 본다.
       처음에 문자열 검색으로 짰다가 설명 문구를 잡아 잘못 실패했다.
    """
    import ast
    tree = ast.parse(SVC.read_text(encoding="utf-8"))
    calls = {
        n.func.attr for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    # 캔들을 아예 안 받는다 = 지표·레인지 조건이 없다는 증거
    assert "get_klines" not in calls, "캔들을 받는다 = 조건이 더 붙었다"
    assert "get_24hr_ticker" in calls
    # 비교 연산은 임계 하나뿐이어야 한다
    cmps = [n for n in ast.walk(tree) if isinstance(n, ast.Compare)]
    thr = [n for n in cmps if any(
        isinstance(c, ast.Name) and c.id == "MIN_CHG_24H" for c in ast.walk(n))]
    assert len(thr) == 1, f"임계 비교가 {len(thr)}개 (1개여야 한다)"


def test_evidence_is_recorded():
    src = SVC.read_text(encoding="utf-8")
    for token in ("+80.07", "-803.25", "8.2%", "1/6.5"):
        assert token in src, f"근거 주석에 '{token}' 이 없다"
