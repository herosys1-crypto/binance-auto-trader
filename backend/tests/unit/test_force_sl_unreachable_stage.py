"""🛡️ Fix 235 — v130 게이트의 **교착 안전판**.

## 실측 사고 (#1873 SKRUSDT SHORT, 2026-08-31)

    force_sl_roi_override   5.00%      <- 여기서 잘렸어야 했다
    미실현                  -746.10
    current_stage           1 / 총 2단계
    평단                    0.01981778
    2단계 트리거            0.25247200  = 평단의 12.7배

v130 게이트는 「다음 단계가 남아 있으면 강제 손절을 보류한다」이다.
그런데 숏은 **가격이 올라가야** 다음 단계가 열린다. 평단의 12.7배까지
올라갈 일은 없으므로 그 단계는 영원히 안 열리고, 손절도 영원히 안 걸린다.

    손절  ->  단계가 남아서 잠김
    단계  ->  도달 불가로 영원히 안 열림
         =>  청산될 때까지 보유    (#1488 이 -6,981 까지 간 구조)

## 판정 기준 = 임의 상수가 아니라 산술

그 단계에 **도달했을 때의 ROI** 가 -100% 를 넘으면 증거금이 이미 전부
사라진 뒤라 **거래소 청산이 먼저 온다** = 증명 가능한 도달 불가.
정상적인 물타기 단계(ROI -20%, -50%)는 그대로 게이트가 지킨다
=> 살아 있는 다른 전략의 손절 동작을 바꾸지 않는다 (대량 청산 위험 없음).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.risk_service import RiskService

APP = Path(__file__).resolve().parents[2] / "app"


def _svc_with_plan(trigger_price):
    """다음 미발동 단계 하나를 돌려주는 RiskService."""
    db = MagicMock()
    plan = SimpleNamespace(stage_no=2, trigger_price=trigger_price, is_triggered=False)
    q = db.query.return_value.filter.return_value.order_by.return_value
    q.first.return_value = plan
    return RiskService(db)


def _svc_without_plan():
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    return RiskService(db)


_S = SimpleNamespace(id=1873)


# ------------------------------------------------------- 핵심 계약

def test_1873_next_stage_is_provably_unreachable():
    """🚨 실측 재현 — 평단 0.0198 / 2단계 0.2525 = ROI 가 -100% 를 한참 넘는다."""
    svc = _svc_with_plan(Decimal("0.25247200"))
    roi = svc._roi_if_next_stage_reached(
        _S, "SHORT", Decimal("0.01981778"), Decimal("2")
    )
    assert roi is not None
    assert roi <= Decimal("-100"), f"도달 불가로 판정되지 않는다: {roi}"
    assert roi < Decimal("-2000"), f"실측값과 자릿수가 다르다: {roi}"


def test_normal_martingale_stage_still_locks_the_stop():
    """🛡 회귀 방지 — 정상 물타기(다음 단계 +10%)는 게이트가 그대로 지킨다.

    이게 깨지면 살아 있는 전략들이 한꺼번에 손절된다 (Fix 198 의 교훈).
    """
    svc = _svc_with_plan(Decimal("110"))
    roi = svc._roi_if_next_stage_reached(_S, "SHORT", Decimal("100"), Decimal("2"))
    assert roi == Decimal("-20"), roi
    assert roi > Decimal("-100"), "정상 단계가 도달 불가로 오판된다"


def test_deep_but_reachable_stage_still_locks():
    """ROI -80% 는 아직 증거금이 남아 있다 = 게이트 유지."""
    svc = _svc_with_plan(Decimal("140"))
    roi = svc._roi_if_next_stage_reached(_S, "SHORT", Decimal("100"), Decimal("2"))
    assert roi == Decimal("-80") and roi > Decimal("-100")


def test_long_direction():
    """LONG 은 아래로 떨어져야 다음 단계가 열린다."""
    svc = _svc_with_plan(Decimal("10"))
    roi = svc._roi_if_next_stage_reached(_S, "LONG", Decimal("100"), Decimal("2"))
    assert roi == Decimal("-180"), roi
    assert roi <= Decimal("-100")


def test_no_plan_falls_back_to_old_behaviour():
    """계획이 없으면 None = 옛 동작(보류) 유지. 판정 못 하면 손대지 않는다."""
    assert _svc_without_plan()._roi_if_next_stage_reached(
        _S, "SHORT", Decimal("100"), Decimal("2")
    ) is None


def test_missing_avg_entry_is_safe():
    svc = _svc_with_plan(Decimal("110"))
    assert svc._roi_if_next_stage_reached(_S, "SHORT", None, Decimal("2")) is None
    assert svc._roi_if_next_stage_reached(_S, "SHORT", Decimal("0"), Decimal("2")) is None


def test_leverage_scales_the_roi():
    """레버리지가 ROI 를 키운다 — 같은 가격이라도 배율에 따라 도달 가능성이 갈린다."""
    svc = _svc_with_plan(Decimal("140"))
    r1 = svc._roi_if_next_stage_reached(_S, "SHORT", Decimal("100"), Decimal("1"))
    r2 = svc._roi_if_next_stage_reached(_S, "SHORT", Decimal("100"), Decimal("3"))
    assert r1 == Decimal("-40") and r2 == Decimal("-120")
    assert r1 > Decimal("-100") >= r2, "배율이 판정을 갈라야 한다"


# ------------------------------------------------------- 소스 가드

def test_gate_actually_calls_the_safety_valve():
    """게이트가 안전판을 안 부르면 #1873 교착이 그대로 재발한다 (헌법 169)."""
    code = (APP / "services" / "risk_service.py").read_text(encoding="utf-8")
    code = chr(10).join(
        ln for ln in code.splitlines() if not ln.lstrip().startswith("#")
    )
    assert "_roi_if_next_stage_reached(" in code
    assert '_roi_at_next <= Decimal("-100")' in code, (
        "force_sl 게이트가 도달 불가 판정을 쓰지 않는다"
    )


def test_unlock_defaults_to_off():
    """🛡 기본값은 반드시 OFF (Fix 198 의 교훈).

    이 게이트를 푸는 순간 해당 전략은 다음 사이클에 **즉시 손절**된다.
    #1873 은 미실현 -746 이므로 켜는 순간 그 손실이 확정된다.
    기본값이 True 로 바뀌면 배포만으로 여러 전략이 한꺼번에 청산될 수 있다.
    """
    code = (APP / "services" / "risk_service.py").read_text(encoding="utf-8")
    assert 'get_bool(' in code and '"force_sl_unlock_unreachable_stage", False' in code, (
        "Fix235 해제 스위치가 없거나 기본값이 False 가 아니다"
    )
    assert '"force_sl_unlock_unreachable_stage", True' not in code


def test_warning_is_emitted_even_while_off():
    """OFF 여도 **예고 로그**는 남아야 한다 — 대상 목록을 눈으로 보고 결정한다."""
    code = (APP / "services" / "risk_service.py").read_text(encoding="utf-8")
    assert "logger.warning" in code and "Fix235" in code, (
        "도달 불가 전략을 발견해도 조용하면 사장님이 알 방법이 없다"
    )
