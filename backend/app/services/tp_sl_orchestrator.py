import time
from decimal import Decimal
from app.core.redis_client import get_redis_client
from app.core.redis_lock import redis_lock, RedisLockError
from app.observability.metrics import strategy_runs_total, strategy_take_profit_total
from app.repositories.strategy_repository import StrategyRepository
from app.services.execution_service import ExecutionService
from app.services.notification_service import NotificationService
from app.services.risk_service import RiskService

class TPSLOrchestratorService:
    def __init__(self, db, *, api_key: str, api_secret: str, is_testnet: bool = False) -> None:
        self.db = db
        self.strategy_repo = StrategyRepository(db)
        self.risk_service = RiskService(db)
        self.notification_service = NotificationService(db)
        self.execution_service = ExecutionService(db, api_key=api_key, api_secret=api_secret, is_testnet=is_testnet)

    def run_for_strategy(self, strategy_id: int) -> None:
        redis_client = get_redis_client()
        try:
            with redis_lock(redis_client, f"lock:strategy:{strategy_id}:tp_sl", ttl_seconds=20, wait_timeout_seconds=0):
                strategy = self.strategy_repo.get_strategy(strategy_id)
                if not strategy or strategy.status in {"WAITING","REENTRY_READY","CLOSED","STOPPING"}:
                    return
                # SHORT 포지션은 current_position_qty 가 음수로 저장됨 (예: -0.002).
                # 이전 버전은 `<= 0` 으로 체크해서 SHORT 전략을 모두 건너뛰는 버그가 있었음.
                # abs() 로 바꿔 LONG/SHORT 양쪽 모두 정상 동작하도록 수정.
                if strategy.current_position_qty is None or abs(Decimal(str(strategy.current_position_qty))) == 0:
                    return
                strategy_runs_total.labels(side=strategy.side, status=strategy.status).inc()
                # 정상 모드 -50% 손절 검사 (크라이시스 Stage 2 의 -1% 손절은 evaluate_take_profit_level 가 처리)
                if self.risk_service.evaluate_stop_loss(strategy.id):
                    self._execute_stop_loss(strategy)
                    return
                tp_level = self.risk_service.evaluate_take_profit_level(strategy.id)
                if tp_level is None:
                    return
                # 사용자 기획 변경 (2026-04-29): 크라이시스 모드도 TP1~4 정규 경로 사용.
                # _execute_take_profit 내부에서 크라이시스이면 qty ratio override (25/25/50/100).
                # risk_service.evaluate_take_profit_level 이 크라이시스 시 임계치를 5/10/15/20% 로 override.
                # 이미 동일 단계 또는 더 높은 단계가 실행됐으면 스킵
                # A12 fix (audit 2026-05-02): TP5_DONE_PARTIAL 누락 — TP5 가 마지막 활성 TP 가
                # 아닌 케이스 (예: tp1~5 모두 활성 + 사용자 ratio < 100%) 에서 부분 청산 후
                # progression 추적이 끊어지는 미세 버그. 이전엔 TP5 발동 후 status="COMPLETED" 만
                # 처리되어 TP5_DONE_PARTIAL 상태가 빠져있었음.
                done_levels_progression = ["TP1_DONE_PARTIAL", "TP2_DONE_PARTIAL", "TP3_DONE_PARTIAL", "TP4_DONE_PARTIAL", "TP5_DONE_PARTIAL", "COMPLETED"]
                tp_level_index = {"TP1": 0, "TP2": 1, "TP3": 2, "TP4": 3, "TP5": 4}.get(tp_level, -1)
                cur_status = (strategy.status or "").upper()
                cur_index = -1
                for i, lab in enumerate(done_levels_progression):
                    if cur_status == lab:
                        cur_index = i
                        break
                if tp_level == "TRAILING_TP" and strategy.status != "COMPLETED":
                    self._execute_take_profit(strategy, "TRAILING_TP")
                elif tp_level_index >= 0 and tp_level_index > cur_index and strategy.status != "COMPLETED":
                    self._execute_take_profit(strategy, tp_level)
        except RedisLockError:
            return

    def _execute_take_profit(self, strategy, level: str) -> None:
        from app.models.strategy_template import StrategyTemplate
        from app.models.symbol import Symbol
        from sqlalchemy import select

        # SHORT 면 음수로 저장되어 있으므로 abs() 로 양수 quantity 확보.
        current_qty = abs(Decimal(str(strategy.current_position_qty)))
        tpl = self.db.get(StrategyTemplate, strategy.strategy_template_id)
        # 템플릿의 qty_ratio 우선 사용. 없으면 기본값 폴백.
        ratio_attr = {
            "TP1": "tp1_qty_ratio", "TP2": "tp2_qty_ratio", "TP3": "tp3_qty_ratio",
            "TP4": "tp4_qty_ratio", "TP5": "tp5_qty_ratio",
        }
        default_ratio = {"TP1": Decimal("25"), "TP2": Decimal("50"), "TP3": Decimal("100"), "TP4": Decimal("100"), "TP5": Decimal("100")}
        # 크라이시스 모드 qty ratio override (사용자 기획):
        # TP1=25%, TP2=25%, TP3=50% of remaining, TP4=100% of remaining
        crisis_qty_ratio = {"TP1": Decimal("25"), "TP2": Decimal("25"), "TP3": Decimal("50"), "TP4": Decimal("100")}

        # 사용자 기획 (2026-04-30 evening, #80 사례 검토 후):
        # "4/4 익절 모두 종료되면 전략 인스턴스 모두 종료. 1단계만 진입했어도 모든 활성 TP
        #  발동 시 나머지 잔량까지 전부 청산하고 종료."
        # 활성 TP = template 의 tp1~5_percent 중 NOT NULL 인 레벨. 가장 큰 번호 = 마지막 TP.
        # 마지막 TP 발동 시 사용자 ratio 무시하고 잔량 100% 청산 + COMPLETED.
        active_tps = []
        if tpl:
            for n in range(1, 6):
                if getattr(tpl, f"tp{n}_percent", None) is not None:
                    active_tps.append(f"TP{n}")
        last_active_tp = active_tps[-1] if active_tps else None

        if level == "TRAILING_TP":
            close_ratio = Decimal("1.00")  # 전량 청산
        elif last_active_tp and level == last_active_tp:
            # 마지막 활성 TP 발동 — 잔량 전부 청산 (사용자 ratio 무시)
            close_ratio = Decimal("1.00")
        elif strategy.crisis_mode_triggered_at and level in crisis_qty_ratio:
            close_ratio = crisis_qty_ratio[level] / Decimal("100")
        else:
            attr = ratio_attr.get(level)
            tpl_val = getattr(tpl, attr, None) if tpl and attr else None
            ratio_pct = Decimal(str(tpl_val)) if tpl_val is not None else default_ratio.get(level, Decimal("100"))
            close_ratio = ratio_pct / Decimal("100")
        if close_ratio >= Decimal("1.00"):
            close_qty = current_qty
        else:
            # Bug #11 fix (2026-04-29): step_size 단위로 floor.
            # 이전 버전은 0.00000001 (8자리) 로 quantize 했는데, 실제 거래소는
            # 심볼별 LOT_SIZE 의 stepSize 를 따라야 함 (예: BTCUSDT=0.001).
            # 너무 정밀한 수량을 보내면 -1111 "Precision is over the maximum"
            # 에러로 거절됨. 이제 심볼의 step_size 로 floor 한다.
            raw_qty = current_qty * close_ratio
            sym = self.db.execute(select(Symbol).where(Symbol.symbol == strategy.symbol)).scalars().first()
            step = Decimal(str(sym.step_size)) if sym and sym.step_size and sym.step_size > 0 else Decimal("0.001")
            # floor to step: floor(raw / step) * step
            close_qty = (raw_qty // step) * step
        if close_qty <= 0:
            return
        # 실제 청산 체결 — 반환된 order 의 avg_price 가 진짜 청산 단가 (mark 보다 정확).
        close_order = self.execution_service.emergency_close_position(strategy.id, quantity=close_qty)
        # 청산 후 남은 수량 계산
        remaining_qty = (current_qty - close_qty).quantize(Decimal("0.00000001"))
        # 상태 진행
        is_final = (level == "TRAILING_TP" or close_ratio >= Decimal("1.00"))
        if level == "TP1":
            strategy.status = "TP1_DONE_PARTIAL" if not is_final else "COMPLETED"
        elif level == "TP2":
            strategy.status = "TP2_DONE_PARTIAL" if not is_final else "COMPLETED"
        elif level == "TP3":
            strategy.status = "TP3_DONE_PARTIAL" if not is_final else "COMPLETED"
        elif level == "TP4":
            strategy.status = "TP4_DONE_PARTIAL" if not is_final else "COMPLETED"
        elif level == "TP5":
            # A12 fix: TP5 가 마지막 활성 TP 가 아닐 수도 있음 (이론적으로). is_final 따라 분기.
            strategy.status = "TP5_DONE_PARTIAL" if not is_final else "COMPLETED"
        else:  # TRAILING_TP
            strategy.status = "COMPLETED"
        if strategy.status == "COMPLETED":
            strategy.reentry_ready = False
            self.risk_service.reset_peak_pnl(strategy.id)
        self.db.commit()
        strategy_take_profit_total.labels(symbol=strategy.symbol, side=strategy.side, level=level).inc()

        # 손익 금액 + 수익률 계산 — 실제 청산가(close_order.avg_price) 기준 (mark 보다 정확)
        # 2026-05-03 강화 v2: stream EXIT FILLED 이벤트 도착 대기 (최대 1초 retry)
        # 시장가 즉시 체결 시 Binance 응답이 avgPrice=0 으로 올 수도. stream 이 0.5~1초
        # 안에 갱신함. 그 동안 짧게 wait + db.refresh 로 정확값 확보.
        avg_exit_price = None
        realized_pnl = None
        pnl_pct = None
        try:
            avg_entry = Decimal(str(strategy.avg_entry_price)) if strategy.avg_entry_price else None
            exit_px = None
            if close_order:
                # Retry chain: 200ms 간격으로 5회 (총 최대 1초) — stream EXIT FILLED 이벤트 대기
                for attempt in range(5):
                    # 1순위: close_order.avg_price
                    if close_order.avg_price and Decimal(str(close_order.avg_price)) > 0:
                        exit_px = Decimal(str(close_order.avg_price))
                        break
                    # 2순위: close_order.price (market order 즉시 체결 시 fill price)
                    if close_order.price and Decimal(str(close_order.price)) > 0:
                        exit_px = Decimal(str(close_order.price))
                        break
                    # 다음 시도 전 대기 + DB refresh (stream 갱신 기다림)
                    if attempt < 4:
                        time.sleep(0.2)
                        try:
                            self.db.refresh(close_order)
                        except Exception:
                            pass
            # 마지막 fallback: latest_position.mark_price (stream 까지 fail 시 추정)
            if exit_px is None:
                from app.repositories.position_repository import PositionRepository
                latest_pos = PositionRepository(self.db).latest_by_strategy(strategy.id)
                if latest_pos and latest_pos.mark_price:
                    exit_px = Decimal(str(latest_pos.mark_price))
            if avg_entry and exit_px and avg_entry > 0:
                leverage = Decimal(str(strategy.leverage)) if strategy.leverage else Decimal("1")
                if strategy.side == "LONG":
                    raw_pct = (exit_px - avg_entry) / avg_entry * Decimal("100")
                    realized_pnl = (close_qty * (exit_px - avg_entry)).quantize(Decimal("0.01"))
                else:  # SHORT
                    raw_pct = (avg_entry - exit_px) / avg_entry * Decimal("100")
                    realized_pnl = (close_qty * (avg_entry - exit_px)).quantize(Decimal("0.01"))
                pnl_pct = (raw_pct * leverage).quantize(Decimal("0.01"))
                avg_exit_price = exit_px
        except Exception:
            pass

        self.notification_service.send_take_profit_alert(
            strategy_instance_id=strategy.id, symbol=strategy.symbol, side=strategy.side, level=level,
            realized_pnl=realized_pnl, avg_exit_price=avg_exit_price, pnl_pct=pnl_pct,
            closed_qty=close_qty, remaining_qty=remaining_qty,
        )

    def _execute_stop_loss(self, strategy) -> None:
        # SHORT 포지션은 음수 qty 로 저장됨 — abs() 로 양수화 후 청산.
        # 이전엔 `current_qty > 0` 이라 SHORT SL 이 실행되지 않는 버그가 있었음.
        current_qty = abs(Decimal(str(strategy.current_position_qty)))
        if current_qty > 0:
            self.execution_service.emergency_close_position(strategy.id, quantity=current_qty)
        strategy.status = "STOPPING"
        self.db.commit()

        # 손실률(%) 계산 — 사용자 마진 대비 leveraged ROI
        # margin = capital / leverage → ROI = USD 손실 × leverage / capital × 100
        loss_amount = Decimal(str(strategy.realized_pnl)) + Decimal(str(strategy.unrealized_pnl))
        pnl_pct = None
        try:
            capital = Decimal(str(strategy.total_capital))
            leverage = Decimal(str(strategy.leverage)) if strategy.leverage else Decimal("1")
            if capital > 0:
                pnl_pct = (loss_amount * leverage / capital * Decimal("100")).quantize(Decimal("0.01"))
        except Exception:
            pass

        self.notification_service.send_stop_loss_alert(
            strategy_instance_id=strategy.id, symbol=strategy.symbol, side=strategy.side,
            total_capital=str(strategy.total_capital),
            current_loss_amount=str(loss_amount.quantize(Decimal("0.01"))),
            pnl_pct=pnl_pct,
        )
        self.risk_service.mark_reentry_ready(strategy.id)

    # ──────────────── 크라이시스 복구 모드 액션 (Phase D-2) ────────────────
    def _execute_crisis_action(self, strategy, action: str) -> None:
        """크라이시스 모드 3 액션 처리 — TP1(+5%) / TRAIL_FULL / HARD_SL."""
        from datetime import datetime, timezone
        # SHORT 포지션은 음수 qty 로 저장됨 — abs() 로 양수화 후 청산.
        # 이전엔 `current_qty <= 0` 이라 SHORT 크라이시스가 모두 return 되는 버그가 있었음.
        current_qty = abs(Decimal(str(strategy.current_position_qty)))
        if current_qty == 0:
            return

        if action == "CRISIS_TP1":
            # 25% 청산 — 첫 TP 발동
            close_qty = (current_qty * Decimal("0.25")).quantize(Decimal("0.00000001"))
            if close_qty <= 0:
                return
            self.execution_service.emergency_close_position(strategy.id, quantity=close_qty)
            strategy.status = "CRISIS_TP1_DONE"
            strategy.crisis_first_tp_done_at = datetime.now(timezone.utc)
            # 피크 PnL 초기화 (지금부터 추적 시작)
            avg_entry = Decimal(str(strategy.avg_entry_price)) if strategy.avg_entry_price else None
            try:
                from app.repositories.position_repository import PositionRepository
                latest_pos = PositionRepository(self.db).latest_by_strategy(strategy.id)
                if latest_pos and latest_pos.mark_price and avg_entry:
                    mark = Decimal(str(latest_pos.mark_price))
                    cur_pnl = ((mark - avg_entry) / avg_entry * Decimal("100")) if strategy.side == "LONG" else ((avg_entry - mark) / avg_entry * Decimal("100"))
                    strategy.peak_pnl_pct_after_first_tp = cur_pnl
            except Exception:
                pass
            self.db.commit()
            strategy_take_profit_total.labels(symbol=strategy.symbol, side=strategy.side, level="CRISIS_TP1").inc()
            self.notification_service.send_crisis_first_tp(
                strategy_instance_id=strategy.id, symbol=strategy.symbol, side=strategy.side,
                pnl_pct=str(strategy.peak_pnl_pct_after_first_tp or "5"), closed_qty=close_qty,
            )

        elif action == "CRISIS_TRAIL_FULL":
            # 남은 전량 청산 — 트레일링 보호 발동
            self.execution_service.emergency_close_position(strategy.id, quantity=current_qty)
            strategy.status = "COMPLETED"
            strategy.reentry_ready = False
            self.risk_service.reset_peak_pnl(strategy.id)
            self.db.commit()
            strategy_take_profit_total.labels(symbol=strategy.symbol, side=strategy.side, level="CRISIS_TRAIL_FULL").inc()
            # 현재 PnL 추출
            try:
                from app.repositories.position_repository import PositionRepository
                latest_pos = PositionRepository(self.db).latest_by_strategy(strategy.id)
                cur_pnl = "?"
                if latest_pos and latest_pos.mark_price and strategy.avg_entry_price:
                    avg = Decimal(str(strategy.avg_entry_price))
                    mark = Decimal(str(latest_pos.mark_price))
                    cur_pnl = str((mark - avg) / avg * Decimal("100") if strategy.side == "LONG" else (avg - mark) / avg * Decimal("100"))
            except Exception:
                cur_pnl = "?"
            self.notification_service.send_crisis_trailing_full(
                strategy_instance_id=strategy.id, symbol=strategy.symbol, side=strategy.side,
                peak_pnl_pct=str(strategy.peak_pnl_pct_after_first_tp or "?"), current_pnl_pct=cur_pnl,
            )

        elif action == "CRISIS_HARD_SL":
            # 남은 전량 손절 — 빠른 손절
            self.execution_service.emergency_close_position(strategy.id, quantity=current_qty)
            strategy.status = "STOPPING"
            self.db.commit()
            strategy_stop_loss_total.labels(symbol=strategy.symbol, side=strategy.side).inc()
            try:
                from app.repositories.position_repository import PositionRepository
                latest_pos = PositionRepository(self.db).latest_by_strategy(strategy.id)
                cur_pnl = "?"
                if latest_pos and latest_pos.mark_price and strategy.avg_entry_price:
                    avg = Decimal(str(strategy.avg_entry_price))
                    mark = Decimal(str(latest_pos.mark_price))
                    cur_pnl = str((mark - avg) / avg * Decimal("100") if strategy.side == "LONG" else (avg - mark) / avg * Decimal("100"))
            except Exception:
                cur_pnl = "?"
            self.notification_service.send_crisis_hard_sl(
                strategy_instance_id=strategy.id, symbol=strategy.symbol, side=strategy.side, pnl_pct=cur_pnl,
            )
            self.risk_service.mark_reentry_ready(strategy.id)
