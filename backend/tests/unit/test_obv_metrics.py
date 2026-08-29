"""🚨 Fix 228 — OBV 방향 지표의 **단일 출처**.

## 왜 만들었나

`obv_slope_pct` 라는 한 컬럼에 **최소 3가지 단위**가 섞여 들어가고 있었다.
세 산식을 실제로 실행해 같은 자릿수가 나오는 것을 확인했다:

    realtime_reentry:299        obv[-1]-obv[-4]           →  2,249,160     (원 계약수량)
    bb_middle_scan:96           분모 0 이면 1.0 로 대체     →  2,249,159.9  (무계)
    strategy_suggestion:239     분모가 10봉 전 누적 레벨   →  3,600,000    (무계)

진입 스냅샷 실측 최대값 **2,249,160** 과 자릿수가 같다.
그래서 학습 표본에서 OBV 가 변별력을 잃었다.

## 새 산식

    (OBV[-1] - OBV[-1-lookback]) / (창 안 |거래량| 합)

분모가 0 이 될 수 없고, **-1~+1 로 묶이며**, 심볼 스케일에 무관하다.
사장님 원칙 "obv가 하락하지 않으면 결국은 obv 방향으로 간다" 가
`>= 0` 한 줄로 표현된다.
"""
from __future__ import annotations

from app.services.obv_metrics import DEFAULT_LOOKBACK, obv_direction_ratio


def _obv_from(deltas):
    """부호 있는 거래량 델타 목록 → 누적 OBV (compute_obv 와 같은 모양, 첫 봉 0)."""
    out = [0.0]
    for d in deltas:
        out.append(out[-1] + d)
    return out


def test_all_buying_is_plus_one():
    """창 안 거래가 전부 매수 쪽이면 +1."""
    obv = _obv_from([1000.0] * 20)
    vols = [1000.0] * 20
    assert abs(obv_direction_ratio(obv, vols) - 1.0) < 1e-9


def test_all_selling_is_minus_one():
    obv = _obv_from([-1000.0] * 20)
    vols = [1000.0] * 20
    assert abs(obv_direction_ratio(obv, vols) + 1.0) < 1e-9


def test_balanced_is_zero():
    """매수·매도가 상쇄되면 0 = 방향 없음."""
    obv = _obv_from([1000.0, -1000.0] * 10)
    vols = [1000.0] * 20
    assert abs(obv_direction_ratio(obv, vols)) < 1e-9


def test_always_bounded_even_on_extreme_input():
    """🚨 핵심 계약 — 어떤 입력에도 -1~+1 을 벗어나면 안 된다.

    옛 산식이 2,249,160 을 냈던 것이 이 프로젝트의 학습 데이터를 망쳤다.
    """
    cases = [
        ([0.0001] + [7.5e5] * 20, [7.5e5] * 20),      # 시작값이 0 근처
        (_obv_from([1e9] * 20), [1.0] * 20),           # 거래량이 비정상적으로 작음
        (_obv_from([-1e9] * 20), [1.0] * 20),
    ]
    for obv, vols in cases:
        v = obv_direction_ratio(obv, vols)
        assert v is None or -1.0 <= v <= 1.0, f"범위 이탈: {v}"


def test_old_formula_really_explodes():
    """음성 대조군 (헌법 170) — 옛 산식이 실제로 백만 단위를 내는가.

    이게 성립하지 않으면 Fix 228 은 고칠 게 없었다는 뜻이다.
    """
    obv = [0.0001] + [i * 7.5e5 for i in range(1, 21)]
    old_a = obv[-1] - obv[-4]                       # realtime_reentry 방식
    old_c = (obv[-1] - obv[0]) / abs(obv[0]) * 100  # generator 방식
    assert old_a > 1_000_000, old_a
    assert old_c > 1_000_000, old_c
    # 같은 데이터로 새 산식은 반드시 묶인다
    new = obv_direction_ratio(obv, [7.5e5] * 20)
    assert new is None or -1.0 <= new <= 1.0


def test_insufficient_data_returns_none():
    """봉 부족·거래량 0 은 None — 0 으로 위장하면 「방향 없음」과 구별이 안 된다."""
    assert obv_direction_ratio([1.0, 2.0], [1.0, 2.0]) is None
    assert obv_direction_ratio(_obv_from([1.0] * 20), [0.0] * 20) is None
    assert obv_direction_ratio(None, None) is None
    assert obv_direction_ratio([], []) is None


def test_broken_values_do_not_raise():
    """문자열·None 이 섞여도 죽지 않는다 (워커가 여기서 멈추면 안 된다)."""
    obv = _obv_from([1000.0] * 20)
    vols = [1000.0] * 18 + ["없음", None]
    v = obv_direction_ratio(obv, vols)
    assert v is None or -1.0 <= v <= 1.0


def test_default_lookback_is_20():
    assert DEFAULT_LOOKBACK == 20


def test_direction_sign_matches_price_flow():
    """부호가 뒤집히면 사장님 원칙이 정반대로 적용된다 — 방향을 고정한다."""
    up = obv_direction_ratio(_obv_from([500.0] * 20), [1000.0] * 20)
    down = obv_direction_ratio(_obv_from([-500.0] * 20), [1000.0] * 20)
    assert up > 0 and down < 0
    assert abs(up + down) < 1e-9, "대칭이어야 한다"
