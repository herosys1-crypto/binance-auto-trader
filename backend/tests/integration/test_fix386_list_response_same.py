"""⚡ Fix 386b — 캐시한 JSON/gzip 응답이 FastAPI response_model 직렬화와 **똑같은지** (화면이 받는 내용 불변)."""
from __future__ import annotations

import gzip
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_cached_bytes_equal_fastapi_response_model(db_session, make_user, make_exchange_account, make_symbol,
                                                   make_template, make_strategy):
    from app.api.v1.strategies.crud import list_strategies
    from app.schemas.strategy import StrategyDetailResponse
    from app.services import strategy_list_cache as LC

    u = make_user()
    ea = make_exchange_account(user=u)
    tpl = make_template()
    for i in range(3):
        sym = f"EQ{i}USDT"
        make_strategy(user=u, exchange_account=ea, template=tpl, symbol_obj=make_symbol(sym), symbol_str=sym)
    items = list_strategies(db=db_session, user_id=u.id)
    assert len(items) == 3

    app = FastAPI()

    @app.get("/x", response_model=list[StrategyDetailResponse])
    def _x():
        return items
    want = TestClient(app).get("/x").json()            # 예전 방식 = FastAPI 가 response_model 로 직렬화

    raw, gz = LC.encode(items)
    assert json.loads(raw) == want
    assert gzip.decompress(gz) == raw


def test_endpoint_returns_gzip_only_when_accepted(db_session, make_user, make_exchange_account, make_symbol,
                                                  make_template, make_strategy):
    from starlette.requests import Request
    from app.api.v1.strategies.crud import list_strategies_endpoint
    from app.services import strategy_list_cache as LC

    LC.invalidate()
    u = make_user()
    ea = make_exchange_account(user=u)
    make_strategy(user=u, exchange_account=ea, template=make_template(), symbol_obj=make_symbol("GZUSDT"),
                  symbol_str="GZUSDT")

    def req(enc):
        return Request({"type": "http", "headers": [(b"accept-encoding", enc.encode())] if enc else []})
    r1 = list_strategies_endpoint(req("gzip, deflate, br"), db=db_session, user_id=u.id)
    assert r1.headers["content-encoding"] == "gzip" and "accept-encoding" in r1.headers["vary"].lower()
    r2 = list_strategies_endpoint(req(""), db=db_session, user_id=u.id)
    assert "content-encoding" not in r2.headers
    assert json.loads(gzip.decompress(r1.body)) == json.loads(r2.body)
    assert LC.STATS["hit"] >= 1                          # 두 번째는 캐시
