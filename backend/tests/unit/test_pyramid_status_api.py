"""💉 Fix 271 — 수익구간 포지션 추가 모니터링 엔드포인트.

사장님: "수익구간에서 꼭 포지션 추가를 할수 있는 모니터링을 만들어줘.
        수익구간에 2번은 포지션 추가를 할수 있는걸로 되어있는데
        **이것이 잘되고 있는지도 분석**해서 만들어줘"

워커 로그로만 알 수 있던 것을 화면에서 볼 수 있게 한다:
  각 활성 포지션이 추가 자격에 얼마나 가까운지 / 몇 번 썼는지 / 못 하는 이유.

🚨 Fix 269 와 함께 봐야 한다 — 추가는 손실을 3~5배로 키우던 원인이었고
   (추가 없음 -13.28 / 1회 -42.92 / 2회 -64.27), 이제 손절 금액을 고정했다.
   `performance_7d` 가 그 효과를 확인하는 자리다.
"""
from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
API = BACKEND / "app" / "api" / "v1" / "admin" / "monitoring.py"


def _src() -> str:
    return API.read_text(encoding="utf-8")


def test_endpoint_exists():
    assert '@router.get("/pyramid-status")' in _src()


def test_uses_the_real_constant_names():
    """🚨 상수명을 틀리면 런타임에 ImportError 로 화면이 죽는다.

    실제 이름은 MIN_UNREALIZED_ROI_PCT 이다 (ROI_TRIGGER_PCT 가 아니다).
    """
    from app.workers.success_pyramiding_worker import (
        MAX_PYRAMID_COUNT, MIN_UNREALIZED_ROI_PCT, _cap_loss_enabled, _get_pyramid_count,
    )
    assert float(MIN_UNREALIZED_ROI_PCT) == 5.0
    assert MAX_PYRAMID_COUNT == 2
    assert callable(_get_pyramid_count) and callable(_cap_loss_enabled)
    assert "MIN_UNREALIZED_ROI_PCT as _TRIG" in _src()


def test_imports_sqlalchemy_locally():
    """🚨 이 파일은 sqlalchemy 를 모듈 상단에 import 하지 않는다 (함수 안 관행).

    처음에 상단에 있다고 가정했다가 NameError 가 날 뻔했다.
    """
    src = _src()
    i = src.index('@router.get("/pyramid-status")')
    body = src[i: i + 900]
    assert "from sqlalchemy import select, text" in body


def test_reports_reason_for_every_position():
    """차단 사유가 없으면 화면이 「왜 안 되는지」를 못 알려준다 (헌법 93)."""
    src = _src()
    i = src.index('@router.get("/pyramid-status")')
    body = src[i:]
    for token in ('"reason"', '"state"', '"gap_pct"', '"pyramid_used"'):
        assert token in body, f"{token} 이 없다"


def test_exposes_cap_loss_state():
    """Fix 269 스위치가 켜져 있는지 화면에서 보여야 한다."""
    assert '"cap_loss_enabled": _cap_loss_enabled(db)' in _src()


def test_includes_performance_breakdown():
    """「잘되고 있는지 분석」 = 추가 횟수별 성적을 같이 준다."""
    src = _src()
    assert "performance_7d" in src
    assert "stage_no IS NULL" in src, "추가 주문 식별 조건이 없다"


def test_one_bad_row_does_not_kill_the_screen():
    src = _src()
    i = src.index('@router.get("/pyramid-status")')
    body = src[i:]
    assert "화면 전체를 죽이지 않게" in body or '"error": str(e)' in body
