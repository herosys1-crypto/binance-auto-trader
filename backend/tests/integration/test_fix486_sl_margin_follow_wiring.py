"""🛡 Fix 486 — `evaluate_stop_loss` 가 증거금 추가를 실제로 따라가는가 (DB 연결 검증).

사장님 (2026-11-11): "증거금을 넣으면 손절선도 따라 내려가게" · "운영중인 인스턴스도 모두 같이 적용되게 해줘"

LONG 평단 100 · 레버 2 · 손절 100% · 수량 10 → 초기 증거금 M0 = 500, 옛 손절가 50.
증거금 100 추가(기록 + 거래소 지갑 600) · 거래소 청산가 42 → 유효 손절 −120%(가격 40), 가드 42 × 1.03 = 43.26.
  · 48 (ROI −104%)  : 옛 규칙이면 손절 → 이제 **버틴다**
  · 43 (ROI −114%)  : 가드선(43.26) 아래 → **손절** (거래소 청산 42 보다 먼저)
기록이 없거나 스냅샷이 오래됐으면 옛 규칙 그대로 48 에서 손절한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.position import Position
from app.models.risk_event import RiskEvent


@pytest.fixture
def mark(monkeypatch):
    box = {"price": None}
    import app.services.mark_price_cache as M
    monkeypatch.setattr(M, "get_mark_price", lambda _sym: box["price"])
    return box


def _strategy(make_user, make_exchange_account, make_symbol, make_template, make_strategy):
    u = make_user()
    ea = make_exchange_account(user=u)
    make_symbol("BTCUSDT")
    tpl = make_template(stages_config={"capitals": ["100"] * 3}, stop_loss_percent_of_capital=Decimal("100"))
    return make_strategy(
        user=u, exchange_account=ea, template=tpl, side="LONG", current_stage=3,
        total_capital=Decimal("600"), leverage=2, avg_entry_price=Decimal("100"),
        current_position_qty=Decimal("10"), realized_pnl=Decimal("0"), unrealized_pnl=Decimal("0"),
    )


def _add_margin_event(db, s, amount="100"):
    db.add(RiskEvent(strategy_instance_id=s.id, event_type="ADD_MARGIN_SUCCESS", severity="INFO",
                     title="🛡 증거금 추가 완료", message="x", event_payload={"amount": amount}))
    db.commit()


def _snapshot(db, s, *, mark, wallet=Decimal("600"), liq=Decimal("42"), age_sec=10, margin_type="isolated",
              source="POSITION_RISK_SYNC"):
    upnl = (Decimal(str(mark)) - Decimal("100")) * Decimal("10")
    db.add(Position(
        strategy_instance_id=s.id, symbol=s.symbol, side="LONG", position_side="LONG",
        entry_price=Decimal("100"), mark_price=Decimal(str(mark)), liquidation_price=liq,
        position_amt=Decimal("10"), isolated_margin=wallet + upnl, unrealized_pnl=upnl,
        margin_type=margin_type, leverage=2, source=source,
        snapshot_time=datetime.now(timezone.utc) - timedelta(seconds=age_sec),
    ))
    db.commit()


def _check(db, mark, s, price):
    from app.services.risk_service import RiskService
    mark["price"] = price
    return RiskService(db).evaluate_stop_loss(s.id)


def test_follows_added_margin_then_stops_at_liq_guard(db_session, mark, make_user, make_exchange_account,
                                                      make_symbol, make_template, make_strategy):
    s = _strategy(make_user, make_exchange_account, make_symbol, make_template, make_strategy)
    _add_margin_event(db_session, s)
    _snapshot(db_session, s, mark=48)
    assert _check(db_session, mark, s, 48) is False, "옛 손절가(50) 아래 48 — 증거금 100 을 넣었으니 버틴다"
    _snapshot(db_session, s, mark=43)
    assert _check(db_session, mark, s, 43) is True, "청산가 42 의 3% 위(43.26)에 닿음 → 거래소 청산 전에 손절"
    ev = db_session.query(RiskEvent).filter_by(strategy_instance_id=s.id, event_type="STOP_LOSS_TRIGGERED").one()
    assert ev.event_payload["margin_follow"]["applied"] is True
    assert ev.event_payload["margin_follow"]["guard_hit"] is True
    assert "Fix 486" in ev.message


def test_no_recorded_add_keeps_old_rule(db_session, mark, make_user, make_exchange_account,
                                        make_symbol, make_template, make_strategy):
    """거래소 지갑이 커 보여도 DB 에 「증거금 추가」 기록이 없으면 넓히지 않는다."""
    s = _strategy(make_user, make_exchange_account, make_symbol, make_template, make_strategy)
    _snapshot(db_session, s, mark=48)
    assert _check(db_session, mark, s, 48) is True


def test_stale_snapshot_keeps_old_rule(db_session, mark, make_user, make_exchange_account,
                                       make_symbol, make_template, make_strategy):
    s = _strategy(make_user, make_exchange_account, make_symbol, make_template, make_strategy)
    _add_margin_event(db_session, s)
    _snapshot(db_session, s, mark=48, age_sec=3600)
    assert _check(db_session, mark, s, 48) is True, "스냅샷이 1시간 전 — 청산 가드를 믿을 수 없으니 옛 규칙"


def test_switch_off_restores_old_rule(db_session, mark, make_user, make_exchange_account,
                                      make_symbol, make_template, make_strategy):
    from app.services import sl_margin_follow as F
    from app.services.system_settings_service import SystemSettingsService
    s = _strategy(make_user, make_exchange_account, make_symbol, make_template, make_strategy)
    _add_margin_event(db_session, s)
    _snapshot(db_session, s, mark=48)
    SystemSettingsService(db_session).set(F.S_ENABLED, "0", description="test")
    db_session.commit()
    assert _check(db_session, mark, s, 48) is True, "스위치를 끄면 옛 규칙으로 돌아간다"


def test_above_old_line_untouched(db_session, mark, make_user, make_exchange_account,
                                  make_symbol, make_template, make_strategy):
    """옛 손절선 위에서는 아무 영향이 없다 (증거금 추가가 손절을 앞당기지 않는다)."""
    s = _strategy(make_user, make_exchange_account, make_symbol, make_template, make_strategy)
    _add_margin_event(db_session, s)
    _snapshot(db_session, s, mark=60, liq=Decimal("59"))      # 가드선(60.77) 안쪽이지만 옛 손절선(50) 위
    assert _check(db_session, mark, s, 60) is False


def test_stream_snapshot_is_ignored(db_session, mark, make_user, make_exchange_account,
                                    make_symbol, make_template, make_strategy):
    """사용자 스트림(ACCOUNT_UPDATE) 스냅샷은 isolated_margin 칸이 「격리지갑」이라 뜻이 다르다 — 쓰지 않는다.

    증거금 추가 기록은 있지만 거래소 지갑에는 추가분이 없는 상황(지갑 500 = 초기 증거금)에서
    스트림 스냅샷(iw=500, up=−520)을 동기화 스냅샷처럼 읽으면 W = 500 − (−520) = 1,020 으로 부풀어
    「추가분 520」으로 잘못 넓어진다. 동기화 스냅샷이 없으니 옛 규칙(48 에서 손절)이어야 한다."""
    s = _strategy(make_user, make_exchange_account, make_symbol, make_template, make_strategy)
    _add_margin_event(db_session, s)
    db_session.add(Position(
        strategy_instance_id=s.id, symbol=s.symbol, side="LONG", position_side="LONG",
        entry_price=Decimal("100"), mark_price=Decimal("48"), liquidation_price=Decimal("42"),
        position_amt=Decimal("10"), isolated_margin=Decimal("500"), unrealized_pnl=Decimal("-520"),
        margin_type="isolated", leverage=2, source="ACCOUNT_UPDATE",
        snapshot_time=datetime.now(timezone.utc) - timedelta(seconds=5),
    ))
    db_session.commit()
    assert _check(db_session, mark, s, 48) is True


def test_newer_stream_snapshot_does_not_hide_sync_snapshot(db_session, mark, make_user, make_exchange_account,
                                                           make_symbol, make_template, make_strategy):
    """동기화 스냅샷 뒤에 스트림 스냅샷이 더 최근으로 쌓여도, 신선한 동기화 스냅샷으로 판정한다."""
    s = _strategy(make_user, make_exchange_account, make_symbol, make_template, make_strategy)
    _add_margin_event(db_session, s)
    _snapshot(db_session, s, mark=48, age_sec=60)
    _snapshot(db_session, s, mark=48, age_sec=5, wallet=Decimal("9999"), liq=Decimal("1"), source="ACCOUNT_UPDATE")
    assert _check(db_session, mark, s, 48) is False, "동기화 스냅샷(지갑 600·청산가 42) 기준으로 버틴다"
    _snapshot(db_session, s, mark=43, age_sec=30)
    _snapshot(db_session, s, mark=43, age_sec=5, wallet=Decimal("9999"), liq=Decimal("1"), source="ACCOUNT_UPDATE")
    assert _check(db_session, mark, s, 43) is True, "스트림 스냅샷의 청산가 1 이 아니라 동기화의 42 로 가드"
