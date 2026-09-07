"""🛡️ Fix 253 — LONG 강제손절 5% (사장님 원 지시로 복귀).

## 경위

    Fix 49 (2026-08-24)  사장님 verbatim: "단계별 진입후 -5% 손실이면 청산하고 대기"
                         -> SHORT 는 지금도 5%
    Fix 87 (2026-08-25)  LONG 만 10% 로 상향.
                         근거: "원 -5% = leverage 2x + 15m 알트 노이즈 = 자연 노이즈 손절"

## 실측이 그 근거를 반증했다 (2026-09-01)

**① LONG 은 이틀 연속 승자 0명**

    08-31   AUTO_BB L  12건  승률 0.0%  -121.88
    09-01   AUTO_BB L  11건  승률 0.0%  -120.82

손절은 설정대로 정확히 작동한다(설정 대비 초과 중앙값 **0.2%p**).
즉 느슨한 손절이 승률을 올린 게 아니라 **잃는 크기만 2배로 키웠다**.

**② 「노이즈에 잘린다」도 사실이 아니었다**

현재 이익 중인 LONG 13건의 최저 ROI:

    SNXXUSDT -4.1 (현재 +38.89)   UNIUSDT -4.3    CLUSDT -2.3
    PENGUUSDT -1.4   SOLUSDT -0.9   HYPEUSDT -0.8   ...

**-5% 를 건드린 승자가 한 건도 없다.**
-5% 를 넘긴 유일한 건 SUPERUSDT(-6.5%)이고 그것도 지금 손실 중이다.

=> 5% 로 조여도 **승자를 자르지 않으면서** 패자 손실만 반감된다.

🚨 이 파일은 값이 **근거 없이 되돌아가는 것**을 막는다.
   바꾸려면 같은 측정을 다시 하고 「이익 중인 LONG 이 -5% 아래로 갔는가」를 확인할 것.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.workers.auto_long_at_bottom_worker import LONG_FORCE_SL_ROI

APP = Path(__file__).resolve().parents[2] / "app"
LONG_W = APP / "workers" / "auto_long_at_bottom_worker.py"
SHORT_W = APP / "workers" / "auto_short_at_top_worker.py"


def _code(p: Path) -> str:
    return chr(10).join(
        ln for ln in p.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_long_stop_default_is_fix362_25():
    """🎯 Fix 362 (2026-09-08 사장님): 새 전략 기본 -25%. LONG 폴백 상수는 그 값의 사본이어야 한다."""
    from app.core.risk_constants import FORCE_SL_ROI_NEW_DEFAULT
    assert LONG_FORCE_SL_ROI == FORCE_SL_ROI_NEW_DEFAULT == Decimal("25")


def test_long_and_short_now_match():
    """🚨 두 방향이 다른 손절선을 쓰면 성적 비교가 오염된다 — 둘 다 같은 설정 헬퍼를 런타임에 읽는다 (Fix 362)."""
    long_code = _code(LONG_W)
    short_code = _code(SHORT_W)
    assert "_nfs362(db)" in short_code and "_nfs362(db)" in long_code
    assert 'force_sl_roi_override = Decimal("5")' not in short_code
    assert "force_sl_roi_override = LONG_FORCE_SL_ROI" not in long_code


def test_no_magic_number_left_in_long_worker():
    """🚨 매직넘버 대입이 다시 생기면 한쪽만 바뀌어 조용히 갈라진다."""
    code = _code(LONG_W)
    assert 'force_sl_roi_override = Decimal("10")' not in code
    assert 'force_sl_roi_override = Decimal("5")' not in code
    assert code.count("force_sl_roi_override = _nfs362(db)") == 2, "두 진입 경로(스캔/알람)가 같은 헬퍼를 쓰지 않는다"


def test_evidence_is_recorded_next_to_the_value():
    """값만 바뀌고 근거가 사라지면 다음 사람이 또 뒤집는다 (Fix 87 이 그랬다)."""
    src = LONG_W.read_text(encoding="utf-8")
    for token in ("Fix 253", "승자 0명", "-5% 를 건드린 승자", "Fix 362"):
        assert token in src, f"근거 주석에 '{token}' 이 없다"


def test_stop_is_stricter_than_global_default():
    """전역은 80% 라 override 가 없으면 사실상 손절이 안 걸린다."""
    assert LONG_FORCE_SL_ROI < Decimal("80")
