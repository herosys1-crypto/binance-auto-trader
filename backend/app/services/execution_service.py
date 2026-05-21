import logging
import time
from decimal import Decimal
from uuid import uuid4
from app.core.redis_client import get_redis_client
from app.core.redis_lock import redis_lock, RedisLockError
from app.core.strategy_status import MANUAL_CLEANUP_REQUIRED
from app.integrations.binance.client import BinanceClient
from app.integrations.binance.futures_trade import BinanceFuturesTradeClient
from app.integrations.binance.execution.router import ExecutionAdapterRouter
from app.integrations.binance.execution.plain_order_adapter import PlainOrderAdapter
from app.models.order import Order
from app.models.risk_event import RiskEvent
from app.repositories.order_repository import OrderRepository
from app.repositories.strategy_repository import StrategyRepository
from app.services.account_kill_switch_service import AccountKillSwitchService
from app.core.sentry import capture_strategy_event

# 2026-05-21 Phase 2 (#77/#78 사후 사장님 요구):
# emergency_close 주문 발송 후 거래소가 실제로 포지션을 감소시켰는지 검증.
# 응답 (response) 이 성공이라도 reduceOnly 거절 / 부분 체결 후 정지 등으로
# 실 포지션이 의도대로 줄지 않는 케이스 발생 가능 (#77 PHB / #78 RONIN).
# 3초 = MARKET 즉시체결 + Binance internal state 반영 여유. 너무 짧으면 false-positive,
# 너무 길면 API 응답 지연 체감.
EMERGENCY_CLOSE_VERIFY_DELAY_SECONDS = 3.0

# 자동 재시도 — 1차 검증 실패 후 10초 대기 후 잔량 재청산 1회.
# 10초: rate limit 회피 + 거래소 internal state 안정화. 너무 짧으면 같은 거절 반복,
# 너무 길면 사장님 대기 시간 ↑. 재시도도 검증 → 그래도 실패면 MANUAL_CLEANUP_REQUIRED.
# 자동 재시도가 합리적인 케이스: 거래소 일시 지연, 부분 체결 후 잔량, rate-limit.
# 자동 재시도가 무의미한 케이스 (-2022 reduceOnly, -2027 마진 부족) 는 재시도 후에도
# 같은 결과 → MANUAL_CLEANUP_REQUIRED 로 빠짐. 명확한 분기는 Phase 3 후보.
EMERGENCY_CLOSE_RETRY_DELAY_SECONDS = 10.0

# 검증 성공 임계 — 90% 이상 감소면 성공 처리 (수수료/부분 체결 잔량 허용).
EMERGENCY_CLOSE_SUCCESS_THRESHOLD_RATIO = Decimal("0.9")

logger = logging.getLogger(__name__)


class EmergencyCloseInProgress(Exception):
    """다른 caller 가 같은 strategy 의 emergency_close 를 처리 중 — 중복 발사 방지."""
    pass

class ExecutionService:
    def __init__(self, db, *, api_key: str, api_secret: str, is_testnet: bool = False) -> None:
        self.db = db
        self.strategy_repo = StrategyRepository(db)
        self.order_repo = OrderRepository(db)
        self.client = BinanceClient(api_key=api_key, api_secret=api_secret, is_testnet=is_testnet)
        self.trade_client = BinanceFuturesTradeClient(self.client)
        self.execution_router = ExecutionAdapterRouter(plain_adapter=PlainOrderAdapter(self.client), algo_adapter=None)

    def apply_leverage(self, strategy):
        return self.client.change_leverage(symbol=strategy.symbol, leverage=strategy.leverage)

    def _margin_cache_key(self, strategy) -> str:
        return f"margin_iso:account:{strategy.exchange_account_id}:symbol:{strategy.symbol}"

    def ensure_isolated_margin(self, strategy) -> None:
        """심볼의 마진 모드를 ISOLATED 로 강제 설정 (사용자 결정 2026-05-06).

        모든 신규 strategy 가 ISOLATED 로 진입해야 「💰 증거금 추가」 사용 가능.
        Binance 정책: 빈 포지션일 때만 변경 가능. 포지션 보유 중 호출 시 -4048 거부.
        이미 ISOLATED 면 -4046 ("No need to change margin type") 응답 — 무시 (idempotent).

        호출 위치: 진입 직전 (start_stage1 / enter_stage_at_market / add_position_now).
        실패 시: warning 로그만 (본 진입 흐름은 진행). CROSS 로 진입되더라도 거래는
        가능하지만 「증거금 추가」 만 못 함.

        2026-05-17 (rate limit ban 사후 — Fix 3): 한 번 ISOLATED 확정되면 Redis 에
        1h 캐시 → 이후 진입 시 change_margin_type 호출 자체를 skip (weight 절감).
        Redis 장애 시 fail-open (기존처럼 매번 호출 — 동작 변화 없음).
        """
        # Redis 캐시 hit 시 거래소 호출 skip (fail-open)
        _redis = None
        try:
            from app.core.redis_client import get_redis_client
            _redis = get_redis_client()
            if _redis is not None and _redis.get(self._margin_cache_key(strategy)):
                logger.debug("ensure_isolated_margin cache hit — skip API strategy=%s symbol=%s",
                             strategy.id, strategy.symbol)
                return
        except Exception:
            _redis = None  # fail-open

        def _mark_cached():
            if _redis is None:
                return
            try:
                _redis.setex(self._margin_cache_key(strategy), 3600, "ISOLATED")
            except Exception:
                pass

        try:
            self.client.change_margin_type(symbol=strategy.symbol, margin_type="ISOLATED")
            logger.info("ensure_isolated_margin OK strategy=%s symbol=%s", strategy.id, strategy.symbol)
            _mark_cached()
        except Exception as e:
            err_msg = str(e)
            # -4046: 이미 같은 마진 모드 (idempotent OK) — 캐시 마킹 (다음부터 skip)
            if "-4046" in err_msg or "no need" in err_msg.lower():
                logger.info("ensure_isolated_margin already ISOLATED (idempotent) strategy=%s symbol=%s",
                            strategy.id, strategy.symbol)
                _mark_cached()
                return
            # -4048: 포지션 보유 중 변경 불가 — warning 만 (강제 진행, 캐시 안 함)
            # 다른 에러 — warning 만 (본 진입 흐름 막지 않음, 캐시 안 함)
            logger.warning(
                "ensure_isolated_margin failed (continuing anyway): strategy=%s symbol=%s error=%s",
                strategy.id, strategy.symbol, e,
            )

    def start_stage1(self, strategy_id: int) -> Order:
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        if AccountKillSwitchService(self.db).is_enabled(strategy.exchange_account_id):
            raise ValueError("Account kill-switch is enabled; new orders are blocked")
        stage_plan = next((p for p in strategy.stage_plans if p.stage_no == 1), None)
        if not stage_plan:
            raise ValueError("Stage 1 plan not found")
        self.ensure_isolated_margin(strategy)  # 2026-05-06 (사용자 결정): 모든 거래 ISOLATED
        self.apply_leverage(strategy)
        order = self._place_stage_entry_order(strategy, stage_plan)
        strategy.status = "STAGE1_OPEN_PENDING"
        strategy.current_stage = 1
        self.db.commit()
        self.db.refresh(order)
        # 2026-05-11 (사용자 요청): 단계 1 진입 시 추가 증거금 자동 투입 (옵션).
        # additional_margin_usdt > 0 이면 add_position_margin 호출. 실패해도 entry 자체는
        # 정상 진행 — 사용자에게 RiskEvent + Telegram 알림. 호출자(API) 가 그 처리.
        add_m = stage_plan.additional_margin_usdt
        if add_m and Decimal(str(add_m)) > 0:
            try:
                self.add_position_margin(strategy_id, amount=Decimal(str(add_m)))
                logger.info(
                    "start_stage1: additional margin +%s USDT applied to strategy=%s symbol=%s",
                    add_m, strategy_id, strategy.symbol,
                )
            except Exception as e:
                logger.warning(
                    "start_stage1: additional margin failed strategy=%s: %s (entry already placed)",
                    strategy_id, e,
                )
                # entry 는 정상이라 raise 안 함 — 별도 RiskEvent 만 기록
                self.db.add(RiskEvent(
                    strategy_instance_id=strategy_id,
                    event_type="STAGE_ADDITIONAL_MARGIN_FAILED",
                    severity="WARN",
                    title="⚠️ 단계 1 추가 증거금 투입 실패 (entry 는 정상)",
                    message=f"단계 1 entry 정상 발사. 추가 증거금 {add_m} USDT 투입 실패: {e}. 수동 처리 필요.",
                    event_payload={"strategy_id": strategy_id, "stage_no": 1, "amount": str(add_m), "error": str(e)},
                ))
                self.db.commit()
        return order

    def trigger_next_stage(self, strategy_id: int, stage_no: int) -> Order:
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        # 2026-05-04 fix: kill-switch 가 stage 1 (start_stage1) 에만 체크되던 버그.
        # stage 2~10 자동 진입은 신규 거래임에도 차단 안 돼 kill-switch 안전장치 부분 무력.
        # 이제는 모든 stage 진입에서 차단.
        if AccountKillSwitchService(self.db).is_enabled(strategy.exchange_account_id):
            raise ValueError(
                f"Account kill-switch is enabled; stage {stage_no} entry blocked. "
                "Kill-switch 를 해제한 후 재시도하세요."
            )
        stage_plan = next((p for p in strategy.stage_plans if p.stage_no == stage_no), None)
        if not stage_plan:
            raise ValueError(f"Stage {stage_no} plan not found")
        order = self._place_stage_entry_order(strategy, stage_plan)
        strategy.current_stage = stage_no
        # 2026-05-04 fix: 옵션 C 1~10단계 동적 — 이전엔 2/3/4 만 dict 있어 5+ stage 진입 시
        # status 변경 안 됨. f-string 으로 N단계 모두 STAGE{N}_OPEN_PENDING 처리.
        if 2 <= stage_no <= 10:
            strategy.status = f"STAGE{stage_no}_OPEN_PENDING"
        self.db.commit()
        self.db.refresh(order)
        return order

    def emergency_close_position(self, strategy_id: int, *, quantity: Decimal) -> Order:
        # 2026-05-08 (사용자 #120 DYDXUSDT orphan 사례): emergency_close_position 이
        # 같은 strategy 에 대해 동시 다발 호출되면 (manual stop API + tp_sl_orchestrator
        # + admin cleanup 등) 같은 양 (예: 245 DYDX) 이 여러 번 청산되어 거래소-DB
        # 불일치 → orphan → KS 발동. caller 측 락이 다 따로라 함수 자체에 idempotency
        # 락 추가. TTL 5s — 중복 차단엔 충분, 정상 retry 는 통과 가능.
        redis_client = get_redis_client()
        lock_key = f"lock:strategy:{strategy_id}:emergency_close"
        try:
            with redis_lock(redis_client, lock_key, ttl_seconds=5, wait_timeout_seconds=0):
                return self._emergency_close_position_locked(strategy_id, quantity=quantity)
        except RedisLockError:
            logger.warning(
                "emergency_close_position skipped — duplicate call within 5s window: strategy_id=%s qty=%s",
                strategy_id, quantity,
            )
            raise EmergencyCloseInProgress(
                f"strategy_id={strategy_id} 의 청산이 이미 진행 중 — 중복 호출 차단"
            )

    def _emergency_close_position_locked(self, strategy_id: int, *, quantity: Decimal) -> Order:
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        # Bug #8 fix (2026-04-29): 포지션이 0 인 전략에 대한 reduceOnly 주문은
        # Binance 가 -2022 "ReduceOnly Order is rejected" 로 거절.
        # Bug #8 강화 (2026-04-29 PM): DB 의 quantity 가 stale 일 수 있어 (예: REENTRY_READY
        # 상태인데 current_position_qty 가 옛값) 진짜 거래소 포지션을 먼저 확인.
        # 거래소가 0 이면 미체결 주문만 취소하고 STOPPED 마킹.
        try:
            position_risk = self.client.get_position_risk(symbol=strategy.symbol)
            if isinstance(position_risk, dict):
                position_risk = [position_risk]
            actual_position = Decimal("0")
            for item in position_risk:
                if item.get("symbol") == strategy.symbol and item.get("positionSide") == strategy.side:
                    actual_position = abs(Decimal(str(item.get("positionAmt", "0"))))
                    break
        except Exception:
            actual_position = abs(Decimal(str(quantity))) if quantity else Decimal("0")
        if actual_position == 0:
            # 거래소에 포지션 없음 — 미체결 주문 취소만 + STOPPED
            try:
                self.client.cancel_all_orders(symbol=strategy.symbol)
            except Exception:
                pass
            strategy.status = "STOPPED"
            strategy.current_position_qty = Decimal("0")
            self.db.commit()
            raise ValueError(
                f"Exchange has no {strategy.side} position for {strategy.symbol}; "
                "cancelled pending orders and marked STOPPED. No reduceOnly market order sent."
            )
        # 거래소 실 포지션과 비교하여 cap 만 함 (요청 qty 가 더 크면 거래소 값으로 줄임).
        # 이전 버전은 무조건 quantity = actual_position 으로 덮어쓰는 critical bug:
        # 부분 TP1 요청 (25% = 199) 도 거래소 풀 포지션 (798) 으로 닫혀버림.
        # 부분 TP/SL 정상 동작을 위해 over-close 만 방지하는 cap 으로 변경.
        try:
            req_qty = abs(Decimal(str(quantity))) if quantity else Decimal("0")
        except Exception:
            req_qty = Decimal("0")
        if req_qty <= 0 or req_qty > actual_position:
            quantity = actual_position  # 요청 없거나 실 포지션 초과 시 풀 청산
        else:
            quantity = req_qty  # 부분 청산 정상 진행 (TP1 25% 등)
        side = "SELL" if strategy.side == "LONG" else "BUY"
        position_side = strategy.side
        client_order_id = self._new_client_order_id(strategy.symbol, "EXIT")
        # Bug fix (2026-05-02 evening, #79 race condition 사례):
        # 이전 흐름:
        #   1) place_market_order → 즉시 체결 + Binance stream EXIT FILLED 이벤트 발송
        #   2) Order DB 추가
        #   3) strategy.status = STOPPING
        #   4) commit
        # user-stream worker 가 1)의 stream event 를 받았을 때 우리 transaction 이
        # 4)의 commit 전이라 다른 session 에서는 옛 status (예: TP3_DONE_PARTIAL) 를 봄
        # → stream_service 의 STOPPING 분기 못 타고 else (REENTRY_READY) 로 잘못 빠짐.
        # 새 흐름: status 변경을 먼저 commit 해서 외부 worker 에게 노출한 뒤 거래소 호출.
        # 단, _execute_take_profit 에서 호출되는 경우 status 가 이미 TP/COMPLETED 로 갔으므로
        # 무조건 STOPPING 으로 덮어쓰지 않게 — current status 가 STAGE_X_OPEN 류일 때만.
        # 2026-05-06: TP1~10_DONE_PARTIAL 모두 보호 (10단계 익절 확장).
        _TP_PARTIAL_SET = {f"TP{n}_DONE_PARTIAL" for n in range(1, 11)}
        if strategy.status not in ({"COMPLETED", "REENTRY_READY", "STOPPED"} | _TP_PARTIAL_SET):
            strategy.status = "STOPPING"
        self.db.commit()
        # A03 fix (audit 2026-05-02): 거래소 호출 실패 시 명시적 로깅 + RiskEvent 기록.
        # 2026-05-13 v4 fix (사용자 #26 JELLYJELLYUSDT 4차 fix):
        # v3 (28자 + underscore) 적용 후에도 -4015 지속 → cid 가 진짜 원인 아닐 수 있음.
        # Fallback: -4015 발생 시 newClientOrderId 빼고 재시도 (Binance 자동 생성).
        # 만약 자동 cid 로도 실패 → real cause 가 cid 무관 (symbol/qty/account 등) — 그 에러가 진짜 원인.
        def _do_place(use_cid: str | None) -> dict:
            if use_cid:
                return self.trade_client.place_market_order(
                    symbol=strategy.symbol, side=side, position_side=position_side,
                    quantity=quantity, new_client_order_id=use_cid,
                )
            # cid 없이 raw payload 로 호출 → Binance 자동 생성
            payload = {
                "symbol": strategy.symbol, "side": side, "positionSide": position_side,
                "type": "MARKET", "quantity": str(quantity),
            }
            return self.client.place_order(payload)

        try:
            response = _do_place(client_order_id)
        except Exception as e:
            err_str = str(e)
            # -4015 fallback: cid 빼고 재시도 (Binance 가 자동 생성)
            if "-4015" in err_str or "Client order id" in err_str:
                logger.warning(
                    "emergency_close: -4015 with cid=%s, retrying WITHOUT newClientOrderId (Binance auto-generate). "
                    "primary_err=%s", client_order_id, err_str,
                )
                try:
                    response = _do_place(None)  # 자동 생성 시도
                    binance_cid = response.get("clientOrderId", "")
                    logger.info(
                        "emergency_close: succeeded without our cid — Binance auto cid=%s strategy_id=%s",
                        binance_cid, strategy.id,
                    )
                    client_order_id = binance_cid or client_order_id  # DB 저장용 (auto cid 우선)
                except Exception as retry_err:
                    # 자동 cid 도 실패 → 진짜 원인은 cid 무관 (symbol/qty/account/position 등)
                    logger.error(
                        "emergency_close: failed EVEN without cid — real underlying issue: %s", retry_err,
                    )
                    self.db.add(RiskEvent(
                        strategy_instance_id=strategy.id,
                        event_type="EMERGENCY_CLOSE_PLACE_FAILED",
                        severity="ERROR",
                        title="Emergency close 시장가 주문 발송 실패 (auto-cid 도 실패)",
                        message=f"symbol={strategy.symbol} qty={quantity} side={side} primary_err={err_str} retry_err={retry_err}",
                        event_payload={"strategy_id": strategy.id, "quantity": str(quantity), "side": side, "primary_error": err_str, "retry_error": str(retry_err)},
                    ))
                    self.db.commit()
                    capture_strategy_event(
                        "emergency_close failed even without cid",
                        level="error",
                        strategy_id=strategy.id, symbol=strategy.symbol, side=strategy.side,
                        account_id=strategy.exchange_account_id, error=retry_err,
                        extras={"quantity": str(quantity), "primary_error": err_str},
                        tags={"event_type": "EMERGENCY_CLOSE_PLACE_FAILED_EVEN_AUTO_CID"},
                    )
                    raise retry_err
            elif "-4131" in err_str or "PERCENT_PRICE" in err_str:
                # 2026-05-19 (#62 MLNUSDT): 저유동성 심볼 MARKET 청산이 PERCENT_PRICE
                # 밴드 밖 → -4131. 밴드 경계가 LIMIT GTC 로 폴백 (가능한 만큼 즉시
                # 청산 + 잔여 유효주문 대기 → reconcile 추적). 전량 실패 루프 차단.
                logger.warning(
                    "emergency_close: -4131 PERCENT_PRICE — LIMIT 폴백 시도 strategy=%s symbol=%s",
                    strategy.id, strategy.symbol,
                )
                try:
                    response = self._emergency_close_limit_fallback(
                        strategy, side=side, position_side=position_side,
                        quantity=quantity, client_order_id=client_order_id,
                    )
                    _emergency_order_type = "LIMIT"
                    _emergency_tif = "GTC"
                    self.db.add(RiskEvent(
                        strategy_instance_id=strategy.id,
                        event_type="EMERGENCY_CLOSE_LIMIT_FALLBACK",
                        severity="WARN",
                        title="⚠️ 저유동성 청산 — MARKET 거부(-4131) → LIMIT 폴백",
                        message=(
                            f"{strategy.symbol} {side} qty={quantity} — 호가 얇아 MARKET "
                            f"-4131. PERCENT_PRICE 밴드 경계 LIMIT GTC 발송 (잔여는 대기)."
                        ),
                        event_payload={"strategy_id": strategy.id, "quantity": str(quantity), "side": side},
                    ))
                    self.db.commit()
                except Exception as fb_err:
                    logger.error(
                        "emergency_close: -4131 LIMIT 폴백도 실패 strategy=%s err=%s",
                        strategy.id, fb_err,
                    )
                    self.db.add(RiskEvent(
                        strategy_instance_id=strategy.id,
                        event_type="EMERGENCY_CLOSE_PLACE_FAILED",
                        severity="ERROR",
                        title="Emergency close 실패 (-4131 + LIMIT 폴백 실패)",
                        message=f"symbol={strategy.symbol} qty={quantity} side={side} market_err={err_str} fallback_err={fb_err}",
                        event_payload={"strategy_id": strategy.id, "quantity": str(quantity), "side": side, "market_error": err_str, "fallback_error": str(fb_err)},
                    ))
                    self.db.commit()
                    capture_strategy_event(
                        "emergency_close -4131 limit fallback failed",
                        level="error", strategy_id=strategy.id, symbol=strategy.symbol,
                        side=strategy.side, account_id=strategy.exchange_account_id, error=fb_err,
                        extras={"quantity": str(quantity), "market_error": err_str},
                        tags={"event_type": "EMERGENCY_CLOSE_4131_FALLBACK_FAILED"},
                    )
                    raise fb_err
            else:
                # -4015 외 다른 에러 — 기존 처리
                logger.error(
                    "emergency_close place_market_order failed: strategy_id=%s symbol=%s qty=%s side=%s error=%s",
                    strategy.id, strategy.symbol, quantity, side, e,
                )
                self.db.add(RiskEvent(
                    strategy_instance_id=strategy.id,
                    event_type="EMERGENCY_CLOSE_PLACE_FAILED",
                    severity="ERROR",
                    title="Emergency close 시장가 주문 발송 실패",
                    message=f"symbol={strategy.symbol} qty={quantity} side={side} error={e}",
                    event_payload={"strategy_id": strategy.id, "quantity": str(quantity), "side": side, "error": str(e)},
                ))
                self.db.commit()
                capture_strategy_event(
                    "emergency_close place_market_order failed",
                    level="error",
                    strategy_id=strategy.id, symbol=strategy.symbol, side=strategy.side,
                    account_id=strategy.exchange_account_id, error=e,
                    extras={"quantity": str(quantity), "exit_side": side},
                    tags={"event_type": "EMERGENCY_CLOSE_PLACE_FAILED"},
                )
                raise
        _ot = locals().get("_emergency_order_type", "MARKET")
        _tif = locals().get("_emergency_tif", None)
        order = Order(strategy_instance_id=strategy.id, stage_no=None, purpose="EXIT", symbol=strategy.symbol, side=side, position_side=position_side, order_type=_ot, time_in_force=_tif, client_order_id=client_order_id, exchange_order_id=response.get("orderId"), trigger_price=None, price=Decimal(str(response.get("price"))) if response.get("price") and Decimal(str(response.get("price"))) > 0 else (Decimal(str(response.get("avgPrice"))) if response.get("avgPrice") else None), orig_qty=quantity, executed_qty=Decimal(str(response.get("executedQty", "0"))), avg_price=Decimal(str(response.get("avgPrice"))) if response.get("avgPrice") else None, status=response.get("status", "NEW"), raw_request={"symbol": strategy.symbol, "side": side, "positionSide": position_side, "type": _ot, "quantity": str(quantity), "newClientOrderId": client_order_id}, raw_response=response)
        self.order_repo.create(order)
        self.db.commit()

        # 2026-05-21 Phase 2 post-verify (#77/#78 사후 사장님 요구):
        # 청산 주문 「접수」 응답은 받았지만 거래소가 실제로 포지션을 줄였는지 별개.
        # reduceOnly 거절 / 부분 체결 후 멈춤 / 거래소 내부 지연 등의 케이스 발생 가능.
        #
        # Phase 2B (사장님 요구 — 진입/TP/SL 도 검증):
        #   - MARKET 청산 모두 검증 (이전엔 STOPPING 만 — TP/SL 누락됐었음)
        #   - is_full_close=True (전량): 검증 실패 시 MANUAL_CLEANUP_REQUIRED 전환 (기존 흐름)
        #   - is_full_close=False (부분 — TP): 검증 실패 시 알림만 (status 변경 X)
        #     이유: `_execute_take_profit` 가 호출 후 status 를 TP_N_DONE_PARTIAL 로 덮어쓰므로
        #          여기서 status MANUAL_CLEANUP_REQUIRED 로 set 해도 무효화됨 (race).
        # LIMIT 폴백은 즉시 체결 보장 X → 검증 skip (reconcile/Phase 1 가드가 백업).
        if _ot == "MARKET":
            is_full_close = quantity >= actual_position
            self._verify_emergency_close_applied(
                strategy,
                initial_position=actual_position,
                requested_close_qty=quantity,
                is_full_close=is_full_close,
            )

        return order

    def _fetch_current_position_qty(self, strategy) -> Decimal | None:
        """거래소에서 현재 포지션 qty (절댓값) 조회. 실패 시 None.

        emergency_close 검증 + 재시도 검증에서 공통 사용.
        """
        try:
            position_risk = self.client.get_position_risk(symbol=strategy.symbol)
            if isinstance(position_risk, dict):
                position_risk = [position_risk]
            for item in position_risk:
                if (
                    item.get("symbol") == strategy.symbol
                    and item.get("positionSide") == strategy.side
                ):
                    return abs(Decimal(str(item.get("positionAmt", "0"))))
            return Decimal("0")  # matched=None = 포지션 없음
        except Exception as e:
            logger.warning(
                "post-verify get_position_risk 실패: strategy=%s err=%s", strategy.id, e,
            )
            return None

    def _is_close_successful(
        self, *, initial_position: Decimal, post_position: Decimal,
        requested_close_qty: Decimal,
    ) -> bool:
        """청산 성공 판정 — 의도된 감소량의 90% 이상이면 성공.

        수수료 / 부분 체결 잔량 허용. 분자: 실 감소량, 분모: 요청 청산 qty.
        """
        actual_reduction = initial_position - post_position
        success_threshold = requested_close_qty * EMERGENCY_CLOSE_SUCCESS_THRESHOLD_RATIO
        return actual_reduction >= success_threshold

    def _verify_emergency_close_applied(
        self,
        strategy,
        *,
        initial_position: Decimal,
        requested_close_qty: Decimal,
        is_full_close: bool = True,
    ) -> None:
        """청산 주문 후 거래소 포지션 검증 + 자동 재시도 1회 + 실패 시 알림/전환.

        흐름:
          1) 3초 대기 → 거래소 포지션 조회
          2) 90% 이상 감소 → 성공, status 유지
          3) 1차 검증 실패 → 10초 대기 → 잔량 재청산 발송 (자동 재시도 1회)
          4) 재시도 검증 → 성공 시 정상, 실패 시:
             - is_full_close=True (긴급/SL 전량 청산): MANUAL_CLEANUP_REQUIRED 전환 + 텔레그램
             - is_full_close=False (TP 부분 청산): 알림만 (status 변경 X, race 방지)

        의도:
          - 사장님 부담 최소화 — 거래소 일시 지연/부분 체결/rate-limit 케이스 자동 회복
          - 자동 재시도 무의미한 케이스 (-2022 reduceOnly, -2027 마진부족) 는 재시도 후에도
            같은 결과 → MANUAL_CLEANUP_REQUIRED (전량) 또는 알림 (부분) 로 빠짐
          - 자동 STOPPED 차단 — 사장님이 거래소에서 직접 청산 후 「✅ 처리 완료」 명시적 ack
          - TP 부분 청산 실패 시 status 변경 안 함 — `_execute_take_profit` 의 status 덮어
            쓰기 race 방지. 다음 cycle 에서 자연 재평가 + 알림으로 사장님 인지.

        검증 호출 자체 실패 (네트워크) 시 status 변경 안 함 — Phase 1 의 5분 가드 백업.
        """
        # ===== 1차 검증 =====
        time.sleep(EMERGENCY_CLOSE_VERIFY_DELAY_SECONDS)
        post_position = self._fetch_current_position_qty(strategy)
        if post_position is None:
            # 검증 호출 자체 실패 — Phase 1 5분 가드가 백업. 보수적으로 status 유지.
            return
        if self._is_close_successful(
            initial_position=initial_position, post_position=post_position,
            requested_close_qty=requested_close_qty,
        ):
            logger.info(
                "emergency_close 1차 검증 성공: strategy=%s initial=%s post=%s",
                strategy.id, initial_position, post_position,
            )
            return

        # ===== 자동 재시도 1회 =====
        # 잔량 (post_position) 기반으로 재청산 — 부분 체결 케이스 정확히 처리.
        retry_qty = post_position
        if retry_qty <= 0:
            # 사실 닫혔는데 race 로 0 반환된 케이스 — 성공으로 간주.
            return

        logger.warning(
            "emergency_close 1차 검증 실패 → 자동 재시도 (%.0f초 후): "
            "strategy=%s initial=%s post=%s retry_qty=%s",
            EMERGENCY_CLOSE_RETRY_DELAY_SECONDS, strategy.id, initial_position,
            post_position, retry_qty,
        )
        self.db.add(RiskEvent(
            strategy_instance_id=strategy.id,
            event_type="EMERGENCY_CLOSE_RETRY_ATTEMPTED",
            severity="WARN",
            title=f"🔁 청산 자동 재시도 — #{strategy.id} {strategy.symbol} {strategy.side}",
            message=(
                f"1차 검증 실패 — 잔량 {retry_qty} 재청산 시도. "
                f"성공 시 정상 종료, 실패 시 MANUAL_CLEANUP_REQUIRED 전환."
            ),
            event_payload={
                "strategy_id": strategy.id,
                "initial_position": str(initial_position),
                "post_position_after_first": str(post_position),
                "retry_qty": str(retry_qty),
            },
        ))
        self.db.commit()

        time.sleep(EMERGENCY_CLOSE_RETRY_DELAY_SECONDS)

        side = "SELL" if strategy.side == "LONG" else "BUY"
        retry_cid = self._new_client_order_id(strategy.symbol, "EXIT_RETRY")
        try:
            self.trade_client.place_market_order(
                symbol=strategy.symbol, side=side, position_side=strategy.side,
                quantity=retry_qty, new_client_order_id=retry_cid,
            )
        except Exception as e:
            # 재시도 호출 자체 실패 → 분기별 처리 (전량: MANUAL_CLEANUP_REQUIRED / 부분: 알림만)
            logger.warning(
                "emergency_close 재시도 발송 실패: strategy=%s err=%s — fail-handler 분기",
                strategy.id, e,
            )
            self._handle_close_verify_failure(
                strategy,
                initial_position=initial_position,
                post_position=post_position,
                requested_close_qty=requested_close_qty,
                retry_error=str(e),
                is_full_close=is_full_close,
            )
            return

        # 재시도 검증
        time.sleep(EMERGENCY_CLOSE_VERIFY_DELAY_SECONDS)
        post_retry = self._fetch_current_position_qty(strategy)
        if post_retry is None:
            # 재시도 후 검증 호출 실패 — 보수적으로 fail-handler 분기
            self._handle_close_verify_failure(
                strategy,
                initial_position=initial_position,
                post_position=post_position,
                requested_close_qty=requested_close_qty,
                retry_error="post-retry verify call failed",
                is_full_close=is_full_close,
            )
            return

        if self._is_close_successful(
            initial_position=initial_position, post_position=post_retry,
            requested_close_qty=requested_close_qty,
        ):
            logger.info(
                "emergency_close 재시도 성공: strategy=%s post_retry=%s",
                strategy.id, post_retry,
            )
            self.db.add(RiskEvent(
                strategy_instance_id=strategy.id,
                event_type="EMERGENCY_CLOSE_RETRY_SUCCEEDED",
                severity="INFO",
                title=f"✅ 청산 재시도 성공 — #{strategy.id} {strategy.symbol} {strategy.side}",
                message=(
                    f"1차 검증 실패 후 자동 재시도로 정상 청산 완료. "
                    f"초기 {initial_position} → 1차 후 {post_position} → 재시도 후 {post_retry}."
                ),
                event_payload={
                    "strategy_id": strategy.id,
                    "initial_position": str(initial_position),
                    "post_position_after_first": str(post_position),
                    "post_position_after_retry": str(post_retry),
                },
            ))
            self.db.commit()
            return

        # 재시도도 실패 → 분기별 fail-handler
        self._handle_close_verify_failure(
            strategy,
            initial_position=initial_position,
            post_position=post_retry,
            requested_close_qty=requested_close_qty,
            retry_error=None,
            is_full_close=is_full_close,
        )

    def _handle_close_verify_failure(
        self,
        strategy,
        *,
        initial_position: Decimal,
        post_position: Decimal,
        requested_close_qty: Decimal,
        retry_error: str | None,
        is_full_close: bool,
    ) -> None:
        """검증 + 재시도 모두 실패 시 분기 처리.

        - is_full_close=True: status STOPPING → MANUAL_CLEANUP_REQUIRED 전환 + 텔레그램
        - is_full_close=False (TP 부분 청산): status 변경 X, 알림 + RiskEvent 만
          이유: `_execute_take_profit` 가 호출 후 status TP_N_DONE_PARTIAL 로 덮어쓰므로
          status MANUAL_CLEANUP_REQUIRED 로 set 해도 무효화 (race). 부분 청산은 다음 cycle
          에서 자연 재평가 + 사장님 인지로 처리.
        """
        if is_full_close:
            self._promote_to_manual_cleanup(
                strategy,
                initial_position=initial_position,
                post_position=post_position,
                requested_close_qty=requested_close_qty,
                retry_error=retry_error,
            )
        else:
            self._notify_partial_close_verify_failed(
                strategy,
                initial_position=initial_position,
                post_position=post_position,
                requested_close_qty=requested_close_qty,
                retry_error=retry_error,
            )

    def _promote_to_manual_cleanup(
        self,
        strategy,
        *,
        initial_position: Decimal,
        post_position: Decimal,
        requested_close_qty: Decimal,
        retry_error: str | None,
    ) -> None:
        """전량 청산 검증 실패 — MANUAL_CLEANUP_REQUIRED 전환 + 텔레그램 CRITICAL + RiskEvent."""
        actual_reduction = initial_position - post_position
        logger.critical(
            "emergency_close 재시도 후에도 실패 — MANUAL_CLEANUP_REQUIRED: "
            "strategy=%s initial=%s post=%s reduced=%s (목표 %s)",
            strategy.id, initial_position, post_position, actual_reduction, requested_close_qty,
        )
        strategy.status = MANUAL_CLEANUP_REQUIRED
        title = (
            f"🔴 [긴급] 청산 검증 실패 (자동 재시도 후) — #{strategy.id} {strategy.symbol} {strategy.side}"
        )
        retry_status_line = (
            f"  재시도 결과: 발송 실패 ({retry_error})"
            if retry_error
            else f"  재시도 후 거래소 qty: {post_position}"
        )
        body = (
            f"⚠️ 강제 청산 1차 발송 + 자동 재시도 1회 모두 검증 실패.\n"
            f"  발송 전 거래소 qty: {initial_position}\n"
            f"  요청 청산 qty: {requested_close_qty}\n"
            f"{retry_status_line}\n"
            f"  최종 감소량: {actual_reduction} (목표 {requested_close_qty})\n\n"
            f"거래소가 자동 재시도에도 청산을 거절하거나 부분 체결 후 정지함. "
            f"reduceOnly 거절 (-2022) / 마진 부족 (-2027) / 거래소 내부 이슈 의심.\n\n"
            f"status: STOPPING → MANUAL_CLEANUP_REQUIRED 전환됨. "
            f"자동 STOPPED 전환 차단 — 사장님 명시적 처리 필요.\n\n"
            f"조치:\n"
            f"  1) 대시보드의 「🛑 재시도」 추가 시도\n"
            f"  2) 실패 시 Binance 거래소 UI 에서 직접 포지션 청산\n"
            f"  3) 완료 후 대시보드에서 「✅ 수동 청산 처리 완료」 클릭"
        )
        self.db.add(RiskEvent(
            strategy_instance_id=strategy.id,
            event_type="EMERGENCY_CLOSE_VERIFY_FAILED",
            severity="CRITICAL",
            title=title,
            message=body,
            event_payload={
                "strategy_id": strategy.id,
                "initial_position": str(initial_position),
                "requested_close_qty": str(requested_close_qty),
                "post_position": str(post_position),
                "actual_reduction": str(actual_reduction),
                "expected_reduction": str(requested_close_qty),
                "retry_attempted": True,
                "retry_error": retry_error,
            },
        ))
        try:
            from app.services.notification_service import NotificationService
            NotificationService(self.db).send_system_alert(title=title, body=body)
        except Exception as e:
            logger.warning("MANUAL_CLEANUP_REQUIRED 텔레그램 알림 실패: %s", e)
        self.db.commit()

    def _notify_partial_close_verify_failed(
        self,
        strategy,
        *,
        initial_position: Decimal,
        post_position: Decimal,
        requested_close_qty: Decimal,
        retry_error: str | None,
    ) -> None:
        """부분 청산 (TP) 검증 실패 — 알림 + RiskEvent (status 변경 안 함).

        TP 부분 청산이 의도된 비율로 안 줄었어도 `_execute_take_profit` 의 status 전환
        로직 (TP_N_DONE_PARTIAL) 이 진행되어 strategy 는 계속 active. 다음 cycle 에서
        잔량 + 마크 가격 기준 재평가 — 다음 TP 임계 도달 시 자연 재시도. status 변경
        은 race 유발하므로 절대 하지 않음.

        사장님 인지가 핵심 — 텔레그램으로 알려서 reconcile 의 qty mismatch 가드도
        함께 보고 수동 조치 가능.
        """
        actual_reduction = initial_position - post_position
        logger.warning(
            "TP/부분 청산 검증 실패 (재시도 후): strategy=%s initial=%s post=%s reduced=%s (목표 %s)",
            strategy.id, initial_position, post_position, actual_reduction, requested_close_qty,
        )
        title = (
            f"⚠️ TP/부분 청산 검증 실패 — #{strategy.id} {strategy.symbol} {strategy.side}"
        )
        retry_status_line = (
            f"  재시도 결과: 발송 실패 ({retry_error})"
            if retry_error
            else f"  재시도 후 거래소 qty: {post_position}"
        )
        body = (
            f"⚠️ TP 부분 청산 1차 발송 + 자동 재시도 1회 모두 검증 실패.\n"
            f"  발송 전 거래소 qty: {initial_position}\n"
            f"  요청 청산 qty: {requested_close_qty}\n"
            f"{retry_status_line}\n"
            f"  실제 감소량: {actual_reduction} (목표 {requested_close_qty})\n\n"
            f"거래소가 부분 청산을 거절하거나 부분만 체결됨. status 는 변경 안 됨 — "
            f"strategy 는 계속 active. 다음 cycle 에서 잔량 기준 자연 재평가.\n\n"
            f"조치:\n"
            f"  1) 다음 cycle 자동 재평가 확인 (1~2분)\n"
            f"  2) 안 풀리면 「🛑 긴급 종료」 로 전량 청산 (재검증 + 재시도 자동 적용)\n"
            f"  3) 또는 Binance UI 에서 직접 처리"
        )
        self.db.add(RiskEvent(
            strategy_instance_id=strategy.id,
            event_type="PARTIAL_CLOSE_VERIFY_FAILED",
            severity="WARN",
            title=title,
            message=body,
            event_payload={
                "strategy_id": strategy.id,
                "initial_position": str(initial_position),
                "requested_close_qty": str(requested_close_qty),
                "post_position": str(post_position),
                "actual_reduction": str(actual_reduction),
                "retry_attempted": True,
                "retry_error": retry_error,
                "status_unchanged_reason": "TP partial — _execute_take_profit overwrites status",
            },
        ))
        try:
            from app.services.notification_service import NotificationService
            NotificationService(self.db).send_system_alert(title=title, body=body)
        except Exception as e:
            logger.warning("부분 청산 검증 실패 알림 실패: %s", e)
        self.db.commit()

    def cancel_exchange_order(self, *, symbol: str, order_id: int | None = None, orig_client_order_id: str | None = None) -> dict:
        return self.client.cancel_order(symbol=symbol, order_id=order_id, orig_client_order_id=orig_client_order_id)

    def add_position_margin(self, strategy_id: int, *, amount: Decimal) -> dict:
        """ISOLATED 모드 포지션에 증거금 추가.

        검증:
        - strategy 존재 + 포지션 보유 (qty != 0)
        - amount > 0
        - 거래소 호출 실패 시 명확한 에러 메시지 (CROSS 모드면 -4046 에러)

        성공 시 RiskEvent + Telegram 알림 발송.
        """
        if amount is None or amount <= 0:
            raise ValueError(f"증거금 추가 금액은 양수여야 합니다 (입력: {amount})")
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        current_qty = abs(Decimal(str(strategy.current_position_qty or 0)))
        if current_qty == 0:
            raise ValueError(
                f"포지션 없음 (qty=0) — 증거금 추가 불가. "
                f"strategy={strategy.id} status={strategy.status}"
            )
        try:
            response = self.client.add_position_margin(
                symbol=strategy.symbol,
                position_side=strategy.side,  # hedge mode: LONG/SHORT
                amount=str(amount.quantize(Decimal("0.00000001"))),
                margin_type=1,  # 1 = add
            )
        except Exception as e:
            err_msg = str(e)
            # 흔한 에러 친절 매핑
            # 2026-05-06 사용자 보고 fix: -4096 도 동일 의미 매핑.
            # -4046: "No need to change margin type" (이미 같은 모드)
            # -4096: "Add margin only support for isolated position" (CROSS 거부 — 가장 일반적)
            # "isolated" / "marginType" / "CROSS" 키워드 fallback.
            if (
                "-4046" in err_msg or "-4096" in err_msg
                or "marginType" in err_msg.lower() or "CROSS" in err_msg.upper()
                or "isolated" in err_msg.lower()
            ):
                hint = (
                    " (CROSS 모드 포지션은 증거금 직접 추가 불가. "
                    "→ Binance UI 에서 해당 심볼을 ISOLATED 모드로 변경하거나, "
                    "현재 포지션을 종료 후 신규 strategy 시작 시 ISOLATED 로 진입하세요. "
                    "포지션 보유 중엔 마진 모드 변경 불가)"
                )
            elif "-2027" in err_msg or "margin balance" in err_msg.lower():
                hint = " (지갑 잔액 부족 — Binance 계정에 USDT 입금 필요)"
            else:
                hint = ""
            logger.error(
                "add_position_margin failed: strategy=%s symbol=%s amount=%s error=%s",
                strategy.id, strategy.symbol, amount, e,
            )
            self.db.add(RiskEvent(
                strategy_instance_id=strategy.id,
                event_type="ADD_MARGIN_FAILED",
                severity="ERROR",
                title="🛡 증거금 추가 실패",
                message=f"symbol={strategy.symbol} amount={amount} error={e}{hint}",
                event_payload={"amount": str(amount), "error": str(e)},
            ))
            self.db.commit()
            capture_strategy_event(
                "add_position_margin failed",
                level="error",
                strategy_id=strategy.id, symbol=strategy.symbol, side=strategy.side,
                account_id=strategy.exchange_account_id, error=e,
                extras={"amount": str(amount)},
                tags={"event_type": "ADD_MARGIN_FAILED"},
            )
            raise ValueError(f"증거금 추가 실패: {e}{hint}") from e

        # 성공 — RiskEvent + Telegram 알림
        self.db.add(RiskEvent(
            strategy_instance_id=strategy.id,
            event_type="ADD_MARGIN_SUCCESS",
            severity="INFO",
            title="🛡 증거금 추가 완료",
            message=(
                f"{strategy.symbol} {strategy.side} 포지션에 {amount} USDT 추가 — "
                f"청산가 완화 효과."
            ),
            event_payload={
                "amount": str(amount),
                "exchange_response": response,
            },
        ))
        self.db.commit()
        # Telegram (실패해도 거래 흐름 영향 없음)
        try:
            from app.services.notification_service import NotificationService
            NotificationService(self.db).send_margin_added_alert(
                strategy_instance_id=strategy.id,
                symbol=strategy.symbol,
                side=strategy.side,
                amount=amount,
            )
        except Exception:
            pass
        return response

    def _place_stage_entry_order(self, strategy, stage_plan) -> Order:
        if stage_plan.planned_qty is None or stage_plan.trigger_price is None:
            raise ValueError(f"Stage {stage_plan.stage_no} planned_qty/trigger_price is missing")
        side = "BUY" if strategy.side == "LONG" else "SELL"
        position_side = strategy.side
        client_order_id = self._new_client_order_id(strategy.symbol, f"ENTRY{stage_plan.stage_no}")
        payload = {"symbol": strategy.symbol, "side": side, "positionSide": position_side, "type": "LIMIT", "quantity": str(stage_plan.planned_qty), "price": str(stage_plan.trigger_price), "timeInForce": "GTC", "newClientOrderId": client_order_id}
        adapter = self.execution_router.route_for_type(payload["type"])
        response = adapter.place_order(payload)
        order = Order(strategy_instance_id=strategy.id, stage_no=stage_plan.stage_no, purpose="ENTRY", symbol=strategy.symbol, side=side, position_side=position_side, order_type="LIMIT", time_in_force="GTC", client_order_id=client_order_id, exchange_order_id=response.get("orderId"), trigger_price=stage_plan.trigger_price, price=stage_plan.trigger_price, orig_qty=stage_plan.planned_qty, executed_qty=Decimal(str(response.get("executedQty", "0"))), avg_price=Decimal(str(response.get("avgPrice"))) if response.get("avgPrice") else None, status=response.get("status", "NEW"), raw_request=payload, raw_response=response)
        self.order_repo.create(order)
        return order

    # 2026-05-04 (사용자 요청): 수동 「▶ 다음 단계」 = 시장가 즉시 진입.
    # 기존 trigger_next_stage 는 LIMIT @ trigger_price 라서 자동 워커와 동일 — 수동의 의미 없음.
    # 새 메서드: 현재가에 MARKET 주문 + planned_capital 기준 수량 재계산 + stage_plan.is_triggered=True.
    def enter_stage_at_market(self, strategy_id: int, stage_no: int) -> Order:
        """수동 ▶: 트리거 비율 무시, planned_capital 로 현재가 시장가 즉시 진입.

        검증/효과:
        - kill-switch 차단 (trigger_next_stage 동일)
        - stage_plan 존재 + is_triggered=False
        - 거래소 ticker 에서 현재가 조회 → qty = planned_capital × leverage / current_price (step_size 절사)
        - MARKET 주문 (price 필드 없음, GTC 무관)
        - stage_plan.is_triggered = True (trigger_price 무시 표시)
        - strategy.current_stage = stage_no, status = STAGE{n}_OPEN_PENDING
        """
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        if AccountKillSwitchService(self.db).is_enabled(strategy.exchange_account_id):
            raise ValueError(
                f"Account kill-switch is enabled; stage {stage_no} entry blocked. "
                "Kill-switch 를 해제한 후 재시도하세요."
            )
        stage_plan = next((p for p in strategy.stage_plans if p.stage_no == stage_no), None)
        if not stage_plan:
            raise ValueError(f"Stage {stage_no} plan not found")
        if stage_plan.planned_capital is None:
            raise ValueError(f"Stage {stage_no} planned_capital is missing")
        # 2026-05-06 (사용자 결정): 모든 거래 ISOLATED. 빈 포지션이면 변경, 보유 중이면 noop.
        self.ensure_isolated_margin(strategy)
        # 현재가 조회 + 수량 계산
        current_price = self._fetch_current_mark_price(strategy.symbol)
        leverage = Decimal(str(strategy.leverage or 1))
        capital = Decimal(str(stage_plan.planned_capital))
        raw_qty = (capital * leverage) / current_price
        qty = self._floor_qty_to_step(strategy.symbol, raw_qty)
        if qty <= 0:
            raise ValueError(
                f"계산된 수량이 0 — capital={capital} USDT, current_price={current_price}, leverage={leverage}x. "
                "더 큰 자본 입력 필요."
            )
        order = self._place_market_entry(
            strategy,
            stage_no=stage_no,
            qty=qty,
            current_price=current_price,
            suffix=f"ENTRY{stage_no}M",  # M = market
        )
        # stage_plan 갱신: trigger 비율 무시 → is_triggered=True 마킹.
        stage_plan.is_triggered = True
        strategy.current_stage = stage_no
        if 2 <= stage_no <= 10:
            strategy.status = f"STAGE{stage_no}_OPEN_PENDING"
        elif stage_no == 1:
            strategy.status = "STAGE1_OPEN_PENDING"
        self.db.commit()
        self.db.refresh(order)
        # 2026-05-12 fix (사용자 #21 SAGAUSDT 4단계 보고): 「수동 ▶ 다음 단계 진입」 에서
        # additional_margin_usdt 자동 투입 코드 누락. start_stage1 + stage_trigger_worker
        # 두 자동 경로엔 있는데 수동만 빠져 사용자가 설정한 증거금이 안 들어감. 동일 패턴 추가.
        # 실패해도 entry 는 정상 (try/except + RiskEvent 기록).
        add_m = stage_plan.additional_margin_usdt
        if add_m and Decimal(str(add_m)) > 0:
            try:
                self.add_position_margin(strategy.id, amount=Decimal(str(add_m)))
                logger.info(
                    f"[manual ▶] additional margin +{add_m} USDT applied to #{strategy.id} stage{stage_no}"
                )
            except Exception as e:
                logger.warning(
                    f"[manual ▶] additional margin failed for #{strategy.id} stage{stage_no}: {e}"
                )
                # entry 자체는 정상 — 사용자에게 알림 (수동 보충 안내).
                try:
                    from app.services.notification_service import NotificationService
                    NotificationService(self.db).send_system_alert(
                        title=f"⚠️ [추가 증거금 실패 — 수동진입] #{strategy.id} {strategy.symbol} 단계{stage_no}",
                        body=(
                            f"수동 ▶ {stage_no}단계 entry 는 정상. 그러나 추가 증거금 {add_m} USDT 투입 실패.\n"
                            f"원인: {e}\n\n"
                            "💡 수동 보충: 「💰 증거금 추가」 버튼 또는 Binance UI 에서 직접 증거금 추가."
                        ),
                    )
                except Exception:
                    pass
        return order

    # 2026-05-04 (사용자 요청): 「💉 포지션 추가」 — ad-hoc 자유 금액 진입.
    # stage_plans 와 무관하게 사용자가 즉시 추가 자본 투입.
    # MARKET (현재가) 또는 LIMIT (지정가) 선택. stream_service 가 평단/qty 자동 갱신.
    def add_position_now(
        self,
        strategy_id: int,
        *,
        amount_usdt: Decimal,
        order_type: str,
        limit_price: Decimal | None = None,
    ) -> Order:
        """사용자 지정 USDT 금액으로 즉시 포지션 추가.

        Args:
            amount_usdt: 추가 자본 (margin, USDT). 양수.
            order_type: "MARKET" 또는 "LIMIT".
            limit_price: order_type=LIMIT 일 때 지정가. MARKET 이면 무시.

        효과:
            - qty = amount_usdt × leverage / price (MARKET 은 현재가, LIMIT 은 지정가)
            - 주문 발송 (MARKET 또는 LIMIT GTC)
            - stage_no=NULL (ad-hoc 표시), purpose='ENTRY'
            - 체결 시 stream_service 가 strategy.current_position_qty/avg_entry_price 자동 갱신
        """
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        if AccountKillSwitchService(self.db).is_enabled(strategy.exchange_account_id):
            raise ValueError(
                "Account kill-switch is enabled; new position entry blocked. "
                "Kill-switch 를 해제한 후 재시도하세요."
            )
        if amount_usdt is None or Decimal(str(amount_usdt)) <= 0:
            raise ValueError(f"amount_usdt must be > 0, got {amount_usdt}")
        order_type_u = (order_type or "").upper()
        if order_type_u not in ("MARKET", "LIMIT"):
            raise ValueError(f"order_type must be MARKET or LIMIT, got {order_type}")
        # 2026-05-06 (사용자 결정): 모든 거래 ISOLATED. 빈 포지션이면 변경, 보유 중이면 noop.
        self.ensure_isolated_margin(strategy)
        # 가격 결정
        if order_type_u == "LIMIT":
            if limit_price is None or Decimal(str(limit_price)) <= 0:
                raise ValueError("LIMIT 주문에는 limit_price (양수) 가 필요합니다")
            ref_price = Decimal(str(limit_price))
        else:
            ref_price = self._fetch_current_mark_price(strategy.symbol)
        # 수량 계산
        leverage = Decimal(str(strategy.leverage or 1))
        amount = Decimal(str(amount_usdt))
        raw_qty = (amount * leverage) / ref_price
        qty = self._floor_qty_to_step(strategy.symbol, raw_qty)
        if qty <= 0:
            raise ValueError(
                f"계산된 수량이 0 — amount={amount} USDT, price={ref_price}, leverage={leverage}x. "
                "더 큰 자본 입력 필요."
            )
        if order_type_u == "MARKET":
            order = self._place_market_entry(
                strategy,
                stage_no=None,  # ad-hoc — stage_no 없음
                qty=qty,
                current_price=ref_price,
                suffix="ADHOC_M",
            )
        else:
            order = self._place_limit_entry(
                strategy,
                stage_no=None,  # ad-hoc
                qty=qty,
                limit_price=ref_price,
                suffix="ADHOC_L",
            )
        self.db.commit()
        self.db.refresh(order)
        return order

    # ───────── 내부 헬퍼 ─────────
    def _fetch_current_mark_price(self, symbol: str) -> Decimal:
        """거래소에서 현재 mark price 조회 — get_position_risk 의 markPrice 사용 (인증 + 인스턴스용).

        Binance fapi/v1/positionRisk 는 markPrice 를 항상 반환하므로 ticker 별도 호출 불필요.
        포지션이 없어도 markPrice 는 받음.
        """
        try:
            position_risk = self.client.get_position_risk(symbol=symbol)
            if isinstance(position_risk, dict):
                position_risk = [position_risk]
            for item in position_risk:
                if item.get("symbol") == symbol:
                    mark = item.get("markPrice")
                    if mark and Decimal(str(mark)) > 0:
                        return Decimal(str(mark))
            raise ValueError(f"markPrice not found in position_risk response for {symbol}")
        except Exception as e:
            raise ValueError(f"현재가 조회 실패 ({symbol}): {e}") from e

    def _floor_qty_to_step(self, symbol: str, raw_qty: Decimal) -> Decimal:
        """심볼 step_size 로 qty 절사. step_size 못 찾으면 0.001 fallback."""
        from app.models.symbol import Symbol
        from sqlalchemy import select
        sym = self.db.execute(select(Symbol).where(Symbol.symbol == symbol)).scalars().first()
        step = Decimal(str(sym.step_size)) if sym and sym.step_size and Decimal(str(sym.step_size)) > 0 else Decimal("0.001")
        return (raw_qty // step) * step

    def _percent_price_bounds(self, symbol: str, mark_price: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        """심볼 PERCENT_PRICE 필터 → (하한, 상한, tick_size).

        Binance: 주문가 ∈ [mark*multiplierDown, mark*multiplierUp].
        필터/심볼 못 찾으면 보수적 ±5% + tick 0.00000001 fallback.
        """
        from app.models.symbol import Symbol
        from sqlalchemy import select
        sym = self.db.execute(select(Symbol).where(Symbol.symbol == symbol)).scalars().first()
        mult_up = Decimal("1.05")
        mult_down = Decimal("0.95")
        tick = Decimal("0.00000001")
        if sym:
            if sym.tick_size and Decimal(str(sym.tick_size)) > 0:
                tick = Decimal(str(sym.tick_size))
            info = sym.raw_exchange_info or {}
            for f in info.get("filters", []):
                if f.get("filterType") == "PERCENT_PRICE":
                    try:
                        mult_up = Decimal(str(f.get("multiplierUp", mult_up)))
                        mult_down = Decimal(str(f.get("multiplierDown", mult_down)))
                    except Exception:
                        pass
                    break
        lower = mark_price * mult_down
        upper = mark_price * mult_up
        return lower, upper, tick

    def _emergency_close_limit_fallback(
        self, strategy, *, side: str, position_side: str, quantity: Decimal,
        client_order_id: str,
    ) -> dict:
        """-4131 (PERCENT_PRICE) 로 MARKET 거부된 저유동성 심볼의 청산 폴백.

        2026-05-19 사용자 보고 (#62 MLNUSDT): 호가창이 얇아 MARKET 청산이
        PERCENT_PRICE 밴드 밖 → -4131 거부 → 포지션 stuck + 매 cycle 재시도 루프.

        해법: PERCENT_PRICE 밴드 경계가에 reduceOnly 아닌 LIMIT GTC 발송
        (hedge 모드라 positionSide 로 방향 제어 — 기존 MARKET 과 동일 패턴).
        - SELL(롱청산): 하한가 (가장 공격적, 밴드 내 최저) — bid 매칭 즉시 일부 체결
        - BUY(숏청산): 상한가 (가장 공격적, 밴드 내 최고) — ask 매칭
        - 미체결 잔여는 밴드 내 GTC 로 대기 → reconcile/stream 이 추적
        (전량 실패보다 「가능한 만큼 즉시 + 잔여 유효 주문 대기」 가 안전)
        """
        mark = self._fetch_current_mark_price(strategy.symbol)
        lower, upper, tick = self._percent_price_bounds(strategy.symbol, mark)
        if side == "SELL":
            # 하한 이상이어야 수락 → tick ceil 로 하한 바로 위 (가장 공격적)
            limit_price = (lower / tick).to_integral_value(rounding="ROUND_CEILING") * tick
        else:  # BUY
            # 상한 이하여야 수락 → tick floor 로 상한 바로 아래 (가장 공격적)
            limit_price = (upper / tick).to_integral_value(rounding="ROUND_FLOOR") * tick
        if limit_price <= 0:
            raise ValueError(f"PERCENT_PRICE 폴백 가격 계산 실패 (mark={mark}, tick={tick})")
        payload = {
            "symbol": strategy.symbol, "side": side, "positionSide": position_side,
            "type": "LIMIT", "quantity": str(quantity),
            "price": str(limit_price), "timeInForce": "GTC",
            "newClientOrderId": client_order_id,
        }
        logger.warning(
            "emergency_close -4131 fallback: LIMIT GTC strategy=%s symbol=%s side=%s "
            "qty=%s price=%s (mark=%s band=[%s,%s])",
            strategy.id, strategy.symbol, side, quantity, limit_price, mark, lower, upper,
        )
        return self.client.place_order(payload)

    def _place_market_entry(self, strategy, *, stage_no: int | None, qty: Decimal, current_price: Decimal, suffix: str) -> Order:
        """공통 MARKET 진입 주문 (stage 또는 ad-hoc).

        2026-05-21 Phase 2B (사장님 요구): 진입 직후 1초 검증 — qty 가 의도대로 증가했나.
        자동 재시도는 안 함 (중복 진입 risk) — 알림만으로 사장님 인지.
        """
        # 검증 기준 — 발송 전 거래소 실 포지션 (DB current_position_qty 가 stale 일 수 있음).
        initial_qty = self._fetch_current_position_qty(strategy)

        side = "BUY" if strategy.side == "LONG" else "SELL"
        position_side = strategy.side
        client_order_id = self._new_client_order_id(strategy.symbol, suffix)
        payload = {
            "symbol": strategy.symbol,
            "side": side,
            "positionSide": position_side,
            "type": "MARKET",
            "quantity": str(qty),
            "newClientOrderId": client_order_id,
        }
        adapter = self.execution_router.route_for_type(payload["type"])
        response = adapter.place_order(payload)
        order = Order(
            strategy_instance_id=strategy.id,
            stage_no=stage_no,
            purpose="ENTRY",
            symbol=strategy.symbol,
            side=side,
            position_side=position_side,
            order_type="MARKET",
            time_in_force=None,
            client_order_id=client_order_id,
            exchange_order_id=response.get("orderId"),
            trigger_price=None,
            price=current_price,  # 참고용 (체결가는 avg_price 가 정확)
            orig_qty=qty,
            executed_qty=Decimal(str(response.get("executedQty", "0"))),
            avg_price=Decimal(str(response.get("avgPrice"))) if response.get("avgPrice") else None,
            status=response.get("status", "NEW"),
            raw_request=payload,
            raw_response=response,
        )
        self.order_repo.create(order)
        self.db.commit()

        # ENTRY 검증 — initial_qty 조회 실패 시 (네트워크 등) skip.
        if initial_qty is not None:
            self._verify_entry_applied(
                strategy,
                initial_qty=initial_qty,
                expected_increase=qty,
                stage_no=stage_no,
            )

        return order

    # 진입 검증 — 1초 (MARKET 즉시 체결 — 청산 3초보다 짧게).
    # 자동 재시도 안 함 — 중복 진입 위험 (사장님 자본이 두 번 들어갈 수 있음).
    ENTRY_VERIFY_DELAY_SECONDS = 1.0

    def _verify_entry_applied(
        self,
        strategy,
        *,
        initial_qty: Decimal,
        expected_increase: Decimal,
        stage_no: int | None,
    ) -> None:
        """MARKET 진입 직후 거래소 포지션 증가 검증 (Phase 2B, 사장님 요구).

        성공: qty 가 expected_increase 의 90% 이상 증가 → log only, 정상 진행
        실패: RiskEvent + 텔레그램 알림 (자동 재시도 X — 중복 진입 risk)

        자동 재시도 안 하는 이유:
          - 거래소 응답이 늦게 와서 실제로는 체결됐는데 검증 시점에 0 으로 보일 수도
          - 재시도하면 자본이 두 번 들어가는 위험 (실측 사례 못 잡으면 큰 손실)
          - 사장님이 알림 받고 거래소 확인 후 수동 처리 권장

        검증 호출 자체 실패 시 status 변경 안 함 — 보수적 skip (reconcile 백업).
        """
        time.sleep(self.ENTRY_VERIFY_DELAY_SECONDS)
        post_qty = self._fetch_current_position_qty(strategy)
        if post_qty is None:
            # 검증 호출 실패 — 보수적 skip. reconcile 이 다음 cycle 에 sync.
            return

        actual_increase = post_qty - initial_qty
        success_threshold = expected_increase * EMERGENCY_CLOSE_SUCCESS_THRESHOLD_RATIO
        if actual_increase >= success_threshold:
            logger.info(
                "ENTRY 검증 성공: strategy=%s stage=%s initial=%s post=%s increased=%s",
                strategy.id, stage_no, initial_qty, post_qty, actual_increase,
            )
            return

        # 검증 실패 — 알림만 (자동 재시도 X)
        logger.warning(
            "ENTRY 검증 실패 (자동 재시도 안 함 — 중복 진입 risk): "
            "strategy=%s stage=%s initial=%s post=%s increased=%s expected=%s",
            strategy.id, stage_no, initial_qty, post_qty, actual_increase, expected_increase,
        )
        title = f"⚠️ 진입 검증 실패 — #{strategy.id} {strategy.symbol} {strategy.side}"
        body = (
            f"MARKET 진입 주문 발송 후 {self.ENTRY_VERIFY_DELAY_SECONDS:.0f}초 검증 실패.\n"
            f"  stage: {stage_no or 'ad-hoc'}\n"
            f"  발송 전 거래소 qty: {initial_qty}\n"
            f"  요청 진입 qty: +{expected_increase}\n"
            f"  발송 후 거래소 qty: {post_qty} (증가량 {actual_increase})\n\n"
            f"거래소가 주문을 접수했으나 포지션이 의도대로 증가하지 않음. "
            f"체결 지연 / 부분 체결 / 거래소 거절 의심.\n\n"
            f"⚠️ 자동 재시도 안 함 — 중복 진입 시 자본이 두 번 들어갈 위험.\n\n"
            f"조치:\n"
            f"  1) Binance 거래소 UI 에서 실 포지션 상태 확인\n"
            f"  2) 체결 안 됐으면 「▶ 다음 단계」 또는 「💉 포지션 추가」 로 수동 재시도\n"
            f"  3) reconcile 이 1~2분 안에 자동 sync 시도"
        )
        self.db.add(RiskEvent(
            strategy_instance_id=strategy.id,
            event_type="ENTRY_VERIFY_FAILED",
            severity="WARN",
            title=title,
            message=body,
            event_payload={
                "strategy_id": strategy.id,
                "stage_no": stage_no,
                "initial_qty": str(initial_qty),
                "expected_increase": str(expected_increase),
                "post_qty": str(post_qty),
                "actual_increase": str(actual_increase),
            },
        ))
        try:
            from app.services.notification_service import NotificationService
            NotificationService(self.db).send_system_alert(title=title, body=body)
        except Exception as e:
            logger.warning("ENTRY 검증 실패 알림 실패: %s", e)
        self.db.commit()

    def _place_limit_entry(self, strategy, *, stage_no: int | None, qty: Decimal, limit_price: Decimal, suffix: str) -> Order:
        """공통 LIMIT 진입 주문 (ad-hoc 지정가 진입용)."""
        side = "BUY" if strategy.side == "LONG" else "SELL"
        position_side = strategy.side
        client_order_id = self._new_client_order_id(strategy.symbol, suffix)
        payload = {
            "symbol": strategy.symbol,
            "side": side,
            "positionSide": position_side,
            "type": "LIMIT",
            "quantity": str(qty),
            "price": str(limit_price),
            "timeInForce": "GTC",
            "newClientOrderId": client_order_id,
        }
        adapter = self.execution_router.route_for_type(payload["type"])
        response = adapter.place_order(payload)
        order = Order(
            strategy_instance_id=strategy.id,
            stage_no=stage_no,
            purpose="ENTRY",
            symbol=strategy.symbol,
            side=side,
            position_side=position_side,
            order_type="LIMIT",
            time_in_force="GTC",
            client_order_id=client_order_id,
            exchange_order_id=response.get("orderId"),
            trigger_price=limit_price,
            price=limit_price,
            orig_qty=qty,
            executed_qty=Decimal(str(response.get("executedQty", "0"))),
            avg_price=Decimal(str(response.get("avgPrice"))) if response.get("avgPrice") else None,
            status=response.get("status", "NEW"),
            raw_request=payload,
            raw_response=response,
        )
        self.order_repo.create(order)
        return order

    @staticmethod
    def _new_client_order_id(symbol: str, suffix: str) -> str:
        """Binance newClientOrderId — 절대 안전 포맷 (사용자 #26 JELLYJELLYUSDT 3차 fix).

        2026-05-12 v1 (35자) → 2026-05-13 v2 (32자, 하이픈) → 32자도 -4015 reject 됨.
        2026-05-13 v3: 하이픈 → 언더스코어 + 28자 cap.

        근거 — Binance Futures 공식 spec:
            newClientOrderId: STRING ^[a-zA-Z0-9_]*$ length<36
        Spot 은 하이픈/콜론 허용하지만 Futures 는 [a-zA-Z0-9_] 만 명시 ← 하이픈 거부 가능성.
        실제로 32자 (하이픈 포함) reject 됨 → 하이픈이 문제 가능 → underscore 로 교체.

        v3 포맷: `{symbol}_{suffix}_{uuid_hex[:N]}` (하이픈 X, alphanumeric+underscore 만)
        - JELLYJELLYUSDT(14) + EXIT(4) → base 20, uuid 8 → 28자 ✓
        - SAGAUSDT(8) + ENTRY10M(8) → base 18, uuid 10 → 28자 ✓
        - BTCUSDT(7) + EXIT(4) → base 13, uuid 15 → 28자 ✓
        모든 케이스 ≤28자 + alphanumeric/underscore 만 → Binance Futures 절대 안전.
        """
        MAX_LEN = 28              # v3: Binance Futures 매우 보수적 cap (실 한도 < 32 추정)
        PREFERRED_UUID = 16       # 충분한 충돌 방지 (64 bits)
        # MIN_UUID = 4 (=16^4 = 65536 unique). 실 운영은 sub-minute 단위 발사라 충분.
        # 더 큰 prefix (긴 symbol+suffix) 는 prefix 보존 우선 — uuid 줄여서 MAX_LEN 보장.
        MIN_UUID = 4
        base_len = len(symbol) + 1 + len(suffix) + 1  # symbol + "_" + suffix + "_"
        uuid_len = max(MIN_UUID, min(PREFERRED_UUID, MAX_LEN - base_len))
        cid = f"{symbol}_{suffix}_{uuid4().hex[:uuid_len]}"  # ← 하이픈 → 언더스코어
        return cid[:MAX_LEN]      # 안전장치 — 어떤 입력에도 28자 보장
