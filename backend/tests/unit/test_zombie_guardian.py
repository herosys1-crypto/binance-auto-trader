"""Zombie Guardian Phase 1/2 회귀 테스트.

배경: 6638177/6133072 commit 에서 좀비 6패턴 통합 처리 로직 도입.
이 테스트는 자동 회복 함수들의 동작과 escalation 안전망의 핵심 동작을 보장한다.

테스트 대상:
  - pre_pass_dedup           : 같은 (acc, sym, side) 중복 active → 최신만 남기고 STOPPED 강등
  - enforce_terminal_qty_zero: TERMINAL 상태에 qty != 0 → qty=0 강제
  - escalate_stuck_strategy  : N 사이클 stuck → 강제 STOPPED + Kill-Switch + Telegram

mock 전략: db 는 MagicMock, strategy 는 SimpleNamespace.
heavy 의존성 (AccountKillSwitchService, NotificationService) 은 monkeypatch 로 차단.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import zombie_guardian as zg


# ============================================================================
# pre_pass_dedup
# ============================================================================
class TestPrePassDedup:
    def _build_db(self, strategies: list[SimpleNamespace]) -> MagicMock:
        """db.execute(select(...).scalars().all() = strategies (id 내림차순으로 정렬됨 가정)."""
        db = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = strategies
        db.execute.return_value = result
        return db

    def test_no_active_strategies_returns_zero(self) -> None:
        db = self._build_db([])
        assert zg.pre_pass_dedup(db) == 0

    def test_single_active_per_key_no_demotion(self) -> None:
        s1 = SimpleNamespace(
            id=10, exchange_account_id=1, symbol="BTCUSDT", side="LONG",
            status="STAGE1_OPEN", current_position_qty=Decimal("0.5"), stopped_at=None,
        )
        s2 = SimpleNamespace(
            id=11, exchange_account_id=1, symbol="ETHUSDT", side="SHORT",
            status="STAGE2_OPEN", current_position_qty=Decimal("-1.0"), stopped_at=None,
        )
        db = self._build_db([s2, s1])  # id 내림차순
        demoted = zg.pre_pass_dedup(db)
        assert demoted == 0
        assert s1.status == "STAGE1_OPEN"
        assert s2.status == "STAGE2_OPEN"

    def test_duplicate_active_keeps_newest_demotes_older(self) -> None:
        # 같은 (1, BTCUSDT, LONG) 키 — id=11 이 최신이라 keep, id=9 가 older 라 demote
        keeper = SimpleNamespace(
            id=11, exchange_account_id=1, symbol="BTCUSDT", side="LONG",
            status="STAGE1_OPEN", current_position_qty=Decimal("0.5"), stopped_at=None,
        )
        zombie = SimpleNamespace(
            id=9, exchange_account_id=1, symbol="BTCUSDT", side="LONG",
            status="STAGE1_OPEN", current_position_qty=Decimal("0.3"), stopped_at=None,
        )
        # select 가 id desc 로 정렬해주므로 keeper 가 먼저 나와야 함
        db = self._build_db([keeper, zombie])
        demoted = zg.pre_pass_dedup(db)
        assert demoted == 1
        assert keeper.status == "STAGE1_OPEN"  # keeper 그대로
        assert keeper.current_position_qty == Decimal("0.5")
        assert zombie.status == "STOPPED"
        assert zombie.current_position_qty == Decimal("0")
        assert zombie.stopped_at is not None
        # RiskEvent 가 기록됐는지 (db.add 호출 1회)
        assert db.add.call_count == 1

    def test_multiple_keys_handled_independently(self) -> None:
        # (1, BTC, LONG) 에 2개, (1, ETH, SHORT) 에 2개 → 각 키마다 1개씩 demote
        btc_new = SimpleNamespace(
            id=20, exchange_account_id=1, symbol="BTCUSDT", side="LONG",
            status="STAGE1_OPEN", current_position_qty=Decimal("0.5"), stopped_at=None,
        )
        btc_old = SimpleNamespace(
            id=18, exchange_account_id=1, symbol="BTCUSDT", side="LONG",
            status="STAGE1_OPEN", current_position_qty=Decimal("0.3"), stopped_at=None,
        )
        eth_new = SimpleNamespace(
            id=19, exchange_account_id=1, symbol="ETHUSDT", side="SHORT",
            status="STAGE2_OPEN", current_position_qty=Decimal("-1.0"), stopped_at=None,
        )
        eth_old = SimpleNamespace(
            id=15, exchange_account_id=1, symbol="ETHUSDT", side="SHORT",
            status="STAGE2_OPEN", current_position_qty=Decimal("-0.8"), stopped_at=None,
        )
        db = self._build_db([btc_new, eth_new, btc_old, eth_old])  # id desc 순
        demoted = zg.pre_pass_dedup(db)
        assert demoted == 2
        assert btc_new.status == "STAGE1_OPEN"
        assert eth_new.status == "STAGE2_OPEN"
        assert btc_old.status == "STOPPED"
        assert eth_old.status == "STOPPED"
        assert db.add.call_count == 2

    def test_different_account_same_symbol_not_dedup(self) -> None:
        # 다른 계정 (acc 1 vs acc 2) 이면 같은 symbol/side 도 별개 — demote 안 함
        a1 = SimpleNamespace(
            id=30, exchange_account_id=1, symbol="BTCUSDT", side="LONG",
            status="STAGE1_OPEN", current_position_qty=Decimal("0.5"), stopped_at=None,
        )
        a2 = SimpleNamespace(
            id=29, exchange_account_id=2, symbol="BTCUSDT", side="LONG",
            status="STAGE1_OPEN", current_position_qty=Decimal("0.7"), stopped_at=None,
        )
        db = self._build_db([a1, a2])
        demoted = zg.pre_pass_dedup(db)
        assert demoted == 0
        assert a1.status == "STAGE1_OPEN"
        assert a2.status == "STAGE1_OPEN"

    def test_preserves_existing_stopped_at(self) -> None:
        existing_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        keeper = SimpleNamespace(
            id=40, exchange_account_id=1, symbol="BTCUSDT", side="LONG",
            status="STAGE1_OPEN", current_position_qty=Decimal("0.5"), stopped_at=None,
        )
        zombie = SimpleNamespace(
            id=39, exchange_account_id=1, symbol="BTCUSDT", side="LONG",
            status="STAGE1_OPEN", current_position_qty=Decimal("0.3"),
            stopped_at=existing_ts,  # 이미 stopped_at 있음
        )
        db = self._build_db([keeper, zombie])
        zg.pre_pass_dedup(db)
        # stopped_at 이 이미 있으면 덮어쓰지 않음 (코드의 `if not s.stopped_at` 가드)
        assert zombie.stopped_at == existing_ts


# ============================================================================
# enforce_terminal_qty_zero
# ============================================================================
class TestEnforceTerminalQtyZero:
    def _build_db(self, strategies: list[SimpleNamespace]) -> MagicMock:
        db = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = strategies
        db.execute.return_value = result
        return db

    def test_no_terminal_strategies_returns_zero(self) -> None:
        db = self._build_db([])
        assert zg.enforce_terminal_qty_zero(db) == 0

    def test_terminal_with_zero_qty_no_change(self) -> None:
        s = SimpleNamespace(
            id=50, symbol="BTCUSDT", side="LONG",
            status="STOPPED", current_position_qty=Decimal("0"),
        )
        db = self._build_db([s])
        fixed = zg.enforce_terminal_qty_zero(db)
        assert fixed == 0
        assert s.current_position_qty == Decimal("0")
        assert db.add.call_count == 0  # RiskEvent 안 남김

    def test_terminal_with_residual_qty_resets_to_zero(self) -> None:
        # #83 XNYUSDT 사례 — STOPPED 인데 qty=-60842 잔재
        s = SimpleNamespace(
            id=83, symbol="XNYUSDT", side="SHORT",
            status="STOPPED", current_position_qty=Decimal("-60842"),
        )
        db = self._build_db([s])
        fixed = zg.enforce_terminal_qty_zero(db)
        assert fixed == 1
        assert s.current_position_qty == Decimal("0")
        assert db.add.call_count == 1

    def test_multiple_terminal_with_residual_all_fixed(self) -> None:
        a = SimpleNamespace(
            id=51, symbol="A", side="LONG",
            status="COMPLETED", current_position_qty=Decimal("10"),
        )
        b = SimpleNamespace(
            id=52, symbol="B", side="SHORT",
            status="REENTRY_READY", current_position_qty=Decimal("-5"),
        )
        c_ok = SimpleNamespace(
            id=53, symbol="C", side="LONG",
            status="STOPPED", current_position_qty=Decimal("0"),
        )
        db = self._build_db([a, b, c_ok])
        fixed = zg.enforce_terminal_qty_zero(db)
        assert fixed == 2
        assert a.current_position_qty == Decimal("0")
        assert b.current_position_qty == Decimal("0")
        assert c_ok.current_position_qty == Decimal("0")
        assert db.add.call_count == 2  # ok 인 c 는 RiskEvent 안 남김

    def test_none_qty_treated_as_zero(self) -> None:
        s = SimpleNamespace(
            id=54, symbol="X", side="LONG",
            status="STOPPED", current_position_qty=None,
        )
        db = self._build_db([s])
        fixed = zg.enforce_terminal_qty_zero(db)
        # None → Decimal("0") → continue (no change)
        assert fixed == 0


# ============================================================================
# escalate_stuck_strategy
# ============================================================================
class TestEscalateStuckStrategy:
    def test_force_stops_strategy_and_triggers_kill_switch(self, monkeypatch) -> None:
        """N 사이클 stuck 좀비 → STOPPED + qty=0 + Kill-Switch + Telegram."""
        kill_calls: list[dict] = []
        notif_calls: list[dict] = []

        class _FakeKillSwitch:
            def __init__(self, db) -> None:
                pass

            def trigger(self, *, exchange_account_id, reason_code, reason_message) -> None:
                kill_calls.append({
                    "account_id": exchange_account_id,
                    "reason_code": reason_code,
                    "reason_message": reason_message,
                })

        class _FakeNotif:
            def __init__(self, db) -> None:
                pass

            def send_system_alert(self, *, title, body) -> None:
                notif_calls.append({"title": title, "body": body})

        monkeypatch.setattr(zg, "AccountKillSwitchService", _FakeKillSwitch)
        monkeypatch.setattr(zg, "NotificationService", _FakeNotif)

        strategy = SimpleNamespace(
            id=89,
            exchange_account_id=1,
            symbol="LABUSDT",
            side="SHORT",
            status="STOPPING",
            current_position_qty=Decimal("-450"),
            stopped_at=None,
        )
        db = MagicMock()

        zg.escalate_stuck_strategy(
            db,
            strategy,
            reason_code="PENDING_STUCK_NO_EXCHANGE_POSITION",
            reason_detail="5 cycles 연속 거래소 매칭 없음",
            exchange_snapshot=None,
        )

        # strategy 강제 STOPPED + qty=0 + stopped_at 채움
        assert strategy.status == "STOPPED"
        assert strategy.current_position_qty == Decimal("0")
        assert strategy.stopped_at is not None

        # CRITICAL RiskEvent 추가
        assert db.add.call_count == 1

        # Kill-Switch 발동
        assert len(kill_calls) == 1
        assert kill_calls[0]["account_id"] == 1
        assert kill_calls[0]["reason_code"].startswith("ZOMBIE:")

        # Telegram 알림
        assert len(notif_calls) == 1
        assert "좀비" in notif_calls[0]["title"]
        assert "#89" in notif_calls[0]["title"]

    def test_with_exchange_snapshot_includes_in_alert(self, monkeypatch) -> None:
        """exchange_snapshot 이 있으면 Telegram body 에 거래소 실제 포지션 포함."""
        notif_calls: list[dict] = []

        class _FakeKillSwitch:
            def __init__(self, db) -> None: pass
            def trigger(self, **kw) -> None: pass

        class _FakeNotif:
            def __init__(self, db) -> None: pass
            def send_system_alert(self, *, title, body) -> None:
                notif_calls.append({"title": title, "body": body})

        monkeypatch.setattr(zg, "AccountKillSwitchService", _FakeKillSwitch)
        monkeypatch.setattr(zg, "NotificationService", _FakeNotif)

        strategy = SimpleNamespace(
            id=92, exchange_account_id=1, symbol="BABYUSDT", side="SHORT",
            status="TP3_DONE_PARTIAL", current_position_qty=Decimal("-860"), stopped_at=None,
        )
        snapshot = {
            "positionAmt": "-860",
            "entryPrice": "0.05",
            "markPrice": "0.048",
            "unRealizedProfit": "1.72",
        }

        zg.escalate_stuck_strategy(
            MagicMock(),
            strategy,
            reason_code="QTY_MISMATCH_PERSISTENT",
            reason_detail="5 cycles 연속 qty 불일치",
            exchange_snapshot=snapshot,
        )

        assert len(notif_calls) == 1
        body = notif_calls[0]["body"]
        assert "거래소 실제 포지션 스냅샷" in body
        assert "-860" in body  # positionAmt 노출
        assert "0.05" in body  # entryPrice

    def test_kill_switch_failure_does_not_block_escalation(self, monkeypatch) -> None:
        """Kill-Switch 가 예외를 던져도 strategy 상태 변경 + RiskEvent + 알림은 수행."""
        notif_calls: list[dict] = []

        class _FakeKillSwitch:
            def __init__(self, db) -> None: pass
            def trigger(self, **kw) -> None:
                raise RuntimeError("kill switch DB 장애")

        class _FakeNotif:
            def __init__(self, db) -> None: pass
            def send_system_alert(self, *, title, body) -> None:
                notif_calls.append({"title": title, "body": body})

        monkeypatch.setattr(zg, "AccountKillSwitchService", _FakeKillSwitch)
        monkeypatch.setattr(zg, "NotificationService", _FakeNotif)

        strategy = SimpleNamespace(
            id=99, exchange_account_id=1, symbol="X", side="LONG",
            status="STAGE1_OPEN", current_position_qty=Decimal("1"), stopped_at=None,
        )

        # 예외가 새어나오지 않아야 함
        zg.escalate_stuck_strategy(
            MagicMock(),
            strategy,
            reason_code="X",
            reason_detail="Y",
        )

        # strategy 상태 변경은 적용
        assert strategy.status == "STOPPED"
        assert strategy.current_position_qty == Decimal("0")
        # 알림은 여전히 발송 (kill-switch 실패와 독립)
        assert len(notif_calls) == 1

    def test_notif_failure_does_not_raise(self, monkeypatch) -> None:
        """Telegram 알림이 실패해도 escalate 자체는 완료."""
        class _FakeKillSwitch:
            def __init__(self, db) -> None: pass
            def trigger(self, **kw) -> None: pass

        class _FakeNotif:
            def __init__(self, db) -> None: pass
            def send_system_alert(self, **kw) -> None:
                raise RuntimeError("Telegram down")

        monkeypatch.setattr(zg, "AccountKillSwitchService", _FakeKillSwitch)
        monkeypatch.setattr(zg, "NotificationService", _FakeNotif)

        strategy = SimpleNamespace(
            id=100, exchange_account_id=1, symbol="X", side="LONG",
            status="STAGE1_OPEN", current_position_qty=Decimal("1"), stopped_at=None,
        )
        # 예외 없이 완료
        zg.escalate_stuck_strategy(
            MagicMock(), strategy,
            reason_code="X", reason_detail="Y",
        )
        assert strategy.status == "STOPPED"

    def test_preserves_existing_stopped_at(self, monkeypatch) -> None:
        """이미 stopped_at 가 있으면 덮어쓰지 않음."""
        class _Fake:
            def __init__(self, db) -> None: pass
            def trigger(self, **kw) -> None: pass
            def send_system_alert(self, **kw) -> None: pass

        monkeypatch.setattr(zg, "AccountKillSwitchService", _Fake)
        monkeypatch.setattr(zg, "NotificationService", _Fake)

        existing_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        strategy = SimpleNamespace(
            id=101, exchange_account_id=1, symbol="X", side="LONG",
            status="STAGE1_OPEN", current_position_qty=Decimal("1"),
            stopped_at=existing_ts,
        )
        zg.escalate_stuck_strategy(
            MagicMock(), strategy,
            reason_code="X", reason_detail="Y",
        )
        assert strategy.stopped_at == existing_ts  # 보존
