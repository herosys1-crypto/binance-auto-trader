from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from app.integrations.binance.mapper import map_order_update_event, map_account_update_event
from app.models.order import Order
from app.models.position import Position
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_stage_plan import StrategyStagePlan
from app.observability.metrics import user_stream_events_total

class StreamService:
    def __init__(self, db) -> None:
        self.db = db

    def handle_order_trade_update(self, payload: dict) -> None:
        user_stream_events_total.labels(event_type="ORDER_TRADE_UPDATE").inc()
        mapped = map_order_update_event(payload)
        order = self.db.execute(select(Order).where(Order.client_order_id == mapped["client_order_id"])).scalar_one_or_none()
        if not order:
            self.db.add(RiskEvent(strategy_instance_id=None, event_type="ORDER_TRADE_UPDATE", severity="WARN", title="Unmatched stream event", message="No local order matched the incoming stream payload", event_payload=payload))
            self.db.commit()
            return
        order.exchange_order_id = mapped["exchange_order_id"]
        order.status = mapped["status"]
        order.executed_qty = Decimal(str(mapped["executed_qty"] or "0"))
        order.avg_price = Decimal(str(mapped["avg_price"])) if mapped["avg_price"] else order.avg_price
        strategy = self.db.get(StrategyInstance, order.strategy_instance_id)
        if strategy and order.purpose == "ENTRY" and order.status == "FILLED":
            strategy.status = {1: "STAGE1_OPEN", 2: "STAGE2_OPEN", 3: "STAGE3_OPEN", 4: "STAGE4_OPEN"}.get(order.stage_no, strategy.status)
            # 단계별 계획 row 갱신 + 첫 진입 시점 추적 (알림 중복 방지).
            # Bug fix (2026-04-30): race condition 해결을 위해 atomic UPDATE WHERE 로 변경.
            # 이전엔 SELECT 후 in-memory mark + commit 이라 동시 처리되는 두 ORDER_TRADE_UPDATE
            # 가 둘 다 is_triggered=False 로 읽고 둘 다 알림 발송하는 문제. atomic 으로 바꾸면
            # rowcount=1 이 첫 FILLED 인식 1 회에만 나옴.
            from sqlalchemy import update as sa_update
            update_result = self.db.execute(
                sa_update(StrategyStagePlan)
                .where(StrategyStagePlan.strategy_instance_id == strategy.id)
                .where(StrategyStagePlan.stage_no == order.stage_no)
                .where(StrategyStagePlan.is_triggered.is_(False))
                .values(is_triggered=True, triggered_at=datetime.now(timezone.utc))
            )
            just_triggered_now = update_result.rowcount > 0
            # 알림 본문에 쓸 stage_plan 데이터 (planned_capital 등) 는 다시 SELECT
            stage_plan = self.db.execute(
                select(StrategyStagePlan)
                .where(StrategyStagePlan.strategy_instance_id == strategy.id)
                .where(StrategyStagePlan.stage_no == order.stage_no)
                .limit(1)
            ).scalars().first()
            # Telegram 알림은 첫 FILLED 인식 시 1회만 발송 (atomic gate)
            if just_triggered_now:
                try:
                    from app.services.notification_service import NotificationService
                    NotificationService(self.db).send_stage_entered_alert(
                        strategy_instance_id=strategy.id,
                        symbol=strategy.symbol,
                        side=strategy.side,
                        stage_no=order.stage_no,
                        entry_price=order.avg_price or order.price,
                        qty=order.executed_qty,
                        invested_capital=stage_plan.planned_capital if stage_plan else None,
                        avg_entry_price=strategy.avg_entry_price,
                    )
                except Exception:  # 알림 실패해도 거래 로직은 영향 없음
                    pass
        elif strategy and order.purpose == "EXIT" and order.status == "FILLED":
            # COMPLETED 가 _execute_take_profit 에서 이미 설정됐으면 보존 (REENTRY_READY 로 덮어쓰지 않음)
            if strategy.status != "COMPLETED":
                strategy.status = "REENTRY_READY"
                strategy.reentry_ready = True
            # Bug fix (2026-04-30): EXIT FILLED 후 stale qty/pnl 리셋. 거래소 ACCOUNT_UPDATE 가
            # 닫힌 포지션을 별도로 안 보내는 케이스 대비. 다음 ACCOUNT_UPDATE 가 와서 다른 값으로
            # 덮어쓰면 그 값이 우선됨.
            strategy.current_position_qty = Decimal("0")
            strategy.unrealized_pnl = Decimal("0")
            # 실현 손익 누적 (TP/SL 결과 청산 가격 기반)
            try:
                if order.avg_price and strategy.avg_entry_price and order.executed_qty:
                    avg_entry = Decimal(str(strategy.avg_entry_price))
                    exit_px = Decimal(str(order.avg_price))
                    qty = Decimal(str(order.executed_qty))
                    if strategy.side == "LONG":
                        realized_delta = qty * (exit_px - avg_entry)
                    else:
                        realized_delta = qty * (avg_entry - exit_px)
                    prev_realized = Decimal(str(strategy.realized_pnl or 0))
                    strategy.realized_pnl = (prev_realized + realized_delta).quantize(Decimal("0.01"))
            except Exception:
                pass
        self.db.commit()

    def handle_account_update(self, payload: dict) -> None:
        user_stream_events_total.labels(event_type="ACCOUNT_UPDATE").inc()
        mapped = map_account_update_event(payload)
        # 같은 symbol+side 로 active 한 strategy 가 여러 개일 수 있으므로
        # 종료된 상태 (REENTRY_READY/CLOSED/STOPPING) 는 제외하고 가장 최근 것 1개만 매칭.
        # status 가 종료에 가까운 4종을 제외하고 created_at desc 로 첫 번째.
        _CLOSED_STATUSES = {"REENTRY_READY", "CLOSED", "STOPPING", "COMPLETED"}
        for pos in mapped["positions"]:
            symbol = pos.get("s")
            position_side = pos.get("ps")
            strategy = (
                self.db.execute(
                    select(StrategyInstance)
                    .where(
                        StrategyInstance.symbol == symbol,
                        StrategyInstance.side == position_side,
                        StrategyInstance.status.notin_(_CLOSED_STATUSES),
                    )
                    .order_by(StrategyInstance.id.desc())
                    .limit(1)
                )
                .scalars()
                .first()
            )
            if not strategy:
                continue
            self.db.add(Position(strategy_instance_id=strategy.id, symbol=symbol, side=strategy.side, position_side=position_side, entry_price=Decimal(str(pos.get("ep"))) if pos.get("ep") else None, break_even_price=Decimal(str(pos.get("bep"))) if pos.get("bep") else None, mark_price=None, liquidation_price=strategy.liquidation_price, position_amt=Decimal(str(pos.get("pa"))) if pos.get("pa") else None, isolated_margin=Decimal(str(pos.get("iw"))) if pos.get("iw") else None, unrealized_pnl=Decimal(str(pos.get("up"))) if pos.get("up") else None, margin_type=pos.get("mt"), leverage=strategy.leverage, source="ACCOUNT_UPDATE"))
            strategy.avg_entry_price = Decimal(str(pos.get("ep"))) if pos.get("ep") else strategy.avg_entry_price
            strategy.current_position_qty = Decimal(str(pos.get("pa"))) if pos.get("pa") else Decimal("0")
            strategy.unrealized_pnl = Decimal(str(pos.get("up"))) if pos.get("up") else Decimal("0")
        self.db.commit()

    def handle_listen_key_expired(self, payload: dict) -> None:
        user_stream_events_total.labels(event_type="listenKeyExpired").inc()
        self.db.add(RiskEvent(strategy_instance_id=None, event_type="LISTEN_KEY_EXPIRED", severity="CRITICAL", title="Binance listenKey expired", message="User data stream expired; new orders must be blocked until stream restarts", event_payload=payload))
        self.db.commit()
