"""🚨 Fix 272 — 체결된 주문을 「취소」로 뒤집던 버그.

## 실측 사고 (#1930 XPLUSDT SHORT)

    08:23:20  💉 포지션 추가 MARKET 7,187 발송 -> **즉시 체결**
    08:25:43  zombie_guardian 이 「openOrders 에 없음」을 보고 **CANCELED 로 정정**

    결과: 거래소 실 포지션 28,932 vs DB 체결합 21,745  (차이 = 그 7,187)
          평단·total_capital 은 4건을 반영했는데 **주문 이력만 어긋났다**
          -> 「포지션 수량 불일치」 알림이 계속 떴고 학습 데이터도 오염됐다

## 원인

「openOrders 에 없다」는 **취소**와 **체결**을 구별하지 못한다.
  - MARKET 은 즉시 체결되므로 openOrders 에 **절대** 안 나타난다 = 항상 거짓 양성
  - LIMIT 도 체결되면 사라진다 = 스트림을 놓치면 같은 오판정

## 수정

단정하지 말고 거래소에 **그 주문의 실제 상태를 묻는다**(get_order):
    FILLED/PARTIALLY_FILLED -> 그 상태로 정정 + 체결 수량·평균가 복구 (회계 수리)
    CANCELED/EXPIRED/REJECTED -> CANCELED (원래 의도)
    조회 실패 -> **건드리지 않는다** (기록을 훼손하느니 그대로 두는 게 낫다)
"""
from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
ZG = BACKEND / "app" / "services" / "zombie_guardian.py"


def _src() -> str:
    return ZG.read_text(encoding="utf-8")


def _code() -> str:
    return "\n".join(
        ln for ln in _src().splitlines() if not ln.lstrip().startswith("#")
    )


def test_queries_the_exchange_before_deciding():
    """🚨 이게 수정의 핵심 — 단정하지 말고 물어본다."""
    code = _code()
    assert "client.get_order(" in code, "거래소에 실제 상태를 묻지 않는다"
    i_q = code.index("client.get_order(")
    i_cancel = code.index('lo.status = "CANCELED"')
    assert i_q < i_cancel, "조회가 CANCELED 정정보다 뒤에 있다 = 무의미"


def test_filled_is_repaired_not_canceled():
    """체결된 주문은 FILLED 로 정정하고 수량·평균가를 복구해야 한다."""
    code = _code()
    i = code.index("client.get_order(")
    body = code[i: i + 2200]
    assert '"FILLED"' in body
    assert "executed_qty" in body and "avg_price" in body
    assert "continue" in body, "체결 건이 CANCELED 경로로 흘러간다"


def test_query_failure_leaves_the_record_alone():
    """🚨 모르면 그대로 둔다 — 기록을 훼손하느니 낫다."""
    src = _src()
    i = src.index("주문 상태 조회 실패")
    body = src[i: i + 300]
    assert "건드리지 않는다" in body
    assert "continue" in body


def test_alive_orders_are_not_flipped():
    """거래소가 아직 NEW 라고 하면 취소로 뒤집으면 안 된다 (조회 경쟁)."""
    code = _code()
    assert '"CANCELED", "EXPIRED", "REJECTED"' in code


def test_probe_budget_prevents_api_storm():
    """후보가 많아도 사이클당 상한을 둔다 (IP ban 이력)."""
    code = _code()
    assert "_probe_budget" in code
    i = code.index("_probe_budget = ")
    assert code[i: i + 40].split("=")[1].strip().split()[0].isdigit()


def test_evidence_is_recorded():
    src = _src()
    for token in ("Fix 272", "#1930", "28,932", "21,745"):
        assert token in src, f"근거 주석에 '{token}' 이 없다"
