"""신 「재진입 알람 워처」 = 강제 종료 후 = 신 진입 기회 감지! (v130!)

spec: docs/CHART_REENTRY_STRATEGY_SPEC.md (사장님 확장 2026-08-06)
사장님 요청:
  '강제종료관 심볼은 상승이나 하락이 10% 이상이고 obv와 rsi의 4시간 보조차트가
   상승 하락 시작시 새전략을 시작할수 있게 알람 만들어주고'

로직:
  1. 최근 24h 내 강제 종료된 심볼 조회 (RiskEvent = force_sl or SL)
  2. 각 심볼 = 종료 후 10% 이상 이동?
  3. 4H OBV + 4H RSI 반전 시작?
  4. 조건 만족 시 = 알림!
     - Redis에 = 알람 저장 (24h TTL)
     - Telegram 사장님 알림
     - UI에서 = 알람 카드 표시!

헌법 v130:
  '차트 분석 신호 = OBV 반전 = 사장님 자율 정확 재진입!'
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

REDIS_KEY_ALERTS = "reentry_alerts:v1"  # sorted set (score=timestamp)
ALERT_TTL_SEC = 24 * 3600  # 24h


def _compute_rsi(closes: list[Decimal], period: int = 14) -> list[Decimal]:
    """RSI 계산 (표준 Wilder's method)."""
    if len(closes) < period + 1:
        return []
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(diff if diff > 0 else Decimal("0"))
        losses.append(-diff if diff < 0 else Decimal("0"))
    if len(gains) < period:
        return []
    # 첫 avg
    avg_gain = sum(gains[:period]) / Decimal(period)
    avg_loss = sum(losses[:period]) / Decimal(period)
    rsi_list: list[Decimal] = []
    for i in range(period, len(gains) + 1):
        if avg_loss == 0:
            rsi = Decimal("100")
        else:
            rs = avg_gain / avg_loss
            rsi = Decimal("100") - (Decimal("100") / (Decimal("1") + rs))
        rsi_list.append(rsi)
        # Wilder's smoothing (next iter)
        if i < len(gains):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / Decimal(period)
            avg_loss = (avg_loss * (period - 1) + losses[i]) / Decimal(period)
    return rsi_list


def _obv_from_klines(kl: list) -> list[Decimal]:
    """OBV 계산 (chart_analyzer와 동일)."""
    if not kl or len(kl) < 2:
        return []
    obv = [Decimal("0")]
    prev_close = Decimal(str(kl[0][4]))
    for k in kl[1:]:
        close = Decimal(str(k[4]))
        vol = Decimal(str(k[5]))
        if close > prev_close:
            obv.append(obv[-1] + vol)
        elif close < prev_close:
            obv.append(obv[-1] - vol)
        else:
            obv.append(obv[-1])
        prev_close = close
    return obv


def check_reentry_alert_for_symbol(
    binance_client,
    symbol: str,
    prev_stop_price: Decimal,
) -> tuple[bool, dict]:
    """4H 봉 = OBV + RSI 반전 + 10% 가격 이동 확인.

    Returns:
        (신호?, detail dict)
    """
    try:
        kl_4h = binance_client.get_klines(symbol=symbol, interval="4h", limit=50)
        if not kl_4h or len(kl_4h) < 20:
            return (False, {"error": "insufficient 4h klines"})

        closes = [Decimal(str(k[4])) for k in kl_4h]
        current = closes[-1]

        # 10% 가격 이동
        if prev_stop_price <= 0:
            return (False, {"error": "invalid prev_stop_price"})
        move_pct = abs((current - prev_stop_price) / prev_stop_price) * Decimal("100")
        cond_10pct = move_pct >= Decimal("10")

        # OBV 반전 (직전 봉 상승 + 현재 하락, or 반대)
        obv = _obv_from_klines(kl_4h)
        if len(obv) < 3:
            return (False, {"error": "insufficient OBV"})
        obv_reverse = (
            (obv[-2] > obv[-3] and obv[-1] < obv[-2])  # 상승 후 하락 (SHORT 기회!)
            or (obv[-2] < obv[-3] and obv[-1] > obv[-2])  # 하락 후 상승 (LONG 기회!)
        )

        # RSI 반전 (동일 패턴)
        rsi = _compute_rsi(closes, period=14)
        if len(rsi) < 3:
            return (False, {"error": "insufficient RSI"})
        rsi_reverse = (
            (rsi[-2] > rsi[-3] and rsi[-1] < rsi[-2])
            or (rsi[-2] < rsi[-3] and rsi[-1] > rsi[-2])
        )

        signal = cond_10pct and obv_reverse and rsi_reverse
        detail = {
            "signal": signal,
            "cond_10pct": cond_10pct,
            "move_pct": str(round(move_pct, 2)),
            "obv_reverse": obv_reverse,
            "rsi_reverse": rsi_reverse,
            "current_price": str(current),
            "prev_stop_price": str(prev_stop_price),
            "rsi_last": str(round(rsi[-1], 2)) if rsi else None,
        }
        return (signal, detail)
    except Exception as e:
        logger.warning("[reentry_alert] %s 검사 실패: %s", symbol, e)
        return (False, {"error": str(e)})


def run_reentry_alert_watcher(db: Session, decrypt_text) -> dict:
    """강제 종료된 심볼 대상 = 재진입 알람 감지!

    Returns:
        summary dict
    """
    from app.models.exchange_account import ExchangeAccount
    from app.models.risk_event import RiskEvent
    from app.models.strategy_instance import StrategyInstance
    from app.integrations.binance.client import BinanceClient
    from app.core.redis_client import get_redis_client

    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    result: dict = {"checked": 0, "alerts": 0, "errors": []}

    # 최근 24h 강제 종료 이벤트 조회
    events = db.execute(
        select(RiskEvent)
        .where(RiskEvent.created_at >= cutoff_24h)
        .where(RiskEvent.event_type.in_([
            "FORCE_SL_TRIGGERED",
            "SL_TRIGGERED",
            "STRATEGY_STOPPED_BY_SL",
        ]))
    ).scalars().all()

    _redis = None
    try:
        _redis = get_redis_client()
    except Exception:
        pass

    checked_symbols: set = set()
    for ev in events:
        strategy = db.get(StrategyInstance, ev.strategy_instance_id) if ev.strategy_instance_id else None
        if not strategy or not strategy.symbol:
            continue
        # 심볼별 = 1회만 검사 (중복 방지)
        _key = (strategy.exchange_account_id, strategy.symbol.upper())
        if _key in checked_symbols:
            continue
        checked_symbols.add(_key)

        account = db.get(ExchangeAccount, strategy.exchange_account_id)
        if not account:
            continue
        try:
            bc = BinanceClient(
                api_key=decrypt_text(account.api_key_enc),
                api_secret=decrypt_text(account.api_secret_enc),
                is_testnet=account.is_testnet,
            )
            prev_stop = Decimal(str(strategy.avg_entry_price or 0))
            if prev_stop <= 0:
                continue
            signal, detail = check_reentry_alert_for_symbol(bc, strategy.symbol, prev_stop)
            result["checked"] += 1
            if signal:
                # 알람 저장 = Redis!
                _alert = {
                    "symbol": strategy.symbol,
                    "side": strategy.side,  # 사장님 원방향 = 재진입 추천!
                    "exchange_account_id": strategy.exchange_account_id,
                    "prev_strategy_id": strategy.id,
                    "detail": detail,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                if _redis:
                    _alert_key = "reentry_alert:" + hashlib.md5(
                        f"{strategy.exchange_account_id}:{strategy.symbol}".encode()
                    ).hexdigest()[:16]
                    _redis.setex(_alert_key, ALERT_TTL_SEC, json.dumps(_alert))
                    # 인덱스 = sorted set (id 기준 조회용)
                    _redis.zadd(
                        REDIS_KEY_ALERTS,
                        {_alert_key: datetime.now(timezone.utc).timestamp()}
                    )
                    # 옛 알람 정리 (24h+ = 자동 제거)
                    _redis.zremrangebyscore(
                        REDIS_KEY_ALERTS,
                        0, (datetime.now(timezone.utc) - timedelta(hours=24)).timestamp()
                    )
                result["alerts"] += 1
                logger.info(
                    "[reentry_alert v130] 🎯 재진입 알람! %s %s detail=%s",
                    strategy.symbol, strategy.side, detail,
                )
                # Telegram 알림 (dedup 6h)
                try:
                    from app.services.notification_service import NotificationService
                    _dedup_key = f"reentry_alert:sent:{strategy.exchange_account_id}:{strategy.symbol}"
                    if _redis and not _redis.get(_dedup_key):
                        NotificationService(db).send_system_alert(
                            title=f"🎯 [재진입 기회!] {strategy.symbol} {strategy.side}",
                            body=(
                                f"🎯 「{strategy.symbol}」 재진입 신호!\n"
                                f"  이전 손절가: {detail.get('prev_stop_price')}\n"
                                f"  현재가: {detail.get('current_price')}\n"
                                f"  이동: {detail.get('move_pct')}% ({strategy.side})\n"
                                f"  4H OBV 반전: ✓\n"
                                f"  4H RSI 반전: ✓ (last={detail.get('rsi_last')})\n\n"
                                f"대시보드 → 알람 클릭 = 신 전략 즉시 생성!"
                            ),
                        )
                        _redis.setex(_dedup_key, 6 * 3600, "1")
                except Exception as _te:
                    logger.warning("[reentry_alert] Telegram 실패: %s", _te)
        except Exception as e:
            result["errors"].append(f"{strategy.symbol}: {e}")

    logger.info("[reentry_alert v130] 완료: checked=%s alerts=%s", result["checked"], result["alerts"])
    return result


if __name__ == "__main__":
    from app.db.session import SessionLocal
    from app.core.crypto import decrypt_text
    with SessionLocal() as _db:
        print(run_reentry_alert_watcher(_db, decrypt_text))
