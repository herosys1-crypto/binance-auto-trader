"""Fix 494 (2026-11-22): testnet 418/429 는 testnet 만 막는다 — mainnet 차단 키·예열은 mainnet 응답만.

운영 실측 15:03:02 UTC: 계정 4(testnet) 고아 점검이 맞은 testnet 418(17,637초)이 전역 키에 기록돼
mainnet 전부가 4.9시간 로컬 차단(같은 순간 mainnet /time 200, used-weight 1). 네트워크·Redis 없이 모의.
"""
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from app.integrations.binance import client as C

TN = "https://testnet.binancefuture.com/fapi/v2/positionRisk?timestamp=1"
MN = "https://fapi.binance.com/fapi/v2/positionRisk?timestamp=1"
NOW = 1_000_000


def _reset():
    C._ip_ban_until_ms_local = 0
    C._warmup_until_ms_local = 0
    C._testnet_ban_until_ms_local = 0
    C._ip_ban_redis_checked_at = float("-inf")
    C._warmup_redis_checked_at = float("-inf")
    C._testnet_ban_redis_checked_at = float("-inf")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in ("_ip_ban_until_ms_local", "_warmup_until_ms_local", "_testnet_ban_until_ms_local",
              "_ip_ban_redis_checked_at", "_warmup_redis_checked_at", "_testnet_ban_redis_checked_at"):
        monkeypatch.setattr(C, k, getattr(C, k))
    _reset()
    monkeypatch.setattr(C, "_now_ms", lambda: NOW)
    store = {}
    r = MagicMock()
    r.get.side_effect = lambda k: store.get(k)
    r.eval.side_effect = lambda _lua, _n, key, until, _ttl: store.__setitem__(key, until.encode())
    with patch("app.core.redis_client.get_redis_client", return_value=r):
        yield store


def _resp(url, status=418, text="Way too many requests; IP banned until 1000017637000.", headers=None):
    m = MagicMock(status_code=status, text=text, headers=headers or {})
    m.url = url
    return m


def test_testnet_418_does_not_block_mainnet(clean):
    C._mark_ip_ban_from_response(_resp(TN))
    assert C._ip_ban_remaining_ms() == 0
    assert C._in_warmup() is False                       # 예열도 안 생김
    assert C._testnet_ban_remaining_ms() == 1000017637000 - NOW
    assert C._IP_BAN_REDIS_KEY not in clean and C._WARMUP_REDIS_KEY not in clean
    assert clean[C._TESTNET_BAN_REDIS_KEY] == b"1000017637000"


def test_mainnet_418_unchanged(clean):
    C._mark_ip_ban_from_response(_resp(MN))
    assert C._ip_ban_remaining_ms() == 1000017637000 - NOW
    assert C._warmup_until_ms_local == 1000017637000 + C.POST_BAN_WARMUP_SEC * 1000
    assert C._testnet_ban_remaining_ms() == 0


def test_unknown_url_is_mainnet():
    m = MagicMock(status_code=418, text="banned", headers={})   # url 이 문자열이 아님 = 옛 동작(mainnet)
    C._mark_ip_ban_from_response(m)
    assert C._ip_ban_remaining_ms() == 60_000 and C._testnet_ban_remaining_ms() == 0


def test_url_from_request_when_response_url_missing():
    m = MagicMock(status_code=429, text="", headers={})
    m.url = None
    m.request.url = TN
    C._mark_ip_ban_from_response(m)
    assert C._testnet_ban_remaining_ms() == C.DEFAULT_429_BLOCK_SEC * 1000 and C._ip_ban_remaining_ms() == 0


def test_testnet_ban_seen_via_redis(clean):
    clean[C._TESTNET_BAN_REDIS_KEY] = b"1060000"
    assert C._testnet_ban_remaining_ms() == 60_000
    assert C._ip_ban_remaining_ms() == 0


def test_testnet_redis_failure_no_exception():
    with patch("app.core.redis_client.get_redis_client", side_effect=RuntimeError("down")):
        C._set_testnet_ban(NOW + 5_000, source="t")
        assert C._testnet_ban_remaining_ms() == 5_000


# ── 실제 _request ─────────────────────────────────────────────────────────
class _OK:
    status_code = 200
    headers: dict = {}
    text = "[]"
    content = b"[]"
    url = MN

    def json(self):
        return []


class _Sess:
    def __init__(self):
        self.sent = []

    def request(self, **kw):
        self.sent.append(kw["url"])
        return _OK()


@pytest.fixture
def clients(monkeypatch):
    monkeypatch.setattr(C, "_add_weight", lambda *a, **k: 0)
    monkeypatch.setattr(C, "_count_request", lambda *a, **k: None)
    monkeypatch.setattr(C, "note_used_weight", lambda *a, **k: 0, raising=False)
    s = _Sess()
    mn = C.BinanceClient(api_key="k", api_secret="s", session=s, base_url="https://fapi.binance.com")
    tn = C.BinanceClient(api_key="k", api_secret="s", session=s, is_testnet=True,
                         base_url="https://testnet.binancefuture.com")
    return mn, tn, s


def _try(cli, path="/fapi/v2/positionRisk"):
    try:
        cli._request("GET", path, params={}, signed=True)
        return True
    except C.BinanceAPIError as e:
        assert e.status_code == 418 and e.locally_suppressed
        return False


def test_request_mainnet_passes_while_testnet_banned(clients):
    mn, tn, s = clients
    C._set_testnet_ban(NOW + 600_000, source="t")
    assert _try(mn) is True and _try(tn) is False
    assert len(s.sent) == 1 and "fapi.binance.com" in s.sent[0]


def test_request_testnet_passes_while_mainnet_banned(clients):
    mn, tn, s = clients
    C._set_ip_ban(NOW + 600_000, source="t")
    assert _try(mn) is False and _try(tn) is True
    assert len(s.sent) == 1 and "testnet" in s.sent[0]


def test_testnet_base_url_without_flag_is_testnet(clients):
    _mn, _tn, s = clients
    cli = C.BinanceClient(api_key="k", api_secret="s", session=s, base_url="https://testnet.binancefuture.com")
    C._set_testnet_ban(NOW + 1_000, source="t")
    assert _try(cli) is False


def test_guard_ip_ban_per_network(clean):
    from fastapi import HTTPException
    from app.api.v1.exchange_accounts import _guard_ip_ban
    C._set_testnet_ban(NOW + 30_000, source="t")
    _guard_ip_ban("x")                                    # mainnet 계정 = 통과
    with pytest.raises(HTTPException):
        _guard_ip_ban("x", testnet=True)
    _reset()
    clean.clear()                                         # 모의 Redis 의 testnet 키도 지운다
    C._set_ip_ban(NOW + 30_000, source="t")
    _guard_ip_ban("x", testnet=True)                      # testnet 계정 = 통과
    with pytest.raises(HTTPException):
        _guard_ip_ban("x")


# ── 속성: 어떤 순서로 섞여 와도 testnet 응답은 mainnet 차단을 늘리지 않는다 ─────────────
@settings(max_examples=200, deadline=None)
@given(st.lists(st.tuples(st.booleans(), st.sampled_from([418, 429]), st.integers(1, 20_000)), max_size=12))
def test_prop_mainnet_ban_only_from_mainnet(events):
    _reset()
    with patch("app.core.redis_client.get_redis_client", side_effect=RuntimeError("no redis")):
        want_mn = want_tn = 0
        for is_tn, code, sec in events:
            until = NOW + sec * 1000
            C._mark_ip_ban_from_response(_resp(TN if is_tn else MN, status=code,
                                               text=f"IP banned until {until:013d}"))
            if is_tn:
                want_tn = max(want_tn, until)
            else:
                want_mn = max(want_mn, until)
        assert C._ip_ban_until_ms_local == want_mn       # mainnet 차단 = mainnet 응답의 최댓값만
        assert C._testnet_ban_until_ms_local == want_tn
        assert C._warmup_until_ms_local == (want_mn + C.POST_BAN_WARMUP_SEC * 1000 if want_mn else 0)
