"""GET /symbols/whitelist-info — UI 가 화이트리스트 상태 표시용 (사용자 요청 2026-05-07)."""
from __future__ import annotations

from app.api.v1.symbols import get_whitelist_info


class TestWhitelistInfo:
    def test_disabled_when_csv_empty(self, db_session, make_user, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.allowed_symbols_csv", None, raising=False)
        u = make_user()
        resp = get_whitelist_info(db=db_session, user_id=u.id)
        assert resp.enabled is False
        assert resp.allowed_symbols == []

    def test_enabled_with_csv(self, db_session, make_user, monkeypatch):
        monkeypatch.setattr(
            "app.core.config.settings.allowed_symbols_csv",
            "BTCUSDT,ETHUSDT", raising=False,
        )
        u = make_user()
        resp = get_whitelist_info(db=db_session, user_id=u.id)
        assert resp.enabled is True
        assert resp.allowed_symbols == ["BTCUSDT", "ETHUSDT"]

    def test_csv_normalizes_case_and_whitespace(self, db_session, make_user, monkeypatch):
        monkeypatch.setattr(
            "app.core.config.settings.allowed_symbols_csv",
            " btcusdt , ETHUSDT,, doge ", raising=False,
        )
        u = make_user()
        resp = get_whitelist_info(db=db_session, user_id=u.id)
        assert resp.enabled is True
        # 정렬 + 대문자 정규화
        assert resp.allowed_symbols == ["BTCUSDT", "DOGE", "ETHUSDT"]
