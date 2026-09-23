"""🚨 Fix 396 — 「💉 포지션 추가」가 총 자본을 두 번 더하던 것 (2026-09-23).

사장님: "이상해 이거래내역을 확인해서 수정해줘" (AGTUSDT LONG 내역 첨부)

실측 (#4564 AGTUSDT LONG, 운영 DB 읽기):
    total_capital = 1,700.00   ← 기록
    실제 체결 명목 1,201.50 ÷ 레버리지 2 = **600.75** (거래소 증거금 610.57)
    내역 = 시작 600 + MARKET 추가 5회 + LIMIT 추가 1회(체결 0)
    1,700 = 600 + 5×200 + 1×100  → **MARKET 추가마다 2배로 더해졌다**

원인 두 곳이 같은 금액을 각각 더했다:
  ① `api/v1/strategies/lifecycle.py` (2026-06-03) — 주문 성공 뒤 무조건 `+= amount_usdt`
  ② `services/execution_service.py` Fix 157 — MARKET 만 `+= amount_usdt`
     (주석에 「포지션 추가는 total_capital 을 올리지 않는다」고 적혀 있었는데 사실이 아니었다)

영향 (돈):
  SL 한도 = total_capital / leverage × sl_pct  → #4564 은 sl_pct 100% 라 **850 USDT** 손실까지
  허용됐다. 실제 투입 자본은 600 이므로 자본보다 큰 손실을 허용하는 상태였다.
  노출 계산(calc_reserved_for_account)·화면 자본도 같이 과대.

수정:
  · ①을 제거 → 자본 반영은 한 곳에서만.
  · MARKET = 주문 직후(execution_service).
  · LIMIT = `stream_service` 에서 **체결된 만큼만** (delta × 가격 ÷ 레버리지).
    미체결 LIMIT 이 자본을 올리지 않는다 (#4564 의 0.01577 지정가 = 체결 0 인데 +100 이었다).
  · 「증거금 추가」(add_margin)는 성격이 달라 그대로 둔다.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.notification_service import _fmt_num, _fmt_price

APP = Path(__file__).resolve().parent.parent / "app"
LIFECYCLE = APP / "api" / "v1" / "strategies" / "lifecycle.py"
EXECUTION = APP / "services" / "execution_service.py"
STREAM = APP / "services" / "stream_service.py"


class TestSingleSourceOfCapital:
    def test_lifecycle_no_longer_increments(self) -> None:
        """add-position 엔드포인트는 total_capital 을 건드리지 않는다."""
        src = LIFECYCLE.read_text(encoding="utf-8")
        body = src[src.index("def add_position_to_strategy"):src.index("def manual_take_profit")
                   if "def manual_take_profit" in src else len(src)]
        assert "total_capital = prev_capital + payload.amount_usdt" not in body
        assert "Fix 396" in body, "왜 없는지 근거를 코드에 남긴다"

    def test_add_margin_still_increments(self) -> None:
        """「증거금 추가」는 여전히 자본을 올린다 (성격이 다른 기능)."""
        src = LIFECYCLE.read_text(encoding="utf-8")
        head = src[:src.index("def add_position_to_strategy")]
        assert "strategy.total_capital = prev_capital + payload.amount" in head

    def test_execution_service_market_only(self) -> None:
        """MARKET 만 즉시 반영 — LIMIT 은 여기서 올리지 않는다."""
        src = EXECUTION.read_text(encoding="utf-8")
        i = src.index("strategy.total_capital = _prev_cap + Decimal(str(amount_usdt))")
        guard = src.rindex('if order_type_u == "MARKET":', 0, i)
        assert i - guard < 400, "MARKET 조건 안에 있어야 한다"

    def test_stream_counts_only_filled_limit_adds(self) -> None:
        """LIMIT 추가는 체결분만, 단계 진입은 제외."""
        src = STREAM.read_text(encoding="utf-8")
        blk = src[src.index("[Fix396]") - 1600:src.index("[Fix396]") + 400]
        assert "order.stage_no is None" in blk, "단계 진입은 계획 자본이 이미 있으므로 제외"
        assert '(order.order_type or "").upper() == "LIMIT"' in blk
        assert "delta_executed * _px" in blk, "체결된 만큼만"
        assert "/ _lev" in blk or ") / _lev" in blk, "명목이 아니라 증거금(margin) 단위"


class TestPriceFormatting:
    """🩹 같이 고친 것 — 알림 가격이 전부 「0.02」로 나왔다 (소수점 2자리 고정)."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("0.01821920", "0.018219"),
            ("0.01577", "0.01577"),
            ("0.00093280", "0.0009328"),
            ("1.5", "1.50"),
            ("152.72", "152.72"),
            ("64250.1234", "64,250.12"),
        ],
    )
    def test_price_decimals_adapt(self, value: str, expected: str) -> None:
        assert _fmt_price(Decimal(value)) == expected

    def test_money_format_unchanged(self) -> None:
        """돈 금액은 2자리 그대로 (100.00 USDT)."""
        assert _fmt_num(Decimal("100")) == "100.00"
        assert _fmt_num(Decimal("1201.5")) == "1,201.50"

    def test_none_is_dash(self) -> None:
        assert _fmt_price(None) == "-"

    def test_price_fields_use_price_formatter(self) -> None:
        """시작가·진입가·평균 단가·지정가·청산 단가는 가격 포맷을 쓴다."""
        src = (APP / "services" / "notification_service.py").read_text(encoding="utf-8")
        for label in ("시작가", "진입가", "평균 단가", "지정가", "청산 단가", "현재가", "청산가"):
            lines = [ln for ln in src.splitlines() if label in ln and "_fmt" in ln]
            assert lines, label
            assert all("_fmt_price(" in ln for ln in lines), f"{label}: {lines}"


def test_crlf_preserved() -> None:
    """프로젝트 규칙 8 — 이 파일들은 CRLF 다."""
    for path in (LIFECYCLE, EXECUTION, STREAM, APP / "services" / "notification_service.py"):
        raw = path.read_bytes()
        assert b"\r\n" in raw, path.name
        assert raw.count(b"\n") == raw.count(b"\r\n"), path.name


def test_capital_increment_sites_are_exactly_three() -> None:
    """자본을 더하는 곳은 셋뿐 — 늘어나면 또 이중 가산이 생긴다.

    ① lifecycle.add_margin          = 「증거금 추가」 (성격이 다른 기능)
    ② execution_service (Fix 157)   = 포지션 추가 MARKET (주문 직후)
    ③ stream_service  (Fix 396)     = 포지션 추가 LIMIT (체결된 만큼만)
    """
    hits = {}
    for path in APP.rglob("*.py"):
        for m in re.finditer(r"total_capital\s*=\s*_?prev[_a-z]*\s*\+", path.read_text(encoding="utf-8")):
            hits.setdefault(path.name, []).append(m.group(0))
    assert set(hits) == {"lifecycle.py", "execution_service.py", "stream_service.py"}, hits
    assert sum(len(v) for v in hits.values()) == 3, hits
