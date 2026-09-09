"""🧭 심볼 관리 재진입 — 로직 (Fix 365, 2026-09-09).

사장님 (verbatim): "첫 진입에 실패하면 청산하고 재진입 모니터링으로 특별 관리해서 우선 포지션 진입할 심볼로 관리를 하고
재진입 모니터링 후 다시 10usdt로 진입해서 성공하면 포지션추가로 가는걸로 해줘 10usdt로 성공할때까지 10번까지 반복해줘
그리고 한번하락하고 성공하면 다시 급반등하는것도 많이 이것조 잡아서 롱으로 그리고 다시 하락하는 시점을 잡을 수 있게
실시간 감시 모니터링을 해줘 … 포지션 롱이든 숏이든 실패하면 재진입 모니터링관리와 모니터링후 포지션 진입을 하는거야
한번 선택한 종목을 지속적으로 분석하면서 관리 재진입하는거야"

세 조각:
  ① 프로브 모드 술어 — OBV 자동 인스턴스는 손실이면 **전량 청산**(손실 구간 300/600 단계 없음). `obv_loss_ladder_mode=ladder` 면 Fix 364 방식.
  ② 명부 집계 — 종료된 OBV 자동 인스턴스를 심볼별로 세어 연속 실패/성공을 기록(첫 실패 포함, 성공하면 0).
  ③ 진입 판정·실행 — 롱·숏 양방향 운영 진입 로직(`check_stage_entry_signal`)을 보고 한쪽만 신호면 같은 템플릿으로 10 USDT 시장가.

주문은 ③ 의 `enter_symbol` 한 곳에서만 나간다(호출자는 워커). 다른 재진입 워커와 겹치지 않는다:
  realtime_reentry 는 수동(DYNAMIC_*)을 일부러 제외(Fix 297) · ladder_restart 는 프로브 모드면 건너뜀(이 파일의 `probe_mode`).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

logger = logging.getLogger(__name__)

FIX = "Fix365"

# ── 설정 키 (system_settings, 행 없으면 기본) ─────────────────────────────────────
S_MODE = "obv_loss_ladder_mode"                 # probe(기본, 사장님 9/9 저녁) | ladder(Fix 364 낮 방식)
S_ENABLED = "managed_symbol_enabled"            # 1
S_ENTRY = "managed_symbol_entry_enabled"        # 1 — 신호에 실제 10 USDT 진입
S_MAX_ATTEMPTS = "managed_symbol_max_attempts"  # 10 (사장님) — 재진입 횟수 상한(연속 실패 기준)
S_DAILY = "managed_symbol_daily_entry_limit"    # 10 (Claude가 정함) — 하루 재진입 상한(KST)
S_MAX_SYMBOLS = "managed_symbol_max_symbols"    # 20 (Claude가 정함) — 감시 심볼 상한
S_IDLE_DAYS = "managed_symbol_idle_release_days"  # 7 (Claude가 정함) — 신호 없이 이 일수면 자동 해제
S_HEDGE = "managed_symbol_allow_hedge"          # 0 (Claude가 정함) — 반대 방향 포지션이 있어도 진입
S_LOOKBACK_H = "managed_symbol_lookback_hours"  # 48 (Claude가 정함) — 종료 인스턴스 집계 창
S_COOLDOWN = "managed_symbol_entry_cooldown_sec"  # 900 (Claude가 정함) — 한 심볼 재진입 시도 뒤 다음 시도까지 (실패 반복 방지)

DEFAULTS: dict[str, Any] = {
    S_MODE: "probe", S_ENABLED: True, S_ENTRY: True, S_MAX_ATTEMPTS: 10, S_DAILY: 10,
    S_MAX_SYMBOLS: 20, S_IDLE_DAYS: 7, S_HEDGE: False, S_LOOKBACK_H: 48, S_COOLDOWN: 900,
}

STATUS_WATCHING = "WATCHING"
STATUS_EXHAUSTED = "EXHAUSTED"
STATUS_RELEASED = "RELEASED"

REDIS_CYCLE_KEY = "managed_symbol:last_cycle"
REDIS_DAILY_KEY = "managed_symbol:entries:{day}"
REDIS_COOLDOWN_KEY = "managed_symbol:cooldown:{symbol}"
KST = timezone(timedelta(hours=9))


# ── 설정 읽기 ─────────────────────────────────────────────────────────────────
def _raw(db, key: str) -> str | None:
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        if row is None or row.value in (None, "") or not str(row.value).strip():
            return None
        return str(row.value).strip()
    except Exception:  # noqa: BLE001
        return None


def get_bool(db, key: str) -> bool:
    v = _raw(db, key)
    if v is None:
        return bool(DEFAULTS[key])
    return v.lower() in ("1", "true", "on", "yes")


def get_int(db, key: str, lo: int, hi: int) -> int:
    v = _raw(db, key)
    try:
        n = int(float(v)) if v is not None else int(DEFAULTS[key])
    except (TypeError, ValueError):
        n = int(DEFAULTS[key])
    return n if lo <= n <= hi else int(DEFAULTS[key])


def loss_ladder_mode(db) -> str:
    v = (_raw(db, S_MODE) or DEFAULTS[S_MODE]).lower()
    return v if v in ("probe", "ladder") else DEFAULTS[S_MODE]


def probe_mode(db) -> bool:
    """프로브 모드 = 손실이면 청산하고 재진입 관리(사장님 9/9 저녁). ladder = 손실 구간 300/600 단계(Fix 364 낮)."""
    return loss_ladder_mode(db) == "probe"


# ── OBV 자동 인스턴스 판별 + 프로브 술어 ─────────────────────────────────────────
def is_obv_instance(db, strategy) -> bool:
    try:
        tpl = getattr(strategy, "strategy_template", None)
        if tpl is None and getattr(strategy, "strategy_template_id", None):
            from app.models.strategy_template import StrategyTemplate
            tpl = db.get(StrategyTemplate, strategy.strategy_template_id)
        return str(getattr(tpl, "trigger_mode", "") or "").upper() == "OBV_REVERSE"
    except Exception:  # noqa: BLE001
        return False


def loss_ladder_disabled(db, strategy) -> tuple[bool, str]:
    """(True, why) 면 이 인스턴스는 손실 구간 단계·잔량 유지 없이 **전량 청산 → 재진입 관리**로 간다."""
    try:
        if probe_mode(db) and is_obv_instance(db, strategy):
            return True, f"{FIX} 프로브 모드: 손실이면 전량 청산 → 재진입 관리 (2단계 없음, 잔량 유지 없음)"
    except Exception as e:  # noqa: BLE001
        logger.debug("[%s] 프로브 판정 실패 → 옛 동작: %s", FIX, e)
    return False, ""


# ── ② 명부 집계 ──────────────────────────────────────────────────────────────
def _get_or_create(db, symbol: str):
    from app.models.managed_symbol import ManagedSymbol
    row = db.execute(select(ManagedSymbol).where(ManagedSymbol.symbol == symbol)).scalar_one_or_none()
    if row is None:
        row = ManagedSymbol(symbol=symbol, status=STATUS_WATCHING, attempts=0, max_attempts=DEFAULTS[S_MAX_ATTEMPTS],
                            successes=0, total_entries=0, last_reasons={})
        db.add(row)
        db.flush()
    return row


FAIL_REASONS = frozenset({"FORCE_SL", "SL", "ZOMBIE_FORCE_STOP"})          # 시스템 손절 = 「첫 진입 실패」
SUCCESS_PREFIXES = ("TP_",)
SUCCESS_REASONS = frozenset({"TRAILING_TP", "MANUAL_TP"})
PROBE_CLOSE_EVENT = "FORCE_SL_FULL_CLOSE"                                       # 프로브 전량 청산 마커 (orchestrator 가 남김)
COUNTED_IDS_CAP = 300


def classify_close(reason: str | None, status: str | None, *, probe_marker: bool = False) -> str:
    """종료 인스턴스 → 'fail' | 'success' | 'skip'. (순수)
    fail    = 시스템 손절(FORCE_SL/SL/좀비 강제정지) 또는 프로브 전량 청산 마커 — 사장님 「첫 진입에 실패」
    success = 익절 계열(TP_*, 트레일링, 수동 익절) 또는 COMPLETED
    skip    = 사장님 ⏸정지·외부 청산·정리·사유 불명 — 세지 않는다 (반박 검증 C1/C13/C15: 사장님이 버린 심볼을 되살리지 않는다)"""
    r = (reason or "").upper()
    st = (status or "").upper()
    if probe_marker or r in FAIL_REASONS:
        return "fail"
    if r in SUCCESS_REASONS or any(r.startswith(p) for p in SUCCESS_PREFIXES) or st == "COMPLETED":
        return "success"
    return "skip"


def apply_closed_instance(ms, si, *, max_attempts: int, outcome: str) -> str:
    """종료 인스턴스 하나를 명부 행에 반영. outcome 은 classify_close 결과. 반환 = 'fail' | 'success' | 'skip' | 'dup'. (순수 — 테스트 대상)
    RELEASED 는 끈적인다: 카운터는 갱신하되 상태는 사장님이 「➕ 추가 / ↺ 초기화」로 다시 올릴 때까지 그대로 (반박 검증 C2/C9/C14)."""
    counted = [int(x) for x in (ms.counted_ids or [])]
    if int(si.id) in counted:
        return "dup"
    counted.append(int(si.id))
    ms.counted_ids = counted[-COUNTED_IDS_CAP:]
    ms.last_instance_id = max(int(si.id), int(ms.last_instance_id or 0))
    if ms.origin_instance_id is None:
        ms.origin_instance_id = int(si.id)
    _fill_account(ms, si)
    ms.max_attempts = int(max_attempts)
    pnl_raw = getattr(si, "realized_pnl", None)
    pnl = float(pnl_raw) if pnl_raw is not None else None
    entered = getattr(si, "avg_entry_price", None) is not None or (pnl is not None and pnl != 0.0)
    if not entered or outcome == "skip":
        return "skip"
    if outcome == "fail":
        ms.attempts = int(ms.attempts or 0) + 1
    else:
        ms.attempts = 0
        ms.successes = int(ms.successes or 0) + 1
    if ms.status != STATUS_RELEASED:
        ms.status = STATUS_EXHAUSTED if ms.attempts > int(max_attempts) else STATUS_WATCHING
    ms.last_side = si.side
    ms.last_pnl = Decimal(str(pnl)) if pnl is not None else None
    ms.last_exit_at = getattr(si, "stopped_at", None) or getattr(si, "updated_at", None)
    return outcome


def _fill_account(ms, si) -> None:
    if getattr(si, "user_id", None) is not None:
        ms.user_id = si.user_id
    if getattr(si, "exchange_account_id", None) is not None:
        ms.exchange_account_id = si.exchange_account_id
    if getattr(si, "strategy_template_id", None):
        ms.strategy_template_id = si.strategy_template_id
        tm = dict(ms.templates or {})
        tm[str(si.side).upper()] = int(si.strategy_template_id)
        ms.templates = tm


def close_outcome(db, si) -> tuple[str, str]:
    """(outcome, reason) — 종료 사유는 RiskEvent 로 유도(trade_learning_service.resolve_close_reason) + 프로브 마커."""
    reason = "UNKNOWN"
    try:
        from app.services.trade_learning_service import resolve_close_reason
        reason = resolve_close_reason(db, si)
    except Exception as e:  # noqa: BLE001
        logger.debug("[%s] close_reason 유도 실패 #%s: %s", FIX, getattr(si, "id", "?"), e)
    marker = False
    try:
        from app.models.risk_event import RiskEvent
        marker = db.execute(
            select(RiskEvent.id).where(RiskEvent.strategy_instance_id == si.id,
                                       RiskEvent.event_type == PROBE_CLOSE_EVENT).limit(1)
        ).scalar() is not None
    except Exception:  # noqa: BLE001
        marker = False
    return classify_close(reason, getattr(si, "status", None), probe_marker=marker), reason


def register_closed_instances(db, *, now: datetime | None = None) -> dict[str, int]:
    """최근 종료된 OBV 자동 인스턴스(사장님 모달·이 워커가 만든 것)를 심볼 명부에 반영."""
    from app.core.strategy_status import TERMINAL_STATUSES
    from app.models.strategy_instance import StrategyInstance
    from app.models.strategy_template import StrategyTemplate
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=get_int(db, S_LOOKBACK_H, 1, 24 * 30))
    max_attempts = get_int(db, S_MAX_ATTEMPTS, 1, 100)
    rows = db.execute(
        select(StrategyInstance)
        .join(StrategyTemplate, StrategyInstance.strategy_template_id == StrategyTemplate.id)
        .where(StrategyTemplate.trigger_mode == "OBV_REVERSE")
        .where(StrategyInstance.status.in_(list(TERMINAL_STATUSES)))
        .where(StrategyInstance.is_archived.is_(False))
        .where(func.coalesce(StrategyInstance.stopped_at, StrategyInstance.updated_at) >= cutoff)
        .order_by(StrategyInstance.id.asc())
    ).scalars().all()
    stat = {"scanned": len(rows), "fail": 0, "success": 0, "dup": 0, "skip": 0, "exhausted": 0}
    for si in rows:
        ms = _get_or_create(db, si.symbol)
        if int(si.id) in [int(x) for x in (ms.counted_ids or [])]:
            stat["dup"] += 1
            continue
        hint, reason = close_outcome(db, si)
        outcome = apply_closed_instance(ms, si, max_attempts=max_attempts, outcome=hint)
        stat[outcome] += 1
        if outcome in ("fail", "success"):
            if ms.status == STATUS_EXHAUSTED:
                stat["exhausted"] += 1
            logger.info("[%s] 집계 %s #%s %s 사유=%s pnl=%s → %s · 연속실패 %s/%s 성공 %s 상태 %s",
                        FIX, si.symbol, si.id, si.side, reason, si.realized_pnl, outcome, ms.attempts, max_attempts,
                        ms.successes, ms.status)
        else:
            logger.info("[%s] 집계 %s #%s %s 사유=%s → 세지 않음(skip)", FIX, si.symbol, si.id, si.side, reason)
    db.commit()
    return stat


# ── ③ 진입 판정 (순수) ──────────────────────────────────────────────────────────
def decide_entry(*, long_ok: bool, short_ok: bool, active_sides: set[str], allow_hedge: bool,
                 attempts: int, max_attempts: int) -> tuple[str | None, str]:
    """어느 방향으로 들어갈지. (None, 이유) 면 이번 사이클은 대기."""
    if attempts > max_attempts:
        return None, f"연속 실패 {attempts} > 상한 {max_attempts} (EXHAUSTED)"
    if active_sides and not allow_hedge:
        return None, f"포지션 보유 중 ({'/'.join(sorted(active_sides))}) — 종료 뒤 다시"
    if long_ok and short_ok:
        return None, "롱·숏 동시 신호 — 보류"
    if long_ok:
        if "LONG" in active_sides:
            return None, "LONG 보유 중"
        return "LONG", "LONG 신호"
    if short_ok:
        if "SHORT" in active_sides:
            return None, "SHORT 보유 중"
        return "SHORT", "SHORT 신호"
    return None, "신호 없음"


def active_sides_for(db, symbol: str) -> set[str]:
    from app.core.strategy_status import TERMINAL_STATUSES
    from app.models.strategy_instance import StrategyInstance
    rows = db.execute(
        select(StrategyInstance.side)
        .where(StrategyInstance.symbol == symbol)
        .where(StrategyInstance.status.notin_(list(TERMINAL_STATUSES)))
        .where(StrategyInstance.is_archived.is_(False))
    ).scalars().all()
    return {str(s).upper() for s in rows}


# ── ③ 템플릿 (방향별) ──────────────────────────────────────────────────────────
def template_for_side(db, ms, side: str):
    """그 방향의 템플릿. 없으면 기준 템플릿을 방향만 바꿔 복제(`_quick_m…`, OBV_REVERSE 유지)."""
    from app.models.strategy_template import StrategyTemplate
    side = side.upper()
    tm = dict(ms.templates or {})
    tid = tm.get(side)
    if tid:
        tpl = db.get(StrategyTemplate, int(tid))
        if tpl is not None:
            return tpl
    base = db.get(StrategyTemplate, int(ms.strategy_template_id)) if ms.strategy_template_id else None
    if base is None:
        raise ValueError(f"{ms.symbol}: 기준 템플릿 없음 (strategy_template_id={ms.strategy_template_id})")
    if str(base.side).upper() == side:
        tm[side] = int(base.id)
        ms.templates = tm
        return base
    clone = StrategyTemplate()
    skip = {"id", "created_at", "updated_at"}
    for col in StrategyTemplate.__table__.columns:
        if col.name in skip:
            continue
        setattr(clone, col.name, getattr(base, col.name))
    clone.name = f"_quick_m{datetime.now(timezone.utc):%Y%m%d%H%M%S}_{side}"
    clone.side = side
    clone.strategy_type = "DYNAMIC_LONG" if side == "LONG" else "DYNAMIC_SHORT"
    clone.trigger_mode = "OBV_REVERSE"
    db.add(clone)
    db.flush()
    tm[side] = int(clone.id)
    ms.templates = tm
    logger.info("[%s] %s %s 템플릿 복제 #%s ← #%s (%s)", FIX, ms.symbol, side, clone.id, base.id, base.name)
    return clone


# ── ③ 진입 실행 ────────────────────────────────────────────────────────────────
def enter_symbol(db, ms, side: str, *, account, decrypt_text, now: datetime | None = None):
    """명부 심볼에 10 USDT(템플릿 1단계) 시장가 진입. 주문이 나가는 유일한 지점 (호출자 = 워커)."""
    from app.models.strategy_stage_plan import StrategyStagePlan
    from app.services.execution_service import ExecutionService
    from app.services.strategy_service import StrategyService
    from app.workers.auto_bb_breakdown_worker import _get_current_price

    now = now or datetime.now(timezone.utc)
    side = side.upper()
    px = _get_current_price(ms.symbol)
    if not px or Decimal(str(px)) <= 0:
        raise ValueError(f"{ms.symbol} 현재가 조회 실패")
    tpl = template_for_side(db, ms, side)
    if ms.user_id is None or ms.exchange_account_id is None:
        raise ValueError(f"{ms.symbol} 계정 정보 없음 (user/account)")
    new_si = StrategyService(db).create_strategy_instance(
        user_id=int(ms.user_id),
        exchange_account_id=int(ms.exchange_account_id),
        strategy_template_id=int(tpl.id),
        symbol=ms.symbol,
        side=side,
        start_price=Decimal(str(px)),
    )
    s1 = db.execute(
        select(StrategyStagePlan)
        .where(StrategyStagePlan.strategy_instance_id == new_si.id)
        .where(StrategyStagePlan.stage_no == 1)
    ).scalar_one_or_none()
    if s1 is not None:
        s1.trigger_price = None          # 시장가 강제 (ladder_restart 와 같은 방식)
        db.commit()
    try:
        ExecutionService(
            db,
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=account.is_testnet,
        ).start_stage1(new_si.id)
    except Exception as e:  # noqa: BLE001
        # control.py 와 같은 처리: 주문이 안 나갔으면 WAITING 고아를 남기지 않는다 (남기면 그 심볼은 영원히 「보유 중」으로 막힌다)
        try:
            db.rollback()
            new_si = db.get(type(new_si), new_si.id) or new_si
            new_si.status = "STOPPED"
            new_si.last_error_message = str(e)[:500]
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        raise
    ms.total_entries = int(ms.total_entries or 0) + 1
    ms.last_entry_at = now
    ms.last_side = side
    db.commit()
    return new_si


# ── 일일 카운터 (Redis, KST) ─────────────────────────────────────────────────────
def _redis():
    try:
        from app.core.redis_client import get_redis_client
        return get_redis_client()
    except Exception:  # noqa: BLE001
        return None


def daily_key(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return REDIS_DAILY_KEY.format(day=now.astimezone(KST).strftime("%Y%m%d"))


def daily_used(now: datetime | None = None) -> int:
    r = _redis()
    if r is None:
        return 10 ** 6            # Redis 없음 = 한도 소진으로 본다 (fail-closed)
    try:
        v = r.get(daily_key(now))
        return int(v) if v else 0
    except Exception:  # noqa: BLE001
        return 10 ** 6


def bump_daily(now: datetime | None = None) -> int:
    r = _redis()
    if r is None:
        return 0
    try:
        k = daily_key(now)
        n = r.incr(k)
        r.expire(k, 2 * 86400)
        return int(n)
    except Exception:  # noqa: BLE001
        return 0


def entry_cooldown_active(symbol: str) -> bool:
    """같은 심볼 재진입 시도 뒤 쿨다운 중인가. Redis 없음/오류 = 활성(fail-closed)."""
    r = _redis()
    if r is None:
        return True
    try:
        return r.get(REDIS_COOLDOWN_KEY.format(symbol=symbol)) is not None
    except Exception:  # noqa: BLE001
        return True


def set_entry_cooldown(symbol: str, seconds: int) -> None:
    r = _redis()
    if r is None:
        return
    try:
        r.setex(REDIS_COOLDOWN_KEY.format(symbol=symbol), max(10, int(seconds)), "1")
    except Exception:  # noqa: BLE001
        pass
