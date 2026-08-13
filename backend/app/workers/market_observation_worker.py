"""🔬 MarketObservationWorker = 진입 X 심볼도 관찰! (v136 사장님!)

배경 (사장님 요청 2026-08-13):
"우리가 포지션에 진입하지 않은 심볼들도 그렇게 하면 앞으로 전략진입에 큰도움될것 같아"

= 매 4시간 = 상위 100 심볼 = snapshot!
= 매 1시간 = 지난 관찰 = 실제 변동 update!
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.crypto import decrypt_text
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.models.market_observation import MarketObservation

logger = logging.getLogger(__name__)

# 상위 몇 개?
TOP_PUMP = 50
TOP_DUMP = 50


def run_market_observation_snapshot() -> dict:
    """매 4시간 = 상위 100 심볼 snapshot!"""
    db: Session = SessionLocal()
    created = 0
    try:
        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            return {"error": "no mainnet account"}

        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )

        tickers = bc.get_24hr_ticker()
        if not isinstance(tickers, list):
            return {"error": "invalid ticker"}

        usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
        try:
            sorted_by = sorted(usdt, key=lambda x: float(x.get("priceChangePercent", 0) or 0), reverse=True)
        except Exception:
            return {"error": "sort failed"}

        pumps = sorted_by[:TOP_PUMP]
        dumps = sorted_by[-TOP_DUMP:][::-1]

        now = datetime.now(timezone.utc)

        # 관찰 저장!
        for rank, t in enumerate(pumps, 1):
            try:
                symbol = str(t.get("symbol"))
                price = float(t.get("lastPrice", 0) or 0)
                change_24h = float(t.get("priceChangePercent", 0) or 0)
                obs = MarketObservation(
                    symbol=symbol,
                    observed_at=now,
                    price_at_obs=Decimal(str(price)) if price > 0 else None,
                    rank_by_pump=rank,
                    market_context={
                        "change_24h_at_obs": change_24h,
                        "volume_24h": float(t.get("quoteVolume", 0) or 0),
                    },
                )
                db.add(obs)
                created += 1
            except Exception:
                continue

        for rank, t in enumerate(dumps, 1):
            try:
                symbol = str(t.get("symbol"))
                price = float(t.get("lastPrice", 0) or 0)
                change_24h = float(t.get("priceChangePercent", 0) or 0)
                obs = MarketObservation(
                    symbol=symbol,
                    observed_at=now,
                    price_at_obs=Decimal(str(price)) if price > 0 else None,
                    rank_by_dump=rank,
                    market_context={
                        "change_24h_at_obs": change_24h,
                        "volume_24h": float(t.get("quoteVolume", 0) or 0),
                    },
                )
                db.add(obs)
                created += 1
            except Exception:
                continue

        db.commit()
        logger.info("[market_observation] snapshot: created=%d", created)
        return {"created": created}
    except Exception as e:
        logger.warning("[market_observation] snapshot 실패: %s", e)
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


def run_market_observation_update() -> dict:
    """매 1시간 = 지난 관찰 update (실제 변동!)"""
    db: Session = SessionLocal()
    updated = 0
    try:
        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            return {"error": "no mainnet account"}

        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )

        # 7일 이내 = 미완료 관찰!
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        observations = db.execute(
            select(MarketObservation)
            .where(MarketObservation.observed_at >= cutoff)
            .where(MarketObservation.change_24h_later.is_(None))
        ).scalars().all()

        # 심볼별 현재가 캐시!
        price_cache: dict[str, float] = {}
        for obs in observations:
            try:
                elapsed_h = (datetime.now(timezone.utc) - obs.observed_at).total_seconds() / 3600
                if elapsed_h < 1:
                    continue
                if obs.price_at_obs is None or float(obs.price_at_obs) <= 0:
                    continue

                if obs.symbol not in price_cache:
                    try:
                        ticker = bc.get_24hr_ticker(symbol=obs.symbol)
                        if isinstance(ticker, dict):
                            price_cache[obs.symbol] = float(ticker.get("lastPrice", 0))
                    except Exception:
                        continue

                current = price_cache.get(obs.symbol, 0)
                if current <= 0:
                    continue

                predict_price = float(obs.price_at_obs)
                change_pct = ((current - predict_price) / predict_price) * 100

                if elapsed_h >= 1 and obs.change_1h is None:
                    obs.change_1h = Decimal(str(round(change_pct, 4)))
                    obs.price_1h_later = Decimal(str(current))
                if elapsed_h >= 4 and obs.change_4h is None:
                    obs.change_4h = Decimal(str(round(change_pct, 4)))
                    obs.price_4h_later = Decimal(str(current))
                if elapsed_h >= 24 and obs.change_24h_later is None:
                    obs.change_24h_later = Decimal(str(round(change_pct, 4)))
                    obs.price_24h_later = Decimal(str(current))
                    # 사후 side 판단! (24h 후 = 확정!)
                    if change_pct >= 3:
                        obs.side_would_have = "LONG"
                    elif change_pct <= -3:
                        obs.side_would_have = "SHORT"
                    else:
                        obs.side_would_have = "NEUTRAL"

                updated += 1
            except Exception:
                continue

        db.commit()
        logger.info("[market_observation] update: updated=%d", updated)
        return {"updated": updated}
    except Exception as e:
        logger.warning("[market_observation] update 실패: %s", e)
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()
