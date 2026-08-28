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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_text
from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_WITH_POSITION, TERMINAL_STATUSES
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
from app.services.trade_learning_service import TradeLearningService, resolve_close_reason

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
        # 🚨 Fix 197 (2026-08-28): 여기가 **오타 하나로 5개월간 죽어 있었다.**
        #   `STAGE_1_OPEN`(언더스코어)로 적혀 있는데 실제 저장값은 `STAGE1_OPEN` 이다
        #   (strategy_status.py / stream_service / execution_service 가 f"STAGE{n}_OPEN" 로 만든다).
        #   → active_strategies 가 **항상 빈 리스트** → _entry_context() 가 한 번도 실행된 적 없음
        #   → entry_context 전건 `{}` → 「진입 당시 지표가 무엇이었나」가 통째로 비어 있다.
        #   같은 오타를 strategy_suggestions.py 는 주석으로 지적해 뒀는데 여기만 안 고쳤다.
        #   → 하드코딩 대신 상수에서 유도한다 (또 어긋나지 않게, 헌법 101).
        open_statuses = sorted(
            st for st in ACTIVE_WITH_POSITION
            if st.startswith("STAGE") or st.startswith("TP") or st == "TRAILING_ARMED"
        )
        active_strategies = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.status.in_(open_statuses))
            .where(StrategyInstance.current_position_qty != 0)
        ).scalars().all()

        # 🚨 진입 스냅샷은 「방금 진입한 건」에만 붙인다.
        #   이미 열려 있던 backlog 에 「지금 차트」를 붙이면 아래 :199-201 이 스스로
        #   금지한 「가짜 셋업 등급」이 승률 통계를 오염시킨다. 배포 직후가 특히 위험하다.
        fresh_cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)

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
                    # Fix 197: 방금 진입한 건에만 「지금 차트」를 붙인다 (backlog 오염 방지)
                    _created = getattr(s, "created_at", None)
                    _fresh = bool(
                        _created and _created >= fresh_cutoff
                        and str(s.status or "").startswith("STAGE")
                    )
                    if tls.on_entry(s, market_context=_entry_context(client, s) if _fresh else {}):
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

        # 2. 최근 종료 전략 = on_exit
        # 🚨 Fix 197: 옛 조건은 `status == "STOPPED"` **단일 문자열** AND `stopped_at >= cutoff` 였다.
        #   그런데 익절 완주는 COMPLETED 이고 (tp_sl_orchestrator), 그 경로는 stopped_at 을
        #   **채우지 않는다**. → 이긴 거래가 **두 번** 걸러졌다
        #   (실측: COMPLETED SHORT 163건 +17,294 / LONG 71건 +6,008 이 전부 누락).
        #   = TradeLearningRecord 가 사실상 **패배 거래 전용 데이터셋**이었다.
        #   「LONG 이 왜 실패하는가」는 성공군과 대조해야 답이 나오는데 대조군이 없었다.
        #   → 종료 상태 전체 + 종료 시각은 coalesce(stopped_at, updated_at) 로 보정.
        #     stopped_at 을 **새로 채우지 않는** 방식이라 재진입 게이트는 1비트도 안 바뀐다
        #     (그 컬럼은 realtime_reentry/auto_reentry/ladder_restart 의 진입 조건이다).
        cutoff = datetime.now(timezone.utc) - timedelta(hours=CLOSED_LOOKBACK_HOURS)
        _closed_at = func.coalesce(StrategyInstance.stopped_at, StrategyInstance.updated_at)
        stopped = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.status.in_(sorted(TERMINAL_STATUSES)))
            .where(_closed_at >= cutoff)
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
                    # Fix 197: StrategyInstance 에 close_reason 컬럼이 없다 → RiskEvent 로 유도
                    ok = tls.on_exit(s, close_reason=resolve_close_reason(db, s))
                elif record.status == "OPEN":
                    # 진행 중 → 종료 mark!
                    ok = tls.on_exit(s, close_reason=resolve_close_reason(db, s))
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
