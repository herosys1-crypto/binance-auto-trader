"""Fix 422 — 화면 급등락 스캔 종목 수를 서버에서 30 으로 강제 (사장님 10/05).

옛 화면 탭(새로고침 안 함)이 max_symbols=60 을 계속 보내 분당 ~125 weight 를 썼다.
"""
from __future__ import annotations

import json

import pytest

from app.api.v1 import live_pump_dump as L


class SpyRedis:
    def __init__(self):
        self.keys = []

    def get(self, key):
        self.keys.append(key)
        return json.dumps({"alerts": []})        # 캐시 적중 → 거래소 호출 없이 바로 반환


@pytest.mark.parametrize("asked, used", [(60, 30), (150, 30), (30, 30), (20, 20), (10, 10)])
def test_server_caps_symbols(monkeypatch, asked, used):
    spy = SpyRedis()
    import app.core.redis_client as RC
    monkeypatch.setattr(RC, "get_redis_client", lambda: spy)
    out = L.scan_live_pump_dump(max_symbols=asked, include_dump=True, min_confidence=0.85, db=None, user_id=1)
    assert out.get("cached") is True
    assert spy.keys == [f"live_pump_dump:scan:{used}:1:0.85"]   # 옛 탭(60)과 새 탭(30)이 같은 캐시를 공유


def test_cap_constant_is_owner_value():
    assert L.LIVE_SCAN_MAX_SYMBOLS == 30
