"""🩹 Fix 389 — 「포지션 추가」 모달이 수량 0 이 되는 입력을 보내지 못하게 한다 (2026-09-21).

사장님 사례 (2026-09-20, FFUSDT S4 #4546 행):
    추가 금액 0.01 USDT · 지정가 1200 (현재가 0.16454) → 서버 400
    "계산된 수량이 0 — amount=0.01 USDT, price=1200, leverage=2x. 더 큰 자본 입력 필요."

화면은 예상 수량 0.0000 을 이미 보여주고 있었는데도 「진입」을 보낼 수 있었다.
이 파일은 그 세 가지 방어가 화면 코드에 남아 있는지만 고정한다 (매매 판정 아님 = UI 층).

정답 숫자: 바이낸스 USDT-M 최소 주문 명목 5 USDT → 필요한 최소 증거금 = 5 / 레버리지
(레버리지 2배면 2.5 USDT). 「Claude가 정함」 — 심볼별 minNotional 조회 대신 5 를 상수로 둔다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "add-position-modal.js"


@pytest.fixture(scope="module")
def src() -> str:
    return JS.read_text(encoding="utf-8")


def test_min_notional_constant(src: str) -> None:
    """최소 명목 상수가 있고 5 USDT 다."""
    assert "const AP_MIN_NOTIONAL_USDT = 5;" in src


def test_preview_blocks_submit_when_below_min_notional(src: str) -> None:
    """미리보기에서 최소 명목 미만이면 진입 버튼을 잠근다 (필요 금액을 알려준다)."""
    assert "notional < AP_MIN_NOTIONAL_USDT" in src
    assert "minAmount = AP_MIN_NOTIONAL_USDT / lev" in src
    i_block = src.index("if (notional < AP_MIN_NOTIONAL_USDT)")
    i_disable = src.index("_btn.disabled = !!block")
    assert i_block < i_disable, "잠금 판정이 버튼 비활성화보다 앞에 있어야 한다"


def test_submit_rechecks_before_sending(src: str) -> None:
    """버튼을 우회해도 전송 직전에 한 번 더 막는다."""
    body = src[src.index("async function submitAddPosition()"):]
    guard = body.index("amount * _lev < AP_MIN_NOTIONAL_USDT")
    post = body.index("/add-position")
    assert guard < post, "검사가 POST 보다 앞에 있어야 한다"


def test_limit_price_prefilled_with_current_price(src: str) -> None:
    """지정가 칸이 비어 있으면 현재가로 채운다 (1200 같은 값이 남지 않게)."""
    assert "if (_lp && !_lp.value && data.price) _lp.value = data.price;" in src


def test_far_limit_price_warns(src: str) -> None:
    """지정가가 현재가와 20% 이상 벌어지면 경고를 띄운다 (막지는 않는다 — 예약 주문은 정상)."""
    assert "Math.abs(gap) >= 20" in src
    assert "숫자를 확인하세요" in src


def test_crlf_preserved() -> None:
    """이 파일은 CRLF 다 (프로젝트 규칙 8)."""
    raw = JS.read_bytes()
    assert b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n"), "LF 단독 줄이 섞이면 안 된다"
