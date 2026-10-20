"""🏷 Fix 476 — /symbols/pump-badges 입력 검사·응답 모양 (표시 전용, Redis 읽기만).
pump_profile 서비스는 리드 파일이라 이 워크트리에 없을 수 있다 → 항상 가짜 모듈로 대체한다."""
import sys
import types

import pytest
from fastapi import HTTPException

from app.api.v1 import symbols as S

BADGE = {"main": "p3", "label": "③ 펌프·덤프", "color": "red",
         "tags": [{"tag": "p3", "label": "③ 펌프·덤프", "color": "red", "desc": "d"}], "reasons": ["r"]}


class _Redis:
    def get(self, key):
        return b"2026-10-21T00:15:00+00:00" if key == "pump:profile:at" else None


@pytest.fixture
def pp(monkeypatch):
    m = types.ModuleType("app.services.pump_profile")
    m.AT_KEY = "pump:profile:at"
    m.calls = []

    def badges_for(symbols, redis=None):
        symbols = list(symbols)
        m.calls.append(symbols)
        return {s: BADGE for s in symbols if s == "AAAUSDT"}

    m.badges_for = badges_for
    m.profiles = lambda redis=None: {"AAAUSDT": {}, "BBBUSDT": {}}
    monkeypatch.setitem(sys.modules, "app.services.pump_profile", m)
    import app.services as _svc                         # 진짜 모듈이 이미 불려 있으면 패키지 속성이 우선 — 같이 바꾼다
    monkeypatch.setattr(_svc, "pump_profile", m, raising=False)
    monkeypatch.setattr(S, "get_redis_client", lambda: _Redis())
    return m


def test_shape_and_upper(pp):
    r = S.pump_badges(symbols="aaausdt, bbbusdt", user_id=1)
    assert r == {"at": "2026-10-21T00:15:00+00:00", "badges": {"AAAUSDT": BADGE}}
    assert pp.calls[-1] == ["AAAUSDT", "BBBUSDT"]


def test_invalid_symbols_filtered(pp):
    r = S.pump_badges(symbols="AAAUSDT,../etc,BAD SYM,a;b,", user_id=1)
    assert pp.calls[-1] == ["AAAUSDT"] and "AAAUSDT" in r["badges"]
    assert S.pump_badges(symbols="!!!", user_id=1)["badges"] == {}


def test_limit_200(pp):
    ok = ",".join(f"S{i}USDT" for i in range(200))
    S.pump_badges(symbols=ok, user_id=1)
    with pytest.raises(HTTPException) as e:
        S.pump_badges(symbols=ok + ",XUSDT", user_id=1)
    assert e.value.status_code == 422


def test_no_symbols_returns_all_tagged(pp):
    S.pump_badges(symbols=None, user_id=1)
    assert pp.calls[-1] == ["AAAUSDT", "BBBUSDT"]


def test_failopen_when_service_raises(pp, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("redis down")
    monkeypatch.setattr(pp, "badges_for", boom)

    def no_redis():
        raise RuntimeError("x")
    monkeypatch.setattr(S, "get_redis_client", no_redis)
    assert S.pump_badges(symbols="AAAUSDT", user_id=1) == {"at": None, "badges": {}}
