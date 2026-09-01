"""📐 Fix 270 — 4H 추세 게이트 (사상 ⑥ 「4시간봉 = 확정된 흐름」).

## 실측 (진입 시점 4H 복원, 최근 10일 158건 — 「통과한 것만 진입했다면」)

    게이트                        건수   승률       합계        건당
    게이트 없음 (현행)             158  21.5%  **-3,599.87**  -22.78
    hist 상승중                    53  39.6%       +35.69     +0.67
    CCI 부호 내 편                 87  32.2%      -399.17     -4.59
    hist 상승중 AND CCI 부호        26  65.4%      +132.47     +5.09
    **hist 상승중 AND hist > 0**    33  57.6%     **+183.32**  **+5.56**  <- 채택

    방향별: LONG -13.51 -> -0.51 / SHORT **-30.16 -> +12.74**
    과적합 검사: 최근 절반 +181.62(22건) / 이전 절반 +1.70(11건) = 양쪽 다 양수

CCI 를 더해도 결과가 **완전히 같았다** — 이 표본에서 `hist > 0` 이 CCI 부호를 포함한다.
조건은 적을수록 좋으므로 뺐다.

## 이 파일이 지키는 것

  ① **원시값이 아니라 방향**으로 쓴다 (원시 효과크기 0.01 / 「상승 중」 2.08).
  ② **fail-open** — 필터이지 안전장치가 아니다. 데이터를 못 받았다고 매매를 멈추면 안 된다.
  ③ **방향 보정** — SHORT 은 부호를 뒤집어야 한다.
  ④ 기본 **OFF** — 진입을 1/5 로 줄이는 큰 변화라 명시적으로 켠다.
"""
from __future__ import annotations

from pathlib import Path

from app.services.trend_4h_gate import (
    SETTING_KEY,
    check_trend_4h,
    trend_4h_gate_enabled,
)

BACKEND = Path(__file__).resolve().parents[2]
FUNNEL = BACKEND / "app" / "workers" / "auto_bb_breakdown_worker.py"
SVC = BACKEND / "app" / "services" / "trend_4h_gate.py"


class _BC:
    """지정한 종가 시퀀스를 돌려주는 최소 스텁."""

    def __init__(self, closes=None, boom=False):
        self._c = closes or []
        self.boom = boom

    def get_klines(self, **kw):
        if self.boom:
            raise RuntimeError("API 끊김")
        # kline = [openTime, o, h, l, c, ...]
        return [[0, c, c, c, c, 0] for c in self._c]


def _series(direction: int, n: int = 60):
    """MACD hist 가 direction 쪽으로 **부호도 맞고 확대되는** 시퀀스.

    ⚠️ 처음엔 「매 봉 조금씩 가속」으로 만들었는데 EMA 가 따라잡아 끝에서
       hist 가 평평해졌다(rising=False). 합성 데이터는 **마지막 구간에서
       명확히 확대**되도록 만들어야 판정을 제대로 검사한다.
    """
    out, v = [], 100.0
    for _ in range(n - 12):                    # 앞부분은 완만
        v *= 1.0 + direction * 0.0005
        out.append(v)
    for _ in range(12):                        # 끝 12봉에서 확실히 확대
        v *= 1.0 + direction * 0.02
        out.append(v)
    return out


def _rising_series(n=60):
    return _series(+1, n)


def _falling_series(n=60):
    return _series(-1, n)


# ───────────────────────── ③ 방향 보정

def test_long_passes_on_accelerating_uptrend():
    ok, why, d = check_trend_4h(_BC(_rising_series()), "X", "LONG")
    assert ok, (why, d)
    assert d["rising"] is True and d["hist_signed"] > 0


def test_short_passes_on_accelerating_downtrend():
    """🚨 SHORT 은 부호를 뒤집어야 한다 — 안 하면 정반대로 판정한다."""
    ok, why, d = check_trend_4h(_BC(_falling_series()), "X", "SHORT")
    assert ok, (why, d)
    assert d["hist_signed"] > 0


def test_long_blocked_on_downtrend():
    ok, why, _d = check_trend_4h(_BC(_falling_series()), "X", "LONG")
    assert not ok


def test_short_blocked_on_uptrend():
    ok, why, _d = check_trend_4h(_BC(_rising_series()), "X", "SHORT")
    assert not ok


def test_mirror_images():
    """같은 시세에 대해 LONG/SHORT 판정이 정확히 반대여야 한다."""
    up = _rising_series()
    a = check_trend_4h(_BC(up), "X", "LONG")[0]
    b = check_trend_4h(_BC(up), "X", "SHORT")[0]
    assert a != b


# ───────────────────────── ② fail-open

def test_api_failure_does_not_block():
    """🚨 이건 좋은 자리를 고르는 필터다 — 데이터가 없다고 매매를 멈추면 안 된다."""
    ok, why, _d = check_trend_4h(_BC(boom=True), "X", "LONG")
    assert ok and "fail-open" in why


def test_short_data_does_not_block():
    ok, why, _d = check_trend_4h(_BC([100.0] * 10), "X", "LONG")
    assert ok and "fail-open" in why


def test_flat_price_does_not_crash():
    ok, _why, _d = check_trend_4h(_BC([100.0] * 60), "X", "LONG")
    assert isinstance(ok, bool)


# ───────────────────────── ④ 스위치

def test_default_is_off():
    """진입을 1/5 로 줄이는 변화라 기본 OFF (헌법 161)."""
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

    assert SETTING_KEY == "trend_4h_gate_enabled"
    assert trend_4h_gate_enabled(_DB(None)) is False
    assert trend_4h_gate_enabled(_DB("1")) is True
    assert trend_4h_gate_enabled(_DB("0")) is False
    assert trend_4h_gate_enabled(_Boom()) is False     # 조회 실패 = OFF (변화 없음)


# ───────────────────────── 배선

def _code(p: Path) -> str:
    return "\n".join(
        ln for ln in p.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_wired_into_the_shared_funnel_before_creation():
    """공용 관문에서 **생성 직전**에 걸려야 모든 진입 워커가 함께 보호된다."""
    code = _code(FUNNEL)
    assert "check_trend_4h" in code
    i_gate = code.index("check_trend_4h")
    i_create = code.index("svc.create_strategy_instance(")
    assert i_gate < i_create, "전략 생성 뒤에 있다 = 무의미"


def test_gate_short_circuits_when_disabled():
    """OFF 면 캔들 API 를 아예 부르지 않아야 한다 (IP ban 위험)."""
    code = _code(FUNNEL)
    i = code.index("trend_4h_gate_enabled")
    body = code[i: i + 500]
    assert "if _t4_on(db):" in body


def test_gate_failure_is_fail_open():
    src = FUNNEL.read_text(encoding="utf-8")
    i = src.index("Fix270] 4H 게이트 오류")
    assert "fail-open" in src[i: i + 200]


def test_evidence_is_recorded():
    src = SVC.read_text(encoding="utf-8")
    for token in ("-3,599.87", "+5.56", "2.08", "0.01", "1/5"):
        assert token in src, f"근거 주석에 '{token}' 이 없다"
