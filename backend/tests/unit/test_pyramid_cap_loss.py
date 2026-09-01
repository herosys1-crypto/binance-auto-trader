"""🚨 Fix 269 — 포지션 추가가 손실을 3~5배로 키우고 있었다.

## 실측 (2026-09-01, 최근 3일 종료 전략 151건)

    구분          건수   승      합계        건당
    추가 없음      97   10   -1,288.42   **-13.28**
    추가 1회       34    5   -1,459.43   **-42.92**   (3.2배)
    추가 2회       15    3     -964.05   **-64.27**   (4.8배)
    추가 7회        1    0     -724.80    -724.80     (#1873, 자본 6,800)

## 원인은 산수다

손절은 **ROI(%) 기준**인데, 추가로 **자본이 커지면** 같은 ROI 라도 손실 **금액**이
그만큼 커진다.

    #1890 SNXXUSDT: 1단계 자본 10 (명목 20)
      8018 ENTRY  1.58 @ 12.67  stage=1
      8074 ENTRY 46.08 @ 13.03  stage=None   <- 이익 구간에서 300 추가
      8106 ENTRY 44.91 @ 13.29  stage=None   <- 또 300 추가
      8147 EXIT  92.57 @ 12.45
      평단 12.67 -> **13.15** 로 밀린 뒤 청산 = **-65.75**
      추가가 없었다면 -0.5 였다. **131배.**

Fix 213 이 볼밴 분할에서 같은 사고를 잡았지만(피라미딩 대상에서 제외), 나머지 경로는
그대로였다. 이번엔 `add_position_now` **한 곳**에서 막는다 (헌법 6).

## 규칙

    cap_loss=True 면 추가 직후 force_sl_roi_override 를 낮춘다.
        이전 손실 = prev_capital x prev_roi / 100
        새 ROI   = 이전 손실 / new_capital x 100
    => 손절 시 잃는 USDT 가 추가 전과 **같다**.

⚠️ override 가 없으면 무엇을 고정할지 기준이 없으므로 건드리지 않고 **경고**한다.
⚠️ 사장님 수동 「💉 포지션 추가」는 cap_loss=False (의도적 증액이므로).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
EXEC = BACKEND / "app" / "services" / "execution_service.py"
PYR = BACKEND / "app" / "workers" / "success_pyramiding_worker.py"


def _code(p: Path) -> str:
    return "\n".join(
        ln for ln in p.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


# ───────────────────────── 산수 (규칙 자체)

def _new_roi(old_cap: float, add: float, old_roi: float) -> float:
    base_loss = old_cap * old_roi / 100
    return base_loss / (old_cap + add) * 100


def test_loss_amount_is_unchanged_after_add():
    """🚨 이게 규칙의 전부 — 추가해도 손절 시 잃는 USDT 가 같아야 한다."""
    old_cap, add, old_roi = 10.0, 300.0, 10.0
    loss_before = old_cap * old_roi / 100
    r = _new_roi(old_cap, add, old_roi)
    loss_after = (old_cap + add) * r / 100
    assert abs(loss_before - loss_after) < 1e-9


def test_real_case_1890_would_have_been_capped():
    """#1890 SNXXUSDT 재현 — 10 에 300 을 두 번 얹었다."""
    cap, roi = 10.0, 10.0                    # 손절 시 -1.0 USDT
    for add in (300.0, 300.0):
        roi = _new_roi(cap, add, roi)
        cap += add
    assert abs(cap - 610.0) < 1e-9
    assert abs(cap * roi / 100 - 1.0) < 1e-6, "손절 금액이 커졌다"
    # 고정을 안 했다면 610 x 10% = 61 USDT 를 잃었을 것이다
    assert abs(610.0 * 10.0 / 100 - 61.0) < 1e-9


def test_roi_shrinks_as_capital_grows():
    assert _new_roi(100, 100, 10.0) == 5.0
    assert _new_roi(100, 300, 10.0) == 2.5


# ───────────────────────── 배선

def test_add_position_now_has_cap_loss_param():
    code = _code(EXEC)
    assert "cap_loss: bool = False" in code, "파라미터가 없다"
    assert "if cap_loss:" in code


def test_cap_loss_updates_the_override():
    code = _code(EXEC)
    i = code.index("if cap_loss:")
    body = code[i: i + 1400]
    assert "force_sl_roi_override" in body
    assert "total_capital" in body


def test_missing_override_is_warned_not_silently_skipped():
    """🚨 override 가 없으면 고정할 수 없다 — 조용히 넘어가면 안 된다."""
    src = EXEC.read_text(encoding="utf-8")
    i = src.index("if cap_loss:")
    body = src[i: i + 1400]
    assert "_prev_roi is None" in body
    assert "logger.warning" in body


def test_failure_is_logged_as_error():
    """실패하면 손실 상한이 깨진 상태다 — warning 이 아니라 error."""
    src = EXEC.read_text(encoding="utf-8")
    i = src.index("if cap_loss:")
    body = src[i: i + 2000]
    assert "logger.error" in body


def test_pyramiding_worker_passes_cap_loss():
    code = _code(PYR)
    assert "cap_loss=_cap_loss" in code
    assert "_cap_loss_enabled(db)" in code


def test_default_is_on_and_failsafe_is_on():
    """손실을 **줄이는** 방향이므로 기본 ON, 조회 실패도 ON 이어야 한다."""
    from app.workers.success_pyramiding_worker import CAP_LOSS_KEY, _cap_loss_enabled

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
            raise RuntimeError("DB 끊김")

    assert CAP_LOSS_KEY == "pyramid_cap_loss_enabled"
    assert _cap_loss_enabled(_DB(None)) is True          # 설정 없음 = ON
    assert _cap_loss_enabled(_DB("1")) is True
    assert _cap_loss_enabled(_DB("0")) is False          # 명시 OFF 존중
    assert _cap_loss_enabled(_Boom()) is True            # 실패해도 묶는 쪽


def test_evidence_is_recorded():
    src = EXEC.read_text(encoding="utf-8")
    for token in ("Fix 269", "-42.92", "-64.27", "131배"):
        assert token in src, f"근거 주석에 '{token}' 이 없다"
