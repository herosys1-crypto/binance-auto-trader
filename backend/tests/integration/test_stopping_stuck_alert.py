"""STOPPING 갇힘 5분 초과 감지 + 텔레그램 CRITICAL 알림 — 회귀 방지.

배경 (2026-05-21, 사장님 #77 PHB / #78 RONIN 사례):
  emergency_close 가 거래소에서 거절돼 strategy.status="STOPPING" 으로 고정되는
  케이스. reconcile 의 matched 분기는 positionAmt != 0 인 STOPPING 을 자동
  정리하지 못함 (= 정상 — 거래소에 실 포지션이 있으므로 강제 STOPPED 마킹 X).
  그 사이 `_NOT_FOR_TP_SL` 필터에 TP/SL 평가도 막힘 → PHB 가 +20% (TP3) 임계점
  지나갔는데도 미발동 → 결국 -24 회귀 (피크 +359 → -24, ~$384 손실).

본 가드:
  - reconcile 매 사이클 STOPPING + updated_at 5분 초과 strategy 스캔
  - 사장님이 즉시 인지하도록 텔레그램 CRITICAL + RiskEvent CRITICAL 발송
  - 같은 strategy 30분 cooldown (Redis) — spam 차단

테스트 시나리오:
  1. STOPPING 5분 안 지남 → 알림 없음
  2. STOPPING 5분 초과 → 텔레그램 + RiskEvent CRITICAL 발송
  3. 같은 strategy 두 사이클 → cooldown 으로 두 번째 사이클은 skip
  4. STOPPING 외 status (STAGE1_OPEN 등) → 알림 없음 (5분 지나도 무관)
  5. is_archived → skip (사장님이 이미 정리한 것)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.models.notification import Notification
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.workers.reconcile_worker import (
    STOPPING_STUCK_ALERT_COOLDOWN_SECONDS,
    STOPPING_STUCK_ALERT_REDIS_PREFIX,
    STOPPING_STUCK_THRESHOLD_SECONDS,
    _detect_stopping_stuck,
    _do_reconcile,
)


def _set_updated_at(db_session, strategy_id: int, *, minutes_ago: int) -> None:
    """ORM 의 onupdate 우회 — sqlite 에 직접 UPDATE.

    StrategyInstance.updated_at 은 onupdate=func.now() 라 ORM 으로 set 후
    commit 하면 다시 NOW 로 덮어씀. 통합 테스트에서 「5분 전」 상태를 흉내내려면
    sql 직접 실행이 필요.
    """
    from sqlalchemy import update

    past = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    db_session.execute(
        update(StrategyInstance)
        .where(StrategyInstance.id == strategy_id)
        .values(updated_at=past)
    )
    db_session.commit()
    db_session.expire_all()


class TestStoppingStuckDetection:
    """`_detect_stopping_stuck` 직접 호출 (전체 reconcile 사이클 없이 빠르게)."""

    def test_threshold_is_5_minutes(self):
        assert STOPPING_STUCK_THRESHOLD_SECONDS == 5 * 60

    def test_cooldown_is_30_minutes(self):
        assert STOPPING_STUCK_ALERT_COOLDOWN_SECONDS == 30 * 60

    def test_under_5min_skipped(self, db_session, make_strategy):
        s = make_strategy(symbol_str="BTCUSDT", side="LONG", status="STOPPING")
        _set_updated_at(db_session, s.id, minutes_ago=3)  # 5분 안 지남

        notif = MagicMock()
        _detect_stopping_stuck(db_session, notif_svc=notif, redis=None)
        db_session.commit()

        assert notif.send_system_alert.call_count == 0
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "STOPPING_STUCK_DETECTED")
        ).scalars().all()
        assert events == []

    def test_over_5min_triggers_alert_and_risk_event(self, db_session, make_strategy):
        s = make_strategy(symbol_str="PHBUSDT", side="LONG", status="STOPPING")
        _set_updated_at(db_session, s.id, minutes_ago=8)

        notif = MagicMock()
        _detect_stopping_stuck(db_session, notif_svc=notif, redis=None)
        db_session.commit()

        assert notif.send_system_alert.call_count == 1
        call = notif.send_system_alert.call_args
        title = call.kwargs.get("title") or call.args[0]
        body = call.kwargs.get("body") or (call.args[1] if len(call.args) > 1 else "")
        assert "#" + str(s.id) in title
        assert "PHBUSDT" in title
        assert "LONG" in title
        assert "STOPPING" in body
        assert "_NOT_FOR_TP_SL" in body or "TP/SL" in body  # 부작용 설명 포함

        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "STOPPING_STUCK_DETECTED")
        ).scalars().all()
        assert len(events) == 1
        assert events[0].severity == "CRITICAL"
        assert events[0].strategy_instance_id == s.id

    def test_cooldown_blocks_repeat_alert(self, db_session, make_strategy):
        s = make_strategy(symbol_str="RONINUSDT", side="SHORT", status="STOPPING")
        _set_updated_at(db_session, s.id, minutes_ago=10)

        # FakeRedis 와 비슷한 동작 — cooldown 키가 있으면 skip
        store: dict[str, str] = {}
        redis = MagicMock()
        redis.get.side_effect = lambda k: store.get(k)
        redis.setex.side_effect = lambda k, ttl, v: store.__setitem__(k, str(v))

        notif = MagicMock()

        _detect_stopping_stuck(db_session, notif_svc=notif, redis=redis)
        db_session.commit()
        assert notif.send_system_alert.call_count == 1
        # cooldown 키 저장됐는지
        assert f"{STOPPING_STUCK_ALERT_REDIS_PREFIX}{s.id}" in store

        # 두 번째 사이클 — cooldown 활성 → skip
        _detect_stopping_stuck(db_session, notif_svc=notif, redis=redis)
        db_session.commit()
        assert notif.send_system_alert.call_count == 1  # 변화 없음

    def test_non_stopping_status_not_alerted(self, db_session, make_strategy):
        # STAGE1_OPEN, STAGE3_OPEN, TP2_DONE_PARTIAL 등 — 5분 지나도 무관
        for status in ["STAGE1_OPEN", "STAGE3_OPEN", "TP2_DONE_PARTIAL", "WAITING"]:
            s = make_strategy(
                symbol_str=f"TEST{status}USDT", side="LONG", status=status,
            )
            _set_updated_at(db_session, s.id, minutes_ago=30)

        notif = MagicMock()
        _detect_stopping_stuck(db_session, notif_svc=notif, redis=None)
        db_session.commit()

        assert notif.send_system_alert.call_count == 0

    def test_archived_strategy_skipped(self, db_session, make_strategy):
        # 사장님이 이미 archive 처리한 STOPPING 은 알림 안 보냄
        s = make_strategy(
            symbol_str="OLDUSDT", side="LONG", status="STOPPING",
            is_archived=True,
        )
        _set_updated_at(db_session, s.id, minutes_ago=30)

        notif = MagicMock()
        _detect_stopping_stuck(db_session, notif_svc=notif, redis=None)
        db_session.commit()

        assert notif.send_system_alert.call_count == 0

    def test_redis_failure_does_not_block_alert(self, db_session, make_strategy):
        """Redis 가 죽어도 알림은 발송 (cooldown 실패 < 갇힘 미인지)."""
        s = make_strategy(symbol_str="PHBUSDT", side="LONG", status="STOPPING")
        _set_updated_at(db_session, s.id, minutes_ago=10)

        redis = MagicMock()
        redis.get.side_effect = Exception("redis down")
        redis.setex.side_effect = Exception("redis down")
        notif = MagicMock()

        _detect_stopping_stuck(db_session, notif_svc=notif, redis=redis)
        db_session.commit()

        # redis 실패해도 알림은 1회 발송
        assert notif.send_system_alert.call_count == 1

    def test_multiple_stuck_strategies_all_alerted(self, db_session, make_strategy):
        """여러 strategy 동시 갇힘 — 각각 별도 알림 + RiskEvent."""
        s1 = make_strategy(symbol_str="AAAUSDT", side="LONG", status="STOPPING")
        s2 = make_strategy(symbol_str="BBBUSDT", side="SHORT", status="STOPPING")
        _set_updated_at(db_session, s1.id, minutes_ago=6)
        _set_updated_at(db_session, s2.id, minutes_ago=15)

        notif = MagicMock()
        _detect_stopping_stuck(db_session, notif_svc=notif, redis=None)
        db_session.commit()

        assert notif.send_system_alert.call_count == 2
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "STOPPING_STUCK_DETECTED")
        ).scalars().all()
        assert len(events) == 2


class TestReconcileFullCycleIncludesStoppingStuck:
    """전체 `_do_reconcile` 사이클이 STOPPING stuck 감지를 포함하는지 검증.

    사용자가 reconcile 만 동작시키면 STOPPING 갇힘 알림도 자동 발송돼야 함 —
    별도 worker 추가 없이 reconcile-worker 안에 통합.
    """

    def test_stuck_strategy_alerted_within_reconcile_cycle(
        self, db_session, make_strategy, fake_binance, identity_decrypt,
        patched_sessionlocal, monkeypatch,
    ):
        """STOPPING + 거래소 포지션 잔재 + 5분 초과 → reconcile 후 텔레그램 알림 발송."""
        s = make_strategy(
            symbol_str="PHBUSDT", side="LONG", status="STOPPING",
            current_position_qty=Decimal("100"),
            avg_entry_price=Decimal("0.06"),
        )
        # 거래소에 포지션 잔재 — matched 분기 타도록 (자동 STOPPED 정리 X)
        fake_binance.set_position(
            "PHBUSDT", position_amt="100", entry_price="0.06",
            mark_price="0.065", position_side="LONG",
        )
        _set_updated_at(db_session, s.id, minutes_ago=10)

        sent_alerts: list[dict] = []

        # NotificationService.send_system_alert 가 Telegram 외부 호출 안 하게 패치
        # — _no_telegram fixture 가 settings 만 차단하므로 send_system_alert 자체는 호출됨
        from app.services import notification_service as ns_module

        original = ns_module.NotificationService.send_system_alert

        def _spy_send(self, *, title, body):
            sent_alerts.append({"title": title, "body": body})
            return original(self, title=title, body=body)

        monkeypatch.setattr(ns_module.NotificationService, "send_system_alert", _spy_send)

        _do_reconcile(identity_decrypt)
        db_session.expire_all()

        # STOPPING 갇힘 알림 발송됨
        stopping_alerts = [a for a in sent_alerts if "전략 종료 갇힘" in a["title"]]
        assert len(stopping_alerts) == 1, (
            f"갇힘 알림 1건 기대했으나 {len(stopping_alerts)}건 (전체 alerts={[a['title'] for a in sent_alerts]})"
        )

        # 2026-05-21 Phase 2: status 가 MANUAL_CLEANUP_REQUIRED 로 자동 전환됨 (사장님 요구).
        # 이전엔 STOPPING 그대로 두어 reconcile 이 거래소 포지션 0 보면 자동 STOPPED 처리됐는데,
        # 이제는 「사장님이 거래소에서 직접 청산 후 명시적 ack」 흐름 강제. 자동 STOPPED 차단.
        s2 = db_session.get(StrategyInstance, s.id)
        assert s2.status == "MANUAL_CLEANUP_REQUIRED", (
            f"5분 초과 STOPPING 은 MANUAL_CLEANUP_REQUIRED 로 전환돼야 함 — 실제: {s2.status}"
        )

        # RiskEvent CRITICAL 기록됨
        events = db_session.execute(
            select(RiskEvent)
            .where(RiskEvent.event_type == "STOPPING_STUCK_DETECTED")
            .where(RiskEvent.strategy_instance_id == s.id)
        ).scalars().all()
        assert len(events) == 1
        assert events[0].severity == "CRITICAL"
        # event_payload 에 status 전환 trail 기록
        payload = events[0].event_payload
        assert payload.get("previous_status") == "STOPPING"
        assert payload.get("new_status") == "MANUAL_CLEANUP_REQUIRED"

    def test_no_stuck_strategies_no_alert(
        self, db_session, make_strategy, fake_binance, identity_decrypt,
        patched_sessionlocal, monkeypatch,
    ):
        """STOPPING 이 5분 안 지났으면 reconcile 후에도 알림 없음."""
        s = make_strategy(
            symbol_str="ETHUSDT", side="LONG", status="STOPPING",
            current_position_qty=Decimal("0.1"),
        )
        fake_binance.set_position(
            "ETHUSDT", position_amt="0.1", entry_price="3000",
            mark_price="3001", position_side="LONG",
        )
        _set_updated_at(db_session, s.id, minutes_ago=2)  # 5분 안 지남

        sent_alerts: list[dict] = []
        from app.services import notification_service as ns_module
        original = ns_module.NotificationService.send_system_alert

        def _spy_send(self, *, title, body):
            sent_alerts.append({"title": title, "body": body})
            return original(self, title=title, body=body)

        monkeypatch.setattr(ns_module.NotificationService, "send_system_alert", _spy_send)

        _do_reconcile(identity_decrypt)

        stopping_alerts = [a for a in sent_alerts if "전략 종료 갇힘" in a["title"]]
        assert stopping_alerts == []
