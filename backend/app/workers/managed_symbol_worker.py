"""🧭 심볼 관리 재진입 워커 (Fix 365, 2026-09-09) — 1분.

사장님: "재진입 모니터링으로 특별 관리해서 우선 포지션 진입할 심볼로 관리 … 다시 10usdt로 진입 … 10번까지 반복 …
        급반등 → 롱, 다시 하락 → 숏 … 실시간 감시 모니터링"

사이클:
  1) 최근 종료된 OBV 자동 인스턴스를 명부에 반영 (시스템 손절 = 실패 +1 / 익절 = 성공, 0 / 수동·외부 = 세지 않음)
  2) 신호도 진입도 없이 오래된 심볼은 자동 해제 (전체 WATCHING 대상)
  3) 판정 대상 = 오래 안 본 순서로 max_symbols 건 (회전) — 롱·숏 운영 진입 로직 판정 → 사유 저장(화면)
  4) 한쪽만 신호 + 포지션 없음 + 프로브 모드 + 진입 ON + 쿨다운 아님 + 일일 한도 + 전용 슬롯(자동 워커 상한과 무관) → 같은 템플릿으로 10 USDT 시장가
새 심볼은 고르지 않는다 — 명부는 사장님이 만든 인스턴스에서만 생긴다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.services import managed_symbols as MS

logger = logging.getLogger(__name__)

__all__ = ["run_managed_symbols_once"]

CYCLE_TTL_SEC = 600


def _store_cycle(summary: dict) -> None:
    try:
        from app.core.redis_client import get_redis_client
        get_redis_client().setex(MS.REDIS_CYCLE_KEY, CYCLE_TTL_SEC, json.dumps(summary, ensure_ascii=False, default=str))
    except Exception as e:  # noqa: BLE001
        logger.debug("[%s] 사이클 요약 저장 실패 (무시): %s", MS.FIX, e)


def _aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def run_managed_symbols_once() -> dict:
    from app.models.managed_symbol import ManagedSymbol
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    stat: dict = {"at": now.isoformat(), "watching": 0, "checked": 0, "entered": 0, "released": 0,
                  "skipped": {}, "register": {}}

    def _skip(why: str) -> None:
        stat["skipped"][why] = stat["skipped"].get(why, 0) + 1

    try:
        if not MS.get_bool(db, MS.S_ENABLED):
            logger.info("[%s] 설정 OFF (%s=0) — 감시·등록 생략", MS.FIX, MS.S_ENABLED)
            _store_cycle({**stat, "off": True})
            return stat

        stat["register"] = MS.register_closed_instances(db, now=now)

        # 2) 자동 해제 — 전체 WATCHING (상위 N 에 밀려 영영 안 보이는 행이 없게, C10/C18)
        idle_days = MS.get_int(db, MS.S_IDLE_DAYS, 1, 365)
        all_watching = db.execute(select(ManagedSymbol).where(ManagedSymbol.status == MS.STATUS_WATCHING)).scalars().all()
        stat["watching"] = len(all_watching)
        for ms in all_watching:
            last_life = max(filter(None, [_aware(ms.last_signal_at), _aware(ms.last_entry_at), _aware(ms.last_exit_at),
                                          _aware(ms.created_at)]), default=None)
            if last_life is not None and now - last_life > timedelta(days=idle_days):
                ms.status = MS.STATUS_RELEASED
                ms.released_at = now
                ms.last_reasons = {**(ms.last_reasons or {}), "state": f"{idle_days}일 동안 신호 없음 → 자동 해제"}
                stat["released"] += 1
                logger.info("[%s] %s 자동 해제 (%d일 무신호)", MS.FIX, ms.symbol, idle_days)
        db.commit()

        # 3) 판정 대상 = 오래 안 본 순 (회전)
        max_symbols = MS.get_int(db, MS.S_MAX_SYMBOLS, 1, 200)
        rows = db.execute(
            select(ManagedSymbol).where(ManagedSymbol.status == MS.STATUS_WATCHING)
            .order_by(ManagedSymbol.last_check_at.asc().nulls_first(), ManagedSymbol.id.asc()).limit(max_symbols)
        ).scalars().all()
        if not rows:
            logger.info("[%s] 감시 심볼 0건 (등록 %s)", MS.FIX, stat["register"])
            _store_cycle(stat)
            return stat

        from app.models.exchange_account import ExchangeAccount
        account = db.execute(select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))).scalar_one_or_none()
        if account is None:
            logger.warning("[%s] mainnet 계정 없음 — 판정 생략", MS.FIX)
            _store_cycle({**stat, "error": "no_account"})
            return stat
        from app.core.api_backoff import is_account_banned
        if is_account_banned(account.id):
            logger.info("[%s] API ban 중 — 판정 생략", MS.FIX)
            _store_cycle({**stat, "error": "api_ban"})
            return stat
        try:
            from app.services.account_kill_switch_service import AccountKillSwitchService
            if AccountKillSwitchService(db).is_enabled(account.id):
                logger.info("[%s] Kill-Switch ON — 판정·진입 생략", MS.FIX)
                _store_cycle({**stat, "error": "kill_switch"})
                return stat
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] Kill-Switch 확인 실패 → 보류: %s", MS.FIX, e)
            _store_cycle({**stat, "error": "kill_switch_check"})
            return stat
        from app.core.crypto import decrypt_text
        from app.integrations.binance.client import BinanceClient
        from app.services.stage_entry_signal import check_stage_entry_signal
        bc = BinanceClient(api_key=decrypt_text(account.api_key_enc), api_secret=decrypt_text(account.api_secret_enc),
                           is_testnet=False)

        probe = MS.probe_mode(db)
        entry_on = MS.get_bool(db, MS.S_ENTRY)
        allow_hedge = MS.get_bool(db, MS.S_HEDGE)
        max_attempts = MS.get_int(db, MS.S_MAX_ATTEMPTS, 1, 100)
        daily_limit = MS.get_int(db, MS.S_DAILY, 0, 1000)
        cooldown_sec = MS.get_int(db, MS.S_COOLDOWN, 10, 86400)
        slots = MS.get_int(db, MS.S_SLOTS, 0, 100)

        for ms in rows:
            stat["checked"] += 1
            reasons: dict = {}
            try:
                from app.services.symbol_exclusion import is_excluded
                if is_excluded(db, ms.symbol):
                    reasons["state"] = "자동매매 제외 심볼 (excluded_symbols) — 진입 없음"
                    ms.last_reasons, ms.last_check_at = reasons, now
                    _skip("excluded")
                    continue
                active = MS.active_sides_for(db, ms.symbol)
                if active and not allow_hedge:
                    reasons["state"] = f"포지션 보유 중 ({'/'.join(sorted(active))}) — 종료되면 다시 본다"
                    ms.last_reasons, ms.last_check_at = reasons, now
                    _skip("in_position")
                    continue
                l_ok, l_why, _ = check_stage_entry_signal(bc, db, ms.symbol, "LONG")
                s_ok, s_why, _ = check_stage_entry_signal(bc, db, ms.symbol, "SHORT")
                reasons["LONG"] = ("✅ " if l_ok else "") + str(l_why)
                reasons["SHORT"] = ("✅ " if s_ok else "") + str(s_why)
                side, why = MS.decide_entry(long_ok=l_ok, short_ok=s_ok, active_sides=active, allow_hedge=allow_hedge,
                                            attempts=int(ms.attempts or 0), max_attempts=max_attempts)
                reasons["state"] = why
                ms.last_check_at = now
                if side is None:
                    ms.last_reasons = reasons
                    _skip("no_signal" if "신호 없음" in why else "hold")
                    continue
                ms.last_signal_at = now
                if not probe:
                    # C7: ladder 모드로 되돌리면 재진입은 ladder_restart 담당 — 여기선 진입 없음
                    reasons["state"] = f"{side} 신호 — ladder 모드({MS.S_MODE}=ladder): 10 USDT 재진입 없음 (ladder_restart 담당)"
                    ms.last_reasons = reasons
                    _skip("ladder_mode")
                    continue
                if not entry_on:
                    reasons["state"] = f"{side} 신호 — 진입 OFF (설정 {MS.S_ENTRY}=0)"
                    ms.last_reasons = reasons
                    _skip("entry_off")
                    continue
                if MS.entry_cooldown_active(ms.symbol):
                    reasons["state"] = f"{side} 신호 — 재진입 쿨다운 ({cooldown_sec // 60}분, 직전 시도 뒤)"
                    ms.last_reasons = reasons
                    _skip("cooldown")
                    continue
                used = MS.daily_used(now)
                if used >= daily_limit:
                    reasons["state"] = f"{side} 신호 — 일일 한도 소진 {used}/{daily_limit}"
                    ms.last_reasons = reasons
                    _skip("daily_limit")
                    continue
                # Fix 365d (사장님 「진행해줘」): 자동 워커 동시보유 상한과 무관한 **전용 슬롯** — 워커가 낸 재진입 중 살아 있는 수
                slots_used = MS.managed_slots_used(db)
                if slots_used >= slots:
                    reasons["state"] = f"{side} 신호 — 관리 재진입 전용 슬롯 소진 {slots_used}/{slots} (설정 {MS.S_SLOTS})"
                    ms.last_reasons = reasons
                    _skip("slot_full")
                    continue
                # 시도 = 한도·쿨다운 소비 (성공 여부와 무관 — 실패 시도가 60초마다 반복되지 않게, C5)
                n = MS.bump_daily(now)
                MS.set_entry_cooldown(ms.symbol, cooldown_sec)
                new_si = MS.enter_symbol(db, ms, side, account=account, decrypt_text=decrypt_text, now=now)
                reasons["state"] = f"🚀 {side} 재진입 #{new_si.id} (재진입 {ms.total_entries}회 · 연속실패 {ms.attempts}/{max_attempts} · 오늘 {n}/{daily_limit})"
                ms.last_reasons = reasons
                stat["entered"] += 1
                logger.warning("[%s] 🚀 %s %s 재진입 #%s — %s | LONG: %s | SHORT: %s", MS.FIX, ms.symbol, side, new_si.id,
                               why, l_why, s_why)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                reasons["error"] = str(e)[:200]
                try:
                    ms.last_reasons, ms.last_check_at = reasons, now
                except Exception:  # noqa: BLE001
                    pass
                logger.error("[%s] %s 처리 실패: %s", MS.FIX, ms.symbol, e)
                _skip("error")
            finally:
                try:
                    db.commit()
                except Exception:  # noqa: BLE001
                    db.rollback()

        logger.info("[%s] 완료: 감시=%d 판정=%d 진입=%d 해제=%d 사유=%s 등록=%s", MS.FIX, stat["watching"], stat["checked"],
                    stat["entered"], stat["released"], stat["skipped"], stat["register"])
        _store_cycle(stat)
        return stat
    except Exception as e:  # noqa: BLE001
        logger.exception("[%s] 실패: %s", MS.FIX, e)
        _store_cycle({**stat, "error": str(e)[:200]})
        return stat
    finally:
        db.close()
