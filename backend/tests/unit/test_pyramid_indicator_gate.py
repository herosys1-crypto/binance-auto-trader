"""💉 Fix 273 — 사장님 요청의 **빠진 절반**을 채운다.

## 사장님 원 요청 (2026-09-01)

  "익절구간에서 **계속 상승하는 차트와 보조지표**면 300usdt 씩 최대 2번 진입을 하고
   **tp1 단계 익절**을 할수 있게 요청했다고 기억하는데"

코드를 확인하니 두 곳이 어긋나 있었다:

  ① **보조지표 조건이 통째로 없었다.** 차트(가격)만 봤다 —
     peak 되돌림 <= 2.5% / 시작가 대비 지속 >= 0.5%.
     RSI·CCI·OBV 는 학습 기록에 **None 으로 저장만** 하고 판정에 안 썼다.
  ② **TP 진행이 추가할 때마다 리셋됐다** (`mode="reset"`).
     #1930 XPLUSDT 에서 max_profit_pct 가 4.04 -> None, 3.08 -> None 로 두 번 지워졌다.
     「tp1 단계 익절」 요청과 정반대다.

## 실측 (추가 시점 88건, 그 전략의 최종 손익으로 판정)

    조건 없음(현행)            88건 승률 20.5%  **-5,832.19**  건당  -66.27
    4H hist 상승중             54건      31.5%    +1,217.21        +22.54
    **4H AND 15m 둘 다 상승**   45건      33.3%  **+1,359.23**   **+30.21**  <- 채택
    4H hist 상승 **아님**       34건       2.9%    -7,049.40      -207.34   <- 손실원

    과적합 검사: 최근 절반 -871 -> +234 / 이전 절반 -4,961 -> +1,125 (양쪽 다 양수)

    방향별: SHORT -91.32 -> **+99.28** (승률 34.8% -> 66.7%)
           LONG  -38.84 ->  -30.23  (**여전히 적자** — 사장님께 보고함)

## 🚨 용도가 다르면 조건도 다르다

진입 게이트(Fix 270)는 `hist 상승 AND hist>0` 이 최고였는데(+5.56/건),
피라미딩에서 `hist>0` 을 더하면 +22.54 -> **+0.31** 로 무너진다.
같은 지표라도 **그 용도로 다시 재야 한다** (세 번째 사례).
"""
from __future__ import annotations

from pathlib import Path

from app.services.trend_4h_gate import PYRAMID_TFS, check_hist_rising, check_pyramid_trend

BACKEND = Path(__file__).resolve().parents[2]
PYR = BACKEND / "app" / "workers" / "success_pyramiding_worker.py"
SVC = BACKEND / "app" / "services" / "trend_4h_gate.py"


class _BC:
    """4h/15m 별로 다른 시세를 주는 스텁."""

    def __init__(self, per_tf=None, boom=False):
        self.per_tf = per_tf or {}
        self.boom = boom

    def get_klines(self, *, symbol=None, interval=None, limit=None, **kw):
        if self.boom:
            raise RuntimeError("API")
        c = self.per_tf.get(interval, [])
        return [[0, x, x, x, x, 0] for x in c]


def _series(direction: int, n: int = 60):
    out, v = [], 100.0
    for _ in range(n - 12):
        v *= 1.0 + direction * 0.0005
        out.append(v)
    for _ in range(12):
        v *= 1.0 + direction * 0.02
        out.append(v)
    return out


UP, DOWN = _series(+1), _series(-1)


def _code(p: Path) -> str:
    return "\n".join(
        ln for ln in p.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


# ───────────────────────── 판정

def test_both_timeframes_must_rise():
    """채택안 = 4H **AND** 15m 둘 다 상승."""
    assert PYRAMID_TFS == ("4h", "15m")
    ok, why, _d = check_pyramid_trend(_BC({"4h": UP, "15m": UP}), "X", "LONG")
    assert ok, why


def test_one_timeframe_failing_blocks():
    """🚨 테스트 stale fix (Fix 345, commit c7417a8, 2026-09-04):
    "15분이 기준이고 4시간을 참고" — 4H 는 더 이상 거부권이 아니다(veto 기본 OFF).
    15m 이 하락이면 그대로 차단하지만, 4H 만 하락이고 15m 이 상승이면 **참고만**
    하고 통과시킨다 (detail 에 4H 방향은 남긴다).
    """
    ok, why, _d = check_pyramid_trend(_BC({"4h": UP, "15m": DOWN}), "X", "LONG")
    assert not ok and "15m" in why, "15m 가 하락인데 통과했다"
    ok, why, _d = check_pyramid_trend(_BC({"4h": DOWN, "15m": UP}), "X", "SHORT")
    assert not ok and "15m" in why, "SHORT 15m 가 불리한데 통과했다"
    ok, why, d = check_pyramid_trend(_BC({"4h": DOWN, "15m": UP}), "X", "LONG")
    assert ok, why
    assert "참고" in why and d["4h_role"] == "reference"
    assert d["4h"]["delta"] < 0, "4H 하락이 detail 에 남아야 한다"


def test_short_is_mirrored():
    """🚨 SHORT 은 부호를 뒤집어야 한다 — 실측에서 SHORT 이 효과가 컸다(+99.28/건)."""
    ok, _why, _d = check_pyramid_trend(_BC({"4h": DOWN, "15m": DOWN}), "X", "SHORT")
    assert ok
    ok2, _w2, _d2 = check_pyramid_trend(_BC({"4h": UP, "15m": UP}), "X", "SHORT")
    assert not ok2


def test_no_hist_sign_condition():
    """🚨 진입 게이트와 다르다 — 여기서 `hist>0` 을 요구하면 +22.54 -> +0.31 로 무너진다.

    판정은 **방향(delta)** 만 본다.

    🚨 테스트 stale fix (Fix 348, commit 5265b22, 2026-09-05): `check_hist_rising`
    이 한 봉 미분(`delta > 0`)에서 연속 N봉 「가속」 판정(`all(x > 0 for x in deltas)`,
    기본 min_bars=3)으로 바뀌었다 — 2026-09-03 차트 학습에서 "이긴 건 「상승중」이
    아니라 「가속」" 이었기 때문. 함수 경계도 다음 상수 정의(`SETTING_PYRAMID_4H_VETO`)
    앞까지로 넓혀 잡는다 (구현이 함수 뒤 헬퍼로 옮겨졌다).
    """
    src = SVC.read_text(encoding="utf-8")
    i = src.index("def check_hist_rising")
    body = src[i: src.index("\nSETTING_PYRAMID_4H_VETO", i)]
    assert "return all(x > 0 for x in deltas), d" in body
    assert "hist_signed" in body, "기록은 남기되"
    assert "now_v <= 0" not in body, "부호 조건이 들어갔다"
    # 가속(3봉 연속 증가) 표본 — 초반 8봉 가속 후 6봉 감속(부호는 여전히 음수)
    c, s = [100.0] * 30, 0.0
    for _ in range(8):
        s += 0.002
        c.append(c[-1] * (1 - s))
    for _ in range(6):
        s *= 0.7
        c.append(c[-1] * (1 - s))
    c.append(c[-1])
    r, d = check_hist_rising(_BC({"15m": c}), "X", "LONG", "15m", use_completed=True, min_bars=3)
    assert d["hist_signed"] < 0 and r is True, d


def test_fail_open_on_api_error():
    """판정 하나가 피라미딩을 통째로 멈추면 안 된다 (Fix 252)."""
    ok, why, _d = check_pyramid_trend(_BC(boom=True), "X", "LONG")
    assert ok and "fail-open" in why


def test_short_data_is_fail_open():
    """🚨 테스트 stale fix (Fix 345): 15m 은 이제 **기준**이라 15m 판정 불가는
    fail-open 통과라도 사유가 "15m 판정 불가"로 바뀐다. 4H 판정 불가는
    참고 항목일 뿐이라 "4H 판정 불가"로 통과한다 (기존 두 케이스 모두
    통과지만 사유 문구가 4H/15m 역할 분리를 반영한다).
    """
    ok, why, _d = check_pyramid_trend(_BC({"4h": UP, "15m": [100.0] * 5}), "X", "LONG")
    assert ok and "15m" in why and "fail-open" in why
    ok, why, d = check_pyramid_trend(_BC({"4h": [100.0] * 5, "15m": UP}), "X", "LONG")
    assert ok and "4H 판정 불가" in why and d["4h"].get("reason")


def test_single_tf_helper_returns_none_when_unknown():
    r, d = check_hist_rising(_BC({"4h": []}), "X", "LONG", "4h")
    assert r is None and d.get("reason")


# ───────────────────────── 배선

def test_gate_is_wired_before_the_add():
    code = _code(PYR)
    assert "check_pyramid_trend" in code
    assert code.index("check_pyramid_trend") < code.index("_exec.add_position_now(")


def test_blocked_adds_are_counted_with_a_distinct_reason():
    """🚨 사유가 뭉뚱그려지면 「왜 안 되는지」를 알 수 없다 (헌법 93)."""
    assert '_bump("indicator_not_rising")' in _code(PYR)


def test_mode_is_preserve_not_reset():
    """🚨 사장님 요청 「tp1 단계 익절」 — reset 은 TP 진행을 매번 지운다.

    #1930 에서 max_profit_pct 가 4.04 -> None, 3.08 -> None 로 두 번 지워졌다.
    """
    code = _code(PYR)
    i = code.index("_exec.add_position_now(")
    body = code[i: i + 400]
    assert 'mode="preserve"' in body
    assert 'mode="reset"' not in body


def test_default_on_and_failsafe_on():
    """사장님이 원래 요청하신 조건이고 실측이 강하다 — 기본 ON, 실패해도 ON."""
    from app.workers.success_pyramiding_worker import (
        INDICATOR_GATE_KEY, _indicator_gate_enabled,
    )

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

    assert INDICATOR_GATE_KEY == "pyramid_indicator_gate_enabled"
    assert _indicator_gate_enabled(_DB(None)) is True
    assert _indicator_gate_enabled(_DB("0")) is False
    assert _indicator_gate_enabled(_Boom()) is True


def test_evidence_is_recorded():
    src = SVC.read_text(encoding="utf-8")
    for token in ("-5,832.19", "+30.21", "-207.34", "+0.31"):
        assert token in src, f"근거 주석에 '{token}' 이 없다"
