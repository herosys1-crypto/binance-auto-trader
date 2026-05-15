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
            self.db.add(RiskEvent(strategy_instance_id=None, event_type="ORDER_TRADE_UPDATE", severity="WARN", title="📡 매칭 안 된 거래소 이벤트", message="시스템에 등록되지 않은 주문 (수동 거래 또는 외부 발생)에 대한 stream 이벤트 — 거래 로직 영향 없음", event_payload=payload))
            self.db.commit()
            return
        # ===== Idempotency / delta-based ledger update =====
        # Bug history:
        #   2026-05-02 (#79 LABUSDT -665 사례) — 같은 FILLED 이벤트 중복 → realized_pnl 이중 누적.
        #     Fix: prev_status == "FILLED" 면 skip.
        #   2026-05-04 (#92 BABYUSDT -286 차이 = TP3 close qty 정확 일치) — PARTIALLY_FILLED →
        #     FILLED 흐름에서 같은 trade settlement 의 신규 체결분이 두 번 차감.
        #     prev_status == "FILLED" 만 검사하던 idempotent gate 통과 후 두 번째 처리.
        #     Fix: delta_executed (= new - prev) 만큼만 처리. 누적 executed_qty 가 아닌 delta 사용.
        #     이렇게 하면 같은 trade 가 여러 번 와도 두 번째 호출 delta=0 → skip. PARTIAL→FILLED
        #     흐름에서도 PARTIAL 시 차감한 만큼은 prev_executed_qty 에 기록되어 FILLED 차감 시
        #     중복되지 않음.
        prev_status = order.status
        prev_executed_qty = Decimal(str(order.executed_qty or 0))
        new_executed_qty = Decimal(str(mapped["executed_qty"] or "0"))
        delta_executed = new_executed_qty - prev_executed_qty

        order.exchange_order_id = mapped["exchange_order_id"]
        order.status = mapped["status"]
        order.executed_qty = new_executed_qty
        order.avg_price = Decimal(str(mapped["avg_price"])) if mapped["avg_price"] else order.avg_price

        # Idempotent gate (delta 기반):
        # delta <= 0 → 신규 체결량 없음 = 이전과 동일한 settlement 의 중복 이벤트 → ledger update skip.
        # 단, status 자체는 위에서 이미 갱신됨 (PARTIAL → FILLED 같은 의미있는 status 전이 보존).
        if delta_executed <= 0:
            self.db.commit()
            return

        strategy = self.db.get(StrategyInstance, order.strategy_instance_id)
        if strategy and order.purpose == "ENTRY" and order.status == "FILLED":
            # 2026-05-04 fix: 옵션 C 1~10단계 동적 지원. 이전엔 1~4단계 dict lookup 이라
            # 5+ 단계 진입 시 status 가 STAGE4_OPEN 에 stuck → UI 잘못 + reconcile 자가
            # 회복도 STAGE5+ 미지원이라 stuck 가중. f-string 으로 N단계 모두 처리.
            if order.stage_no and 1 <= order.stage_no <= 10:
                strategy.status = f"STAGE{order.stage_no}_OPEN"
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
        elif strategy and order.purpose == "EXIT" and order.status in ("FILLED", "PARTIALLY_FILLED"):
            # 부분 청산 (TP1/2/3) vs 전체 청산 구분.
            # Bug fix history:
            #   2026-04-30 PM (#58 NAORISUSDT) — TP1 부분 청산이 전체 청산처럼 처리되어 잔량 누락.
            #     Fix: cur_qty - exec_qty 로 remaining 계산해서 partial vs full 구분.
            #   2026-05-04 (#92 BABYUSDT -286) — PARTIAL → FILLED 흐름에서 같은 trade 의
            #     신규 qty 가 두 번 차감 (TP3 close 286 이 두 번 → DB -574, 거래소 -860).
            #     Fix: 누적 executed_qty 가 아닌 delta_executed 만큼만 차감.
            cur_qty_abs = Decimal(str(strategy.current_position_qty or 0)).copy_abs()
            delta_abs = delta_executed.copy_abs()
            remaining_abs = cur_qty_abs - delta_abs
            # is_full_close 판단: 이번 delta 청산 후 잔량 0 인가
            # AND 이번 이벤트가 status=FILLED (PARTIALLY_FILLED 면 후속 이벤트 더 옴 — 부분 청산 처리)
            is_full_close = (remaining_abs <= Decimal("0.00000001")) and (order.status == "FILLED")

            if is_full_close:
                # 2026-05-08 #120 fix (defense-in-depth): is_full_close 가 True 라도
                # 거래소 실제 포지션을 한 번 더 확인. DB qty 가 stale 인 경우 (예:
                # 직전 다른 EXIT 이벤트가 race 로 차감 누락) 우리가 close 한 양보다
                # 더 큰 포지션이 거래소에 남아있을 수 있음.
                # → REENTRY_READY 로 잘못 마킹하면 다음 zombie scan 에서 orphan 감지 → KS.
                # 실제 잔량 > 0 이면 partial 로 처리하고 다음 cycle 에 reconcile 가 정정.
                actual_remaining = self._fetch_actual_position_qty(strategy)
                if actual_remaining is not None and actual_remaining > Decimal("0.00000001"):
                    # 거래소엔 아직 포지션 있음 — REENTRY_READY 차단, partial 로 처리
                    sign = Decimal("-1") if strategy.side == "SHORT" else Decimal("1")
                    strategy.current_position_qty = (actual_remaining * sign).quantize(Decimal("0.00000001"))
                    self.db.add(RiskEvent(
                        strategy_instance_id=strategy.id,
                        event_type="EXIT_FULL_CLOSE_MISMATCH",
                        severity="WARN",
                        title="⚠️ EXIT FILLED 'is_full_close' 차단 — 거래소 잔량 존재",
                        message=(
                            f"DB 는 잔량 0 으로 판단했으나 거래소에 {actual_remaining} 남음. "
                            f"REENTRY_READY 마킹 차단 + DB qty 정정. 다음 cycle 재평가."
                        ),
                        event_payload={
                            "delta_executed": str(delta_abs),
                            "db_cur_qty_before": str(cur_qty_abs),
                            "actual_remaining": str(actual_remaining),
                            "order_client_id": order.client_order_id,
                        },
                    ))
                else:
                    # 정상 — qty/unrealized 0, status 전환
                    strategy.current_position_qty = Decimal("0")
                    strategy.unrealized_pnl = Decimal("0")
                    # status 전환:
                    #   COMPLETED  : _execute_take_profit 가 이미 마킹 → 보존
                    #   STOPPING   : 사용자 「수동 정지」 → STOPPED (좀비 방지)
                    #   기타       : TP/SL 자동 청산 → REENTRY_READY
                    if strategy.status == "COMPLETED":
                        pass
                    elif strategy.status == "STOPPING":
                        strategy.status = "STOPPED"
                        strategy.stopped_at = datetime.now(timezone.utc)
                    else:
                        strategy.status = "REENTRY_READY"
                        strategy.reentry_ready = True
            else:
                # 부분 청산 — delta 만큼 차감 (cur_qty - delta_abs).
                # status / reentry_ready 는 그대로 (TP partial 진행 중 또는 PARTIAL 후속 대기).
                sign = Decimal("-1") if strategy.side == "SHORT" else Decimal("1")
                strategy.current_position_qty = (remaining_abs * sign).quantize(Decimal("0.00000001"))
                # unrealized_pnl 은 다음 ACCOUNT_UPDATE 가 갱신
            # 실현 손익 누적 — delta 기반 (이번 이벤트 신규 체결분만 PnL 반영)
            try:
                if order.avg_price and strategy.avg_entry_price and delta_abs > 0:
                    avg_entry = Decimal(str(strategy.avg_entry_price))
                    exit_px = Decimal(str(order.avg_price))
                    qty = delta_abs  # 누적이 아닌 delta!
                    if strategy.side == "LONG":
                        realized_delta = qty * (exit_px - avg_entry)
                    else:
                        realized_delta = qty * (avg_entry - exit_px)
                    prev_realized = Decimal(str(strategy.realized_pnl or 0))
                    strategy.realized_pnl = (prev_realized + realized_delta).quantize(Decimal("0.01"))
                    # 2026-05-04 v2: 일일 손실 한도 incremental 누적.
                    # daily_loss_aggregator 의 v1 한계 (realized 누적 안 됨) 보완.
                    # account_daily_risk_limit 의 오늘 row 에 realized_delta 추가.
                    # 누적 실패해도 ledger 본 흐름은 정상 처리 (try/except 격리).
                    try:
                        from app.services.account_daily_loss_limiter import (
                            AccountDailyLossLimiterService,
                        )
                        AccountDailyLossLimiterService(self.db).add_realized_delta(
                            exchange_account_id=strategy.exchange_account_id,
                            realized_delta=realized_delta,
                        )
                    except Exception:
                        pass
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

    def _fetch_actual_position_qty(self, strategy) -> Decimal | None:
        """거래소 실제 포지션 잔량 (절대값) 반환. 실패 시 None.

        2026-05-08 #120 fix: stream EXIT FILLED 처리 시 is_full_close 판정의
        defensive check 용. DB qty 기준으로 잔량 0 이라 판단해도, 거래소에
        실제로 포지션이 남아있으면 REENTRY_READY 마킹 차단.

        실패 시 (API 에러, 계정 비활성 등) None 반환 — caller 가 기존 동작 유지.
        외부 호출이라 실패 가능성 무시 못함, fail-soft.
        """
        try:
            from app.core.crypto import decrypt_text
            from app.integrations.binance.client import BinanceClient
            from app.repositories.exchange_account_repository import ExchangeAccountRepository
            account = ExchangeAccountRepository(self.db).get(strategy.exchange_account_id)
            if not account or not account.is_active:
                return None
            client = BinanceClient(
                api_key=decrypt_text(account.api_key_enc),
                api_secret=decrypt_text(account.api_secret_enc),
                is_testnet=account.is_testnet,
            )
            risk = client.get_position_risk(symbol=strategy.symbol)
            if isinstance(risk, dict):
                risk = [risk]
            for p in risk:
                if p.get("symbol") == strategy.symbol and p.get("positionSide") == strategy.side:
                    amt = Decimal(str(p.get("positionAmt", "0")))
                    return amt.copy_abs()
            return Decimal("0")  # 매칭 항목 없으면 잔량 0
        except Exception:
            return None  # fail-soft

    def handle_listen_key_expired(self, payload: dict) -> None:
        user_stream_events_total.labels(event_type="listenKeyExpired").inc()
        self.db.add(RiskEvent(strategy_instance_id=None, event_type="LISTEN_KEY_EXPIRED", severity="CRITICAL", title="🚨 Binance listenKey 만료", message="거래소 user data stream 끊김 — 새 주문 차단 (재연결까지 대기)", event_payload=payload))
        self.db.commit()
