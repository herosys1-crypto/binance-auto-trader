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


def _record_block_reason(redis_client, sid: int, reason: str, stage_no: int = 0) -> None:
    """차단 이유 Redis 기록 (= 진단 endpoint + 화면 표시).

    사장님 헌법 8번 (= silent 차단 금지): 모든 차단 = 사장님이 즉시 알 수 있어야 함.
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
        })
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
        # 2026-05-17 rate limit ban 스파이럴 사후: account 별 ban skip (tp_sl 와 동일 패턴).
        _banned_accounts: set[int] = set()
        for strategy, account in rows:
            if account.id in _banned_accounts:
                continue
            if is_account_banned(account.id):
                _banned_accounts.add(account.id)
                logger.info("[stage-trigger] API ban active account=%s — skip cycle", account.id)
                continue
            next_stage_no: int | None = None  # 2026-06-01: try 진입 전 명시 (except 분기에서 안전 참조)
            try:
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
                if not next_plan.trigger_price:
                    # LIQUIDATION_BUFFER 모드 (마지막 단계) — trigger_price 가 None.
                    # 실시간으로 청산가 -5% 기반 산출 필요. 일단 skip (후속 작업으로 분리).
                    _record_block_reason(_redis, strategy.id, f"단계{next_stage_no} trigger_price=None (LIQUIDATION_BUFFER 미구현)", next_stage_no)
                    _alert_silent_block_once(_redis, db, strategy, f"단계{next_stage_no} trigger_price 미설정", next_stage_no)
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
                    # Redis 캐시 + DB snapshot 둘 다 없음 = 진짜로 mark-price-stream 점검 필요
                    _record_block_reason(_redis, strategy.id, "mark_price 없음 (Redis 캐시 + DB snapshot 모두 누락)", next_stage_no)
                    _alert_silent_block_once(_redis, db, strategy, "mark_price 없음 (mark-price-stream 점검 필요)", next_stage_no)
                    continue
                mark = Decimal(str(mark))
                trigger = Decimal(str(next_plan.trigger_price))
                # SHORT: 가격 위로 더 갔으면 추가 SHORT 진입 (mark >= trigger)
                # LONG: 가격 아래로 더 갔으면 추가 LONG 진입 (mark <= trigger)
                should_fire = (mark >= trigger) if strategy.side == "SHORT" else (mark <= trigger)
                if not should_fire:
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
                    # wallet 검증 자체 실패 — 진입 진행 (preflight 가 백업 차단)
                    logger.warning("[stage-trigger] Phase B wallet 검증 실패 (preflight 가 백업): %s", _e)

                logger.info(
                    f"[stage-trigger] firing stage{next_stage_no} for #{strategy.id} "
                    f"{strategy.symbol} {strategy.side} (mark={mark} {'>=' if strategy.side == 'SHORT' else '<='} trig={trigger})"
                )
                exec_service.trigger_next_stage(strategy.id, next_stage_no)
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
                logger.exception(f"[stage-trigger] failed for strategy #{strategy.id}: {e}")
                try:
                    NotificationService(db).send_system_alert(
                        title="[시스템 오류] Stage 자동 진입 실패",
                        body=f"strategy_id={strategy.id} stage={next_stage_no if next_stage_no is not None else '?'} error={e}",
                    )
                except Exception:
                    pass
    finally:
        db.close()
