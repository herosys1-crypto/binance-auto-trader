"""Fix 488 — 방향 엔진 판정 불변식 (Hypothesis).

I1 미래 참조 없음: closed_at ≥ day_start 인 행을 아무리 바꿔도 판정 불변.
I2 대칭: LONG↔SHORT 이름을 바꾸면 판정도 반대(None 은 None).
I3 표본: 어느 방향이든 창 안 건수 < min_n 이면 None.
I4 역방향: 판정이 있으면 그 방향의 창 안 평균이 다른 방향보다 낮다.
"""
from datetime import datetime, timedelta, timezone

import pytest

hyp = pytest.importorskip("hypothesis")
from hypothesis import given  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from app.services import direction_engine as DE  # noqa: E402

D = datetime(2026, 11, 13, tzinfo=timezone.utc)
SIDE = st.sampled_from(["LONG", "SHORT"])
ROI = st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False)
PAST = st.floats(min_value=0.01, max_value=23.99)
ROW_PAST = st.tuples(SIDE, PAST, ROI).map(lambda t: (t[0], D - timedelta(hours=t[1]), t[2]))
ROW_FUT = st.tuples(SIDE, st.floats(min_value=0, max_value=72), ROI).map(lambda t: (t[0], D + timedelta(hours=t[1]), t[2]))
MIN_N = st.integers(min_value=1, max_value=5)


@given(st.lists(ROW_PAST, max_size=40), st.lists(ROW_FUT, max_size=40), st.lists(ROW_FUT, max_size=40), MIN_N)
def test_i1_no_lookahead(past, fut_a, fut_b, min_n):
    assert DE.decide(past + fut_a, D, min_n=min_n)["side"] == DE.decide(past + fut_b, D, min_n=min_n)["side"]


@given(st.lists(ROW_PAST, max_size=40), MIN_N)
def test_i2_symmetry(rows, min_n):
    flip = {"LONG": "SHORT", "SHORT": "LONG"}
    a = DE.decide(rows, D, min_n=min_n)["side"]
    b = DE.decide([(flip[s], t, r) for s, t, r in rows], D, min_n=min_n)["side"]
    assert (a is None and b is None) or (a is not None and b == flip[a])


@given(st.lists(ROW_PAST, max_size=40), MIN_N)
def test_i3_min_n(rows, min_n):
    nl = sum(1 for s, _, _ in rows if s == "LONG")
    ns = len(rows) - nl
    if nl < min_n or ns < min_n:
        assert DE.decide(rows, D, min_n=min_n)["side"] is None


@given(st.lists(ROW_PAST, min_size=2, max_size=40), MIN_N)
def test_i4_contrarian(rows, min_n):
    r = DE.decide(rows, D, min_n=min_n)
    if r["side"] is not None:
        m = {s: [x for side, _, x in rows if side == s] for s in ("LONG", "SHORT")}
        mean = {s: sum(v) / len(v) for s, v in m.items()}          # 반올림 전 평균으로 검증
        other = "SHORT" if r["side"] == "LONG" else "LONG"
        assert mean[r["side"]] < mean[other]
