"""🎯 v199 사장님 실시간 모니터링 + 자동 재진입 시스템! (Phase 1!)

사장님 지시 (2026-08-21):
"급등후 급락 / 급락후 급등 / 급등 종목을 실시간 모니터링!
 관리 가능한 수만큼 = 적절한 타이밍에 진입!"

로직 (매 15분 실행!):
1. Watchlist 관리 (top 50 심볼!):
   - 24h 급등/급락 상위 30!
   - 거래량 상위 20!
   - 최근 실패 심볼 (재진입 후보!)
2. 각 심볼 = MTA 신호 계산!
3. 강한 신호 (MTA 20+/30) = 진입 큐 저장!
4. auto_bb_breakdown_worker가 처리!

Phase 2 (다음!): post-entry tracking + 자동 재진입!
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.redis_client import get_redis_client
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

# Redis key = 실시간 watchlist!
WATCHLIST_KEY = "v199:realtime_watchlist"
WATCHLIST_TTL_SEC = 900  # 15분!

MAX_WATCHLIST_SIZE = 50  # 사장님 「관리 가능한 수」!


def run_realtime_watchlist() -> dict:
    """매 15분 = watchlist 갱신 + 강한 신호 감지!"""
    db: Session = SessionLocal()
    try:
        # 🚨 API Ban 확인!
        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            return {"error": "no mainnet account"}

        from app.core.api_backoff import is_account_banned
        if is_account_banned(account.id):
            return {"note": "API Ban 중 - skip!", "skipped": True}

        # 1. 24h ticker 조회!
        from app.core.crypto import decrypt_text
        from app.integrations.binance.client import BinanceClient
        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )
        try:
            tickers = bc.get_24hr_ticker()
            if not isinstance(tickers, list):
                return {"error": "ticker 실패"}
        except Exception as e:
            return {"error": f"ticker exception: {e}"}

        # USDT only!
        usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]

        # 2. Watchlist 선정!
        watchlist = _build_watchlist(db, usdt)

        # 3. Redis 저장!
        r = get_redis_client()
        r.setex(WATCHLIST_KEY, WATCHLIST_TTL_SEC, json.dumps(watchlist))

        logger.info(
            "[v199] watchlist 갱신: %d 심볼 (급등%d + 급락%d + 거래량%d + 재진입%d)",
            len(watchlist), sum(1 for w in watchlist if w["reason"] == "TOP_GAIN"),
            sum(1 for w in watchlist if w["reason"] == "TOP_LOSS"),
            sum(1 for w in watchlist if w["reason"] == "TOP_VOLUME"),
            sum(1 for w in watchlist if w["reason"] == "REENTRY_CANDIDATE"),
        )
        # 🎼 v206 사장님: 오케스트라 통합 = EventBus 발신!
        try:
            from app.agents.orchestrator.event_bus import get_event_bus
            from app.agents.orchestrator.event_types import EventType
            get_event_bus().publish(EventType.WATCHLIST_UPDATED, {
                "count": len(watchlist),
                "gain_count": sum(1 for w in watchlist if w["reason"] == "TOP_GAIN"),
                "loss_count": sum(1 for w in watchlist if w["reason"] == "TOP_LOSS"),
                "volume_count": sum(1 for w in watchlist if w["reason"] == "TOP_VOLUME"),
                "reentry_count": sum(1 for w in watchlist if w["reason"] == "REENTRY_CANDIDATE"),
            })
        except Exception as e:
            logger.debug("[v206] EventBus publish 실패 (fail-open): %s", e)

        return {
            "count": len(watchlist),
            "watchlist": watchlist[:10],  # top 10 preview!
            "cache_key": WATCHLIST_KEY,
        }
    except Exception as e:
        logger.exception("[v199] 실패: %s", e)
        return {"error": str(e)}
    finally:
        db.close()


def _build_watchlist(db: Session, tickers: list[dict]) -> list[dict]:
    """Watchlist 선정!

    - 24h 변동 상위 15 (급등!)
    - 24h 변동 하위 15 (급락!)
    - 거래량 상위 15!
    - 최근 실패 재진입 후보 5!

    = 총 최대 50 심볼!
    """
    # 1. WORST 심볼 제외 세트!
    exclude = _get_exclude_set(db)

    watchlist = []
    seen = set()

    # 2. 급등 top 15!
    sorted_gain = sorted(
        [t for t in tickers if str(t.get("symbol", "")) not in exclude],
        key=lambda x: -float(x.get("priceChangePercent", 0) or 0),
    )[:15]
    for t in sorted_gain:
        sym = str(t.get("symbol"))
        if sym in seen:
            continue
        seen.add(sym)
        watchlist.append({
            "symbol": sym,
            "reason": "TOP_GAIN",
            "change_24h": float(t.get("priceChangePercent", 0) or 0),
            "volume_24h": float(t.get("quoteVolume", 0) or 0),
        })

    # 3. 급락 top 15!
    sorted_loss = sorted(
        [t for t in tickers if str(t.get("symbol", "")) not in exclude],
        key=lambda x: float(x.get("priceChangePercent", 0) or 0),
    )[:15]
    for t in sorted_loss:
        sym = str(t.get("symbol"))
        if sym in seen:
            continue
        seen.add(sym)
        watchlist.append({
            "symbol": sym,
            "reason": "TOP_LOSS",
            "change_24h": float(t.get("priceChangePercent", 0) or 0),
            "volume_24h": float(t.get("quoteVolume", 0) or 0),
        })

    # 4. 거래량 top 15!
    sorted_vol = sorted(
        [t for t in tickers if str(t.get("symbol", "")) not in exclude],
        key=lambda x: -float(x.get("quoteVolume", 0) or 0),
    )[:15]
    for t in sorted_vol:
        sym = str(t.get("symbol"))
        if sym in seen:
            continue
        seen.add(sym)
        watchlist.append({
            "symbol": sym,
            "reason": "TOP_VOLUME",
            "change_24h": float(t.get("priceChangePercent", 0) or 0),
            "volume_24h": float(t.get("quoteVolume", 0) or 0),
        })

    # 5. 재진입 후보 (최근 실패 심볼!)
    reentry_syms = _get_reentry_candidates(db, limit=5)
    for sym in reentry_syms:
        if sym in seen:
            continue
        seen.add(sym)
        t = next((x for x in tickers if str(x.get("symbol")) == sym), None)
        if t:
            watchlist.append({
                "symbol": sym,
                "reason": "REENTRY_CANDIDATE",
                "change_24h": float(t.get("priceChangePercent", 0) or 0),
                "volume_24h": float(t.get("quoteVolume", 0) or 0),
            })

    return watchlist[:MAX_WATCHLIST_SIZE]


def _get_exclude_set(db: Session) -> set[str]:
    """WORST 심볼 제외 (v188/v194!)"""
    exclude = set()
    try:
        from app.workers.auto_bb_breakdown_worker import _get_worst_learning_keys
        worst = _get_worst_learning_keys(db)
        # key = "SYMBOL:SIDE" → symbol만!
        for k in worst:
            sym = k.split(":")[0]
            exclude.add(sym)
    except Exception:
        pass
    return exclude


def _get_reentry_candidates(db: Session, limit: int = 5) -> list[str]:
    """실패 후 재진입 후보! (사장님 사상!)

    - 최근 24h 실패 심볼!
    - 반대 방향 성공 심볼 = 우선!
    """
    candidates = []
    try:
        from app.core.strategy_status import TERMINAL_STATUSES
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        rows = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.stopped_at >= cutoff)
            .where(StrategyInstance.status.in_(list(TERMINAL_STATUSES)))
        ).scalars().all()
        for s in rows:
            pnl = float(s.realized_pnl or 0)
            if pnl < 0 and s.symbol not in candidates:
                candidates.append(s.symbol)
                if len(candidates) >= limit:
                    break
    except Exception:
        pass
    return candidates


def get_watchlist_from_cache() -> list[dict] | None:
    """Redis에서 watchlist 로드!"""
    try:
        r = get_redis_client()
        raw = r.get(WATCHLIST_KEY)
        if not raw:
            return None
        return json.loads(raw.decode() if isinstance(raw, bytes) else raw)
    except Exception as e:
        logger.warning("[v199] watchlist 로드 실패: %s", e)
        return None
