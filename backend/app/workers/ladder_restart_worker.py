"""🔁 Fix 175 (2026-08-27): 사다리 전 단계 실패 → 대기 모니터링 → **처음부터** 재시작.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 verbatim (2026-08-27):
  "그리고 혹시 이렇게까지 실패한 심볼은 대기모니터링헤서
   다시 처음부터 포지션에 들어가면 좋겠는데"
  재시작 횟수 = **2회 (총 3사이클)** — 사장님 선택.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

■ 왜 새로 만들었는가 — 기존 재진입 경로가 사장님 요구와 다르다

  auto_bb_breakdown_worker 의 REENTRY_QUEUE (v219) 는 두 가지가 다르다:
    1) `_reentry_stage = _get_reentry_count(...) + 2`
       → **2·3단계 금액**으로 재진입한다. 사장님은 「**처음부터**」를 원하신다.
    2) `StrategyTemplate.strategy_type.like('auto_bb_break%')`
       → **자동 생성 전략만** 대상이다. 사장님이 모달(「새 전략 (OBV 방식)」)로
         만드신 전략은 대상에 아예 들어가지 않는다.
  즉 사장님 전략에는 재시작 경로가 **없었다.**

■ 동작

  1) 대상 찾기 — 아래를 **모두** 만족하는 최근 종료 전략
       · trigger_mode = OBV_REVERSE (사장님 모달 전략. 기존 방식은 건드리지 않는다)
       · 종료 상태(TERMINAL) + is_archived=False
       · realized_pnl < 0 (실패)
       · **사다리를 끝까지 썼다** (current_stage >= 총 단계 수)
         → 중간에 수동 정지한 건은 대상이 아니다
       · LOOKBACK_HOURS 내 종료
  2) 재시작 횟수 확인 — MAX_RESTART(2) 미만
  3) 24h 누적 손실 게이트 — 같은 심볼/방향이 이미 크게 잃었으면 중단
     (auto_bb_breakdown 의 REENTRY_QUEUE PnL 게이트와 같은 사상)
  4) 동시보유 상한 확인 (fail-SAFE)
  5) **운영 진입 로직** 통과 확인 — stage_entry_signal.check_stage_entry_signal
     = 「지금 새로 진입한다면 통과할 조건」. 사장님이 Fix 173 에서 지시하신 그 기준.
  6) 통과 시 같은 template 으로 **새 전략 생성 + 1단계 시장가 진입**
     → template 이 같으므로 사다리(100/300/900)도 그대로 처음부터다.

■ 안전장치

  · 카운터는 auto_bb_breakdown 의 `reentry_count:` 와 **분리한다**
    (`ladder_restart_count:`). 두 경로는 자본 프로필이 완전히 다르다 —
    저쪽은 2·3단계 금액, 이쪽은 사다리 전체를 처음부터다. 예산을 섞으면
    어느 쪽이 몇 번 남았는지 사람이 추론할 수 없게 된다.
  · 익절로 끝난 심볼은 카운터를 리셋한다 (성공했으면 다시 2회 기회).
  · 이미 같은 심볼/방향의 활성 전략이 있으면 건너뛴다 (중복 진입 방지).
  · 진입하지 못한 이유는 항상 로그로 남긴다 (헌법 80 = 워커 무로그 return 금지).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE, TERMINAL_STATUSES
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate

logger = logging.getLogger(__name__)

__all__ = ["run_ladder_restart_once", "get_restart_count", "reset_restart_count"]

# 사장님 선택 (2026-08-27): 2회 재시작 = 총 3사이클
MAX_RESTART = 2
RESTART_COUNT_KEY = "ladder_restart_count:{symbol}:{side}"
RESTART_COUNT_TTL_DAYS = 7
LOOKBACK_HOURS = 24          # 이 시간 내 종료된 실패 건만 대상
MAX_24H_LOSS_USDT = -300.0   # 같은 심볼/방향 24h 누적 손실이 이보다 나쁘면 중단
MAX_PER_CYCLE = 3            # 한 사이클에 재시작 최대 건수 (폭주 방지)


def _redis():
    try:
        from app.core.redis_client import get_redis_client
        return get_redis_client()
    except Exception:
        return None


def get_restart_count(symbol: str, side: str) -> int:
    r = _redis()
    if r is None:
        return 0
    try:
        v = r.get(RESTART_COUNT_KEY.format(symbol=symbol, side=side))
        return int(v) if v else 0
    except Exception:
        return 0


def _bump_restart_count(symbol: str, side: str) -> int:
    r = _redis()
    if r is None:
        return 0
    try:
        n = get_restart_count(symbol, side) + 1
        r.setex(
            RESTART_COUNT_KEY.format(symbol=symbol, side=side),
            RESTART_COUNT_TTL_DAYS * 86400, str(n),
        )
        return n
    except Exception:
        return 0


def reset_restart_count(symbol: str, side: str) -> None:
    """익절 성공 = 카운터 리셋 (다시 2회 기회)."""
    r = _redis()
    if r is None:
        return
    try:
        r.delete(RESTART_COUNT_KEY.format(symbol=symbol, side=side))
    except Exception:
        pass


def _total_stages(tpl) -> int:
    """template 의 사다리 칸 수 = 총 단계 수."""
    try:
        caps = (tpl.stages_config or {}).get("capitals") or []
        return len(caps) if caps else 0
    except Exception:
        return 0


def run_ladder_restart_once() -> dict:
    """5분 주기. 사다리 전 단계 실패 심볼을 운영 로직 조건에서 처음부터 재시작."""
    db = SessionLocal()
    stat = {"scanned": 0, "restarted": 0, "skipped": {}}

    def _skip(why: str) -> None:
        stat["skipped"][why] = stat["skipped"].get(why, 0) + 1

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
        rows = db.execute(
            select(StrategyInstance, StrategyTemplate)
            .join(StrategyTemplate,
                  StrategyInstance.strategy_template_id == StrategyTemplate.id)
            .where(StrategyInstance.is_archived.is_(False))
            .where(StrategyInstance.status.in_(list(TERMINAL_STATUSES)))
            .where(StrategyInstance.stopped_at >= cutoff)
            .where(StrategyTemplate.trigger_mode == "OBV_REVERSE")
        ).all()
        stat["scanned"] = len(rows)
        if not rows:
            logger.info("[ladder_restart] 대상 없음 (최근 %dh 종료된 OBV 전략 0건)", LOOKBACK_HOURS)
            return stat

        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            logger.warning("[ladder_restart] mainnet 계정 없음")
            return stat

        from app.core.api_backoff import is_account_banned
        if is_account_banned(account.id):
            logger.info("[ladder_restart] API ban 중 = skip")
            return stat

        from app.core.crypto import decrypt_text
        from app.integrations.binance.client import BinanceClient
        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )

        seen: set[tuple[str, str]] = set()
        for si, tpl in rows:
            if stat["restarted"] >= MAX_PER_CYCLE:
                _skip("cycle_budget")
                continue
            key = (si.symbol, si.side)
            if key in seen:
                _skip("dup_in_cycle")
                continue
            seen.add(key)

            # ── 실패 건만 (익절 성공은 카운터 리셋 후 skip) ──
            pnl = float(si.realized_pnl or 0)
            if pnl >= 0:
                reset_restart_count(si.symbol, si.side)
                _skip("profit_no_restart")
                continue

            # ── 사다리를 **끝까지** 썼는가 (중간 수동 정지는 대상 아님) ──
            total = _total_stages(tpl)
            if total <= 0:
                _skip("no_ladder_in_template")
                continue
            if int(si.current_stage or 0) < total:
                logger.info(
                    "[ladder_restart] %s %s skip: 사다리 미소진 (%s/%s단계) = 재시작 대상 아님",
                    si.symbol, si.side, si.current_stage, total,
                )
                _skip("ladder_not_exhausted")
                continue

            # ── 재시작 횟수 ──
            cnt = get_restart_count(si.symbol, si.side)
            if cnt >= MAX_RESTART:
                logger.info(
                    "[ladder_restart] %s %s skip: 재시작 %d/%d 소진 (7일 후 리셋)",
                    si.symbol, si.side, cnt, MAX_RESTART,
                )
                _skip("max_restart")
                continue

            # ── 이미 활성 전략이 있으면 중복 진입 금지 ──
            dup = db.execute(
                select(StrategyInstance)
                .where(StrategyInstance.symbol == si.symbol)
                .where(StrategyInstance.side == si.side)
                .where(StrategyInstance.status.in_(list(ACTIVE_LIKE)))
                .where(StrategyInstance.is_archived.is_(False))
                .limit(1)
            ).scalar_one_or_none()
            if dup is not None:
                _skip("already_active")
                continue

            # ── 24h 누적 손실 게이트 (REENTRY_QUEUE 와 같은 사상) ──
            recent = sum(
                float(x.realized_pnl or 0) for x, _t in rows
                if x.symbol == si.symbol and x.side == si.side
            )
            if recent <= MAX_24H_LOSS_USDT:
                logger.warning(
                    "[ladder_restart] 🚨 %s %s skip: 24h 누적 %.2f USDT <= %.0f = 재시작 중단",
                    si.symbol, si.side, recent, MAX_24H_LOSS_USDT,
                )
                _skip("loss_gate")
                continue

            # ── 동시보유 상한 (fail-SAFE) ──
            try:
                from app.services.position_limit import check_position_slot
                slot_ok, slot_why, _a, _c = check_position_slot(db, "ladder_restart")
            except Exception as e:
                logger.error("[ladder_restart] 상한 검사 실패 → 보류: %s", e)
                _skip("slot_check_error")
                continue
            if not slot_ok:
                logger.info("[ladder_restart] %s %s skip: %s", si.symbol, si.side, slot_why)
                _skip("slot_full")
                continue

            # ── 운영 진입 로직 (Fix 173 과 같은 게이트) ──
            try:
                from app.services.stage_entry_signal import check_stage_entry_signal
                sig_ok, sig_why, sig_det = check_stage_entry_signal(
                    bc, db, si.symbol, si.side,
                )
            except Exception as e:
                logger.warning("[ladder_restart] %s 신호 판정 실패 → 보류: %s", si.symbol, e)
                _skip("signal_error")
                continue
            if not sig_ok:
                logger.info(
                    "[ladder_restart] ⏳ %s %s 대기: %s (재시작 %d/%d)",
                    si.symbol, si.side, sig_why, cnt, MAX_RESTART,
                )
                _skip("signal_wait")
                continue

            # ── 재시작: 같은 template = 사다리 그대로 1단계부터 ──
            try:
                from app.models.strategy_stage_plan import StrategyStagePlan
                from app.services.execution_service import ExecutionService
                from app.services.strategy_service import StrategyService
                from app.workers.auto_bb_breakdown_worker import _get_current_price

                # ⚠️ start_price=None 은 쓸 수 없다.
                #   auto_bb_breakdown_worker:1547 에 그 롤백 기록이 있다:
                #   "start_price=None → planned_capital=None 오류! = 현재가 필요 (preview 계산 위해!)"
                #   자동 진입 경로와 **똑같이** 현재가로 만든 뒤,
                #   1단계 trigger_price 를 None 으로 만들어 MARKET 경로를 강제한다 (v130).
                _px = _get_current_price(si.symbol)
                if not _px or _px <= 0:
                    logger.warning("[ladder_restart] %s 현재가 조회 실패 → 보류", si.symbol)
                    _skip("no_price")
                    continue
                new_si = StrategyService(db).create_strategy_instance(
                    user_id=si.user_id,
                    exchange_account_id=si.exchange_account_id,
                    strategy_template_id=si.strategy_template_id,
                    symbol=si.symbol,
                    side=si.side,
                    start_price=Decimal(str(_px)),
                )
                # MARKET 강제 = 지정가로 걸려 미체결로 남지 않게
                _s1 = db.execute(
                    select(StrategyStagePlan)
                    .where(StrategyStagePlan.strategy_instance_id == new_si.id)
                    .where(StrategyStagePlan.stage_no == 1)
                ).scalar_one_or_none()
                if _s1 is not None:
                    _s1.trigger_price = None
                    db.commit()
                ExecutionService(
                    db,
                    api_key=decrypt_text(account.api_key_enc),
                    api_secret=decrypt_text(account.api_secret_enc),
                    is_testnet=account.is_testnet,
                ).start_stage1(new_si.id)
                n = _bump_restart_count(si.symbol, si.side)
                stat["restarted"] += 1
                logger.warning(
                    "[ladder_restart] 🔁 재시작! %s %s #%s → #%s (%d/%d회) | %s | 이전 PnL %.2f",
                    si.symbol, si.side, si.id, new_si.id, n, MAX_RESTART, sig_why, pnl,
                )
            except Exception as e:
                db.rollback()
                logger.error(
                    "[ladder_restart] ❌ %s %s 재시작 실패: %s", si.symbol, si.side, e,
                )
                _skip("create_failed")

        logger.info(
            "[ladder_restart] 완료: 검사=%d 재시작=%d 사유=%s",
            stat["scanned"], stat["restarted"], stat["skipped"],
        )
        return stat
    except Exception as e:
        logger.exception("[ladder_restart] 실패: %s", e)
        return stat
    finally:
        db.close()
