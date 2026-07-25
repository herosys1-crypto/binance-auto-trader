import logging
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
from app.services.mark_price_cache import get_mark_price

logger = logging.getLogger(__name__)


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
            # 🚨 2026-07-24 v127 HIGH fix: ENTRY FILLED 시 qty 즉시 sync!
            #   옛 silent bug: ACCOUNT_UPDATE 유실 시 qty stale (30초~2분) → TP1 계획보다 작은 청산량!
            #   fix: EXIT partial (line 182) 패턴 재사용 = _fetch_actual_position_qty 호출!
            try:
                actual_qty = self._fetch_actual_position_qty(strategy)
                if actual_qty is not None:
                    strategy.current_position_qty = actual_qty
            except Exception as _e:
                logger.warning(
                    "[stream v127] ENTRY FILLED qty sync 실패 (계속!): strategy=%s error=%s",
                    strategy.id, _e,
                )
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
                except Exception as _e:  # 알림 실패해도 거래 로직은 영향 없음
                    logger.warning("[#13] stage_entered_alert 발송 실패 strategy=%s stage=%s: %s", strategy.id, order.stage_no, _e)
            # 2026-06-02 (#11): ENTRY 의 commission 도 차감 (realized_pnl 정확성).
            # ENTRY 는 PnL 0 이지만 commission 은 발생 → strategy.realized_pnl 에서 차감.
            try:
                commission_str = mapped.get("commission") or "0"
                commission_asset = (mapped.get("commission_asset") or "").upper()
                if commission_asset == "USDT":
                    entry_commission = Decimal(str(commission_str))
                    if entry_commission > 0:
                        prev_realized = Decimal(str(strategy.realized_pnl or 0))
                        strategy.realized_pnl = (prev_realized - entry_commission).quantize(Decimal("0.01"))
            except Exception as _e:
                logger.warning("[#13] ENTRY commission 차감 실패 strategy=%s: %s", strategy.id if strategy else None, _e)
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
                #
                # 2026-06-02 fix (사장님 발견 MYXUSDT alert 3회):
                #   ACCOUNT_UPDATE 가 정확한 pa 로 먼저 갱신 후 ORDER_TRADE_UPDATE 가 또
                #   delta 차감 → 중복 차감 (DB -408 vs 거래소 -611, 정확히 TP2 청산량 203 차이).
                #   해결: partial 청산도 actual_position REST 호출로 정확한 잔량 사용.
                #   REST 1회 추가 부담 < 동기화 정확성. failure 시 기존 delta 차감 fallback.
                sign = Decimal("-1") if strategy.side == "SHORT" else Decimal("1")
                actual_remaining_partial = self._fetch_actual_position_qty(strategy)
                if actual_remaining_partial is not None:
                    # Binance 실 잔량 우선 — ACCOUNT_UPDATE 와 충돌 회피
                    strategy.current_position_qty = (actual_remaining_partial * sign).quantize(Decimal("0.00000001"))
                else:
                    # REST 실패 fallback — 기존 delta 차감
                    strategy.current_position_qty = (remaining_abs * sign).quantize(Decimal("0.00000001"))
                # unrealized_pnl 은 다음 ACCOUNT_UPDATE 가 갱신
            # 실현 손익 누적 — delta 기반 (이번 이벤트 신규 체결분만 PnL 반영).
            # 2026-06-02 (#11 fix): commission 즉시 차감 — 이전엔 gross PnL 만 누적해서
            # realized_pnl_sync_worker (매 1분) 가 보정할 때까지 사장님 화면에 부정확 표시.
            # 이제 ORDER 이벤트 처리 시 즉시 net (gross - commission) 누적.
            try:
                if order.avg_price and strategy.avg_entry_price and delta_abs > 0:
                    avg_entry = Decimal(str(strategy.avg_entry_price))
                    exit_px = Decimal(str(order.avg_price))
                    qty = delta_abs  # 누적이 아닌 delta!
                    if strategy.side == "LONG":
                        realized_delta = qty * (exit_px - avg_entry)
                    else:
                        realized_delta = qty * (avg_entry - exit_px)
                    # commission 차감 — USDT 수수료만 (BNB 는 mark price 환산 필요 → 별도 task).
                    # 사장님 setup = 거의 USDT 수수료. BNB Burn 사용 시 0 으로 처리 (보수적).
                    commission_str = mapped.get("commission") or "0"
                    commission_asset = (mapped.get("commission_asset") or "").upper()
                    commission_usdt = Decimal("0")
                    try:
                        if commission_asset == "USDT":
                            commission_usdt = Decimal(str(commission_str))
                    except Exception as _e:
                        logger.warning("[#13] EXIT commission Decimal 변환 실패 strategy=%s raw=%r: %s", strategy.id, commission_str, _e)
                        commission_usdt = Decimal("0")
                    realized_delta = realized_delta - commission_usdt
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
                    except Exception as _e:
                        logger.warning("[#13] AccountDailyLossLimiter add_realized_delta 실패 strategy=%s acc=%s: %s", strategy.id, strategy.exchange_account_id, _e)
            except Exception as _e:
                logger.warning("[#13] EXIT realized_pnl 계산 전체 실패 strategy=%s order=%s: %s", strategy.id, order.client_order_id, _e)
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
            # 🚨 2026-06-22 사장님 critical fix (v51 ROOT CAUSE — "또 2단계가 진행되지 않았어"):
            # ACCOUNT_UPDATE payload 엔 markPrice 가 없어 옛 코드는 mark_price=None 으로 스냅샷 생성.
            # 그런데 ACCOUNT_UPDATE 는 포지션 변동 시마다 발생 → 이 None 스냅샷이 "latest" 가 되어
            # reconcile(2분 주기) 가 채운 mark_price 를 곧바로 덮어버림 (= 1시간+ None 지속 원인).
            # → latest snapshot.mark_price 를 읽는 4개 worker 가 동시에 silent skip:
            #   stage_trigger(2단계 자동 진입 차단) / liquidation_risk(청산 감시 꺼짐) /
            #   tp_miss_detector / setting_preservation. = 사장님 헌법 "silent bug 금지" 위반.
            # fix: 스냅샷 생성 시점의 Redis 실시간 캐시(markPrice@1s) 로 채움 → latest 가 더 이상
            #   None 으로 오염 X (= 4개 reader 동시 치유, 헌법 6번 단일 진실). 캐시 miss 시만 None.
            _cached_mark = get_mark_price(symbol)
            self.db.add(Position(strategy_instance_id=strategy.id, symbol=symbol, side=strategy.side, position_side=position_side, entry_price=Decimal(str(pos.get("ep"))) if pos.get("ep") else None, break_even_price=Decimal(str(pos.get("bep"))) if pos.get("bep") else None, mark_price=_cached_mark, liquidation_price=strategy.liquidation_price, position_amt=Decimal(str(pos.get("pa"))) if pos.get("pa") else None, isolated_margin=Decimal(str(pos.get("iw"))) if pos.get("iw") else None, unrealized_pnl=Decimal(str(pos.get("up"))) if pos.get("up") else None, margin_type=pos.get("mt"), leverage=strategy.leverage, source="ACCOUNT_UPDATE"))
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
        except Exception as _e:
            logger.warning("[#13] _fetch_actual_position_qty 실패 strategy=%s symbol=%s: %s", strategy.id, strategy.symbol, _e)
            return None  # fail-soft

    def handle_listen_key_expired(self, payload: dict) -> None:
        # 🌟 2026-06-09 사장님 critical UX fix:
        # listenKey 만료 = Binance 24시간 표준 자동 만료 (= 정상 동작!)
        # consumer 가 자동 재연결 (binance_user_stream_consumer.py while True)
        # = CRITICAL 아닌 INFO 격하 + 친절한 메시지 (= 사장님 안심)
        user_stream_events_total.labels(event_type="listenKeyExpired").inc()
        self.db.add(RiskEvent(
            strategy_instance_id=None,
            event_type="LISTEN_KEY_EXPIRED",
            severity="INFO",  # CRITICAL → INFO (= Binance 표준 자동 동작)
            title="🔄 Binance 24시간 자동 만료 (정상)",
            message="Binance 표준 자동 만료 - 자동 재연결 진행 중 (= 사장님 행동 X, 안심하세요)",
            event_payload=payload,
        ))
        self.db.commit()

    def handle_listen_key_renewed(self) -> None:
        """🌟 2026-06-09 신 메서드: listenKey 자동 재발급 성공 시 호출.
        = 사장님 화면에 "✅ 복구됨" 알림 = 안심
        """
        user_stream_events_total.labels(event_type="listenKeyRenewed").inc()
        self.db.add(RiskEvent(
            strategy_instance_id=None,
            event_type="LISTEN_KEY_RENEWED",
            severity="INFO",
            title="✅ user-stream 자동 복구 완료",
            message="Binance user-stream 재연결 성공 - 정상 주문 처리 가능",
            event_payload={},
        ))
        self.db.commit()
