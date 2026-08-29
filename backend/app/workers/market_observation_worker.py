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


# ═══════════════════════════════════════════════════════════════════════════
# 🚨 Fix 226 (2026-08-30 사장님): 관찰 시점의 **지표까지** 남긴다.
#
# 사장님 verbatim:
#   "다시 상승하기 힘들다지 없다는건 아니야. 찾으면 너무 좋은데 많이 학습이 필요해.
#    **초기에 상승하는 심볼들의 차트와 보조지표를 찾아서 학습해서 수치화** 해야해"
#
# 이 워커는 이미 4시간마다 **급등 50 / 급락 50** 을 저장하고(사장님이 원하신 그 기준),
# 1시간마다 1h/4h/24h **결과**를 채운다. 즉 「관찰 → 결과」 파이프라인은 이미 있다.
# 빠진 것은 **관찰 시점의 지표**뿐이었다 — market_context 에 24h 변동률과 거래대금만
# 있어서 "어떤 지표 조합이 그 뒤 상승으로 이어졌나" 를 물어볼 수가 없었다.
#
# 여기서 남기면 그대로 학습 표본이 된다:
#     관찰 시점 지표  ×  그 뒤 1h/4h/24h 결과  =  수치화의 근거
#
# ⚠️ OBV 는 **비율로** 저장한다. 기존 obv_slope_pct 는 (끝-처음)/|처음| 형태라
#    시작값이 0 근처면 폭발한다 — 실측에서 **2,249,160** 이 나온 원인으로 의심된다.
#    여기서는 창 안 총거래량으로 나눠 항상 -1~+1 로 묶는다(obv_gate 와 같은 발상).
# ═══════════════════════════════════════════════════════════════════════════
_IND_TFS = (("15m", 60), ("4h", 60))


def _indicator_snapshot(bc, symbol: str) -> dict:
    """관찰 시점 지표 — 학습용. 실패해도 관찰 저장 자체를 막지 않는다."""
    from app.services.chart_analyzer import ChartAnalyzer

    out: dict = {}
    for tf, limit in _IND_TFS:
        try:
            a = ChartAnalyzer.analyze_timeframe(bc, symbol, tf, limit=limit)
            if not a:
                continue
            closes = a.get("closes") or []
            hist = a.get("macd_hist") or []
            obv = a.get("obv") or []
            vols = a.get("volumes") or []
            up, mid, lo = a.get("bb_up_last"), a.get("bb_mid_last"), a.get("bb_lo_last")
            c = float(closes[-1]) if closes else None
            d: dict = {
                "close": c,
                "rsi": a.get("rsi_now"),
                "rsi_prev": a.get("rsi_prev"),
                "cci": a.get("cci_now"),
                "cci_prev": a.get("cci_prev"),
                "bb_up": up, "bb_mid": mid, "bb_lo": lo,
            }
            # 밴드 내 위치: 0=하단 / 0.5=중단 / 1=상단. 밖이면 0 미만·1 초과.
            if c is not None and up is not None and lo is not None and up > lo:
                d["bb_pos"] = (c - float(lo)) / (float(up) - float(lo))
            if len(hist) >= 20:
                h20 = [float(x) for x in hist[-20:]]
                mx, mn = max(h20), min(h20)
                d["macd_hist"] = float(hist[-1])
                d["macd_hist_prev"] = float(hist[-2])
                d["macd_hist_max20"] = mx
                d["macd_hist_min20"] = mn
                # 사장님 "macd 막대 최고점 대비 조정 수치" — 1.0=최고점, 0.5=절반으로 축소
                if mx > 0:
                    d["macd_from_peak"] = float(hist[-1]) / mx
                if mn < 0:
                    d["macd_from_trough"] = float(hist[-1]) / mn
            if len(obv) >= 20 and len(vols) >= 20:
                # Fix 228: 공통 함수로 통일 (워커마다 산식이 갈리면 단위가 또 섞인다)
                from app.services.obv_metrics import obv_direction_ratio
                d["obv_dir_20"] = obv_direction_ratio(obv, vols)
                o20 = [float(x) for x in obv[-20:]]
                d["obv_is_max20"] = bool(o20[-1] >= max(o20))
                d["obv_is_min20"] = bool(o20[-1] <= min(o20))
            out[tf] = d
        except Exception as e:      # 한 심볼 실패가 전체 관찰을 막으면 안 된다
            logger.debug("[market_obs] %s %s 지표 수집 실패: %s", symbol, tf, e)
    return out


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
                        # Fix 226: 관찰 시점 지표 = 학습 표본의 X 값
                        "ind": _indicator_snapshot(bc, symbol),
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
                        # Fix 226: 관찰 시점 지표 = 학습 표본의 X 값
                        "ind": _indicator_snapshot(bc, symbol),
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
