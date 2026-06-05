import time
from decimal import Decimal, InvalidOperation
from typing import Any
from app.core.redis_client import get_redis_client
from app.core.redis_lock import redis_lock, RedisLockError
from app.core.risk_constants import (
    CRISIS_QTY_RATIO_DEFAULT as _CRISIS_QTY_RATIO_DEFAULT,
    CRISIS_RATIO_KEYS as _CRISIS_RATIO_KEYS,
    DEFAULT_STEP_SIZE_FALLBACK,
    DEFAULT_TP_QTY_RATIO_PCT,
    FULL_CLOSE_RATIO,
    LEVERAGE_FALLBACK,
    PERCENT_DENOMINATOR,
    QTY_PRECISION,
    TP_FINAL_QTY_RATIO_PCT,
    USDT_PRICE_PRECISION,
)
from app.models.risk_event import RiskEvent
from app.observability.metrics import strategy_runs_total, strategy_stop_loss_total, strategy_take_profit_total
from app.repositories.strategy_repository import StrategyRepository
from app.services.execution_service import EmergencyCloseInProgress, ExecutionService
from app.services.notification_service import NotificationService
from app.services.risk_service import RiskService

# 2026-05-14 Phase 2 centralize: 위 상수 모두 app.core.risk_constants 에서 import.
# _CRISIS_QTY_RATIO_DEFAULT / _CRISIS_RATIO_KEYS 는 backward compat 을 위해 alias 유지
# (test_crisis_qty_ratios_resolver.py 가 이 이름으로 import).


def _resolve_crisis_qty_ratios(override: Any) -> dict[str, Decimal]:
    """template.crisis_qty_ratios JSONB → {TP1..TP4: Decimal} 머지.

    - override 가 None / 빈 dict → 전체 default
    - 일부 키만 있으면 나머지는 default
    - invalid 값 (음수, 100 초과, 비숫자) 도 default fallback
    - 알 수 없는 키는 무시 (TP5 등은 크라이시스에서 사용 안 함)
    """
    out = dict(_CRISIS_QTY_RATIO_DEFAULT)
    if not override or not isinstance(override, dict):
        return out
    for key in _CRISIS_RATIO_KEYS:
        if key not in override:
            continue
        raw = override[key]
        try:
            val = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            continue  # invalid → default 유지
        if val < 0 or val > 100:
            continue  # 범위 밖 → default 유지
        out[key] = val
    return out


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
                # 2026-05-06: TP1~10 progression 동적 (10단계 익절 확장).
                done_levels_progression = [f"TP{n}_DONE_PARTIAL" for n in range(1, 11)] + ["COMPLETED"]
                tp_level_index = {f"TP{n}": n - 1 for n in range(1, 11)}.get(tp_level, -1)
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
        ratio_attr = {f"TP{n}": f"tp{n}_qty_ratio" for n in range(1, 11)}
        # 사용자 기획 v6 (2026-05-12 밤): TP1~9 모두 「잔량의 25%」 균일.
        # "익절시작은 +10%에서 25%씩 시작하고 +15% 일때 잔량에 25% 이렇게 tp10단계까지".
        # TP10 만 100% (절대 마지막 안전망 — trailing 미발동 + 가격 계속 상승 케이스).
        # 이전 default (TP2=50, TP3~5=100) 는 사용자 「TP3 후 trailing」 의도 위배 — TP3
        # 가 100% 면 trailing 영영 발동 못함. 균일 25% 로 변경 → 잔량 보유 → trailing 기회.
        default_ratio = {f"TP{n}": DEFAULT_TP_QTY_RATIO_PCT for n in range(1, 10)}
        default_ratio["TP10"] = TP_FINAL_QTY_RATIO_PCT
        # 크라이시스 모드 qty ratio (사용자 기획 default):
        # TP1=25%, TP2=25%, TP3=50% of remaining, TP4=100% of remaining
        # 2026-05-04 (alembic 0009): template.crisis_qty_ratios JSONB override 가능.
        # 일부 키만 채워도 나머지는 default 사용. invalid 값은 default fallback.
        crisis_qty_ratio = _resolve_crisis_qty_ratios(getattr(tpl, "crisis_qty_ratios", None))

        # 사용자 기획 v6 (2026-05-12 밤): last_active_tp shortcut 폐지.
        # 이전 (#80, 2026-04-30): 「마지막 enabled TP 발동 시 잔량 100% 청산」 안전망.
        #   문제: 사용자가 TP1~3 만 enable + 사용자 의도 TP3 후 trailing 인데, TP3 가
        #         last_active_tp → 100% 청산 → status COMPLETED → trailing 영원히 X.
        # 신규 정책: TPs 가 균일 25% (TP10 만 default 100%) — 잔량 보유 → trailing 기회.
        #   대안 안전망: TP10 default 100% + crisis 모드 + SL -50% + 사용자 수동 stop.
        #   사용자가 TP3 만 enable + trailing 발동 안 하는 시나리오 우려시 → 명시적
        #   tp3_qty_ratio = 100 으로 setting (코드는 사용자 setting 우선).
        # 사용자 기획 v7 (2026-05-14): 단축 익절 — stage<3 인데 TP3+ 발동 시 잔량 100% 즉시 청산.
        # 이유: trailing 자격 (stage>=3) 미달 → trailing 영영 미발동.
        # 대신 TP3 (+20% threshold) 까지 갔다는 건 충분한 수익 = 잔량 빠르게 정리하는 게 안전.
        # 적용 조건:
        #   - level == TPx (x >= TRAILING_MIN_TP_INDEX = 3)
        #   - current_stage < TRAILING_MIN_STAGE = 3
        #   - 크라이시스 모드 아닐 때만 (크라이시스는 별도 ratio)
        from app.services.risk_service import TRAILING_MIN_TP_INDEX, TRAILING_MIN_STAGE
        v7_short_exit = False
        if (
            level.startswith("TP") and level[2:].isdigit()
            and not strategy.crisis_mode_triggered_at
        ):
            try:
                tp_n = int(level[2:])
                if tp_n >= TRAILING_MIN_TP_INDEX and (strategy.current_stage or 0) < TRAILING_MIN_STAGE:
                    v7_short_exit = True
            except ValueError:
                pass

        if level == "TRAILING_TP":
            close_ratio = FULL_CLOSE_RATIO  # 트레일링은 항상 100% (v6 변경 없음)
        elif v7_short_exit:
            close_ratio = FULL_CLOSE_RATIO  # v7: 단축 익절 — 잔량 100% (stage 미달 + TP3+)
        elif strategy.crisis_mode_triggered_at and level in crisis_qty_ratio:
            close_ratio = crisis_qty_ratio[level] / PERCENT_DENOMINATOR
        else:
            attr = ratio_attr.get(level)
            tpl_val = getattr(tpl, attr, None) if tpl and attr else None
            ratio_pct = Decimal(str(tpl_val)) if tpl_val is not None else default_ratio.get(level, DEFAULT_TP_QTY_RATIO_PCT)
            close_ratio = ratio_pct / PERCENT_DENOMINATOR
        if close_ratio >= FULL_CLOSE_RATIO:
            close_qty = current_qty
        else:
            # Bug #11 fix (2026-04-29): step_size 단위로 floor.
            # 이전 버전은 0.00000001 (8자리) 로 quantize 했는데, 실제 거래소는
            # 심볼별 LOT_SIZE 의 stepSize 를 따라야 함 (예: BTCUSDT=0.001).
            # 너무 정밀한 수량을 보내면 -1111 "Precision is over the maximum"
            # 에러로 거절됨. 이제 심볼의 step_size 로 floor 한다.

            # 2026-06-05 사장님 사상 옵션 B v2 (사장님 명시):
            # "TP1 부터 익절은 포지션과 증거금 포함해서 전체금액에 25%씩 익절
            #  중간에 수동포지션과 증거금 추가한 금액모두를 기준으로 하는겁니다."
            #
            # = TP 청산 기준 = max(DB total_capital, Binance isolated_margin)
            # - DB total_capital = 사장님 strategy 생성 시 입력 (✏️ 수정 가능)
            # - Binance isolated_margin = 실 lock 마진 (단계 진입 + 증거금 + 수동 포지션 추가 모두 포함)
            # - 사장님이 어디서 추가하든 = 둘 중 큰 값 사용 = 사장님 노력 100% 보호
            #
            # 청산 수량 계산:
            #   qty_based = current_qty × close_ratio (옛 거래소 표준)
            #   effective_margin = max(total_capital, latest_isolated_margin)
            #   capital_based = (effective_margin × close_ratio × leverage) / avg_entry
            #   raw_qty = max(qty_based, capital_based)  ← 사장님 의도 정확
            #   close_qty = min(raw_qty, current_qty)    ← 보유 초과 방지
            qty_based = current_qty * close_ratio
            avg_entry = Decimal(str(strategy.avg_entry_price or 0))
            sLev = Decimal(str(strategy.leverage or 1))
            sCap = Decimal(str(strategy.total_capital or 0))

            # 2026-06-05 사장님 보호 안전장치 (옵션 B):
            # 수동 익절 후 1시간 동안 = qty_based 만 사용 (capital_based skip)
            # 이유: 사장님이 수동 청산 (예: 80%) 후 = 잔여 qty 작음 → capital_based 초과 시
            # 다음 자동 TP = 전체 청산 → 사장님 "잔여 유지" 의도 위배.
            # Redis flag (TTL 1h) 로 일시 보호 → 1h 후 = PR #88 정상 로직 복귀.
            manual_tp_protect_active = False
            try:
                from app.core.redis_client import get_redis_client
                redis = get_redis_client()
                if redis.exists(f"manual_tp_protect:strategy:{strategy.id}"):
                    manual_tp_protect_active = True
            except Exception:
                pass  # Redis 실패 = 정상 PR #88 로직 사용

            # Position 의 최신 isolated_margin (reconcile_worker 가 매 사이클 갱신)
            # 사장님이 Binance UI 직접 추가한 증거금/포지션도 isolated_margin 에 즉시 반영
            from app.models.position import Position as _Position
            latest_pos = self.db.execute(
                select(_Position)
                .where(_Position.strategy_instance_id == strategy.id)
                .order_by(_Position.id.desc())
                .limit(1)
            ).scalars().first()
            binance_isolated = (
                Decimal(str(latest_pos.isolated_margin))
                if latest_pos and latest_pos.isolated_margin
                else Decimal("0")
            )

            # 효과 마진 = max(DB 자본, Binance 실 마진) — 사장님 어디서 추가하든 보호
            effective_margin = max(sCap, binance_isolated)

            if manual_tp_protect_active:
                # 사장님 수동 청산 후 1h 보호 모드 — qty_based 만 사용 (잔여 유지)
                raw_qty = qty_based
                self.db.add(RiskEvent(
                    strategy_instance_id=strategy.id,
                    event_type="MANUAL_TP_PROTECT_APPLIED",
                    severity="INFO",
                    title=f"🛡 수동 청산 후 보호 ({level}) — qty 기준만 적용",
                    message=(
                        f"사장님 최근 수동 청산 (1h 이내) → 잔여 유지 보호 모드. "
                        f"TP {level} 청산 = qty_based ({qty_based:.4f}) 만 사용 "
                        f"(capital_based {(effective_margin * close_ratio * sLev / avg_entry):.4f} skip)."
                    ),
                ))
            elif avg_entry > 0 and sLev > 0 and effective_margin > 0:
                # PR #88 정상 로직: 자본 기준 = max(qty, capital) 채택
                capital_based = (effective_margin * close_ratio * sLev) / avg_entry
                raw_qty = max(qty_based, capital_based)
                # 보유 초과 방지 (current_qty 보다 클 수 없음 — Binance 실 보유)
                if raw_qty > current_qty:
                    raw_qty = current_qty
            else:
                # 자본/평단/lev 정보 없으면 fallback = 옛 qty 기준
                raw_qty = qty_based

            sym = self.db.execute(select(Symbol).where(Symbol.symbol == strategy.symbol)).scalars().first()
            step = Decimal(str(sym.step_size)) if sym and sym.step_size and sym.step_size > 0 else DEFAULT_STEP_SIZE_FALLBACK
            # floor to step: floor(raw / step) * step
            close_qty = (raw_qty // step) * step
            # 2026-05-14 fix (사용자 #40 BUSDT 후속): step_size flooring 으로 close_qty=0 이 되면
            # 「3단계 익절」 같은 사용자 기획대로 진행 안 됨 (TP partial close 누락).
            # 잔량이 step_size 이상이면 최소 1 step 보장 — 사용자 「3건 익절」 의도 충족.
            # 잔량 자체가 1 step 미만이면 (이미 거의 청산됨) close 진행 안 함 (current_qty 부족).
            if close_qty <= 0 and current_qty >= step:
                close_qty = step  # 최소 1 lot 보장
                # WARN 기록 — fee 손실 인지 + 사용자 알림
                self.db.add(RiskEvent(
                    strategy_instance_id=strategy.id,
                    event_type="TP_MIN_STEP_ENFORCED",
                    severity="INFO",
                    title=f"⚙️ {level} 최소 step 보장",
                    message=(
                        f"{level} 청산 비율 {close_ratio*100:.1f}% × 잔량 {current_qty} = {raw_qty} 가 "
                        f"step_size ({step}) 미만 → 1 step ({step}) 으로 보장. "
                        f"사용자 「TP 단계별 진행」 의도 유지."
                    ),
                ))
                self.db.flush()
        if close_qty <= 0:
            return
        # 실제 청산 체결 — 반환된 order 의 avg_price 가 진짜 청산 단가 (mark 보다 정확).
        # 2026-05-08 #120 fix: 다른 caller (manual stop, admin cleanup) 가 이미 청산 중이면
        # idempotency lock 이 EmergencyCloseInProgress 발생 → 다음 cycle 에 재평가.
        try:
            close_order = self.execution_service.emergency_close_position(strategy.id, quantity=close_qty)
        except EmergencyCloseInProgress:
            return  # 다른 caller 가 청산 중 — status/qty 변경 없이 대기, 다음 cycle 재평가
        # 청산 후 남은 수량 계산
        remaining_qty = (current_qty - close_qty).quantize(QTY_PRECISION)
        # 상태 진행 — 2026-05-06: TP1~10 동적 (10단계 익절 확장).
        is_final = (level == "TRAILING_TP" or close_ratio >= FULL_CLOSE_RATIO)
        if level == "TRAILING_TP":
            strategy.status = "COMPLETED"
        elif level.startswith("TP") and level[2:].isdigit():
            n = int(level[2:])
            if 1 <= n <= 10:
                strategy.status = f"TP{n}_DONE_PARTIAL" if not is_final else "COMPLETED"
            else:
                strategy.status = "COMPLETED"  # 알 수 없는 level → safe COMPLETED
        else:
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
                        except Exception as _e:
                            logger.warning("[#13] db.refresh(close_order) failed strategy=%s: %s", strategy.id, _e)
            # 마지막 fallback: latest_position.mark_price (stream 까지 fail 시 추정)
            if exit_px is None:
                from app.repositories.position_repository import PositionRepository
                latest_pos = PositionRepository(self.db).latest_by_strategy(strategy.id)
                if latest_pos and latest_pos.mark_price:
                    exit_px = Decimal(str(latest_pos.mark_price))
            if avg_entry and exit_px and avg_entry > 0:
                leverage = Decimal(str(strategy.leverage)) if strategy.leverage else LEVERAGE_FALLBACK
                if strategy.side == "LONG":
                    raw_pct = (exit_px - avg_entry) / avg_entry * PERCENT_DENOMINATOR
                    realized_pnl = (close_qty * (exit_px - avg_entry)).quantize(USDT_PRICE_PRECISION)
                else:  # SHORT
                    raw_pct = (avg_entry - exit_px) / avg_entry * PERCENT_DENOMINATOR
                    realized_pnl = (close_qty * (avg_entry - exit_px)).quantize(USDT_PRICE_PRECISION)
                pnl_pct = (raw_pct * leverage).quantize(USDT_PRICE_PRECISION)
                avg_exit_price = exit_px
        except Exception as _e:
            logger.warning("[#13] TP pnl_pct 계산 실패 strategy=%s level=%s: %s", strategy.id, level, _e)

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
            try:
                self.execution_service.emergency_close_position(strategy.id, quantity=current_qty)
            except EmergencyCloseInProgress:
                return  # #120 fix: 다른 caller 가 청산 중 — 다음 cycle 재시도
        strategy.status = "STOPPING"
        self.db.commit()

        # 손실률(%) 계산 — 사용자 마진 대비 leveraged ROI
        # margin = capital / leverage → ROI = USD 손실 × leverage / capital × 100
        loss_amount = Decimal(str(strategy.realized_pnl)) + Decimal(str(strategy.unrealized_pnl))
        pnl_pct = None
        try:
            capital = Decimal(str(strategy.total_capital))
            leverage = Decimal(str(strategy.leverage)) if strategy.leverage else LEVERAGE_FALLBACK
            if capital > 0:
                pnl_pct = (loss_amount * leverage / capital * PERCENT_DENOMINATOR).quantize(USDT_PRICE_PRECISION)
        except Exception as _e:
            logger.warning("[#13] SL pnl_pct 계산 실패 strategy=%s: %s", strategy.id, _e)

        self.notification_service.send_stop_loss_alert(
            strategy_instance_id=strategy.id, symbol=strategy.symbol, side=strategy.side,
            total_capital=str(strategy.total_capital),
            current_loss_amount=str(loss_amount.quantize(USDT_PRICE_PRECISION)),
            pnl_pct=pnl_pct,
        )
        self.risk_service.mark_reentry_ready(strategy.id)

    # ──────────────── 크라이시스 복구 모드 액션 (Phase D-2) — 🚨 DEAD CODE ────────────────
    def _execute_crisis_action(self, strategy, action: str) -> None:
        """🚨 DEAD CODE (2026-06-03 #12 분석 확인) — 호출처 없음 + Stage 2 보호 미연결.

        호출처 검색: `grep _execute_crisis_action backend/app/` → 0건 (정의만 있음).

        원래 의도 (Phase D-2 미완성):
          - CRISIS_TP1:        TP1 발동 후 25% 청산 + Stage 2 진입 (status=CRISIS_TP1_DONE)
          - CRISIS_TRAIL_FULL: 피크 대비 트레일링 -5% 회귀 → 전량 청산
          - CRISIS_HARD_SL:    피크 대비 -1% 회귀 → 전량 빠른 손절

        미연결 이유:
          - risk_service.evaluate_take_profit_level 가 'CRISIS_TRAIL_FULL'/'CRISIS_HARD_SL' 반환 X
          - 크라이시스 모드 시 정상 TP 흐름 (_execute_take_profit) 이 TP override 만 처리 (5/10/15/20%)
          - Stage 2 보호 정책 자체가 미구현

        사장님 결정 (2026-05-14): 크라이시스 비활성 (-100 sentinel)
          → 신규 strategy 는 크라이시스 진입 X → 이 함수 wire-up 필요성 매우 낮음

        미래 wire-up 시 참고 (원본 코드 = git history 에 보존):
          1. risk_service.evaluate_take_profit_level 가 Stage 2 보호 액션 반환하도록 추가
          2. process_action 에서 이 함수 호출
          3. 또는 별도 worker (crisis_stage2_protection_monitor) 신설

        안전 가드: 호출 시 NotImplementedError raise (silent 실행 차단).
        """
        raise NotImplementedError(
            f"_execute_crisis_action({action!r}) DEAD CODE — Stage 2 보호 미구현. "
            "docstring 참고 후 wire-up 또는 함수 영구 제거."
        )
