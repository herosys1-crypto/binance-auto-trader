"""GET /api/v1/positions/external — 외부 포지션 가시성 (사장님 요구 2026-05-21).

배경 (#77 PHB +157 / RONIN +26 후속):
  사장님이 거래소에서 직접 진입한 포지션이 대시보드에 안 보여서 운영 인지 못 함.
  이제 active strategy 가 추적 안 하는 거래소 포지션을 별도 목록으로 반환.

테스트 시나리오:
  1. 추적 중인 포지션은 결과에서 제외 (도구 안)
  2. 추적 안 되는 포지션은 결과에 포함 (도구 밖)
  3. positionAmt=0 (flat) 인 거래소 응답은 제외
  4. 다른 사용자 계정은 제외 (multi-user 안전성)
  5. 거래소 호출 실패한 계정은 silent skip (다른 계정 정상 반환)
  6. is_archived = True strategy 는 「추적 중」 으로 안 봄 → 같은 symbol+side 외부 포지션 표시
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.positions import list_external_positions
from app.core.crypto import encrypt_text


@pytest.fixture(autouse=True)
def _stub_decrypt(monkeypatch):
    """decrypt_text 가 enc:xxx 같은 fake 값도 그대로 반환하도록 stub."""
    monkeypatch.setattr(
        "app.api.v1.positions.decrypt_text", lambda enc: enc,
    )


def _stub_binance_client(monkeypatch, *, position_risk_by_account: dict[int, list[dict]],
                         failing_accounts: set[int] | None = None):
    """BinanceClient 를 fake 로 교체 — account 별 응답 시뮬."""
    failing = failing_accounts or set()

    class _FakeClient:
        def __init__(self, *, api_key, api_secret, is_testnet):
            # api_key 가 enc:apikey:{acc_id} 패턴이라 가정 — 그것으로 account 식별
            # 테스트에서는 monkey patch 로 _account_id_for 직접 set
            self.api_key = api_key
            self.is_testnet = is_testnet

        def get_position_risk(self, symbol=None):
            acc_id = _FakeClient._lookup_acc_id(self.api_key)
            if acc_id in failing:
                raise Exception(f"network error account={acc_id}")
            return list(position_risk_by_account.get(acc_id, []))

        @staticmethod
        def _lookup_acc_id(api_key: str) -> int:
            # `enc:apikey:{acc_id}` 형식에서 acc_id 추출 (테스트용)
            try:
                return int(api_key.rsplit(":", 1)[-1])
            except ValueError:
                return 0

    monkeypatch.setattr("app.api.v1.positions.BinanceClient", _FakeClient)
    return _FakeClient


def _mk_position(symbol: str, side: str, amt: str, *, entry="0", mark="0",
                 pnl="0", lev="10", margin="cross", liq="0") -> dict:
    return {
        "symbol": symbol, "positionSide": side, "positionAmt": amt,
        "entryPrice": entry, "markPrice": mark, "unRealizedProfit": pnl,
        "leverage": lev, "marginType": margin, "liquidationPrice": liq,
    }


class TestListExternalPositions:
    def test_tracked_positions_excluded(
        self, db_session, make_strategy, make_user, make_exchange_account, monkeypatch,
    ):
        """ACTIVE strategy 가 추적 중인 symbol+side 는 외부 목록에서 제외."""
        u = make_user()
        ea = make_exchange_account(
            user=u, api_key_enc=f"enc:apikey:{u.id * 10 + 1}",
            api_secret_enc="enc:secret",
        )
        # acc.id 가 위 api_key 의 마지막 숫자와 일치하도록 stub
        # — 테스트 fixture 의 acc.id 는 실제 DB 의 값이므로 그것을 사용
        # → BinanceClient stub 이 api_key 에서 acc_id 추출
        # 실제 acc.id 로 다시 stub 갱신:
        ea.api_key_enc = f"enc:apikey:{ea.id}"
        db_session.commit()

        # 도구가 추적 중: BTCUSDT LONG
        make_strategy(
            symbol_str="BTCUSDT", side="LONG", status="STAGE1_OPEN",
            current_position_qty=Decimal("0.5"),
            user=u, exchange_account=ea,
        )

        # 거래소 응답: BTCUSDT LONG (추적) + ETHUSDT SHORT (외부)
        _stub_binance_client(monkeypatch, position_risk_by_account={
            ea.id: [
                _mk_position("BTCUSDT", "LONG", "0.5", entry="50000", mark="51000", pnl="500"),
                _mk_position("ETHUSDT", "SHORT", "-1.0", entry="3000", mark="2900", pnl="100"),
            ],
        })

        result = list_external_positions(db=db_session, user_id=u.id)

        # ETHUSDT SHORT 만 외부로 분류
        assert len(result) == 1
        assert result[0].symbol == "ETHUSDT"
        assert result[0].side == "SHORT"
        assert result[0].position_amt == Decimal("-1.0")
        assert result[0].unrealized_pnl == Decimal("100")

    def test_flat_positions_excluded(
        self, db_session, make_user, make_exchange_account, monkeypatch,
    ):
        """positionAmt=0 (flat) 인 응답은 외부 포지션 아님 — 제외."""
        u = make_user()
        ea = make_exchange_account(user=u)
        ea.api_key_enc = f"enc:apikey:{ea.id}"
        db_session.commit()

        _stub_binance_client(monkeypatch, position_risk_by_account={
            ea.id: [
                _mk_position("BTCUSDT", "LONG", "0"),
                _mk_position("ETHUSDT", "SHORT", "0"),
                _mk_position("PHBUSDT", "LONG", "1000", mark="0.06"),  # 진짜 외부
            ],
        })

        result = list_external_positions(db=db_session, user_id=u.id)
        assert len(result) == 1
        assert result[0].symbol == "PHBUSDT"

    def test_other_user_accounts_excluded(
        self, db_session, make_user, make_exchange_account, monkeypatch,
    ):
        """다른 사용자 계정의 포지션은 결과에서 제외 (multi-user 안전성)."""
        u1 = make_user()
        u2 = make_user()
        ea1 = make_exchange_account(user=u1)
        ea2 = make_exchange_account(user=u2)
        ea1.api_key_enc = f"enc:apikey:{ea1.id}"
        ea2.api_key_enc = f"enc:apikey:{ea2.id}"
        db_session.commit()

        _stub_binance_client(monkeypatch, position_risk_by_account={
            ea1.id: [_mk_position("BTCUSDT", "LONG", "0.1")],
            ea2.id: [_mk_position("ETHUSDT", "SHORT", "-1.0")],
        })

        # u1 으로 호출 — ea1 의 포지션만 보여야
        result = list_external_positions(db=db_session, user_id=u1.id)
        assert len(result) == 1
        assert result[0].symbol == "BTCUSDT"
        assert result[0].account_id == ea1.id

    def test_failing_account_silent_skip(
        self, db_session, make_user, make_exchange_account, monkeypatch,
    ):
        """거래소 호출 실패한 계정은 silent skip — 다른 계정 정상 반환."""
        u = make_user()
        ea1 = make_exchange_account(user=u)
        ea2 = make_exchange_account(user=u)
        ea1.api_key_enc = f"enc:apikey:{ea1.id}"
        ea2.api_key_enc = f"enc:apikey:{ea2.id}"
        db_session.commit()

        _stub_binance_client(
            monkeypatch,
            position_risk_by_account={
                ea1.id: [_mk_position("BTCUSDT", "LONG", "0.5")],
                ea2.id: [_mk_position("ETHUSDT", "SHORT", "-1.0")],
            },
            failing_accounts={ea1.id},
        )

        # 예외 발생 안 함 (ea1 silent skip) + ea2 만 반환
        result = list_external_positions(db=db_session, user_id=u.id)
        assert len(result) == 1
        assert result[0].symbol == "ETHUSDT"

    def test_archived_strategy_not_treated_as_tracked(
        self, db_session, make_strategy, make_user, make_exchange_account, monkeypatch,
    ):
        """is_archived=True strategy 는 추적 중 아님 — 같은 symbol+side 외부 포지션 표시."""
        u = make_user()
        ea = make_exchange_account(user=u)
        ea.api_key_enc = f"enc:apikey:{ea.id}"
        db_session.commit()

        # archived strategy — 도구가 더 이상 추적 안 함
        make_strategy(
            symbol_str="OLDUSDT", side="LONG", status="STAGE1_OPEN",
            current_position_qty=Decimal("100"),
            user=u, exchange_account=ea,
            is_archived=True,
        )

        _stub_binance_client(monkeypatch, position_risk_by_account={
            ea.id: [_mk_position("OLDUSDT", "LONG", "100", mark="1.0")],
        })

        result = list_external_positions(db=db_session, user_id=u.id)
        assert len(result) == 1
        assert result[0].symbol == "OLDUSDT"

    def test_no_accounts_returns_empty(
        self, db_session, make_user, monkeypatch,
    ):
        """사용자가 active 계정 없으면 빈 리스트 (거래소 호출 X)."""
        u = make_user()
        # exchange account 안 만듦

        called = {"n": 0}
        class _ShouldNotCall:
            def __init__(self, *a, **kw): called["n"] += 1
            def get_position_risk(self, symbol=None): called["n"] += 1; return []
        monkeypatch.setattr("app.api.v1.positions.BinanceClient", _ShouldNotCall)

        result = list_external_positions(db=db_session, user_id=u.id)
        assert result == []
        assert called["n"] == 0  # 거래소 호출 안 함

    def test_response_fields_populated(
        self, db_session, make_user, make_exchange_account, monkeypatch,
    ):
        """ExternalPositionResponse 모든 필드가 정확히 채워지는지."""
        u = make_user()
        ea = make_exchange_account(user=u, is_testnet=False)
        ea.api_key_enc = f"enc:apikey:{ea.id}"
        db_session.commit()

        _stub_binance_client(monkeypatch, position_risk_by_account={
            ea.id: [_mk_position(
                "PHBUSDT", "LONG", "1000",
                entry="0.06", mark="0.072", pnl="12",
                lev="10", margin="isolated", liq="0.05",
            )],
        })

        result = list_external_positions(db=db_session, user_id=u.id)
        assert len(result) == 1
        p = result[0]
        assert p.account_id == ea.id
        assert "mainnet" in p.account_label
        assert p.symbol == "PHBUSDT"
        assert p.side == "LONG"
        assert p.position_amt == Decimal("1000")
        assert p.entry_price == Decimal("0.06")
        assert p.mark_price == Decimal("0.072")
        assert p.unrealized_pnl == Decimal("12")
        assert p.leverage == 10
        assert p.margin_type == "isolated"
        assert p.liquidation_price == Decimal("0.05")
