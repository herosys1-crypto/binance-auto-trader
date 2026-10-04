"""Fix 416 — 거버너 우선순위: 학습·관측 잡은 1,100 에서 먼저 물러서고 실매매 스캐너는 1,500 까지 쓴다.

운영 2026-10-03 18:46 UTC: 15분봉 직후 학습(가상매매·시장관측)과 실매매 스캐너가 같은 1,500 선에서 경쟁 → 실매매 스캔 71건 거절.
테스트는 순수 판정 함수 + **실제 BinanceClient._request** (Redis 카운터·HTTP 만 가짜) 둘 다 본다.
"""
from __future__ import annotations

import random

import pytest

from app.integrations.binance import client as C
from app.integrations.binance import weight_priority as P

SCAN = C._SCAN_ENDPOINTS
KL = "/fapi/v1/klines"


# ── 순수 판정 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", ["/fapi/v1/order", "/fapi/v2/positionRisk", "/fapi/v2/account", "/fapi/v1/leverage"])
@pytest.mark.parametrize("caller", ["paper_trading", "pump_top_detector", ""])
def test_essential_never_throttled(path, caller):
    assert P.scan_throttled(path, 3000, caller, scan_endpoints=SCAN) is None


def test_live_scanner_uses_full_budget():
    assert P.scan_throttled(KL, 1400, "pump_top_detector", scan_endpoints=SCAN) is None
    assert P.scan_throttled(KL, 1500, "pump_top_detector", scan_endpoints=SCAN) is None
    assert P.scan_throttled(KL, 1501, "pump_top_detector", scan_endpoints=SCAN) == 1500


def test_learning_caller_yields_first():
    assert P.scan_throttled(KL, 1100, "paper_trading", scan_endpoints=SCAN) is None
    assert P.scan_throttled(KL, 1101, "paper_trading", scan_endpoints=SCAN) == 1100
    assert P.scan_throttled(KL, 1400, "market_obs_update", scan_endpoints=SCAN) == 1100


@pytest.mark.parametrize("caller", ["", None, "paper_trading_x", "PAPER_TRADING", "api:live-pump-dump/scan", 123, b"paper_trading"])
def test_unknown_or_odd_caller_is_normal_tier(caller):
    assert P.scan_throttled(KL, 1101, caller, scan_endpoints=SCAN) is None
    assert P.scan_throttled(KL, 1501, caller, scan_endpoints=SCAN) == 1500


@pytest.mark.parametrize("total", [None, "1600", float("nan"), True, object()])
def test_bad_total_never_blocks(total):
    assert P.scan_throttled(KL, total, "paper_trading", scan_endpoints=SCAN) is None


def test_huge_int_total_is_safe():
    assert P.scan_throttled(KL, 10 ** 400, "pump_top_detector", scan_endpoints=SCAN) == 1500


def test_constants_match_client_and_scheduler_job_names():
    assert P.SCAN_WEIGHT_BUDGET_PER_MIN == C.SCAN_WEIGHT_BUDGET_PER_MIN
    assert P.LOW_PRIORITY_SCAN_BUDGET_PER_MIN < C.SCAN_WEIGHT_BUDGET_PER_MIN
    import pathlib
    src = (pathlib.Path(C.__file__).resolve().parents[2] / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    missing = [n for n in P.LOW_PRIORITY_CALLERS if f'"{n}"' not in src and f"'{n}'" not in src]
    assert not missing, f"스케줄러 잡 이름과 다름(오타면 낮은 등급이 적용 안 됨): {missing}"


# ── 실제 거버너 (_request) ─────────────────────────────────────────────────
class FakeResp:
    status_code = 200
    headers: dict = {}
    text = "[]"
    content = b"[]"

    def json(self):
        return []


class FakeSession:
    def __init__(self):
        self.sent = 0

    def request(self, **_kw):
        self.sent += 1
        return FakeResp()


@pytest.fixture
def gov(monkeypatch):
    """Redis 대신 메모리 카운터. 무게 = estimate_weight 그대로(sign 포함)."""
    state = {"total": 0, "counts": {}}

    def add_weight(endpoint, params=None, sign=1):
        state["total"] += sign * C.estimate_weight(endpoint, params)
        return state["total"]

    def count(endpoint, status):
        state["counts"][status] = state["counts"].get(status, 0) + 1

    monkeypatch.setattr(C, "_add_weight", add_weight)
    monkeypatch.setattr(C, "_count_request", count)
    monkeypatch.setattr(C, "_ip_ban_remaining_ms", lambda: 0)
    monkeypatch.setattr(C, "note_used_weight", lambda *a, **k: 0, raising=False)
    sess = FakeSession()
    cli = C.BinanceClient(api_key="k", api_secret="s", session=sess)
    return cli, state, sess


def _call(cli, caller, path=KL, params=None):
    tok = C.set_caller(caller)
    try:
        cli._request("GET", path, params=params if params is not None else {"symbol": "ADAUSDT", "limit": 200})
        return True
    except C.BinanceAPIError as e:
        assert e.status_code == 429 and e.locally_suppressed
        return False
    finally:
        C.reset_caller(tok)


def test_real_governor_thresholds(gov):
    cli, state, sess = gov
    state["total"] = 1098
    assert _call(cli, "paper_trading") is True           # 1100 = 통과
    assert state["total"] == 1100
    assert _call(cli, "paper_trading") is False          # 1102 > 1100 → 막힘, 되돌림
    assert state["total"] == 1100 and state["counts"].get("weight_throttled_low") == 1
    assert _call(cli, "pump_top_detector") is True       # 실매매는 계속 통과
    state["total"] = 1499
    assert _call(cli, "pump_top_detector") is False      # 1501 > 1500
    assert state["counts"].get("weight_throttled") == 1
    assert state["total"] == 1499


def test_real_governor_essential_passes_even_for_learning_caller(gov):
    cli, state, sess = gov
    state["total"] = 5000
    before = sess.sent
    assert _call(cli, "paper_trading", path="/fapi/v2/positionRisk", params={}) is True
    assert sess.sent == before + 1


def test_real_governor_message_names_tier(gov):
    cli, state, _ = gov
    state["total"] = 1200
    tok = C.set_caller("chart_timing")
    try:
        with pytest.raises(C.BinanceAPIError) as ei:
            cli._request("GET", KL, params={"symbol": "ADAUSDT", "limit": 200})
    finally:
        C.reset_caller(tok)
    assert "/1100 this minute" in str(ei.value) and "low-priority chart_timing" in str(ei.value)


# ── 운영 18:46 재현 (실측 비율 그대로, 총수요 > 1,500 이 되도록 다른 잡 채움) ─────────────
MIX = {  # 호출자: weight (요청 1건 = 2)
    "paper_trading": 324, "market_obs_update": 221,         # 학습 545
    "pump_top_detector": 315, "macd_reversal_15m": 122,      # 실매매 437
    "api:live-pump-dump/scan": 136,                          # 화면
    "filler_scan": 700,                                      # 같은 분의 나머지 스캔(실측 분 총합이 1,500 을 넘게 한 몫)
}
LIVE = {"pump_top_detector", "macd_reversal_15m"}


def _simulate(gov, monkeypatch, low_budget):
    cli, state, _ = gov
    monkeypatch.setattr(P, "LOW_PRIORITY_SCAN_BUDGET_PER_MIN", low_budget)
    monkeypatch.setattr(C._scan_throttled, "__kwdefaults__",
                        {**C._scan_throttled.__kwdefaults__, "low_budget": low_budget})
    # 심판 지적: 패치가 실제 거버너 호출에 먹는지 먼저 확인 (client.py 가 low_budget 을 명시해 넘기면 이 단언이 깨진다)
    assert C._scan_throttled(KL, 1101, "paper_trading", scan_endpoints=SCAN) == (None if low_budget >= 1101 else low_budget)
    reqs = [c for c, w in MIX.items() for _ in range(w // 2)]
    random.Random(1846).shuffle(reqs)
    rejected = {}
    for c in reqs:
        if not _call(cli, c):
            rejected[c] = rejected.get(c, 0) + 1
    return rejected, state["total"]


def test_1846_replay_live_scanners_protected(gov, monkeypatch):
    # 대조군: 우선순위 없음(low_budget = budget) → 실매매 스캐너도 거절된다 (운영과 같은 현상)
    ctrl, ctrl_total = _simulate(gov, monkeypatch, 1500)
    assert sum(ctrl.get(c, 0) for c in LIVE) > 0
    assert ctrl_total <= 1500

    gov[1]["total"] = 0                                  # 새 분
    gov[1]["counts"].clear()
    rej, total = _simulate(gov, monkeypatch, 1100)
    live_ctrl = sum(ctrl.get(c, 0) for c in LIVE)
    live_new = sum(rej.get(c, 0) for c in LIVE)
    learn_new = rej.get("paper_trading", 0) + rej.get("market_obs_update", 0)
    assert live_new < live_ctrl                          # 실매매 거절이 줄었다
    assert learn_new > ctrl.get("paper_trading", 0) + ctrl.get("market_obs_update", 0)   # 학습이 대신 물러섰다
    assert total <= 1500                                 # IP 안전선은 그대로


def test_client_does_not_pin_low_budget():
    """거버너는 low_budget 을 넘기지 않는다 = weight_priority 의 상수 하나가 단일 출처. _add_weight 는 int 만 돌려준다(부동소수 오차 없음)."""
    import inspect
    src = inspect.getsource(C.BinanceClient._request)
    call = src[src.index("_scan_throttled("):]
    call = call[:call.index(")") + 1]
    assert "low_budget" not in call and "scan_endpoints=_SCAN_ENDPOINTS" in call
    assert "int(r.incrby(key, w))" in inspect.getsource(C._add_weight)
