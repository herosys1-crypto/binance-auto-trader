"""ban-warmup (2026-11-22): IP 차단이 풀린 직후 몰림 → 재차단 악순환 끊기. 네트워크·Redis 없이 모의."""
from unittest.mock import MagicMock, patch

import pytest

from app.integrations.binance import client as C
from app.integrations.binance.weight_priority import scan_throttled


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(C, "_ip_ban_until_ms_local", 0)
    monkeypatch.setattr(C, "_warmup_until_ms_local", 0)
    monkeypatch.setattr(C, "_warmup_redis_checked_at", 0.0)
    monkeypatch.setattr(C, "_ip_ban_redis_checked_at", 0.0)
    r = MagicMock()
    r.get.return_value = None
    with patch("app.core.redis_client.get_redis_client", return_value=r):
        yield r


def test_ban_records_warmup_after_ban(monkeypatch):
    monkeypatch.setattr(C, "_now_ms", lambda: 1_000_000)
    C._set_ip_ban(1_000_000 + 60_000, source="t")
    assert C._warmup_until_ms_local == 1_000_000 + 60_000 + C.POST_BAN_WARMUP_SEC * 1000


def test_warmup_window_boundaries(monkeypatch):
    now = [1_000_000]
    monkeypatch.setattr(C, "_now_ms", lambda: now[0])
    C._set_ip_ban(1_060_000, source="t")
    end = 1_060_000 + C.POST_BAN_WARMUP_SEC * 1000
    assert C._in_warmup() is False                 # 차단 중엔 예열 아님(요청 자체가 막힘)
    for t, want in ((1_060_000, True), (end - 1, True), (end, False), (end + 1, False)):
        now[0] = t
        assert C._in_warmup() is want, t


def test_warmup_only_extends(monkeypatch):
    monkeypatch.setattr(C, "_now_ms", lambda: 1_000)
    C._set_warmup(500_000)
    C._set_warmup(400_000)
    assert C._warmup_until_ms_local == 500_000


@pytest.mark.parametrize("headers,expect", [({"Retry-After": "300"}, 300), ({}, 120), ({"Retry-After": "x"}, 120),
                                            ({"Retry-After": "0"}, 120), ({"Retry-After": "99999"}, 120)])
def test_429_retry_after(monkeypatch, headers, expect):
    monkeypatch.setattr(C, "_now_ms", lambda: 1_000_000)
    resp = MagicMock(status_code=429, text="Too many requests", headers=headers)
    C._mark_ip_ban_from_response(resp)
    assert C._ip_ban_until_ms_local == 1_000_000 + expect * 1000


def test_418_without_time_keeps_60s(monkeypatch):
    monkeypatch.setattr(C, "_now_ms", lambda: 1_000_000)
    C._mark_ip_ban_from_response(MagicMock(status_code=418, text="banned", headers={"Retry-After": "300"}))
    assert C._ip_ban_until_ms_local == 1_000_000 + 60_000


def test_ban_seen_via_redis_pulls_warmup(monkeypatch, clean):
    """다른 컨테이너가 쓴 차단(Redis)만 본 프로세스도 예열 끝 = 차단 끝 + 15분 (불변식)."""
    now = [1_000_000]
    monkeypatch.setattr(C, "_now_ms", lambda: now[0])
    clean.get.side_effect = lambda k: b"1060000" if k == C._IP_BAN_REDIS_KEY else None
    assert C._ip_ban_remaining_ms() == 60_000
    assert C._warmup_until_ms_local == 1_060_000 + C.POST_BAN_WARMUP_SEC * 1000
    clean.get.side_effect = lambda k: None
    now[0] = 1_060_001
    assert C._in_warmup() is True


def test_explicit_until_wins(monkeypatch):
    monkeypatch.setattr(C, "_now_ms", lambda: 1_000_000)
    resp = MagicMock(status_code=418, text="IP banned until 1000123456789", headers={"Retry-After": "5"})
    C._mark_ip_ban_from_response(resp)
    assert C._ip_ban_until_ms_local == 1000123456789


def test_redis_failure_no_exception(monkeypatch):
    monkeypatch.setattr(C, "_now_ms", lambda: 1_000)
    with patch("app.core.redis_client.get_redis_client", side_effect=RuntimeError("down")):
        C._set_ip_ban(61_000, source="t")
        assert C._in_warmup() is False
        monkeypatch.setattr(C, "_now_ms", lambda: 61_001)
        assert C._in_warmup() is True              # 로컬만으로 동작


def test_governor_budgets_during_warmup():
    scan = frozenset({"/fapi/v1/klines"})
    # 예열 중: 스캔 500 · 학습 잡 0 · 필수 경로는 항상 통과
    assert scan_throttled("/fapi/v1/klines", 501, "", scan_endpoints=scan, budget=C.WARMUP_SCAN_BUDGET_PER_MIN, low_budget=0) == 500
    assert scan_throttled("/fapi/v1/klines", 499, "", scan_endpoints=scan, budget=500, low_budget=0) is None
    assert scan_throttled("/fapi/v1/klines", 1, "paper_trading", scan_endpoints=scan, budget=500, low_budget=0) == 0
    assert scan_throttled("/fapi/v1/order", 99999, "paper_trading", scan_endpoints=scan, budget=500, low_budget=0) is None
    # 평상시 그대로
    assert scan_throttled("/fapi/v1/klines", 1499, "", scan_endpoints=scan) is None
    assert scan_throttled("/fapi/v1/klines", 1101, "paper_trading", scan_endpoints=scan) == 1100


class _FakeRedis:
    """get·setex·eval(SET_MAX)·incrby·hincrby·expire 를 가진 메모리 Redis — 실제 요청 경로 시험용."""
    def __init__(self):
        self.kv, self.n = {}, {}

    def get(self, k):
        return self.kv.get(k)

    def setex(self, k, ttl, v):
        self.kv[k] = str(v).encode()

    def eval(self, script, nkeys, key, val, ttl):
        if int(val) > int(self.kv.get(key, b"0")):
            self.kv[key] = str(val).encode()
        return 1

    def incrby(self, k, w):
        self.n[k] = self.n.get(k, 0) + int(w)
        return self.n[k]

    def hincrby(self, *a, **k):
        return 1

    def expire(self, *a, **k):
        return True

    def delete(self, *a, **k):
        return 1


def _client():
    sess = MagicMock()
    resp = MagicMock(status_code=200, content=b"{}", headers={})
    resp.json.return_value = {}
    sess.request.return_value = resp
    return C.BinanceClient(api_key="k", api_secret="s", base_url="http://x", session=sess), sess


def _run_request(path, caller, warm, *, signed=False):
    fr = _FakeRedis()
    with patch("app.core.redis_client.get_redis_client", return_value=fr),             patch.object(C, "_ip_ban_until_ms_local", 0),             patch.object(C, "_warmup_until_ms_local", (C._now_ms() + 600_000) if warm else 0),             patch.object(C, "_warmup_redis_checked_at", float("inf")), patch.object(C, "_ip_ban_redis_checked_at", float("inf")):
        cl, sess = _client()
        tok = C.set_caller(caller)
        try:
            try:
                cl._request("GET", path, params={"symbol": "BTCUSDT", "interval": "15m", "limit": 100}, signed=signed)
                err = None
            except C.BinanceAPIError as e:
                err = e
        finally:
            C.reset_caller(tok)
        return err, sess, fr


def test_real_request_learning_scan_blocked_during_warmup():
    """실제 _request: 예열 중 학습 잡(paper_trading) 스캔은 로컬 429 로 막히고 거래소 호출 0 · 무게는 되돌림(Fix 127)."""
    err, sess, fr = _run_request("/fapi/v1/klines", "paper_trading", True)
    assert err is not None and err.status_code == 429 and err.locally_suppressed
    sess.request.assert_not_called()
    assert all(v == 0 for v in fr.n.values())                     # 거절된 요청 무게는 남지 않음
    assert C._ip_ban_until_ms_local == 0                          # Fix 119: 로컬 예외는 차단을 새로 기록하지 않음


def test_real_request_essential_passes_during_warmup():
    """실제 _request: 예열 중에도 필수(계정) 요청은 거래소로 나간다."""
    err, sess, _ = _run_request("/fapi/v2/account", "paper_trading", True, signed=True)
    assert err is None
    sess.request.assert_called_once()


def test_real_request_learning_scan_passes_when_not_warm():
    err, sess, _ = _run_request("/fapi/v1/klines", "paper_trading", False)
    assert err is None
    sess.request.assert_called_once()


def test_real_request_normal_scan_under_warm_budget_passes():
    err, sess, _ = _run_request("/fapi/v1/klines", "live_scanner", True)
    assert err is None                                            # 일반 스캐너는 예열 상한(500) 안에서 통과
    sess.request.assert_called_once()


def test_first_recheck_right_after_start(monkeypatch, clean):
    """프로세스 시작 직후(monotonic ≈ 1초)에도 Redis 예열을 바로 읽는다(Gemini 심판)."""
    monkeypatch.setattr(C, "_warmup_redis_checked_at", float("-inf"))
    monkeypatch.setattr(C, "_ip_ban_redis_checked_at", float("-inf"))
    monkeypatch.setattr(C.time, "monotonic", lambda: 1.0)
    monkeypatch.setattr(C, "_now_ms", lambda: 2_000_000)
    clean.get.side_effect = lambda k: b"3000000" if k == C._WARMUP_REDIS_KEY else None
    assert C._in_warmup() is True


from hypothesis import given, settings, strategies as st  # noqa: E402


@settings(max_examples=300, deadline=None)
@given(st.lists(st.tuples(st.sampled_from(["set", "redis", "tick"]), st.integers(0, 50_000_000)), min_size=1, max_size=25))
def test_prop_warmup_covers_ban(ops):
    """속성: 어떤 순서의 갱신(직접 기록 · 다른 컨테이너의 Redis 차단 · 시간 경과)에서도
    I1 예열 끝 ≥ 차단 끝 + 15분 · I2 예열 끝은 줄지 않음 · I3 차단 중엔 예열 아님."""
    store = {}
    r = MagicMock()
    r.get.side_effect = lambda k: store.get(k)
    r.setex.side_effect = lambda k, ttl, v: store.__setitem__(k, str(v).encode())
    def _eval(script, nkeys, key, val, ttl):   # 원자 SET_MAX 를 store 에 실제로 반영(Gemini 3차)
        if int(val) > int(store.get(key, b"0")):
            store[key] = str(val).encode()
        return 1
    r.eval.side_effect = _eval
    now = [1_000_000]
    with patch("app.core.redis_client.get_redis_client", return_value=r), \
            patch.object(C, "_now_ms", lambda: now[0]), patch.object(C.time, "monotonic", lambda: now[0] / 1000.0):
        C._ip_ban_until_ms_local = 0
        C._warmup_until_ms_local = 0
        C._warmup_redis_checked_at = float("-inf")
        C._ip_ban_redis_checked_at = float("-inf")
        prev_warm = 0
        for op, x in ops:
            if op == "set":
                C._set_ip_ban(now[0] + x, source="p")
            elif op == "redis":
                store[C._IP_BAN_REDIS_KEY] = str(now[0] + x).encode()   # 다른 컨테이너가 쓴 차단
                C._ip_ban_redis_checked_at = float("-inf")
            else:
                now[0] += x
            left = C._ip_ban_remaining_ms()
            warm = C._in_warmup()
            if C._ip_ban_until_ms_local:
                assert C._warmup_until_ms_local >= C._ip_ban_until_ms_local + C.POST_BAN_WARMUP_SEC * 1000   # I1
            assert C._warmup_until_ms_local >= prev_warm                                                    # I2
            prev_warm = C._warmup_until_ms_local
            if left > 0:
                assert warm is False                                                                        # I3
            if C._warmup_until_ms_local:                                                                    # I4 Redis 에도 기록
                assert int(store.get(C._WARMUP_REDIS_KEY, b"0")) >= C._ip_ban_until_ms_local


class _AtomicRedis:
    """eval(SET_MAX) 을 원자적으로 흉내 — 실제 Redis 처럼 스크립트 하나가 끝날 때까지 끼어들기 없음."""
    def __init__(self):
        self.store = {}

    def eval(self, script, nkeys, key, val, ttl):
        assert "redis.call('SET'" in script and nkeys == 1
        if int(val) > int(self.store.get(key, b"0")):
            self.store[key] = val.encode()
            return 1
        return 0

    def get(self, key):
        return self.store.get(key)


def test_set_max_is_atomic_against_interleaving():
    """두 프로세스가 같은 옛 값을 읽은 뒤 쓰는 경합 모양: 15분 기록 뒤 5분 기록이 와도 15분이 남는다."""
    r = _AtomicRedis()
    C._redis_set_max(r, "k", 1_900_000, 1_000_000)   # B: 15분
    C._redis_set_max(r, "k", 1_300_000, 1_000_000)   # A: 5분 (늦게 도착)
    assert r.get("k") == b"1900000"


@settings(max_examples=300, deadline=None)
@given(st.lists(st.integers(0, 10**9), min_size=1, max_size=40))
def test_prop_redis_value_is_max_of_writes(writes):
    """속성: 어떤 순서로 몇 번을 쓰든 Redis 값 = 지금까지 쓴 값의 최댓값(줄지 않음)."""
    r = _AtomicRedis()
    best = 0
    for w in writes:
        C._redis_set_max(r, "k", w + 1, 0)
        best = max(best, w + 1)
        assert int(r.get("k")) == best


def test_eval_unavailable_falls_back():
    r = MagicMock()
    r.eval.side_effect = RuntimeError("no eval")
    r.get.return_value = b"5"
    C._redis_set_max(r, "k", 10, 0)
    r.setex.assert_called_once()
