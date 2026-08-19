"""🤖 AutoBBBreakdownWorker = BB 이탈 SUSTAINED 자동 진입! (v174 사장님 완성!)

사장님 지시 (2026-08-18):
- 1일 5개 (조절 옵션!)
- 손실난 것 = 진입 수량에서 빼기 (카운트!)
- 익절 = 다시 수량 회복! (카운트 X!)
- BB 이탈 SUSTAINED 심볼 = 성공률 85%+ = 자동 진입!

로직 (매 4시간!):
- system_settings 「auto_bb_break_daily_limit」 확인!
- 0 = OFF (수동만!)
- 1+ = 하루 최대 N개 = 자동 진입!
- 카운터 = 활성+손절 (익절 제외!) = v163 로직!
- SUSTAINED (3봉+ 지속 이탈!) + 성공률 85%+ 만!
- 이미 활성 심볼 = 제외!
- 사장님 default profile = template + strategy 자동 생성!
- StrategySuggestion 저장 (자동 진입 표시!)
- 텔레그램 알림!
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_suggestion import StrategySuggestion
from app.models.strategy_template import StrategyTemplate
from app.models.symbol import Symbol
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

# 🎯 v174 사장님: 자동 진입 최소 성공률!
MIN_SUCCESS_PROBABILITY = 0.85

# 🚨 v176 사장님 (2026-08-19): 손실 방지 강화!
# CBRSUSDT #1013 = -10.97% 손실 사례 = 학습 부족!
# 사장님 지시: "이런 손실 없게 학습을 잘 해줘!"
MIN_SYMBOL_SUCCESS_RATE = 0.30  # 심볼 30% 미만 = 자동 진입 제외!
LOSS_BLOCKLIST_HOURS = 24  # 최근 24h 손실 심볼 = 자동 진입 제외!


def run_auto_bb_breakdown() -> dict:
    """매 4시간 = SUSTAINED 심볼 자동 진입! (v174 완성!)"""
    db: Session = SessionLocal()
    entered = 0
    skipped = 0
    results: list[dict] = []
    try:
        # 1. daily_limit 확인!
        limit_row = db.get(SystemSetting, "auto_bb_break_daily_limit")
        daily_limit = int(limit_row.value) if limit_row and limit_row.value else 0
        if daily_limit <= 0:
            return {"note": "auto_bb_break_daily_limit=0 (OFF!)", "entered": 0}

        # 2. 카운터 (v163: 활성 + 손절 = 카운트, 익절 = 제외!)
        used = _count_used_slots(db)
        remaining = daily_limit - used
        if remaining <= 0:
            return {
                "note": f"오늘 사용 {used}/{daily_limit} (활성+손절, 익절 제외!)",
                "entered": 0,
            }

        # 3. SUSTAINED 스캔 (SHORT + LONG!)
        from app.api.v1.bb_middle_scan import scan_bb_breakdown
        try:
            scan_short = scan_bb_breakdown(
                interval="4h", direction="down", max_symbols=100,
                db=db, user_id=1,
            )
            scan_long = scan_bb_breakdown(
                interval="4h", direction="up", max_symbols=100,
                db=db, user_id=1,
            )
        except Exception as e:
            logger.warning("[auto_bb_breakdown] 스캔 실패: %s", e)
            return {"error": f"scan failed: {e}", "entered": 0}

        all_sustained: list[dict] = []
        for it in (scan_short.get("sustained") or []):
            all_sustained.append({**it, "side": "SHORT"})
        for it in (scan_long.get("sustained") or []):
            all_sustained.append({**it, "side": "LONG"})
        # 성공률 큰 순!
        all_sustained.sort(key=lambda x: -(x.get("success_probability") or 0))

        # 4. 이미 활성 심볼 = 제외!
        active_keys = _get_active_symbol_keys(db)
        # 🚨 v176: 최근 24h 손실 심볼 = 제외!
        recent_loss_keys = _get_recent_loss_symbol_keys(db)

        # 5. 사장님 default profile 로드!
        from app.api.v1.suggestion_profiles import _load_profiles
        profiles, default_name = _load_profiles(db)
        default_profile = next(
            (p for p in profiles if p.get("name") == default_name), None,
        )
        if not default_profile:
            return {"error": "default profile 없음!", "entered": 0}
        cfg = default_profile.get("config", {})

        # 6. 각 SUSTAINED = 실 진입!
        for it in all_sustained:
            if entered >= remaining:
                break
            symbol = it["symbol"]
            side = it["side"]
            key = f"{symbol}:{side}"

            # 6a. 이미 활성 = skip!
            if key in active_keys:
                skipped += 1
                continue

            # 🚨 v176: 최근 24h 손실 심볼 = skip! (CBRSUSDT 재발 방지!)
            if key in recent_loss_keys:
                skipped += 1
                logger.info(
                    "[auto_bb_breakdown] 🚨 v176 skip: %s (최근 24h 손실 심볼!)", key,
                )
                continue

            # 🚨 v176: 심볼 30일 성공률 < 30% = skip! (학습 반영!)
            try:
                from app.workers.prediction_outcome_worker import get_symbol_success_rate
                sr = get_symbol_success_rate(db, symbol, side, days=30)
                if sr < MIN_SYMBOL_SUCCESS_RATE:
                    skipped += 1
                    logger.info(
                        "[auto_bb_breakdown] 🚨 v176 skip: %s (심볼 30일 성공률 %.0f%% < %d%%)",
                        key, sr * 100, int(MIN_SYMBOL_SUCCESS_RATE * 100),
                    )
                    continue
            except Exception:
                pass  # sr 조회 실패 = 계속 진행 (fail-open)

            # 6b. 성공률 필터!
            prob = float(it.get("success_probability") or 0)
            if prob < MIN_SUCCESS_PROBABILITY:
                continue  # low prob = 나머지 다 낮음 (정렬됨!)

            # 6c. 실 진입!
            try:
                new_strategy = _create_auto_bb_strategy(db, symbol, side, cfg)
                # StrategySuggestion 저장 (자동 진입 표시!)
                sugg = StrategySuggestion(
                    symbol=symbol, side=side,
                    suggestion_type="bb4h_auto_entry",
                    strategy_config={**cfg, "symbol": symbol, "side": side},
                    confidence_score=Decimal(str(round(prob, 4))),
                    reason=(
                        f"BB 4H SUSTAINED 자동 진입! "
                        f"성공률 {int(prob*100)}% / 지속 {it.get('sustained_bars', 0)}봉 / "
                        f"regime={it.get('regime', 'NEUTRAL')}"
                    ),
                    status="EXECUTED",
                    execution_mode="AUTO",
                    executed_at=datetime.now(timezone.utc),
                    executed_strategy_id=new_strategy.id,
                    outcome_status="PENDING",
                )
                db.add(sugg)
                db.commit()

                results.append({
                    "symbol": symbol,
                    "side": side,
                    "success_probability": prob,
                    "sustained_bars": it.get("sustained_bars"),
                    "regime": it.get("regime"),
                    "strategy_id": new_strategy.id,
                })
                entered += 1

                # 6d. 텔레그램 알림!
                _notify_auto_entry(new_strategy, prob, it)

                logger.info(
                    "[auto_bb_breakdown] ✅ 자동 진입: #%d %s %s (prob=%.0f%%)",
                    new_strategy.id, symbol, side, prob * 100,
                )
            except Exception as e:
                logger.warning(
                    "[auto_bb_breakdown] ❌ %s %s 진입 실패: %s", symbol, side, e,
                )
                skipped += 1
                db.rollback()
                continue

        return {
            "daily_limit": daily_limit,
            "used_before": used,
            "remaining_before": remaining,
            "sustained_total": len(all_sustained),
            "entered_now": entered,
            "skipped": skipped,
            "results": results,
        }
    except Exception as e:
        logger.exception("[auto_bb_breakdown] 예외: %s", e)
        return {"error": str(e), "entered": entered}
    finally:
        db.close()


def _count_used_slots(db: Session) -> int:
    """v163 로직: 활성 + 손절 = 카운트! (익절 = 제외!)

    오늘 EXECUTED (execution_mode='AUTO') + suggestion_type='bb4h_auto_entry'
    - 익절 (SUCCESS outcome) = 제외!
    - 활성 or 손절 (PENDING/FAIL outcome) = 카운트!
    """
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    rows = db.execute(
        select(StrategySuggestion)
        .where(StrategySuggestion.status == "EXECUTED")
        .where(StrategySuggestion.execution_mode == "AUTO")
        .where(StrategySuggestion.suggestion_type == "bb4h_auto_entry")
        .where(StrategySuggestion.executed_at >= today_start)
    ).scalars().all()
    # 익절 (SUCCESS) 제외!
    return sum(1 for r in rows if r.outcome_status != "SUCCESS")


def _get_active_symbol_keys(db: Session) -> set[str]:
    """현재 활성 심볼 keys = 'SYMBOL:SIDE' 집합!"""
    active_keys = set()
    from app.core.strategy_status import TERMINAL_STATUSES
    for a in db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.status.notin_(TERMINAL_STATUSES))
        .where(StrategyInstance.is_archived.is_(False))
    ).scalars().all():
        active_keys.add(f"{a.symbol}:{a.side}")
    return active_keys


def _get_recent_loss_symbol_keys(db: Session) -> set[str]:
    """🚨 v176: 최근 24h 손실 심볼 keys!

    사장님 CBRSUSDT #1013 = -10.97% 손실 → 3분 후 재진입 = 같은 심볼!
    = 손실 후 즉시 재진입 = 위험! 24h 쿨다운!
    """
    from datetime import timedelta
    loss_keys = set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOSS_BLOCKLIST_HOURS)
    # STOPPED 이면서 = realized_pnl < 0 = 손실 심볼!
    for s in db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.status.in_([
            "STOPPED", "CLOSED", "CLOSED_BY_SL", "STOPPED_CAPITAL_EXHAUSTED",
        ]))
        .where(StrategyInstance.stopped_at >= cutoff)
    ).scalars().all():
        try:
            pnl = float(s.realized_pnl or 0)
            if pnl < 0:  # 손실!
                loss_keys.add(f"{s.symbol}:{s.side}")
        except Exception:
            pass
    return loss_keys


def _create_auto_bb_strategy(
    db: Session, symbol: str, side: str, cfg: dict[str, Any],
) -> StrategyInstance:
    """사장님 default profile 기반 = template + strategy 자동 생성!"""
    # symbol 검증!
    symbol_row = db.execute(
        select(Symbol).where(Symbol.symbol == symbol)
    ).scalar_one_or_none()
    if not symbol_row:
        raise ValueError(f"symbol {symbol} not in DB")

    # capital 정리!
    capitals = cfg.get("capitals") or [500, 500, 500, 500]
    total_capital = sum(float(c) for c in capitals)
    trigger_percents = cfg.get("trigger_percents") or [None, 10, 20, 20]

    stages_config = {
        "capitals": capitals,
        "trigger_percents": trigger_percents,
        "stages_count": len(capitals),
    }

    # 신 template!
    now = datetime.now(timezone.utc)
    tpl = StrategyTemplate(
        name=f"AUTO_BB_{symbol}_{side}_{now.strftime('%Y%m%d_%H%M%S')}",
        strategy_type="auto_bb_break",
        side=side,
        leverage=int(cfg.get("leverage", 2)),
        total_capital=Decimal(str(total_capital)),
        stages_config=stages_config,
        stage1_capital=Decimal(str(capitals[0])) if len(capitals) > 0 else None,
        stage2_capital=Decimal(str(capitals[1])) if len(capitals) > 1 else None,
        stage3_capital=Decimal(str(capitals[2])) if len(capitals) > 2 else None,
        stage4_capital=Decimal(str(capitals[3])) if len(capitals) > 3 else None,
        stage2_trigger_percent=(
            Decimal(str(trigger_percents[1])) if len(trigger_percents) > 1 and trigger_percents[1] else None
        ),
        stage3_trigger_percent=(
            Decimal(str(trigger_percents[2])) if len(trigger_percents) > 2 and trigger_percents[2] else None
        ),
        stage4_trigger_percent=(
            Decimal(str(trigger_percents[3])) if len(trigger_percents) > 3 and trigger_percents[3] else None
        ),
        tp1_percent=Decimal(str(cfg.get("tp1_percent", 10))),
        tp2_percent=Decimal(str(cfg.get("tp2_percent", 15))),
        tp3_percent=Decimal(str(cfg.get("tp3_percent", 20))),
        tp4_percent=Decimal(str(cfg.get("tp4_percent", 25))),
        tp1_qty_ratio=Decimal(str(cfg.get("tp1_qty_ratio", 10))),
        tp2_qty_ratio=Decimal(str(cfg.get("tp2_qty_ratio", 15))),
        tp3_qty_ratio=Decimal(str(cfg.get("tp3_qty_ratio", 20))),
        tp4_qty_ratio=Decimal(str(cfg.get("tp4_qty_ratio", 25))),
        stop_loss_percent_of_capital=Decimal(str(cfg.get("stop_loss_percent_of_capital", 90))),
        is_active=True,
    )
    db.add(tpl)
    db.flush()

    # strategy_instance 생성 (start_price=None = MARKET!)!
    from app.services.strategy_service import StrategyService
    svc = StrategyService(db)

    # 현재가 조회 = start_price!
    start_price = _get_current_price(symbol)

    strategy = svc.create_strategy_instance(
        user_id=1,
        exchange_account_id=1,
        strategy_template_id=tpl.id,
        symbol=symbol,
        side=side,
        start_price=start_price,
        leverage_override=int(cfg.get("leverage", 2)),
        retry_after_liquidation_enabled=bool(cfg.get("retry_after_liquidation_enabled", False)),
        retry_trigger_pct=(
            Decimal(str(cfg.get("retry_trigger_pct", 10)))
            if cfg.get("retry_trigger_pct") else None
        ),
    )
    return strategy


def _get_current_price(symbol: str) -> Decimal:
    """현재가 조회 = start_price!"""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        val = r.get(f"mark_price:{symbol}")
        if val:
            return Decimal(str(val.decode() if isinstance(val, bytes) else val))
    except Exception:
        pass
    # fallback = Binance API!
    try:
        from app.integrations.binance.client import BinanceClient
        from app.models.exchange_account import ExchangeAccount
        from app.core.crypto import decrypt_text
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            account = db.execute(
                select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
            ).scalar_one_or_none()
            if account:
                bc = BinanceClient(
                    api_key=decrypt_text(account.api_key_enc),
                    api_secret=decrypt_text(account.api_secret_enc),
                    is_testnet=False,
                )
                ticker = bc.get_24hr_ticker(symbol=symbol)
                if isinstance(ticker, dict):
                    return Decimal(str(ticker.get("lastPrice", 0)))
        finally:
            db.close()
    except Exception:
        pass
    raise ValueError(f"현재가 조회 실패: {symbol}")


def _notify_auto_entry(strategy: StrategyInstance, prob: float, scan_info: dict) -> None:
    """자동 진입 텔레그램 알림!"""
    try:
        from app.services.notification_service import get_notification_service
        ns = get_notification_service()
        if ns is None:
            return
        emoji = "🐻" if strategy.side == "SHORT" else "🐂"
        ns.send_system_alert(
            title=f"🤖 [자동 진입] #{strategy.id} {strategy.symbol} {strategy.side} {emoji}",
            body="\n".join([
                f"⚡ BB 4H SUSTAINED 자동 진입!",
                f"📊 성공률: {int(prob * 100)}%",
                f"🎯 4구간: {scan_info.get('regime', 'NEUTRAL')}",
                f"🔥 지속 봉수: {scan_info.get('sustained_bars', 0)}봉",
                f"💰 자본: {strategy.total_capital} USDT",
                f"⚖️ 레버리지: {strategy.leverage}x",
                "",
                f"= 사장님 default profile로 자동 진입 완료!",
                f"= 대시보드에서 진행 상황 확인!",
            ]),
        )
    except Exception as e:
        logger.warning("[auto_bb_breakdown] 알림 실패: %s", e)
