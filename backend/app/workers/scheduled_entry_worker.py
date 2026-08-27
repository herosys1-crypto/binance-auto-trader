"""📅 Fix 182 (2026-08-27): 예약 전략 — 조건이 맞을 때 시스템이 대신 진입한다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 verbatim (2026-08-27):
  "이전략을 내가 바로 들어가는 경우도 있고 예약 전략으로 만들면 시스템이
   진입가능할때 예약해 놓은 전략으로 진행할수 있게 예약기능을 만들어줘
   예정 전략인스턴스로 해줘"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

■ 왜 새 상태를 안 만들었나

  `POST /strategies` 는 **생성만** 하고 진입하지 않는다 (status="WAITING").
  실제 진입은 `POST /strategies/{id}/start` 가 따로 부른다.
  → 「만들어두고 시작을 안 누른 전략」은 **이미 WAITING 으로 남아 있다.**
    예약 기능의 절반은 원래 있었고, 없던 것은 **그걸 감시해 진입시키는 워커**뿐이다.

  다만 WAITING 에는 두 종류가 섞인다:
      ① 사장님이 곧 「시작」을 누를 것        ← 건드리면 안 됨
      ② 시스템이 조건 보고 넣어야 할 예약     ← 이 워커의 대상
  구별자로 `capital_management_mode = "scheduled"` 를 쓴다. 이 컬럼은 원래
  저장만 되고 로직에 안 쓰였고, Fix 178 이 "split_entry" 를 같은 방식으로
  쓰고 있다 (헌법 127 = 모델/모드 선택은 이미 있는 필드로 표현한다).

■ 진입 판정 = 운영 로직 그대로

  `check_stage_entry_signal` (Fix 173) = 자동 진입 워커와 **같은 게이트**:
      ① obv_gate(4H) ② 양방향 차단 ③ regime(SHORT) ④ confirm_peak(15m)
  사장님이 지목하신 Fix 114(confirm_peak)가 ④ 로 포함된다.
  ⚠️ Fix 55(15m RSI/MACD/OBV 반전)는 **2단계 이상 전용**이라 1단계 진입에는
     적용되지 않는다 (stage_trigger_worker:`if next_stage_no >= 2`).
     예약이 1단계를 넣고 나면, 2·3단계는 기존대로 Fix 114 + Fix 55 를 지난다.

■ WAITING 의 성질 (확인된 사실)

  · ACTIVE_LIKE 에 **없다** → 예약은 동시보유 슬롯을 먹지 않고, 중복 가드에도 안 걸린다.
    그래서 진입 **직전에** 슬롯과 중복을 다시 확인한다 (헌법 119).
  · TP/SL 대상이 아니다 (run_workers:`_NOT_FOR_TP_SL`) → 예약 상태에서 청산될 일 없다.

■ 안전장치

  · 기본 OFF (`scheduled_entry_enabled` = "1" 이어야 동작) — 사장님이 켜야 돈다
  · **만료** (기본 7일) — 예약이 영원히 남아 잊혀진 채 어느 날 갑자기 들어가는 걸 막는다
  · 동시보유 상한 / 같은 심볼·방향 활성 / API ban / 계정 없음 = 진입 보류
  · 진입 못 한 이유는 항상 집계 + Redis 기록 (헌법 8/80)
  · 한 사이클 최대 진입 건수 제한 (폭주 방지)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance

logger = logging.getLogger(__name__)

__all__ = ["run_scheduled_entry_once", "SCHEDULED_MARKER"]

SCHEDULED_MARKER = "scheduled"          # capital_management_mode 값
ENABLED_KEY = "scheduled_entry_enabled"  # "1" 이어야 동작 (기본 OFF)
EXPIRE_DAYS_KEY = "scheduled_entry_expire_days"
DEFAULT_EXPIRE_DAYS = 7
MAX_PER_CYCLE = 3
BLOCK_KEY = "scheduled_entry_block:strategy:{sid}"
BLOCK_TTL = 900   # 15분 (다음 사이클까지 표시)


def _redis():
    try:
        from app.core.redis_client import get_redis_client
        return get_redis_client()
    except Exception:
        return None


def _record(sid: int, reason: str) -> None:
    """왜 아직 안 들어갔는지 화면/진단에서 볼 수 있게 (헌법 8)."""
    r = _redis()
    if r is None:
        return
    try:
        import json
        r.setex(BLOCK_KEY.format(sid=sid), BLOCK_TTL, json.dumps({
            "reason": reason,
            "at": datetime.now(timezone.utc).isoformat(),
        }))
    except Exception:
        pass


def _expire_days(db) -> int:
    from app.models.system_setting import SystemSetting
    try:
        row = db.get(SystemSetting, EXPIRE_DAYS_KEY)
        if row is not None and str(row.value).strip():
            return max(1, min(int(str(row.value).strip()), 365))
    except Exception:
        pass
    return DEFAULT_EXPIRE_DAYS


def run_scheduled_entry_once() -> dict:
    """5분 주기. 예약 전략 중 진입 조건이 맞은 것을 시작시킨다."""
    db = SessionLocal()
    stat: dict = {"scanned": 0, "entered": 0, "expired": 0, "skipped": {}}

    def _skip(why: str) -> None:
        stat["skipped"][why] = stat["skipped"].get(why, 0) + 1

    try:
        from app.models.system_setting import SystemSetting
        sw = db.get(SystemSetting, ENABLED_KEY)
        if sw is None or str(sw.value).strip() != "1":
            logger.info("[scheduled_entry] ⏹️ OFF (%s != 1)", ENABLED_KEY)
            return {"note": "OFF", **stat}

        rows = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.status == "WAITING")
            .where(StrategyInstance.is_archived.is_(False))
            .where(StrategyInstance.capital_management_mode == SCHEDULED_MARKER)
            .order_by(StrategyInstance.id)
        ).scalars().all()
        stat["scanned"] = len(rows)
        if not rows:
            logger.info("[scheduled_entry] 예약 전략 0건")
            return stat

        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            logger.warning("[scheduled_entry] mainnet 계정 없음")
            return stat

        from app.core.api_backoff import is_account_banned
        if is_account_banned(account.id):
            logger.info("[scheduled_entry] API ban 중 = skip")
            return stat

        from app.core.crypto import decrypt_text
        from app.integrations.binance.client import BinanceClient
        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=account.is_testnet,
        )

        exp_days = _expire_days(db)
        cutoff = datetime.now(timezone.utc) - timedelta(days=exp_days)

        from app.services.position_limit import check_position_slot
        from app.services.stage_entry_signal import check_stage_entry_signal

        for si in rows:
            if stat["entered"] >= MAX_PER_CYCLE:
                _skip("cycle_budget")
                continue

            # ── 만료 (잊힌 예약이 갑자기 들어가는 걸 막는다) ──
            _created = si.created_at
            if _created is not None:
                if _created.tzinfo is None:
                    _created = _created.replace(tzinfo=timezone.utc)
                if _created < cutoff:
                    si.is_archived = True
                    db.commit()
                    stat["expired"] += 1
                    logger.warning(
                        "[scheduled_entry] ⌛ #%s %s %s 예약 만료 (%d일 경과) → 보관 처리",
                        si.id, si.symbol, si.side, exp_days,
                    )
                    continue

            # ── 같은 심볼·방향에 이미 활성 전략이 있으면 skip ──
            dup = db.execute(
                select(StrategyInstance)
                .where(StrategyInstance.symbol == si.symbol)
                .where(StrategyInstance.side == si.side)
                .where(StrategyInstance.status.in_(list(ACTIVE_LIKE)))
                .where(StrategyInstance.is_archived.is_(False))
                .limit(1)
            ).scalar_one_or_none()
            if dup is not None:
                _record(si.id, f"같은 심볼·방향 활성 전략 #{dup.id} 존재")
                _skip("already_active")
                continue

            # ── 동시보유 상한 (진입 직전 재확인, 헌법 119) ──
            try:
                slot_ok, slot_why, _a, _c = check_position_slot(db, "scheduled_entry")
            except Exception as e:
                logger.error("[scheduled_entry] 상한 검사 실패 → 보류: %s", e)
                _record(si.id, f"상한 검사 실패: {e}")
                _skip("slot_error")
                break
            if not slot_ok:
                _record(si.id, slot_why)
                _skip("slot_full")
                break

            # ── 진입 신호 = 운영 로직 (Fix 173) ──
            try:
                sig_ok, sig_why, _det = check_stage_entry_signal(bc, db, si.symbol, si.side)
            except Exception as e:
                logger.warning("[scheduled_entry] #%s 신호 판정 실패 → 보류: %s", si.id, e)
                _record(si.id, f"신호 판정 실패: {e}")
                _skip("signal_error")
                continue
            if not sig_ok:
                logger.info(
                    "[scheduled_entry] ⏳ #%s %s %s 대기: %s",
                    si.id, si.symbol, si.side, sig_why,
                )
                _record(si.id, sig_why)
                _skip("signal_wait")
                continue

            # ── 진입! ──
            try:
                from app.services.execution_service import ExecutionService
                ExecutionService(
                    db,
                    api_key=decrypt_text(account.api_key_enc),
                    api_secret=decrypt_text(account.api_secret_enc),
                    is_testnet=account.is_testnet,
                ).start_stage1(si.id)
                stat["entered"] += 1
                try:
                    r = _redis()
                    if r is not None:
                        r.delete(BLOCK_KEY.format(sid=si.id))
                except Exception:
                    pass
                logger.warning(
                    "[scheduled_entry] 🚀 예약 진입! #%s %s %s | %s",
                    si.id, si.symbol, si.side, sig_why,
                )
            except Exception as e:
                db.rollback()
                logger.error("[scheduled_entry] ❌ #%s 진입 실패: %s", si.id, e)
                _record(si.id, f"진입 실패: {e}")
                _skip("start_failed")

        logger.info(
            "[scheduled_entry] 완료: 예약=%d 진입=%d 만료=%d 사유=%s",
            stat["scanned"], stat["entered"], stat["expired"], stat["skipped"],
        )
        return stat
    except Exception as e:
        logger.exception("[scheduled_entry] 실패: %s", e)
        return stat
    finally:
        db.close()
