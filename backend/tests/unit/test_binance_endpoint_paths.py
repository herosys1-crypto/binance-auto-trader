"""BinanceClient 의 endpoint path 정확성 검증 (정적 분석).

배경 (2026-05-06 사용자 #102 사례):
  add_position_margin 의 path 가 `/fapi/v1/positionMargin/modify` (잘못)
  → Binance 응답 `-5000 Path is invalid`. 공식 endpoint 는 `/fapi/v1/positionMargin`.

  이 테스트는 코드의 endpoint path 와 Binance 공식 명세 비교 — 미래에 path
  실수로 변경되면 즉시 발견 (정적 분석이라 거래소 호출 불필요).

Binance Futures USDⓢ-M endpoint 공식 reference:
  https://binance-docs.github.io/apidocs/futures/en/#change-position-margin-trade
"""
from __future__ import annotations

import inspect

import pytest

from app.integrations.binance.client import BinanceClient


class TestBinanceEndpointPaths:
    def test_add_position_margin_uses_correct_path(self):
        """`POST /fapi/v1/positionMargin` (NOT `/positionMargin/modify`).

        실제 _request 호출 부분의 path 만 검증 (docstring/주석 영향 받지 않게).
        """
        src = inspect.getsource(BinanceClient.add_position_margin)
        # docstring/주석 제거 — """..."""  + # 라인 모두 제외
        import re
        src_no_doc = re.sub(r'""".*?"""', '', src, flags=re.DOTALL)
        src_no_doc = re.sub(r'#.*', '', src_no_doc)
        # 실제 request 호출의 path 검증
        assert '"/fapi/v1/positionMargin"' in src_no_doc, (
            f"add_position_margin 의 실제 path 가 `/fapi/v1/positionMargin` 이 아님.\n"
            f"코드 (주석 제거):\n{src_no_doc[:500]}"
        )
        assert "/positionMargin/modify" not in src_no_doc, (
            "request 호출에 잘못된 path `/positionMargin/modify` 사용 중 — "
            "Binance -5000 'Path is invalid' 에러 발생"
        )

    @pytest.mark.parametrize("method_name,expected_path", [
        ("get_exchange_info", "/fapi/v1/exchangeInfo"),
        ("get_server_time", "/fapi/v1/time"),
        ("ping", "/fapi/v1/ping"),
        ("get_account", "/fapi/v2/account"),
        ("get_balance", "/fapi/v2/balance"),
        ("get_position_risk", "/fapi/v2/positionRisk"),
        ("change_leverage", "/fapi/v1/leverage"),
        ("change_margin_type", "/fapi/v1/marginType"),
        ("change_position_mode", "/fapi/v1/positionSide/dual"),
        ("add_position_margin", "/fapi/v1/positionMargin"),
        ("get_klines", "/fapi/v1/klines"),
        ("get_24hr_ticker", "/fapi/v1/ticker/24hr"),
        ("start_user_stream", "/fapi/v1/listenKey"),
        ("keepalive_user_stream", "/fapi/v1/listenKey"),
        ("close_user_stream", "/fapi/v1/listenKey"),
    ])
    def test_endpoint_path_in_method_source(self, method_name, expected_path):
        """각 BinanceClient 메서드 본문에 정확한 Binance 공식 path 가 있는지 검증."""
        method = getattr(BinanceClient, method_name, None)
        if method is None:
            pytest.skip(f"BinanceClient.{method_name} 메서드 없음 — 미구현 또는 이름 변경")
        src = inspect.getsource(method)
        assert expected_path in src, (
            f"BinanceClient.{method_name} 의 path 검증 실패. "
            f"기대 path '{expected_path}' 가 source 에 없음.\n"
            f"Binance API 공식 명세 확인 — https://binance-docs.github.io/apidocs/futures/en/"
        )
