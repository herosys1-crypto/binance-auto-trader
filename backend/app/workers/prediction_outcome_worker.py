"""🎓 PredictionOutcomeWorker = 예측 결과 학습! (v135 사장님!)

배경 (사장님 요청 2026-08-13):
"지금실행이 기타 분석 분석 실행전과 후 를 변동에 대해서도 분석된것을
 학습해서 추천 심볼에 적용해줘"

로직:
- 매 1시간 실행!
- 예측된 카드 (PENDING/DISMISSED/EXECUTED) = 예측 시점 가격 vs 현재!
- 1h/4h/24h 후 = 실제 변동 저장!
- LONG 예측 = 상승 = SUCCESS / 하락 = FAIL!
- SHORT 예측 = 하락 = SUCCESS / 상승 = FAIL!
- 심볼별 성공률 = 다음 예측에 반영!

기준 (SUCCESS 판정):
- LONG: 4h 후 = +1.5% 이상 = SUCCESS!
- SHORT: 4h 후 = -1.5% 이하 = SUCCESS!
- 그 외 = FAIL!
- 24h 지나도 = 판정 없으면 = EXPIRED!
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
from app.models.strategy_suggestion import StrategySuggestion

logger = logging.getLogger(__name__)


SUCCESS_THRESHOLD = 1.5  # % (LONG +1.5% / SHORT -1.5%)


def run_prediction_outcome() -> dict:
    """예측 outcome 자동 계산!"""
    db: Session = SessionLocal()
    updated = 0
    success = 0
    fail = 0
    expired = 0
    try:
        # Binance client!
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

        # 대상 = outcome_status = None/PENDING + 최근 7일 이내 예측!
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        candidates = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.created_at >= cutoff)
            .where(
                (StrategySuggestion.outcome_status.is_(None))
                | (StrategySuggestion.outcome_status == "PENDING")
            )
        ).scalars().all()

        # 현재가 캐시!
        price_cache: dict[str, float] = {}

        for s in candidates:
            try:
                elapsed = (datetime.now(timezone.utc) - s.created_at).total_seconds() / 3600  # 시간!

                # 심볼 = 현재가 (한 번만 조회!)
                if s.symbol not in price_cache:
                    try:
                        ticker = bc.get_24hr_ticker(symbol=s.symbol)
                        if isinstance(ticker, dict):
                            price_cache[s.symbol] = float(ticker.get("lastPrice", 0))
                    except Exception:
                        continue

                current_price = price_cache.get(s.symbol, 0)
                if current_price <= 0:
                    continue

                # 예측 시점 가격 = strategy_config or 첫 조회 시 저장!
                if s.outcome_price_at_prediction is None or s.outcome_price_at_prediction == 0:
                    # 예측 시점 가격 = 5분봉 klines 조회!
                    try:
                        klines = bc.get_klines(symbol=s.symbol, interval="5m", limit=200)
                        # 예측 시각과 가장 가까운 봉!
                        target_time_ms = int(s.created_at.timestamp() * 1000)
                        closest_kline = None
                        for k in (klines or []):
                            if int(k[0]) >= target_time_ms - 5*60*1000:
                                closest_kline = k
                                break
                        if closest_kline:
                            s.outcome_price_at_prediction = Decimal(str(closest_kline[1]))  # open price
                    except Exception:
                        continue

                if s.outcome_price_at_prediction is None or float(s.outcome_price_at_prediction) <= 0:
                    continue

                predict_price = float(s.outcome_price_at_prediction)
                change_pct = ((current_price - predict_price) / predict_price) * 100

                # 시간대별 변동 (elapsed >= 각 시간대!)
                if elapsed >= 1 and s.outcome_change_1h is None:
                    s.outcome_change_1h = Decimal(str(round(change_pct, 4)))
                if elapsed >= 4 and s.outcome_change_4h is None:
                    s.outcome_change_4h = Decimal(str(round(change_pct, 4)))
                if elapsed >= 24 and s.outcome_change_24h is None:
                    s.outcome_change_24h = Decimal(str(round(change_pct, 4)))

                # 판정 (elapsed >= 4h!)
                if elapsed >= 4 and (s.outcome_status is None or s.outcome_status == "PENDING"):
                    change_4h = float(s.outcome_change_4h or change_pct)
                    if s.side == "LONG":
                        s.outcome_status = "SUCCESS" if change_4h >= SUCCESS_THRESHOLD else "FAIL"
                    else:  # SHORT
                        s.outcome_status = "SUCCESS" if change_4h <= -SUCCESS_THRESHOLD else "FAIL"

                    if s.outcome_status == "SUCCESS":
                        success += 1
                    elif s.outcome_status == "FAIL":
                        fail += 1

                # Expired (24h 지나도 판정 없으면!)
                elif elapsed >= 24 and s.outcome_status == "PENDING":
                    s.outcome_status = "EXPIRED"
                    expired += 1

                # PENDING mark (1h 이내 아직 미판정!)
                elif s.outcome_status is None:
                    s.outcome_status = "PENDING"

                s.outcome_checked_at = datetime.now(timezone.utc)
                updated += 1
            except Exception as e:
                logger.warning("[prediction_outcome] %s 실패: %s", s.symbol, e)
                continue

        db.commit()
        logger.info(
            "[prediction_outcome] updated=%d success=%d fail=%d expired=%d",
            updated, success, fail, expired,
        )
        return {
            "updated": updated,
            "success": success,
            "fail": fail,
            "expired": expired,
        }
    except Exception as e:
        logger.warning("[prediction_outcome] 실행 실패: %s", e)
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


def get_symbol_success_rate(db: Session, symbol: str, side: str, days: int = 30) -> float:
    """심볼별 예측 성공률! (predictor에서 confidence 조정용!)"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(StrategySuggestion)
        .where(StrategySuggestion.symbol == symbol)
        .where(StrategySuggestion.side == side)
        .where(StrategySuggestion.created_at >= cutoff)
        .where(StrategySuggestion.outcome_status.in_(["SUCCESS", "FAIL"]))
    ).scalars().all()

    if not rows:
        return 0.5  # 데이터 X = 중립!

    wins = sum(1 for r in rows if r.outcome_status == "SUCCESS")
    total = len(rows)
    return round(wins / total, 4)
