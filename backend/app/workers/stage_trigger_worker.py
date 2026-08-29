"""Stage 2~N 자동 진입 트리거 감시 worker.

이전엔 stage 1 LIMIT 주문만 거래소에 발송됐고, stage 2~N 은 자동 트리거 worker
가 없어서 가격이 트리거를 통과해도 진입이 안 되는 critical bug 가 있었음.
이 worker 가 그 missing piece — 활성 전략의 다음 stage 트리거를 매 10초마다 체크.

동작:
- 상태가 STAGE{1~9}_OPEN 인 전략 조회
- 각 전략의 다음 stage_no 계산 (current_stage + 1)
- 그 stage_plan 의 trigger_price 와 현재 mark_price 비교
- SHORT: mark >= trigger 시 진입 / LONG: mark <= trigger 시 진입
- ExecutionService.trigger_next_stage() 호출 → 거래소에 LIMIT 주문 발송

LIMIT 주문은 즉시 fill 될 수도, book 에 대기할 수도 있음. fill 시 stream_service
가 stage_plan.is_triggered = True 로 갱신.
"""
from __future__ import annotations
import logging
import os
from decimal import Decimal

from sqlalchemy import select

from app.core.api_backoff import is_account_banned, maybe_record_ban_from_exc
from app.core.database import SessionLocal
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.repositories.position_repository import PositionRepository
from app.services.execution_service import ExecutionService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

# 다음 stage 진입 검사 대상 상태 (stage 1~9 가 OPEN 이면 그 다음 stage 진입 검사 — 10 은 마지막).
# 2026-05-14 Phase 1 centralize: STAGES_WITH_NEXT (app.core.strategy_status).
from app.core.strategy_status import STAGES_WITH_NEXT
ACTIVE_STAGE_STATUSES = STAGES_WITH_NEXT


def _count_total_stages_from_template(tpl) -> int:
    """Template 의 stages_config 에서 총 활성 단계 수 산출 (1~10 동적).

    A08 fix (audit 2026-05-02): 이전엔 _get_total_stages 가 매번 새 SessionLocal
    + db.get 호출 → N+1 쿼리 (활성 전략 N개 × 새 세션). 이제 호출자가 미리 batch
    fetch 한 tpl 객체를 전달하면 세션 추가 호출 없음.
    """
    if not tpl:
        return 4
    cfg = tpl.stages_config or {}
    capitals = cfg.get("capitals") or []
    return len(capitals) if capitals else 4


# ---------------------------------------------------------------------------
# 2026-05-19 사용자 보고 (#다수, -2019 "Margin is insufficient"):
# 13개 동시 전략으로 가용 증거금 소진 → 다음 단계 진입이 -2019 거부.
# is_triggered 가 False 라 stage_trigger 가 매 10초 재시도 → 거래소 주문 spam
# (rate-limit 기여) + RiskEvent/Telegram spam + 자동 해소 안 됨 (마진은 포지션
# 정리/입금 전엔 안 생김). ban guard / -4131 / flat-record 와 동일 클래스.
#
# 해법: -2019 감지 시 (strategy,stage) Redis 쿨다운 (30분) + 알림 1회만.
# 쿨다운 중엔 그 단계 skip. 만료 후 1회 재시도 (포지션 정리로 마진 회복 가능) —
# 여전히 부족하면 재쿨다운 (알림은 쿨다운 동안 dedup 되어 재발송 X).
# ---------------------------------------------------------------------------
_MARGIN_COOLDOWN_TTL = 1800  # 30분
_MARGIN_COOLDOWN_KEY = "stage_margin_cooldown:strategy:{sid}:stage:{n}"

# 🌟 2026-06-10 v18 사장님 critical (= 자동 진입 silent 차단 영구 차단):
# 사장님 우려: "2단계도 문제인데 3단계로 문제가 되면 큰 자금을 잃게 되는데 확실하게 답을 찾아 수정해줘"
# = 모든 silent 차단 = Redis 기록 + 화면 즉시 표시 + Telegram (1시간 dedup)
# = 사장님 즉시 인지 + 수동 조치 가능 + silent 위험 영구 차단
_BLOCK_REASON_KEY = "stage_trigger_block:strategy:{sid}"
_BLOCK_REASON_TTL = 600  # 10분 (= 다음 cycle 까지 표시)
_BLOCK_ALERT_DEDUP_KEY = "stage_trigger_block_alert:strategy:{sid}:reason:{r}"
_BLOCK_ALERT_DEDUP_TTL = 3600  # 1시간 (= 알림 spam 차단)


def _record_block_reason(
    redis_client, sid: int, reason: str, stage_no: int = 0, detail: dict | None = None,
) -> None:
    """차단 이유 Redis 기록 (= 진단 endpoint + 화면 표시).

    사장님 헌법 8번 (= silent 차단 금지): 모든 차단 = 사장님이 즉시 알 수 있어야 함.

    🚨 Fix 201 (2026-08-28): `detail` 추가.
      지금까지 지표 상세(rsi/macd/cci 의 now·prev·turn)는 **로그에만** 있었다.
      그래서 사장님이 「왜 안 들어가지?」를 알려면 서버 로그를 봐야 했다.
      화면 배지를 눌렀을 때 근거를 보여주려면 사유와 **같이** 저장돼 있어야 한다.
    """
    if redis_client is None:
        return
    try:
        import json
        from datetime import datetime, timezone
        payload = json.dumps({
            "reason": reason,
            "stage_no": stage_no,
            "blocked_at": datetime.now(timezone.utc).isoformat(),
            "detail": detail or {},
        }, default=str)          # Decimal 등이 섞여도 기록이 통째로 날아가지 않게
        redis_client.setex(_BLOCK_REASON_KEY.format(sid=sid), _BLOCK_REASON_TTL, payload)
    except Exception:
        pass


def _clear_block_reason(redis_client, sid: int) -> None:
    """차단 해소 (= 정상 진입 시 호출)."""
    if redis_client is None:
        return
    try:
        redis_client.delete(_BLOCK_REASON_KEY.format(sid=sid))
    except Exception:
        pass


def _alert_silent_block_once(redis_client, db, strategy, reason: str, stage_no: int) -> None:
    """silent 차단 = 1시간 dedup Telegram 알림 (= spam 방지 + 사장님 인지).

    이미 1시간 내에 같은 이유로 알림 보냈으면 = skip (dedup).
    """
    if redis_client is None:
        return
    try:
        dedup_key = _BLOCK_ALERT_DEDUP_KEY.format(sid=strategy.id, r=reason[:30])
        if redis_client.get(dedup_key):
            return  # 1시간 내 이미 알림 = skip
        redis_client.setex(dedup_key, _BLOCK_ALERT_DEDUP_TTL, "1")
        NotificationService(db).send_system_alert(
            title=f"⚠️ [자동 진입 차단] #{strategy.id} {strategy.symbol} 단계{stage_no}",
            body=(
                f"🚨 자동 진입 차단 중 — 사장님 자본 보호 안전망 발동.\n\n"
                f"📌 차단 이유: {reason}\n"
                f"📌 strategy_id: #{strategy.id}\n"
                f"📌 심볼: {strategy.symbol} ({strategy.side})\n"
                f"📌 차단 단계: {stage_no}\n\n"
                f"💡 사장님 조치:\n"
                f"  • 화면 진단: /api/v1/admin/diagnostic/auto-entry-status\n"
                f"  • 수동 진입: 「▶ 다음 단계」 버튼\n"
                f"  • 1시간 후 = 자동 재시도 (또는 cycle 재개 시)\n\n"
                f"⚠️ 이 알림 = 1시간 dedup (= spam 차단)"
            ),
        )
    except Exception:
        pass


def _margin_cooldown_active(redis_client, sid: int, stage_no: int) -> bool:
    if redis_client is None:
        return False
    try:
        return bool(redis_client.get(_MARGIN_COOLDOWN_KEY.format(sid=sid, n=stage_no)))
    except Exception:
        return False


def _set_margin_cooldown(redis_client, sid: int, stage_no: int) -> bool:
    """쿨다운 설정. 새로 설정했으면 True (알림 발송), 이미 있었으면 False (dedup)."""
    if redis_client is None:
        return True  # redis 없으면 알림은 보냄 (안전), 쿨다운만 불가
    key = _MARGIN_COOLDOWN_KEY.format(sid=sid, n=stage_no)
    try:
        if redis_client.get(key):
            return False  # 이미 쿨다운 중 — 알림 dedup
        redis_client.setex(key, _MARGIN_COOLDOWN_TTL, "1")
        return True
    except Exception:
        return True


def _is_margin_insufficient(exc: Exception) -> bool:
    msg = str(exc)
    return "-2019" in msg or "Margin is insufficient" in msg


# ---------------------------------------------------------------------------
# 🌟 Fix 55 사장님 critical (2026-08-24): 마틴게일 단계별 지표 반전 확인!
# 사장님 verbatim: "충분히 상승/하락 반복 → 조정 시점 진입 → 3단계까지 실패는 말이 안돼!"
#
# 옛 로직: PRICE_DOWN_PCT = mark >= trigger 도달만 = 지표 확인 없음!
#   → 2/3/4단계 = 자본 6배씩 폭발하는데도 = 같은 조건으로 자동 진입!
#
# 신 로직 (Fix 55):
#   - 2단계 = 지표 반전 2/3 통과 (MEDIUM)
#   - 3단계+ = 지표 반전 3/3 통과 (STRICT)
#   - 24h 변동 필터 (헌법 64): SHORT + +15% 이상 = skip / LONG + -15% 이하 = skip
#   - 1단계는 대상 아님 (원 진입 = 신 진입 워커 별도!)
# ---------------------------------------------------------------------------
def _check_stage_indicator_reversal(bc, symbol: str, side: str, next_stage: int) -> tuple[bool, dict]:
    """Fix 55: 마틴게일 2단계+ 지표 반전 확인 (RSI / MACD Hist / OBV).

    SHORT = 상승 반전 필요 (가격 상승 중단!)
    LONG  = 하락 반전 필요 (가격 하락 중단!)

    Returns (passed, detail_dict). fail-safe: 지표 확인 실패 시 False (skip!).
    """
    try:
        from app.services.chart_analyzer import ChartAnalyzer
        result = ChartAnalyzer.analyze_timeframe(bc, symbol, "15m")
        if not result:
            return False, {"error": "analyze_timeframe empty"}
        rsi_now = result.get("rsi_now")
        rsi_prev = result.get("rsi_prev")
        macd_hist = result.get("macd_hist") or []
        obv = result.get("obv") or []

        macd_hist_now = macd_hist[-1] if macd_hist else None
        macd_hist_prev = macd_hist[-2] if len(macd_hist) >= 2 else None
        # OBV 기울기 = 최근 5 봉 방향 (양수=상승 / 음수=하락)
        obv_slope = None
        if len(obv) >= 5:
            obv_slope = obv[-1] - obv[-5]

        side_u = (side or "").upper()
        if side_u == "SHORT":
            # SHORT 추가 진입 = 상승세 꺾임 확인!
            rsi_reversal = (
                rsi_prev is not None and rsi_now is not None
                and rsi_now < rsi_prev - 1.0
            )
            macd_reversal = (
                macd_hist_prev is not None and macd_hist_now is not None
                and macd_hist_now < macd_hist_prev
            )
            obv_reversal = obv_slope is not None and obv_slope < 0
        else:  # LONG
            # LONG 추가 진입 = 하락세 꺾임 확인!
            rsi_reversal = (
                rsi_prev is not None and rsi_now is not None
                and rsi_now > rsi_prev + 1.0
            )
            macd_reversal = (
                macd_hist_prev is not None and macd_hist_now is not None
                and macd_hist_now > macd_hist_prev
            )
            obv_reversal = obv_slope is not None and obv_slope > 0

        passed = sum([bool(rsi_reversal), bool(macd_reversal), bool(obv_reversal)])

        # 단계별 필요 통과 수 (사장님 verbatim: 3단계까지 최대!)
        if next_stage == 2:
            required = 2  # 2/3 (MEDIUM)
        else:  # 3단계+ = 자본 폭발 방지 매우 신중!
            required = 3  # 3/3 (STRICT)

        detail = {
            "rsi": bool(rsi_reversal),
            "macd": bool(macd_reversal),
            "obv": bool(obv_reversal),
            "passed": passed,
            "required": required,
            "rsi_now": rsi_now,
            "rsi_prev": rsi_prev,
            "macd_hist_now": macd_hist_now,
            "obv_slope": obv_slope,
        }
        return passed >= required, detail
    except Exception as e:
        logger.warning("[Fix55/reversal] %s stage=%s: %s", symbol, next_stage, e)
        return False, {"error": str(e)}  # fail-safe = skip 진입!


def _check_stage_24h_filter(bc, symbol: str, side: str) -> tuple[bool, float | None]:
    """Fix 55: 24h 변동 필터 (헌법 64 = 급등 반대매매 금지!).

    SHORT + 24h ≥ +15% = skip (급등에 SHORT 진입 = 물타기 폭발!)
    LONG  + 24h ≤ -15% = skip (급락에 LONG 진입 = 물타기 폭발!)

    fail-open: ticker 조회 실패 시 True (기존 로직 유지 = 진입 허용).
    """
    try:
        t = bc.get_24hr_ticker(symbol=symbol)
        if isinstance(t, list):
            t = t[0] if t else {}
        chg = float(t.get("priceChangePercent", 0) or 0)
        side_u = (side or "").upper()
        if side_u == "SHORT" and chg >= 15:
            return False, chg
        if side_u == "LONG" and chg <= -15:
            return False, chg
        return True, chg
    except Exception as e:
        logger.warning("[Fix55/24h] %s: %s", symbol, e)
        return True, None  # fail-open (기존 로직 유지)


def run_stage_trigger_once(decrypt_text) -> None:
    """활성 전략의 다음 stage 트리거 검사 + 자동 LIMIT 주문 발송.

    매 10초마다 scheduler 가 호출. Redis lock 은 scheduler 가 처리.
    """
    from app.core.redis_client import get_redis_client
    try:
        _redis = get_redis_client()
    except Exception:
        _redis = None
    db = SessionLocal()
    try:
        from app.models.strategy_template import StrategyTemplate
        rows = db.execute(
            select(StrategyInstance, ExchangeAccount)
            .join(ExchangeAccount, StrategyInstance.exchange_account_id == ExchangeAccount.id)
            .where(StrategyInstance.status.in_(ACTIVE_STAGE_STATUSES))
            .where(StrategyInstance.is_archived.is_(False))  # 2026-05-06 C-full
            .where(ExchangeAccount.is_active.is_(True))
        ).all()
        # A08 fix: N+1 방지 — 모든 strategy 의 template 을 한 번에 batch fetch.
        # 이전엔 strategy 마다 SessionLocal() + db.get() 호출 → 활성 N개일 때 N개 세션.
        template_ids = {s.strategy_template_id for s, _ in rows if s.strategy_template_id}
        templates = (
            {t.id: t for t in db.query(StrategyTemplate).filter(StrategyTemplate.id.in_(template_ids)).all()}
            if template_ids else {}
        )
        # 🎯 Fix 121 (2026-08-26 헌법 80): 완료 로그가 아예 없어서
        #   「정상인데 발동 조건 미달」과 「워커 사망」을 구별할 수 없었다.
        #   사장님이 Fix 113/114 검증하려고 로그를 봤는데 아무것도 없었음.
        _stat = {"rows": len(rows), "scanned": 0, "fired": 0, "banned": 0, "err": 0}
        # 2026-05-17 rate limit ban 스파이럴 사후: account 별 ban skip (tp_sl 와 동일 패턴).
        _banned_accounts: set[int] = set()
        for strategy, account in rows:
            if account.id in _banned_accounts:
                continue
            if is_account_banned(account.id):
                _banned_accounts.add(account.id)
                logger.info("[stage-trigger] API ban active account=%s — skip cycle", account.id)
                _stat["banned"] += 1
                continue
            _stat["scanned"] += 1
            next_stage_no: int | None = None  # 2026-06-01: try 진입 전 명시 (except 분기에서 안전 참조)
            try:
                # 🚨 2026-08-10 v131 사장님 critical (#828 TSTUSDT 사례!):
                # 「청산 후 재진입」 세팅 = 옛 stage_trigger 완전 skip!
                # 사장님 사고:
                #   1단계 진입 → 손실 → 청산 (전량 0!)
                #   → 청산가 기준 트리거 → 2단계 신 진입!
                #   = 각 단계 = 순차 = 절대 동시 보유 X!
                #
                # 옛 병행 로직 (v131 초기 = 잘못!):
                #   retry ON 이어도 = 옛 +10% 도달 시 = 2단계 진입!
                #   → 1+2단계 동시 보유! → 사장님 사고 X!
                #
                # 신 v131 (사장님 정확 사고!):
                #   retry ON = STAGES_WITH_NEXT (STAGE1_OPEN 등) 상태 = 옛 로직 skip!
                #   = 오직 LIQUIDATED_WAITING_RETRY 상태 = 신 로직으로 진입!
                if getattr(strategy, "retry_after_liquidation_enabled", False):
                    if strategy.status != "LIQUIDATED_WAITING_RETRY":
                        # 옛 stage_trigger 로직 skip! (사장님 사고 = 청산 후만!)
                        continue
                # 2026-06-01 Critical fix: STAGE_OPEN_PENDING 도 검사 대상 (Sub-account user-stream
                # ORDER 미수신 시 PENDING 머무름). 단, 실 포지션 없으면 (current_position_qty=0)
                # 다음 stage 검사 X — 1단계 진입 자체가 아직 안 됐다는 의미. 안전망.
                if strategy.status and strategy.status.endswith("_OPEN_PENDING"):
                    cur_qty = strategy.current_position_qty
                    if cur_qty is None or abs(float(cur_qty)) < 1e-12:
                        # 🌟 v18 fix: 1단계 미체결 = silent 차단 → 사장님 인지!
                        _record_block_reason(_redis, strategy.id, "1단계 LIMIT 미체결 (qty=0)", (strategy.current_stage or 0) + 1)
                        _alert_silent_block_once(_redis, db, strategy, "1단계 LIMIT 미체결", (strategy.current_stage or 0) + 1)
                        continue  # 1단계 LIMIT 미체결 — 다음 stage 검사 의미 X
                next_stage_no = (strategy.current_stage or 0) + 1
                total_stages = _count_total_stages_from_template(templates.get(strategy.strategy_template_id))
                if next_stage_no > total_stages:
                    # 모든 단계 완료 = 정상 = block_reason 정리
                    _clear_block_reason(_redis, strategy.id)
                    continue  # 모든 단계 진입 완료
                # Stage plans 조회 (lazy load 회피 위해 새 쿼리)
                from app.models.strategy_stage_plan import StrategyStagePlan
                next_plan = db.execute(
                    select(StrategyStagePlan)
                    .where(StrategyStagePlan.strategy_instance_id == strategy.id)
                    .where(StrategyStagePlan.stage_no == next_stage_no)
                ).scalar_one_or_none()
                if not next_plan:
                    # 🌟 v18 fix: stage_plans 손상 = 사장님 critical!
                    _record_block_reason(_redis, strategy.id, f"단계{next_stage_no} plan 없음 (DB 손상?)", next_stage_no)
                    _alert_silent_block_once(_redis, db, strategy, f"단계{next_stage_no} stage_plan 없음 (DB 손상 가능)", next_stage_no)
                    continue
                if next_plan.is_triggered:
                    continue  # 이미 진입됨 (= 정상, 차단 X)
                # 2026-05-19: 마진부족(-2019) 쿨다운 중인 단계는 skip (재시도 spam 차단)
                if _margin_cooldown_active(_redis, strategy.id, next_stage_no):
                    # 🌟 v18 fix: cooldown 차단 = 사장님 즉시 인지!
                    _record_block_reason(_redis, strategy.id, "Redis margin cooldown (30분 대기)", next_stage_no)
                    continue
                # ══════════════════════════════════════════════════════════
                # 🚨 Fix 113 (2026-08-26 사장님: "새전략 기본방식 / OBV
                #    자동 단계별 진입이 진행되지 않아")
                #
                # 옛 버그: 여기서 trigger_price 가 없으면 무조건 continue.
                #   그런데 모드 분기(아래 L~470)는 이 게이트 「뒤」에 있다!
                #   → 가격 트리거를 애초에 쓰지 않는 3개 모드가 전부 영구 차단:
                #     (1) OBV_REVERSE          = OBV 신호로 진입 (가격 무관!)
                #     (2) LIQUIDATED_WAITING_RETRY = 청산가 기준 (가격 무관!)
                #     (3) LIQUIDATION_BUFFER   = 청산가 기반 실시간 산출 대상인데
                #                                산출 코드가 없어 "미구현" 상태였음
                #   ⚠️ Decimal("0") 도 falsy → trigger_price=0 이어도 같이 막혔음!
                #
                # 신: 모드를 「먼저」 판정하고, 가격 트리거가 실제로 필요한
                #     경로에만 이 게이트를 적용한다. LIQUIDATION_BUFFER 는
                #     이 자리에서 청산가 기준으로 산출 (= 미구현 해소!).
                # ══════════════════════════════════════════════════════════
                _tpl_trigger_mode = "PRICE_DOWN_PCT"
                try:
                    from app.models.strategy_template import StrategyTemplate as _TmplM0
                    _tpl_row0 = (
                        db.get(_TmplM0, strategy.strategy_template_id)
                        if strategy.strategy_template_id else None
                    )
                    if _tpl_row0 and getattr(_tpl_row0, "trigger_mode", None):
                        _tpl_trigger_mode = _tpl_row0.trigger_mode
                except Exception as _tme:
                    logger.warning("[Fix113] #%s template trigger_mode 조회 실패: %s", strategy.id, _tme)

                _plan_mode = str(getattr(next_plan, "trigger_mode", "") or "").upper()
                _is_retry_mode = strategy.status == "LIQUIDATED_WAITING_RETRY"
                _is_obv_mode = _tpl_trigger_mode == "OBV_REVERSE"
                _is_liqbuf_mode = _plan_mode == "LIQUIDATION_BUFFER"

                _trigger_px = next_plan.trigger_price
                if not _trigger_px:
                    if _is_liqbuf_mode:
                        # 🎯 Fix 113: 「청산가 산출 시점에 채움」 = 여기가 그 시점!
                        #   SHORT = 가격이 위로 가며 청산에 접근 → 청산가 살짝 아래에서 진입
                        #   LONG  = 가격이 아래로 가며 청산에 접근 → 청산가 살짝 위에서 진입
                        # 🚨 Fix 128 (2026-08-26): Fix 113 의 청산가 산출에 2가지 결함
                        #   (15 에이전트 감사 지적 — 둘 다 실 자본 오발주로 이어짐)
                        #
                        # (a) last_liquidation_price 는 「과거에 청산된 가격」이다.
                        #     stream_service:253 이 청산 체결 시 order.avg_price 를 넣는다.
                        #     활성 포지션의 「현재 청산가」가 아니므로 fallback 으로 쓰면 안 된다.
                        #     → 청산 후 재진입 대기(LIQUIDATED_WAITING_RETRY) 일 때만 의미가 있다.
                        #
                        # (b) buffer 로 쓴 trigger_percent 의 기본값이 20 이다
                        #     (DEFAULT_LAST_SHORT_TRIGGER_PCT — 원래 PRICE_UP_PCT 용 값!).
                        #     SHORT 에서 trigger = 청산가 × 0.8 이면 현재가보다 「아래」로
                        #     떨어질 수 있고, 그러면 mark >= trigger 가 즉시 참 = 즉시 발주!
                        #     → buffer 를 1~10% 로 제한하고, 방향 sanity 검사를 추가한다.
                        _liq = None
                        try:
                            _lp = PositionRepository(db).latest_by_strategy(strategy.id)
                            if _lp and _lp.liquidation_price and Decimal(str(_lp.liquidation_price)) > 0:
                                _liq = Decimal(str(_lp.liquidation_price))   # 거래소 실시간 청산가
                            elif _is_retry_mode and strategy.last_liquidation_price:
                                # 청산 후 재진입 대기 상태에서만 「과거 청산가」가 의미를 갖는다
                                _liq = Decimal(str(strategy.last_liquidation_price))
                        except Exception as _le:
                            logger.warning("[Fix113/liqbuf] #%s 청산가 조회 실패: %s", strategy.id, _le)
                        if not _liq or _liq <= 0:
                            _record_block_reason(
                                _redis, strategy.id,
                                f"단계{next_stage_no} LIQUIDATION_BUFFER: 현재 청산가 미확보 "
                                f"(Position.liquidation_price 동기화 대기)",
                                next_stage_no,
                            )
                            continue
                        # buffer 는 「청산가 코앞」을 뜻한다 = 1~10% 로 제한 (기본 5%)
                        try:
                            _buf_raw = Decimal(str(getattr(next_plan, "trigger_percent", None) or 5))
                        except Exception:
                            _buf_raw = Decimal("5")
                        _buf_pct = min(max(_buf_raw, Decimal("1")), Decimal("10"))
                        if _buf_pct != _buf_raw:
                            logger.warning(
                                "[Fix128/liqbuf] #%s buffer %s%% → %s%% 로 제한 "
                                "(trigger_percent 는 원래 PRICE_*_PCT 용 값이라 그대로 쓰면 위험!)",
                                strategy.id, _buf_raw, _buf_pct,
                            )
                        if strategy.side == "SHORT":
                            _trigger_px = _liq * (Decimal("1") - _buf_pct / Decimal("100"))
                        else:
                            _trigger_px = _liq * (Decimal("1") + _buf_pct / Decimal("100"))
                        logger.info(
                            "[Fix113/liqbuf] #%s %s 단계%d trigger 산출: 청산가=%s buffer=%s%% → %s",
                            strategy.id, strategy.side, next_stage_no, _liq, _buf_pct, _trigger_px,
                        )
                        # 🚨 Fix 128 방향 sanity: 「아직 도달하지 않은 가격」이어야 한다.
                        #   SHORT 는 가격이 올라가며 청산에 접근 → trigger 는 현재가보다 위,
                        #   LONG 은 내려가며 접근 → trigger 는 현재가보다 아래여야 한다.
                        #   아니면 계산이 무의미한 상태 = 즉시 발주 위험 → 차단!
                        _mark_now = None
                        try:
                            from app.services.mark_price_cache import get_mark_price as _gmp
                            _m = _gmp(strategy.symbol)
                            if _m:
                                _mark_now = Decimal(str(_m))
                        except Exception:
                            _mark_now = None
                        if _mark_now and _mark_now > 0:
                            _wrong_side = (
                                (strategy.side == "SHORT" and _trigger_px <= _mark_now)
                                or (strategy.side == "LONG" and _trigger_px >= _mark_now)
                            )
                            if _wrong_side:
                                _reason128 = (
                                    f"단계{next_stage_no} LIQUIDATION_BUFFER 즉시발주 방지: "
                                    f"trigger={_trigger_px} 가 현재가({_mark_now}) 반대편 "
                                    f"(청산가={_liq} buffer={_buf_pct}%) = 계산 무의미 → 차단"
                                )
                                logger.warning("[Fix128/liqbuf] #%s %s", strategy.id, _reason128)
                                _record_block_reason(_redis, strategy.id, _reason128, next_stage_no)
                                _alert_silent_block_once(
                                    _redis, db, strategy, _reason128, next_stage_no,
                                )
                                continue
                    elif _is_retry_mode or _is_obv_mode:
                        # 가격 트리거 불필요 = 통과! (아래 모드 분기에서 실제 판정)
                        logger.info(
                            "[Fix113] #%s 단계%d trigger_price 없음이지만 %s 모드 = 통과!",
                            strategy.id, next_stage_no,
                            "LIQUIDATED_WAITING_RETRY" if _is_retry_mode else "OBV_REVERSE",
                        )
                    else:
                        _record_block_reason(
                            _redis, strategy.id,
                            f"단계{next_stage_no} trigger_price 미설정 (mode={_plan_mode or 'N/A'})",
                            next_stage_no,
                        )
                        _alert_silent_block_once(
                            _redis, db, strategy,
                            f"단계{next_stage_no} trigger_price 미설정", next_stage_no,
                        )
                        continue
                # 현재 mark price 조회.
                # 🚨 2026-06-22 사장님 critical fix (v51 — "또 2단계가 진행되지 않았어"):
                # 옛 버그: DB Position snapshot 의 mark_price 만 사용 → stage 1 진입 직후엔
                #   snapshot 에 markPrice 가 아직 안 채워져 None → "mark_price 없음" silent 차단.
                #   reconcile_worker(2분 주기) 가 채우기 전까지 stage 2 자동 진입 영구 보류.
                #   = 사장님 화면엔 live 현재가가 멀쩡히 보이는데도 자동 진입만 막힘
                #     (#221 IDUSDT / #220 AINUSDT / #215 / #217 / #218 / #219 전부 동일 차단).
                # 진짜 원인: 자동 진입(가장 critical 경로)만 가장 stale 한 소스(DB snapshot)를
                #   사용. UI/PNL(helpers.py) 과 수동 진입(control.py L1043/L1363) 은 이미 Redis
                #   실시간 캐시(get_mark_price = markPrice@1s) 를 "현재가" 단일 진실로 사용 중.
                #   → 알림이 "mark-price-stream 점검 필요" 라 stream 을 의심하게 만들지만 실제로
                #     stream(Redis) 은 정상 작동 — 자동 진입 코드가 그걸 안 읽을 뿐이었음.
                # fix (헌법 6번 단일 진실): 자동 진입도 Redis 캐시 우선, miss 시 DB snapshot fallback.
                #   = 화면 현재가 == 자동 진입 트리거 가격 (= 같은 소스 = silent bug 영구 차단).
                from app.services.mark_price_cache import get_mark_price
                mark = get_mark_price(strategy.symbol)  # Redis 실시간 (1s) 우선
                if mark is None or mark <= 0:
                    # 캐시 miss → DB Position snapshot fallback (reconcile 가 채운 값)
                    latest_pos = PositionRepository(db).latest_by_strategy(strategy.id)
                    if latest_pos and latest_pos.mark_price:
                        mark = Decimal(str(latest_pos.mark_price))
                if mark is None or mark <= 0:
                    # 🚨 2026-06-25 사장님 critical fix (v52 — #231 SYNUSDT race condition!):
                    # 옛 v51 = Redis 캐시 우선 + DB snapshot fallback = 둘 다 없으면 차단 알림!
                    # But = 1단계 진입 직후 = mark-price-stream SUBSCRIBE 호출 = But 첫 update 안 옴!
                    # = stage_trigger_worker (1분 주기) = 1단계 진입 직후 = race 첫 사이클!
                    # = Redis 캐시 X + DB snapshot X = silent false-positive 차단!
                    # = #231 SYNUSDT 06.24 14:50:32 진입 + 14:50:33 차단 = 12초 race!
                    #
                    # fix v52a (2026-06-25 hot-fix): Position.entered_at = X! → strategy.started_at!
                    # = 사장님 #234 ACUUSDT / #237 SLXUSDT = silent bug = Position 속성 잘못!
                    # = strategy.started_at = 전략 시작 시각 = grace period 기준 정확!
                    GRACE_PERIOD_SEC = 180  # 3분 = mark-price-stream SUBSCRIBE + 첫 update 충분!
                    if strategy.started_at:
                        from datetime import datetime, timezone
                        now_utc = datetime.now(timezone.utc)
                        started_utc = strategy.started_at
                        if started_utc.tzinfo is None:
                            started_utc = started_utc.replace(tzinfo=timezone.utc)
                        elapsed = (now_utc - started_utc).total_seconds()
                        if elapsed < GRACE_PERIOD_SEC:
                            # grace 기간 = 차단 알림 X = 다음 cycle 재시도!
                            logger.info(
                                "[stage-trigger v52a grace] #%s %s 전략 시작 %.0fs 전 = mark_price 대기 중 (grace=%ds)",
                                strategy.id, strategy.symbol, elapsed, GRACE_PERIOD_SEC,
                            )
                            continue
                    # grace 후 또는 started_at 없음 = 정상 차단 알림!
                    _record_block_reason(_redis, strategy.id, "mark_price 없음 (Redis 캐시 + DB snapshot 모두 누락)", next_stage_no)
                    _alert_silent_block_once(_redis, db, strategy, "mark_price 없음 (mark-price-stream 점검 필요)", next_stage_no)
                    continue
                mark = Decimal(str(mark))
                # 🌟 2026-08-06 v130 사장님 신 로직: trigger_mode 분기!
                # spec: docs/CHART_REENTRY_STRATEGY_SPEC.md
                # 기존 (PRICE_DOWN_PCT): 가격 도달 시 진입
                # 신 (OBV_REVERSE): 4H OBV 첫 하락 + 15m/1h + 10% 가격 이동
                # ⚠️ Fix 113: _tpl_trigger_mode 는 위(trigger_price 게이트 직전)에서
                #   이미 판정했다 = 재조회 X (헌법 6 단일 진실 + DB 왕복 절약).
                #
                # 🚨🚨 Fix 129 (2026-08-26 CRITICAL — 사장님 "obv 단계 진입이 안 돼"의 진짜 원인):
                #   `trigger` 는 아래 else(PRICE_DOWN_PCT) 분기 「안에서만」 정의되는데,
                #   발주 직전 로그(L~846)가 f-string 으로 무조건 참조한다.
                #   → OBV_REVERSE / LIQUIDATED_WAITING_RETRY 경로는 정의되지 않은 채 도달
                #   → NameError → 바깥 except 가 삼킴 → "failed for strategy #N" 만 남고
                #     trigger_next_stage 가 호출되지 않는다 = 주문이 나가지 않는다!
                #   즉 「발주 직전 로그 한 줄」 때문에 OBV 단계 진입이 한 번도 성공한 적이 없다.
                #   (Fix 113 으로 게이트를 통과시켜도 여기서 죽으므로 여전히 진입 0건)
                trigger = None
                should_fire = False
                # ══════════════════════════════════════════════════════════════
                # 🎯 Fix 174 (2026-08-27 사장님): 청산 후 다음 단계도 「운영 로직」으로.
                #
                # 사장님 질문: "처음 진입한 포지션이 -5% 면 청산하고 다음 단계 포지션이
                #              진입되나요?" → 되긴 하는데, **가격 트리거**로 들어갔다.
                #
                # 옛 구조의 문제: 아래 retry 분기가 OBV 분기(더 아래)보다 **먼저** 실행되고
                # 주석에 "trigger_mode / OBV 무관" 이라고 못 박혀 있었다.
                # → 청산 후 재진입은 「청산가 대비 retry_trigger_pct(기본 10%)」라는
                #   **가격 트리거**로만 들어갔고, Fix 173 에서 만든 운영 로직이
                #   이 경로에는 아예 닿지 않았다.
                #   사장님이 "트리거%를 내가 임의로 정했는데 이제 운영 로직으로" 라고
                #   하신 것과 정면으로 어긋난다.
                #
                # 신: OBV 모드 전략이면 청산 후 재진입도 운영 로직으로 판정한다.
                #     기존 방식(PRICE_*) 전략은 손대지 않는다 — 사장님 지시 범위가
                #     "일단 obv 로직에 만들어줘" 였다.
                # ══════════════════════════════════════════════════════════════
                if strategy.status == "LIQUIDATED_WAITING_RETRY" and _is_obv_mode:
                    try:
                        from app.integrations.binance.client import BinanceClient
                        from app.services.stage_entry_signal import check_stage_entry_signal
                        _bc_r = BinanceClient(
                            api_key=decrypt_text(account.api_key_enc),
                            api_secret=decrypt_text(account.api_secret_enc),
                            is_testnet=account.is_testnet,
                        )
                        _sig_ok, _sig_why, _sig_det = check_stage_entry_signal(
                            _bc_r, db, strategy.symbol, strategy.side,
                        )
                        should_fire = _sig_ok
                        if _sig_ok:
                            logger.info(
                                "[stage-trigger Fix174 retry+OBV] 🎯 청산 후 재진입 신호! "
                                "strategy=%s stage=%s %s %s | %s",
                                strategy.id, next_stage_no, strategy.symbol, strategy.side, _sig_why,
                            )
                        else:
                            logger.info(
                                "[stage-trigger Fix174 retry+OBV] ⏳ 청산 후 대기: "
                                "strategy=%s stage=%s %s %s — %s",
                                strategy.id, next_stage_no, strategy.symbol, strategy.side, _sig_why,
                            )
                            _record_block_reason(
                                _redis, strategy.id,
                                f"Fix174 청산후 대기: {_sig_why}", next_stage_no,
                            )
                    except Exception as _e:
                        logger.warning("[stage-trigger Fix174 retry+OBV] 판정 실패 (보류): %s", _e)
                        try:
                            _record_block_reason(
                                _redis, strategy.id,
                                f"Fix174 청산후 판정 실패: {_e}", next_stage_no,
                            )
                        except Exception:
                            pass
                        should_fire = False
                # 🌟 v131 (2026-08-09 사장님!): 청산 후 자동 재진입 (기존 방식 = 가격 트리거)
                # LIQUIDATED_WAITING_RETRY = 청산가 기준 트리거 감시! (retry_trigger_pct!)
                elif strategy.status == "LIQUIDATED_WAITING_RETRY":
                    try:
                        _liq_price = Decimal(str(strategy.last_liquidation_price or 0))
                        # 🌟 v131 하이브리드 (사장님!): 단계별 개별 우선 → 기본값!
                        _trg_pct = Decimal(str(strategy.retry_trigger_pct or 10))  # 기본값!
                        try:
                            _overrides = getattr(strategy, "retry_stage_trigger_pcts", None) or {}
                            _key = str(next_stage_no)
                            if _key in _overrides and _overrides[_key] is not None:
                                _trg_pct = Decimal(str(_overrides[_key]))  # 개별 override!
                                logger.info(
                                    "[v131 retry] 개별 트리거 사용! strategy=%s stage=%s pct=%s (기본=%s)",
                                    strategy.id, next_stage_no, _trg_pct, strategy.retry_trigger_pct,
                                )
                        except Exception as _oe:
                            logger.warning("[v131 retry] 개별 트리거 조회 실패 → 기본값: %s", _oe)
                        if _liq_price <= 0:
                            _record_block_reason(
                                _redis, strategy.id,
                                "청산가 없음 (last_liquidation_price=0) — retry 진입 skip!",
                                next_stage_no,
                            )
                            continue
                        # LONG: 가격이 청산가 대비 -트리거% 도달 → 저점 매수!
                        # SHORT: 가격이 청산가 대비 +트리거% 도달 → 고점 매도!
                        if strategy.side == "LONG":
                            _target = _liq_price * (Decimal("1") - _trg_pct / Decimal("100"))
                            should_fire = mark <= _target
                        else:  # SHORT
                            _target = _liq_price * (Decimal("1") + _trg_pct / Decimal("100"))
                            should_fire = mark >= _target
                        if should_fire:
                            logger.info(
                                "[stage-trigger v131 retry] 🎯 청산 후 재진입! strategy=%s stage=%s "
                                "청산가=%s trigger=%s%% target=%s mark=%s",
                                strategy.id, next_stage_no, _liq_price, _trg_pct, _target, mark,
                            )
                    except Exception as _e:
                        logger.warning("[stage-trigger v131 retry] 판정 실패: %s", _e)
                        should_fire = False
                elif _tpl_trigger_mode == "OBV_REVERSE":
                    # ══════════════════════════════════════════════════════════
                    # 🎯 Fix 173 (2026-08-27 사장님): 「운영 중인 로직」으로 단계 진입.
                    #
                    # 사장님 verbatim:
                    #   "기본에는 트리거%를 내가 임의로 정했는데 지금부터는 지금 운영중인
                    #    로직으로 포지션에 들어가게 해줘 ... 지금까지 다음 포지션 진입에
                    #    대한 신뢰가 없어서 사용하지 못했는데 가능할까?"
                    #
                    # 옛 코드는 ChartAnalyzer.check_obv_reverse_signal 을 썼는데
                    # 신뢰를 못 받은 이유가 코드에 그대로 있었다:
                    #   1) **SHORT 전용 하드코딩** — check_4h_first_bear_bar /
                    #      check_15m_1h_bearish_trend 둘 다 「하락」만 본다.
                    #      LONG 전략에 걸면 방향이 반대라 사실상 발동하지 않는다.
                    #   2) **3중 AND** (4H 첫 하락봉 AND 15m+1h 하락 AND 손절가 대비 10%)
                    #      — 동시에 성립하는 창이 매우 좁다.
                    #   3) **운영 로직과 다르다** — 자동 진입 워커는 obv_gate +
                    #      confirm_peak 를 쓴다. 즉 「자동 진입이 옳다고 보는 기준」과
                    #      「단계 진입이 보는 기준」이 서로 달랐다. 신뢰가 안 생기는 게 당연하다.
                    #   4) **차단 사유가 안 남는다** — 왜 안 들어갔는지 볼 수 없었다.
                    #
                    # 신: stage_entry_signal.check_stage_entry_signal =
                    #     자동 진입 워커와 **같은 함수를 같은 순서로** 호출한다.
                    #     방향(LONG/SHORT)도 자동 판정한다.
                    #     차단되면 사유를 Redis 에 남긴다 (헌법 8 = silent 차단 금지).
                    #
                    # ⚠️ 단계별 「지정 금액」은 이 판정과 무관하게 그대로 쓰인다 —
                    #    stage_plan.planned_capital 이 발주 시 Fix 130 경로에서
                    #    현재가 기준으로 수량 재계산된다. 사장님이 입력한 금액 그대로다.
                    # ══════════════════════════════════════════════════════════
                    try:
                        from app.integrations.binance.client import BinanceClient
                        from app.services.stage_entry_signal import check_stage_entry_signal
                        _bc = BinanceClient(
                            api_key=decrypt_text(account.api_key_enc),
                            api_secret=decrypt_text(account.api_secret_enc),
                            is_testnet=account.is_testnet,
                        )
                        _sig_ok, _sig_why, _sig_det = check_stage_entry_signal(
                            _bc, db, strategy.symbol, strategy.side,
                        )
                        should_fire = _sig_ok
                        if _sig_ok:
                            logger.info(
                                "[stage-trigger Fix173 OBV] 🎯 진입 신호! strategy=%s stage=%s "
                                "%s %s | %s | detail=%s",
                                strategy.id, next_stage_no, strategy.symbol, strategy.side,
                                _sig_why, _sig_det.get("gates"),
                            )
                        else:
                            # 헌법 8 / 93: 차단은 반드시 사유를 남긴다 (= 사장님 신뢰의 근거)
                            logger.info(
                                "[stage-trigger Fix173 OBV] ⏳ 대기: strategy=%s stage=%s %s %s — %s",
                                strategy.id, next_stage_no, strategy.symbol, strategy.side, _sig_why,
                            )
                            _record_block_reason(
                                _redis, strategy.id, f"Fix173 OBV 대기: {_sig_why}", next_stage_no,
                            )
                    except Exception as _e:
                        # 판정 자체가 실패 = 자본을 넣지 않는다 (보류) + 사유 기록
                        logger.warning("[stage-trigger Fix173 OBV] 분석 실패 (보류): %s", _e)
                        try:
                            _record_block_reason(
                                _redis, strategy.id, f"Fix173 OBV 분석 실패: {_e}", next_stage_no,
                            )
                        except Exception:
                            pass
                        should_fire = False
                        should_fire = False
                else:
                    # 기존 로직 (PRICE_DOWN_PCT)
                    # ⚠️ Fix 113: next_plan.trigger_price 가 아니라 _trigger_px 사용!
                    #   LIQUIDATION_BUFFER 는 위에서 청산가 기준으로 방금 산출했다.
                    trigger = Decimal(str(_trigger_px))
                    # SHORT: 가격 위로 더 갔으면 추가 SHORT 진입 (mark >= trigger)
                    # LONG: 가격 아래로 더 갔으면 추가 LONG 진입 (mark <= trigger)
                    should_fire = (mark >= trigger) if strategy.side == "SHORT" else (mark <= trigger)
                if not should_fire:
                    continue
                # ══════════════════════════════════════════════════════════
                # 🚨 Fix 203 (2026-08-29 사장님 지시): 볼밴 분할은 지표 게이트 **제외**
                #
                # 사장님 verbatim:
                #   "나는 분명히 볼밴 하단 -3%일때 100 진입 그리고 하락해서 -5% 일때
                #    추가 200 진입 그리고 -7% 하락하면 300 진입이고 모두 진입한 상태에서
                #    전체금액의 -10% 일때 청산한다고 했어 이건 그냥 이렇게 진행하고 해"
                #
                # 왜 빼야 하는가 — 아래 게이트(Fix55 지표반전 / Fix114 정점확인)는
                # 「하락이 멈춘 뒤에 사라」는 뜻이다. 그런데 볼밴 분할은 **하락하는 동안
                # 나눠 사서 평단을 낮추는** 전략이다. 두 요구가 정면으로 충돌한다.
                #
                # 실측 피해 (2026-08-29): 볼밴 17건 중 **3차 체결 0건**.
                #   Fix 195 로 트리거를 -24% → -7% 로 고쳤는데도 0건이었고,
                #   사유는 전부 "Fix114 정점 미확인" 이었다 (#1729 BEATUSDT 단계3 알림).
                #   그 결과 「작게 넣고(100) 얕은 손절(-7.85%)」이라는 최악의 조합이 됐다.
                #   설계대로 3차까지 채우면 손절선이 기준선 -10.41% 로 내려가,
                #   손실 10건 중 최소 6건은 애초에 손절당하지 않았을 깊이였다.
                #
                # ⚠️ 다른 전략은 게이트를 그대로 받는다 — 이 예외는 split_entry 뿐이다.
                #    (#1488 이 -6,981 간 뒤 만든 안전망을 통째로 걷어내는 게 아니다)
                #    손실 상한은 손절이 맡는다: 평단 ROI -10% = 600 투입 시 -60 USDT.
                # ══════════════════════════════════════════════════════════
                _is_split = (
                    str(getattr(strategy, "capital_management_mode", "") or "").lower()
                    == "split_entry"
                )
                if _is_split and next_stage_no >= 2:
                    logger.info(
                        "[Fix203/split] #%s %s %s 단계%s = 지표 게이트 건너뜀 "
                        "(볼밴 분할은 하락 중 분할 매수 = 사장님 설계)",
                        strategy.id, strategy.symbol, strategy.side, next_stage_no,
                    )
                # 🌟 Fix 55 사장님 critical (2026-08-24): 마틴게일 2단계+ 지표 반전 확인 필수!
                # 사장님 verbatim: "충분히 상승/하락 반복 → 조정 시점 진입 → 3단계까지 실패는 말이 안돼!"
                # = 옛 로직 (가격 도달만) → 신 로직 (가격 도달 + 지표 반전 + 24h 필터)!
                # 1단계는 대상 아님 (원 진입 = 신 진입 워커 별도!)
                if next_stage_no >= 2 and not _is_split:
                    try:
                        from app.integrations.binance.client import BinanceClient as _BC55
                        _bc55 = _BC55(
                            api_key=decrypt_text(account.api_key_enc),
                            api_secret=decrypt_text(account.api_secret_enc),
                            is_testnet=account.is_testnet,
                        )
                        # ══════════════════════════════════════════════════
                        # 🚨 Fix 114 (2026-08-26): (A) 24h 절대 차단 → 정점 확인으로 교체
                        #
                        # 사장님 실측 #1488: SHORT stage=2 가
                        #   "Fix55 24h 필터 차단 (chg=+153.00%)" 으로 영구 차단됨.
                        #
                        # 왜 잘못됐나:
                        #  1) 헌법 68 = 헌법 64(급등 반대매매 금지)의 「예외」가
                        #     바로 사장님 정점 SHORT. 헌법 72 = "급등해서 볼밴
                        #     상단돌파 했을때 마틴게일로 진입해야 확실한 수익".
                        #     24h ≥ +15% 절대 차단은 이 사상을 영구 봉쇄한다.
                        #  2) 이건 「신규 진입」이 아니라 「이미 열린 포지션의
                        #     계획된 2단계」다. 막으면 물타기 없이 1단계만 남아
                        #     오히려 가장 나쁜 상태가 된다 (300 만 물린 채 방치).
                        #  3) 24h 숫자 하나는 「아직 오르는 중」과 「정점 지나
                        #     꺾임」을 구별하지 못한다. 그 판정은 Fix 111 의
                        #     confirm_peak(15m 반복 + 지표 꺾임)이 훨씬 정확하다.
                        #
                        # 신: 24h 는 로그/기록용 참고값. 실 게이트는 정점 확인.
                        #     (아래 (B) 지표 반전 STRICT 게이트는 그대로 유지!)
                        # ══════════════════════════════════════════════════
                        # ══════════════════════════════════════════════════
                        # 🚨 Fix 200 (2026-08-28 사장님 지시): 「지정한 가격에 반드시
                        #   들어가게」 — 전략 단위 정점 게이트 예외.
                        #
                        # 사장님 절대 원칙: "전략 인스턴스에 설정하는 옵션이 우선".
                        # 그런데 모달에서 **직접 지정한 가격 트리거**를 정점 게이트가
                        # 덮으면, 사장님이 정한 가격에 영원히 안 들어갈 수 있다.
                        # 실제 사례 #1637 AKEUSDT SHORT — 마크가 2단계 트리거를
                        # 넘었는데도 "지표 꺾임 1/2" 로 1분마다 계속 차단됐다.
                        #
                        # → 기본은 게이트 유지(자동 진입 보호). **명시적으로 켠 전략만**
                        #   건너뛴다. 켜면 로그에 매번 WARNING 을 남겨 숨지 않게 한다.
                        #   Redis: stage_peak_bypass:strategy:{id} (값=사유, 7일 TTL)
                        # ══════════════════════════════════════════════════
                        _peak_bypass = None
                        try:
                            _bp = _redis.get(f"stage_peak_bypass:strategy:{strategy.id}") if _redis else None
                            if _bp:
                                _peak_bypass = _bp.decode() if isinstance(_bp, bytes) else str(_bp)
                        except Exception:
                            _peak_bypass = None

                        if _peak_bypass:
                            logger.warning(
                                "[Fix200/peak-bypass] #%s %s %s stage=%s = 정점 확인을 "
                                "**건너뜁니다** (사장님 지정 가격 우선 / 사유=%s)",
                                strategy.id, strategy.symbol, strategy.side,
                                next_stage_no, _peak_bypass,
                            )
                            _ok24, _chg = True, None
                            _pk114_ok = True
                            _pk114_why = f"정점 게이트 건너뜀 ({_peak_bypass})"
                            _pk114_det = {"bypass": _peak_bypass}
                        else:
                            _ok24, _chg = _check_stage_24h_filter(_bc55, strategy.symbol, strategy.side)
                            from app.services.peak_confirmation import confirm_peak as _cp114
                            _pk114_ok, _pk114_why, _pk114_det = _cp114(
                                _bc55, strategy.symbol, strategy.side,
                            )
                        if not _pk114_ok:
                            _reason114 = (
                                f"Fix114 정점 미확인 (stage={next_stage_no} "
                                f"side={strategy.side} 24h={_chg if _chg is not None else 'n/a'}%): {_pk114_why}"
                            )
                            logger.info(
                                "[Fix114/peak] skip strategy=%s stage=%s %s %s | %s | %s",
                                strategy.id, next_stage_no, strategy.symbol, strategy.side,
                                _pk114_why, _pk114_det,
                            )
                            # Fix 201: 지표 상세를 사유와 **함께** 남긴다 (화면 배지 근거)
                            _record_block_reason(
                                _redis, strategy.id, _reason114, next_stage_no,
                                detail=_pk114_det if isinstance(_pk114_det, dict) else None,
                            )
                            _alert_silent_block_once(_redis, db, strategy, _reason114, next_stage_no)
                            continue
                        if not _ok24:
                            # 헌법 68 예외 발동 = 차단하지 않고 「기록만」 남긴다.
                            logger.warning(
                                "[Fix114/헌법68] strategy=%s stage=%s %s %s 24h=%.2f%% 이지만 "
                                "정점 확인 통과 → 마틴게일 진행! (%s)",
                                strategy.id, next_stage_no, strategy.symbol, strategy.side,
                                _chg or 0, _pk114_why,
                            )
                        # (B) 지표 반전 확인 (2단계=2/3, 3단계+=3/3 STRICT!)
                        _ok_rev, _rev_detail = _check_stage_indicator_reversal(
                            _bc55, strategy.symbol, strategy.side, next_stage_no
                        )
                        if not _ok_rev:
                            _reason55b = (
                                f"Fix55 지표 반전 미달 (stage={next_stage_no} "
                                f"passed={_rev_detail.get('passed')}/{_rev_detail.get('required')})"
                            )
                            logger.info(
                                "[Fix55/reversal] skip strategy=%s stage=%s %s %s detail=%s",
                                strategy.id, next_stage_no, strategy.symbol, strategy.side, _rev_detail,
                            )
                            # 🚨 Fix 201b: 이 경로도 배지 상세를 채운다.
                            #   _rev_detail 은 평평한 bool 이라 화면 규약(indicators)과 모양이
                            #   다르다 — 그냥 넘기면 표가 빈다. 여기서 변환해서 넘긴다.
                            #   (prev 가 없는 칸은 화면이 「-」로 그린다)
                            _rev_ind = {
                                "rsi": {"now": _rev_detail.get("rsi_now"),
                                        "prev": _rev_detail.get("rsi_prev"),
                                        "turn": bool(_rev_detail.get("rsi"))},
                                "macd": {"now": _rev_detail.get("macd_hist_now"),
                                         "prev": None,
                                         "turn": bool(_rev_detail.get("macd"))},
                                "obv": {"now": _rev_detail.get("obv_slope"),
                                        "prev": None,
                                        "turn": bool(_rev_detail.get("obv"))},
                            }
                            _record_block_reason(
                                _redis, strategy.id, _reason55b, next_stage_no,
                                detail={
                                    "indicators": _rev_ind,
                                    "turns": _rev_detail.get("passed"),
                                    "required": _rev_detail.get("required"),
                                },
                            )
                            _alert_silent_block_once(_redis, db, strategy, _reason55b, next_stage_no)
                            continue
                        logger.info(
                            "[Fix55] ✅ 지표 반전 통과! strategy=%s stage=%s %s %s "
                            "passed=%s/%s chg24h=%.2f%%",
                            strategy.id, next_stage_no, strategy.symbol, strategy.side,
                            _rev_detail.get("passed"), _rev_detail.get("required"), _chg or 0,
                        )
                    except Exception as _e55:
                        # 예외 = fail-safe = skip (자본 보호 우선!)
                        logger.warning(
                            "[Fix55] 검증 예외 → skip 진입! strategy=%s stage=%s err=%s",
                            strategy.id, next_stage_no, _e55,
                        )
                        _record_block_reason(
                            _redis, strategy.id,
                            f"Fix55 검증 예외 (skip): {str(_e55)[:60]}",
                            next_stage_no,
                        )
                        continue
                # LIMIT 주문 발송
                exec_service = ExecutionService(
                    db,
                    api_key=decrypt_text(account.api_key_enc),
                    api_secret=decrypt_text(account.api_secret_enc),
                    is_testnet=account.is_testnet,
                )
                # 🚨 2026-06-08 사장님 사상 v2 (사장님 정책 완화 명시):
                # "거래소 잔액에 130% 까지 허용하는 걸로만 하자 꼭 지금처럼 예약률을 표현해줘"
                #
                # 옛 strict (오전): 실 + 예약 ≤ wallet × 1.00 (음수 절대 차단)
                # 신 완화 (오후): 실 + 예약 ≤ wallet × 1.30 (130%까지 허용)
                #
                # = 사장님 운영 유연성 우선 (약간 음수 허용 = 단기 손실 진입 시 자동 진입 계속)
                # = 130% 초과 시만 차단 (= 위험 임계 — 사장님 자본 보호 최종 안전망)
                # = UI 예약률 표시 = 그대로 유지 (사장님 요구)
                # 🌟 2026-06-09 v17 Phase 3: 단일 진실 모듈 사용 (= 사장님 헌법 6번)
                # capital_calculator.calc_reserved_for_account() = 화면과 100% 동일 함수!
                # = silent bug 영구 차단 (= 같은 데이터 = 단 하나 함수)
                from app.services.capital_calculator import (
                    calc_reserved_for_account,
                    calc_wallet_limit,
                    get_wallet_limit_pct,
                )
                try:
                    _bal_info = exec_service.client.get_account()
                    _wallet_total = Decimal(str(_bal_info.get('totalWalletBalance', '0')))
                    _real_margin = Decimal(str(_bal_info.get('totalPositionInitialMargin', '0')))
                    # 단일 진실 함수 호출 (= 화면과 동일!)
                    _total_reserved = calc_reserved_for_account(db, account.id)
                    _max_allowed = calc_wallet_limit(_wallet_total)
                    _user_limit_pct = get_wallet_limit_pct()
                    # 🚨 2026-06-09 v17 silent bug fix (사장님 검증 발견!):
                    # 옛 _all_active 변수 = 단일 진실 모듈 통합 시 제거됨
                    # → L228 에서 len(_all_active) NameError = 알림 메시지 silent crash
                    # → wallet 검증 자체 실패 = 사장님 자동 진입 차단 silent bug
                    # fix: alert 메시지용 활성 strategy 카운트 = 단순 query 로 별도 조회
                    # 🚨 2026-06-10 v24 critical fix (사장님 SENTUSDT silent bug 발견!):
                    # 옛 코드: from app.core.constants import ACTIVE_STAGE_STATUSES
                    # = app.core.constants 모듈 = 존재 X = ImportError raise
                    # = Python scope rule = local def 시도 = UnboundLocalError L183!
                    # = stage_trigger_worker = 17 strategy 모두 = 처음부터 fail!
                    # = 사장님 모든 자동 진입 silent X!
                    # fix: 옛 module-level ACTIVE_STAGE_STATUSES 그대로 사용 (= L37 정의)
                    _all_active = db.execute(
                        select(StrategyInstance)
                        .where(StrategyInstance.exchange_account_id == account.id)
                        .where(StrategyInstance.is_archived.is_(False))
                        .where(StrategyInstance.status.in_(ACTIVE_STAGE_STATUSES))
                    ).scalars().all()
                    # 단일 진실: 예약 (= calc_reserved_for_account) = 실 + 미진입 자본 합
                    # → 별도 + _real_margin 더하지 않음 (= reserved 안에 이미 포함!)
                    _total_committed = _total_reserved  # capital_calculator 가 모든 것 포함
                    if _total_committed > _max_allowed and _wallet_total > 0:
                        # 🚨 wallet 130% 초과 — 자동 진입 차단 + cooldown + Telegram (dedup)
                        _committed_ratio = (_total_committed / _wallet_total * 100) if _wallet_total > 0 else 0
                        # 🌟 v18 fix: 130% 차단 = Redis block_reason 기록!
                        _record_block_reason(
                            _redis, strategy.id,
                            f"130% 한도 초과 ({_committed_ratio:.1f}% / 130%)",
                            next_stage_no,
                        )
                        _first = _set_margin_cooldown(_redis, strategy.id, next_stage_no)
                        logger.warning(
                            "[stage-trigger] 130%% 초과 차단 strategy=%s stage=%s — "
                            "실=%s + 예약=%s = %s (%.1f%%) > 허용=%s (130%%) wallet=%s (alert=%s)",
                            strategy.id, next_stage_no, _real_margin, _total_reserved,
                            _total_committed, _committed_ratio, _max_allowed, _wallet_total, _first,
                        )
                        if _first:
                            try:
                                NotificationService(db).send_system_alert(
                                    title=f"🚨 [Wallet 130% 초과 — 자동 진입 차단] #{strategy.id} {strategy.symbol} 단계{next_stage_no}",
                                    body=(
                                        f"사장님 정책 (2026-06-08 v2): 실 + 예약 ≤ wallet × 1.30 위반 → 차단.\n\n"
                                        f"📌 계산 (예약률 = 실 + 예약 / wallet × 100):\n"
                                        f"  • 🔒 실 사용 마진 (Binance lock): {_real_margin:.2f} USDT\n"
                                        f"  • 📦 포지션 예약됨 (활성 {len(_all_active)}개 자본 잔여): {_total_reserved:.2f} USDT\n"
                                        f"  • 합 (실 + 예약): {_total_committed:.2f} USDT\n"
                                        f"  • 💼 Wallet: {_wallet_total:.2f} USDT\n"
                                        f"  • 📊 예약률: {_committed_ratio:.1f}% (허용 한도: 130%)\n"
                                        f"  • 초과: {(_total_committed - _max_allowed):.2f} USDT\n\n"
                                        f"⚙️ 자동 stage 진입 차단 (사장님 자본 보호 — 130% 초과 시).\n"
                                        f"💡 조치 (택1):\n"
                                        f"  • USDT 입금 → wallet 회복 (예약률 ↓)\n"
                                        f"  • strategy 일부 수동 청산 → 실/예약 감소\n"
                                        f"  • EPICUSDT total_capital 동기화 (PR #107 + ✏️ 수정)\n"
                                        f"  • {_MARGIN_COOLDOWN_TTL // 60}분 후 자동 재시도 (cooldown)"
                                    ),
                                )
                            except Exception:
                                pass
                        continue  # 다음 cycle
                except Exception as _e:
                    # 🌟 2026-08-08 v130 사장님: wallet 검증 실패 = fail-open 복원!
                    #   v127 default deny → 사장님 진입 안 되는 사고!
                    #   preflight (Binance availableBalance) = 백업 = 안전!
                    logger.warning("[stage-trigger v130] wallet 검증 실패 (preflight 백업으로 계속): %s", _e)

                # Fix 129: trigger 는 가격 트리거 경로에서만 정의된다 → 모드를 함께 표기
                _fire_mode = (
                    "RETRY(청산가)" if _is_retry_mode
                    else "OBV_REVERSE" if _is_obv_mode
                    else "LIQ_BUFFER" if _is_liqbuf_mode
                    else "PRICE"
                )
                logger.info(
                    "[stage-trigger] firing stage%s for #%s %s %s mode=%s mark=%s trig=%s",
                    next_stage_no, strategy.id, strategy.symbol, strategy.side,
                    _fire_mode, mark, trigger if trigger is not None else "n/a",
                )
                exec_service.trigger_next_stage(strategy.id, next_stage_no)
                _stat["fired"] += 1
                # 🌟 v18 fix: 정상 진입 = block_reason 정리 (= 화면 알림 해소)
                _clear_block_reason(_redis, strategy.id)

                # 2026-05-11 (사용자 요청): 단계 진입 시 추가 증거금 자동 투입.
                # next_plan.additional_margin_usdt > 0 이면 add_position_margin API 호출.
                # entry 주문이 LIMIT 발사된 후 즉시 호출 — Binance 가 포지션이 조금이라도
                # 있으면 추가 마진 받음 (체결되지 않은 LIMIT 만 있어도 OK 인지는 isolated 모드
                # 에서 Binance 정책 따라 다름. 실패하면 다음 cycle 자동 정정 X — 명시적
                # RiskEvent 기록 후 사용자가 수동 처리).
                add_m = next_plan.additional_margin_usdt
                if add_m and Decimal(str(add_m)) > 0:
                    try:
                        exec_service.add_position_margin(strategy.id, amount=Decimal(str(add_m)))
                        logger.info(
                            f"[stage-trigger] additional margin +{add_m} USDT applied to #{strategy.id} {strategy.symbol}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"[stage-trigger] additional margin failed for #{strategy.id} stage{next_stage_no}: {e}"
                        )
                        # entry 자체는 정상 — 추가 증거금만 실패. 사용자에게 알림.
                        try:
                            NotificationService(db).send_system_alert(
                                title=f"⚠️ [추가 증거금 실패] #{strategy.id} {strategy.symbol} 단계{next_stage_no}",
                                body=(
                                    f"단계 {next_stage_no} entry 는 정상 발사됨. 그러나 추가 증거금 {add_m} USDT 투입 실패.\n"
                                    f"원인: {e}\n\n"
                                    "💡 수동 처리: Binance UI 에서 직접 증거금 추가 가능. 또는 마진 모드 isolated 확인."
                                ),
                            )
                        except Exception:
                            pass
            except Exception as e:
                # rate limit/ban 이면 기록 + 이 account 나머지 strategy skip (스파이럴 차단)
                if maybe_record_ban_from_exc(e, account.id, notification_service=NotificationService(db)):
                    _banned_accounts.add(account.id)
                    logger.warning("[stage-trigger] rate limit detected account=%s — skip rest of cycle", account.id)
                    continue
                # 2026-05-19: 마진부족(-2019) — 30분 쿨다운 + 알림 1회 (매 cycle spam 차단).
                # 마진은 포지션 정리/입금 전엔 안 생기므로 blind 재시도 무의미.
                if _is_margin_insufficient(e):
                    _sn = next_stage_no if next_stage_no is not None else 0
                    first = _set_margin_cooldown(_redis, strategy.id, _sn)
                    logger.warning(
                        "[stage-trigger] margin insufficient strategy=%s stage=%s — cooldown %dm (alert=%s)",
                        strategy.id, _sn, _MARGIN_COOLDOWN_TTL // 60, first,
                    )
                    if first:  # 쿨다운 동안 1회만 알림 (dedup)
                        try:
                            NotificationService(db).send_system_alert(
                                title=f"⚠️ [마진 부족] 전략 #{strategy.id} {strategy.symbol} 단계{_sn} 진입 보류",
                                body=(
                                    f"가용 증거금 부족(-2019)으로 단계 {_sn} 진입 실패. "
                                    f"{_MARGIN_COOLDOWN_TTL // 60}분간 자동 재시도 보류.\n\n"
                                    "💡 조치: ① 다른 전략 일부 정리(포지션 청산) 또는 "
                                    "② 거래소 잔액 입금 → 마진 확보 시 다음 cycle 자동 재개.\n"
                                    "동시 전략 수가 많으면 MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT 조정 검토."
                                ),
                            )
                        except Exception:
                            pass
                    continue  # 일반 「시스템 오류」 spam 알림 안 보냄
                _stat["err"] += 1
                logger.exception(f"[stage-trigger] failed for strategy #{strategy.id}: {e}")
                try:
                    NotificationService(db).send_system_alert(
                        title="[시스템 오류] Stage 자동 진입 실패",
                        body=f"strategy_id={strategy.id} stage={next_stage_no if next_stage_no is not None else '?'} error={e}",
                    )
                except Exception:
                    pass
        # 🎯 Fix 121: 완료 로그 (헌법 80 = 무로그 종료 금지)
        logger.info(
            "[stage-trigger] 완료: 활성=%d 검사=%d 발동=%d ban_skip=%d 오류=%d",
            _stat["rows"], _stat["scanned"], _stat["fired"], _stat["banned"], _stat["err"],
        )
    finally:
        db.close()
