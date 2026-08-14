"""🎓 LearningSyncWorker = 매 5분 자동 학습 저장! (v134 사장님!)

배경 (사장님 요청 2026-08-13):
"모든 거래 학습해서 저장하고 [...] 자동화했을때도 항상 진행과정과
 종료된거래를 학습해서 다음에 더 잘 활용할수 있게 저장해줘"

로직:
- 활성 전략 조회!
- record 없으면 = on_entry (진입!)
- record 있고 OPEN = snapshot (진행!)
- STOPPED = on_exit (종료 인사이트!)

= 실시간 훅 없이도 = 자동 커버!

v137/v138 (2026-08-14 사장님 「학습 자료와 같이 활용」):
- on_entry 시 = 📐 EMA/VCP + ☁️ SAR/구름대 셋업 등급 + 🤝 합의를 entry_context에 저장!
  (기존엔 entry_context = {} 빈 값 = 진입 당시 차트 상태가 안 남았음!)
- 이 등급이 나중에 /trade-learning/setup-stats = 「등급별·합의별 실제 승률」이 됨!
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_text
from app.core.database import SessionLocal
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.trade_learning_record import TradeLearningRecord
from app.services import strategy_confluence
from app.services.bb_4h_band_analyzer import BB4HBandAnalyzer
from app.services.bb_4h_band_analyzer import to_learning_context as bb4h_context
from app.services.bb_top_analyzer import BBTopAnalyzer
from app.services.bb_top_analyzer import to_learning_context as bb_top_context
from app.services.ema_vcp_analyzer import EMAVCPAnalyzer
from app.services.ema_vcp_analyzer import to_learning_context as ema_vcp_context
from app.services.pump_continuation_analyzer import PumpContinuationAnalyzer
from app.services.pump_continuation_analyzer import to_learning_context as pump_cont_context
from app.services.pump_dump_live_analyzer import PumpDumpLiveAnalyzer
from app.services.pump_dump_live_analyzer import to_learning_context as pump_context
from app.services.sar_ichimoku_analyzer import SARIchimokuAnalyzer
from app.services.sar_ichimoku_analyzer import to_learning_context as sar_context
from app.services.trade_learning_service import TradeLearningService

logger = logging.getLogger(__name__)


# 종료된지 24시간 이내 = on_exit 대상!
CLOSED_LOOKBACK_HOURS = 24


def _make_client(db: Session) -> BinanceClient | None:
    """mainnet Binance client (실패 = None = 학습 저장만 계속!)."""
    try:
        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            return None
        return BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )
    except Exception as e:
        logger.warning("[learning_sync] Binance client 생성 실패: %s", e)
        return None


def _entry_context(client: BinanceClient | None, strategy: StrategyInstance) -> dict:
    """진입 시 차트 상태 스냅샷 (v138: 2대 전략 등급 + 합의!).

    4h/1h/15m 캔들을 **1회만 조회해서 두 분석기가 공유** = Binance 호출 절감!
    실패해도 학습 저장 자체는 계속 = fail-safe (빈 dict 반환!).
    """
    if client is None:
        return {}
    try:
        symbol, side = strategy.symbol, strategy.side
        klines = {}
        # v140: 15m은 200봉 필요 (BB20 + MACD26 + 다이버전스 20)
        for iv, lim in (("4h", 120), ("1h", 120), ("15m", BBTopAnalyzer.KLINE_LIMIT),
                        ("5m", PumpDumpLiveAnalyzer.KLINE_LIMIT)):
            try:
                kl = client.get_klines(symbol=symbol, interval=iv, limit=lim)
                klines[iv] = kl if isinstance(kl, list) else None
            except Exception:
                klines[iv] = None

        ema = EMAVCPAnalyzer(client).analyze(
            symbol, side,
            klines_4h=klines["4h"], klines_1h=klines["1h"], klines_15m=klines["15m"],
        )
        sar = SARIchimokuAnalyzer(client).analyze(
            symbol, side,
            klines_4h=klines["4h"], klines_1h=klines["1h"], klines_15m=klines["15m"],
        )
        conf = strategy_confluence.evaluate(ema, sar, side)
        # v140: 15m 천장/바닥 = 사장님 주력 전략!
        bb_top = BBTopAnalyzer(client).analyze(
            symbol, side,
            klines_15m=klines["15m"], klines_1h=klines["1h"], klines_4h=klines["4h"],
        )
        # v141: 급등락 실시간 상태 (진입 당시 급등 중이었나?)
        pump = PumpDumpLiveAnalyzer(client).analyze(
            symbol, klines_5m=klines["5m"], klines_15m=klines["15m"],
        )
        return {
            "ema_vcp": ema_vcp_context(ema),
            "sar_ichimoku": sar_context(sar),
            "confluence": strategy_confluence.to_learning_context(conf),
            "bb_top": bb_top_context(bb_top),
            "pump_dump": pump_context(pump),
            "pump_continuation": pump_cont_context(
                PumpContinuationAnalyzer(client).analyze(symbol, klines_5m=klines["5m"])
            ),
            "bb_4h": bb4h_context(
                BB4HBandAnalyzer(client).analyze(symbol, side, klines_4h=klines["4h"])
            ),
        }
    except Exception as e:
        logger.warning(
            "[learning_sync] 셋업 스냅샷 실패 sid=%s: %s", strategy.id, e,
        )
        return {}


def run_learning_sync() -> dict:
    """5분마다 실행 = 학습 자동 sync!"""
    db: Session = SessionLocal()
    entered = 0
    snapped = 0
    closed = 0
    failed = 0   # v139: 실패 건수 = 더 이상 숨기지 않음!
    try:
        tls = TradeLearningService(db)
        client = _make_client(db)  # v137/v138! 셋업 등급 + 합의 저장용!

        # 1. 활성 전략 = on_entry or snapshot!
        open_statuses = [
            "STAGE_1_OPEN", "STAGE_2_OPEN", "STAGE_3_OPEN",
            "STAGE_4_OPEN", "STAGE_5_OPEN", "STAGE_6_OPEN",
            "STAGE_7_OPEN", "STAGE_8_OPEN", "STAGE_9_OPEN",
            "STAGE_10_OPEN",
        ]
        active_strategies = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.status.in_(open_statuses))
            .where(StrategyInstance.current_position_qty != 0)
        ).scalars().all()

        for s in active_strategies:
            try:
                # record 존재 여부!
                record = db.execute(
                    select(TradeLearningRecord)
                    .where(TradeLearningRecord.strategy_instance_id == s.id)
                ).scalar_one_or_none()

                if record is None:
                    # 신규 = on_entry! (v137/v138: 진입 당시 2대 전략 등급 + 합의 저장!)
                    # v139: 성공한 것만 카운트! (기존엔 실패해도 세서 로그가 거짓말했음!)
                    if tls.on_entry(s, market_context=_entry_context(client, s)):
                        entered += 1
                    else:
                        failed += 1
                elif record.status == "OPEN":
                    # 진행 중 = snapshot!
                    if tls.snapshot(s):
                        snapped += 1
                    else:
                        failed += 1
            except Exception as e:
                logger.warning("[learning_sync] entry/snapshot 실패 sid=%d: %s", s.id, e)

        db.commit()

        # 2. 최근 STOPPED 전략 = on_exit (누락 방지!)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=CLOSED_LOOKBACK_HOURS)
        stopped = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.status == "STOPPED")
            .where(StrategyInstance.stopped_at >= cutoff)
        ).scalars().all()

        for s in stopped:
            try:
                record = db.execute(
                    select(TradeLearningRecord)
                    .where(TradeLearningRecord.strategy_instance_id == s.id)
                ).scalar_one_or_none()

                if record is None:
                    # 신규 = 진입 + 종료 동시!
                    # v137: 여긴 EMA/VCP 스냅샷 X!
                    #   = 이미 끝난 거래 = 지금 차트는 「진입 당시」가 아님!
                    #   = 가짜 셋업 등급이 승률 통계를 오염시킴 = 금지!
                    tls.on_entry(s)
                    ok = tls.on_exit(s, close_reason=getattr(s, "close_reason", None))
                elif record.status == "OPEN":
                    # 진행 중 → 종료 mark!
                    ok = tls.on_exit(s, close_reason=getattr(s, "close_reason", None))
                else:
                    continue  # 이미 CLOSED = 할 일 없음!

                # v139: 실제 성공한 것만 카운트!
                if ok:
                    closed += 1
                else:
                    failed += 1
            except Exception as e:
                logger.warning("[learning_sync] exit 실패 sid=%d: %s", s.id, e)
                failed += 1

        db.commit()

        # v139: 실패가 있으면 error 로 올려서 절대 못 놓치게! (헌법 3번)
        if failed:
            logger.error(
                "[learning_sync] ⚠️ 학습 저장 실패 %d건! (entered=%d snapped=%d closed=%d) "
                "= 학습 데이터가 쌓이지 않고 있습니다!",
                failed, entered, snapped, closed,
            )
        else:
            logger.info(
                "[learning_sync] 완료: entered=%d snapped=%d closed=%d",
                entered, snapped, closed,
            )
        return {"entered": entered, "snapped": snapped, "closed": closed, "failed": failed}
    except Exception as e:
        logger.warning("[learning_sync] 실행 실패: %s", e)
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()
