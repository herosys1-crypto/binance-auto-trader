"""🪢 Fix 489 불변식 — `rule_families.single_trailing_pct` (실매매 청산 폭을 정하는 값).

T1 어떤 설정 문자열이 와도 예외 없이 None 또는 0.5~20 의 유한한 float
T2 None 은 설정값이 수치상 0 일 때만 (끄기는 명시적으로만 — 오타·언더플로로 옛 동작이 되지 않는다)
T3 범위 안의 유한한 값은 그대로 (변형 없음)
T4 설정이 없으면 3.0 (실제 `setting()` 의 「행 없음 = 기본값」 경로로)

오라클은 구현(Decimal 파싱)과 다른 방법을 쓴다: 0 여부 = 가수부 숫자가 전부 '0' 인가(문자열), 크기 = 분수(Fraction).
"""
import math
import re
from fractions import Fraction

import pytest

hypothesis = pytest.importorskip("hypothesis")

from hypothesis import example, given, strategies as st

from app.services import rule_families as RF

_SHAPE = re.compile(r"([+-]?)([0-9]*)(?:\.([0-9]*))?(?:[eE]([+-]?[0-9]+))?")


class _DB:
    def __init__(self, value):
        self.value = value

    def get(self, _m, key):
        return None if self.value is None else type("R", (), {"value": self.value})()


def _oracle(raw: str):
    """("bad"|"zero"|"num", 값) — 문자열 모양으로만 판단한다 (Decimal·float 을 쓰지 않는다)."""
    t = raw.strip()
    m = _SHAPE.fullmatch(t)
    if not t or not m or not t.isascii():
        return "bad", None
    _sign, ip, fp, ex = m.groups()
    ip, fp = ip or "", fp or ""
    if not (ip or fp):
        return "bad", None
    if set(ip + fp) <= {"0"}:
        return "zero", None
    e = int(ex or 0)
    if abs(e) > 60:                                # 범위(0.5~20)와 한참 멀다 — 분수로 만들지 않는다
        return "num", None
    v = Fraction(int((ip + fp) or "0"), 10 ** len(fp)) * (Fraction(10) ** e)
    return "num", (-v if _sign == "-" else v)


NUMBERISH = st.one_of(
    st.text(max_size=12),
    st.text(alphabet="0123456789+-.eE_ ０", max_size=14),
    st.floats(allow_nan=True, allow_infinity=True).map(repr),
    st.integers(-10**6, 10**6).map(str),
    st.decimals(allow_nan=True, allow_infinity=True).map(str),
    st.tuples(st.sampled_from(["", "+", "-"]), st.integers(0, 999), st.integers(-12000, 12000)).map(lambda t: f"{t[0]}{t[1]}e{t[2]}"),
)


@given(NUMBERISH)
@example("1e-10000")
@example("0e99999")
@example("-0.0")
@example("0.5")
@example("20")
@example("20.0000000000000000001")
@example("0.4999999999999999999999")
def test_t1_t2_total_bounded_and_off_only_on_zero(raw):
    out = RF.single_trailing_pct(_DB(raw))
    kind, v = _oracle(raw)
    if out is None:
        assert kind == "zero"                                           # T2
        return
    assert isinstance(out, float) and math.isfinite(out) and 0.5 <= out <= 20   # T1
    assert kind != "zero"                                               # 0 인데 값이 나오면 안 된다
    if kind == "num" and v is not None and Fraction(1, 2) <= v <= 20:
        assert out == float(v)                                          # 범위 안 = 그 값
    else:
        assert out == 3.0                                               # 그 밖 = 기본값


@given(st.floats(min_value=0.5, max_value=20, allow_nan=False, allow_infinity=False))
def test_t3_in_range_passthrough(v):
    assert RF.single_trailing_pct(_DB(repr(v))) == v


@given(st.floats(allow_nan=False, allow_infinity=False).filter(lambda v: v != 0 and not 0.5 <= v <= 20))
def test_out_of_range_is_default_not_off(v):
    assert RF.single_trailing_pct(_DB(repr(v))) == 3.0


def test_t4_missing_is_default():
    assert RF.single_trailing_pct(_DB(None)) == 3.0
