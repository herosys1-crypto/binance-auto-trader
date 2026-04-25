"""BinanceClient HMAC-SHA256 서명 단위 테스트.

실제 네트워크 호출 없이, 내부 `_sign` 함수의 동작만 검증.
Binance 공식 예제(문서의 샘플 키/시크릿)로 서명을 맞추면 네트워크 없이도
HMAC 구현이 올바른지 확인할 수 있다.
"""
from __future__ import annotations

import pytest

from app.integrations.binance.client import BinanceClient


class TestBinanceSigning:
    # Binance API 문서 샘플 시크릿
    _API_KEY = "vmPUZE6mv9SD5VNHk4HlWFsOr6aKE2zvsw0MuIgwCIPy6utIco14y7Ju91duEh8A"
    _API_SECRET = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"

    def _client(self) -> BinanceClient:
        return BinanceClient(api_key=self._API_KEY, api_secret=self._API_SECRET)

    def test_sign_is_deterministic_for_same_input(self) -> None:
        client = self._client()
        query = "symbol=LTCBTC&side=BUY&type=LIMIT&quantity=1&price=0.1&timeInForce=GTC&timestamp=1499827319559"
        sig_a = client._sign(query)
        sig_b = client._sign(query)
        assert sig_a == sig_b

    def test_sign_returns_hex_string_64_chars(self) -> None:
        """HMAC-SHA256 출력은 256-bit, hex 로 64 글자."""
        client = self._client()
        sig = client._sign("x=1&y=2&timestamp=123")
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_sign_official_example(self) -> None:
        """Binance 문서에 나와있는 샘플(HMAC SHA256) 결과와 일치하는지 확인."""
        client = self._client()
        query = (
            "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC"
            "&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
        )
        # 공식 문서에 표기된 기대 서명
        expected = "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"
        assert client._sign(query) == expected

    def test_sign_differs_with_different_secret(self) -> None:
        c1 = BinanceClient(api_key="k", api_secret="s1")
        c2 = BinanceClient(api_key="k", api_secret="s2")
        query = "a=1&timestamp=1"
        assert c1._sign(query) != c2._sign(query)


class TestBinanceClientConfig:
    def test_mainnet_base_url(self) -> None:
        c = BinanceClient(api_key="k", api_secret="s", is_testnet=False)
        assert "fapi.binance.com" in c.base_url
        assert "testnet" not in c.base_url

    def test_testnet_base_url(self) -> None:
        c = BinanceClient(api_key="k", api_secret="s", is_testnet=True)
        assert "testnet.binancefuture.com" in c.base_url

    def test_custom_base_url_override(self) -> None:
        c = BinanceClient(api_key="k", api_secret="s", base_url="https://example.test/")
        assert c.base_url == "https://example.test"  # trailing slash stripped
