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


SUCCESS_THRESHOLD = 10.0  # % (LONG +10% / SHORT -10%)
# 🚨 v156 사장님 지시 (2026-08-16):
#   "10%이상 수익만 성공으로 해줘"
# = 옛 v135 기준 (1.5%) = 너무 낮음 → 100% 성공률이 사실은 애매!
# = 신 기준 (10%) = 진짜 큰 수익 낸 심볼만 SUCCESS!
# = 심볼 성공률 = 진짜 신뢰할 수 있는 데이터!

# v139: 시점별 가격 조회 캐시 (symbol, interval) → klines
_KLINE_CACHE: dict[str, list] = {}


def _price_at(bc, symbol: str, target: datetime) -> float | None:
    """특정 시각의 가격 = 그 시각 직전 완료 15m 봉 종가 (v139 신!).

    기존엔 「현재가」로 1h/4h/24h를 전부 채워서 학습 데이터가 오염됐습니다.
    미래 시각이면 None (아직 판정 불가).
    """
    now = datetime.now(timezone.utc)
    if target > now:
        return None
    try:
        kl = _KLINE_CACHE.get(symbol)
        if kl is None:
            # 15m × 1000 = 약 10일치 = 24h 판정에 충분!
            kl = bc.get_klines(symbol=symbol, interval="15m", limit=1000) or []
            _KLINE_CACHE[symbol] = kl
        target_ms = int(target.timestamp() * 1000)
        prev = None
        for k in kl:
            if int(k[6]) <= target_ms:   # close_time
                prev = k
            else:
                break
        return float(prev[4]) if prev else None
    except Exception:
        return None


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

                # 🚨 v139 CRITICAL FIX (2026-08-14 백테스트에서 발견!)
                #
                # 기존 버그: 1h/4h/24h 칸을 전부 **지금 현재가**로 채웠습니다.
                #   worker 는 1시간마다 도는데, 어떤 예측을 처음 볼 때 이미 4시간이
                #   지났으면 outcome_change_1h 에 4시간치 변동이 들어갔습니다.
                #
                # 실측 피해 (프로덕션 789건):
                #   - 1h == 4h 로 같은 값이 들어간 건 = 397건 (60%!)
                #   - 캔들 재계산과 1%p 초과 불일치 = 459/662건 (69%)
                #   = 「예측 후 1시간 변동」 학습 데이터가 사실상 전부 가짜였음!
                #
                # fix: 각 시간대는 **그 시점의 캔들 종가**로 계산 (현재가 X!)
                for hours, field in ((1, "outcome_change_1h"),
                                     (4, "outcome_change_4h"),
                                     (24, "outcome_change_24h")):
                    if elapsed < hours or getattr(s, field) is not None:
                        continue
                    px = _price_at(bc, s.symbol, s.created_at + timedelta(hours=hours))
                    if px is None:
                        continue
                    setattr(
                        s, field,
                        Decimal(str(round((px - predict_price) / predict_price * 100, 4))),
                    )

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

        _KLINE_CACHE.clear()   # v139: 실행마다 캐시 비움 (다음 실행은 새 캔들!)
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


def recompute_all_outcomes() -> dict:
    """🚨 v156 사장님 지시: 「10%이상 수익만 성공」 = 기존 판정 재계산!

    옛 판정 (1.5% 기준!) → 신 판정 (10% 기준!) 재적용!
    - outcome_change_4h >= 10% (LONG) or <= -10% (SHORT) = SUCCESS!
    - 그 외 = FAIL!
    - outcome_change_4h 데이터 있는 것만 재판정!
    """
    db: Session = SessionLocal()
    updated = 0
    to_success = 0
    to_fail = 0
    try:
        rows = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.outcome_status.in_(["SUCCESS", "FAIL", "EXPIRED"]))
            .where(StrategySuggestion.outcome_change_4h.isnot(None))
        ).scalars().all()

        for s in rows:
            try:
                change_4h = float(s.outcome_change_4h or 0)
                old_status = s.outcome_status
                if s.side == "LONG":
                    new_status = "SUCCESS" if change_4h >= SUCCESS_THRESHOLD else "FAIL"
                else:  # SHORT
                    new_status = "SUCCESS" if change_4h <= -SUCCESS_THRESHOLD else "FAIL"

                if new_status != old_status:
                    s.outcome_status = new_status
                    updated += 1
                    if new_status == "SUCCESS":
                        to_success += 1
                    else:
                        to_fail += 1
            except Exception:
                continue

        db.commit()
        logger.info(
            "[recompute_outcomes] v156 재계산 완료: %d건 변경 (→SUCCESS: %d, →FAIL: %d)",
            updated, to_success, to_fail,
        )
        return {
            "reprocessed": len(rows),
            "changed": updated,
            "to_success": to_success,
            "to_fail": to_fail,
            "threshold": SUCCESS_THRESHOLD,
        }
    except Exception as e:
        logger.warning("[recompute_outcomes] 실패: %s", e)
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
