"""📊 Fix 179 (2026-08-27): 급등락 심볼 「볼밴 이탈 분할 매수」 전략.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 verbatim (2026-08-27):
  "급등락중인 심볼을 모니터링하고 있는데 15분차트로 상승중인 심볼은 볼밴 하단
   이탈 하면 분할 매수 1-3번 정도 매수하고 긴상승에는 중단 이탈시 1-3번 분할
   매수하고 1-3번 매수 했는데 -5% 청산하고 tp1 익절도 5%부터 분할로 25%씩
   롱과숏을 이렇게 운영하는 시스템 ... 자금 100 200 300 이렇게 600으로 포지션
   운영하는 방식이야 익절 회기도 -3% 짧게"

사장님 선택 (2026-08-27):
  · 「긴 상승」 판정 = 가격이 4H 중단선 위(LONG)/아래(SHORT) **24시간 유지**
  · 2·3차 분할 = **더 깊은 이탈** (기준선 대비 -1%, -2%)
  · 기존 사다리(10/300/600 청산 후 대체)와 **병행** — 별도 전략으로 공존
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

■ 기존 사다리와 자본 모델이 **정반대**다 (그래서 별도 전략이다)

    사다리 (Fix 133/177) : 10 → 청산 → 300 → 청산 → 600   (한 번에 1개 포지션)
    이 전략             : 100 + 200 + 300 = 600 **동시 보유** (평단 형성)

  같은 워커/템플릿에 섞으면 -5% 의 의미가 달라져 사고가 난다.
  구분자 = `capital_management_mode = "split_entry"` (Fix 178 이 이 값을 읽는다).

■ 진입 규칙 (15m 기준선 이탈)

    ┌──────────────┬──────────────────────┬──────────────────────┐
    │ 추세 상태     │ LONG (상승 중 눌림)   │ SHORT (하락 중 반등)  │
    ├──────────────┼──────────────────────┼──────────────────────┤
    │ 일반          │ close < BB 하단       │ close > BB 상단       │
    │ 긴 추세       │ close < BB 중단       │ close > BB 중단       │
    └──────────────┴──────────────────────┴──────────────────────┘

    「긴 추세」= 4H 종가가 4H 중단선 위(LONG)/아래(SHORT)로 LONG_TREND_BARS(6봉=24h) 연속 유지.

    분할 차수 = 기준선을 **얼마나 더 벗어났는가**:
        1차 100 : 기준선 이탈 (0%)
        2차 200 : 기준선 대비 -1% (SHORT 는 +1%)
        3차 300 : 기준선 대비 -2% (SHORT 는 +2%)
    → 2·3차는 stage_plan.trigger_price 로 심어두고 **기존 stage_trigger_worker 가
      가격 트리거로 처리**한다. 새 진입 경로를 만들지 않는다 (헌법 6).

■ 청산 규칙

    손절   : 평단 ROI **-5%** → 전량 (1·2·3차 어느 시점이든. Fix 178 이 보장)
    익절   : TP1 **+5%** 부터 **25%씩 4회** = +5 / +10 / +15 / +20
    트레일링: 고점 대비 **-3%** 회귀 시 잔량 청산

■ 안전장치

    · 동시보유 상한(check_position_slot) 적용 — 기존 자동 진입과 예산을 공유한다
    · 같은 심볼/방향 활성 전략이 있으면 skip (중복 진입 금지)
    · API ban / 계정 없음 / 현재가 없음 = 진입 보류 (fail-SAFE)
    · 진입하지 못한 이유는 항상 집계해 로그로 남긴다 (헌법 80)
    · ⚠️ 이 전략은 **물타기**다. 방향이 틀리면 600 전부가 물린다.
      -5% 손절이 반드시 살아 있어야 하므로 force_sl_enabled_override=True 를 강제한다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate

logger = logging.getLogger(__name__)

__all__ = ["run_pump_split_entry_once"]

# ── 사장님 지정 파라미터 ────────────────────────────────────────────────
CAPITALS = [Decimal("100"), Decimal("200"), Decimal("300")]   # 총 600
SPLIT_STEP_PCT = [Decimal("0"), Decimal("1"), Decimal("2")]   # 기준선 대비 이탈 심도
FORCE_SL_ROI = Decimal("5")        # 평단 ROI -5% 전량 청산
TP_PERCENTS = [5, 10, 15, 20]      # +5% 부터
TP_QTY_RATIOS = [25, 25, 25, 25]   # 25% 씩
TRAILING_RETRACE_PCT = Decimal("3")  # 익절 회귀 -3% (짧게)
LEVERAGE = 2

# ── 대상 선정 ──────────────────────────────────────────────────────────
MIN_ABS_24H_CHANGE = 15.0   # 급등락 = |24h 변동| 이상
MAX_CANDIDATES = 40
LONG_TREND_TF = "4h"
LONG_TREND_BARS = 6         # 4H 6봉 = 24시간
KLINE_15M = 60

STRATEGY_TYPE = "pump_split"
MODE_MARKER = "split_entry"   # Fix 178 이 읽는 값


def _fmt(v) -> str:
    return f"{float(v):.6f}"


def _is_long_trend(a4: dict, side: str) -> tuple[bool, str]:
    """4H 종가가 4H 중단선 위(LONG)/아래(SHORT)로 LONG_TREND_BARS 연속 유지했는가.

    사장님 선택: 「긴 상승 = 가격이 4H 중단선 위 24시간 유지」
    ⚠️ analyze_timeframe 은 마지막 봉의 밴드값만 준다. 과거 봉마다의 중단선을
       다시 계산하는 대신, 20MA(=중단선) 를 직접 산출해 봉별로 비교한다.
    """
    closes = a4.get("closes") or []
    n = len(closes)
    if n < 20 + LONG_TREND_BARS:
        return False, f"4H 봉 부족({n})"
    ok = 0
    # i=1 이 마지막 봉. 각 봉의 20MA 는 **그 봉을 포함한** 직전 20봉 평균이다
    # (볼린저 중단선 정의와 동일). 음수 슬라이스는 i=1 에서 빈 배열이 되므로
    # 양수 인덱스로 계산한다.
    for i in range(1, LONG_TREND_BARS + 1):
        end = n - i + 1          # exclusive
        start = end - 20
        if start < 0:
            return False, "4H 20MA 창 부족"
        window = closes[start:end]
        mb = sum(float(x) for x in window) / 20.0
        c = float(closes[n - i])
        if (side == "LONG" and c > mb) or (side == "SHORT" and c < mb):
            ok += 1
        else:
            break
    return (ok >= LONG_TREND_BARS,
            f"4H 중단선 {'위' if side == 'LONG' else '아래'} 연속 {ok}/{LONG_TREND_BARS}봉")


def _entry_plan(a15: dict, side: str, long_trend: bool) -> tuple[Decimal | None, str]:
    """기준선(base)과 사유를 반환. 이탈 안 했으면 (None, 사유)."""
    up, mid, lo = a15.get("bb_up_last"), a15.get("bb_mid_last"), a15.get("bb_lo_last")
    closes = a15.get("closes") or []
    if not closes or up is None or mid is None or lo is None:
        return None, "15m 밴드/종가 없음"
    close = Decimal(str(closes[-1]))
    if side == "LONG":
        base = Decimal(str(mid)) if long_trend else Decimal(str(lo))
        label = "중단" if long_trend else "하단"
        if close >= base:
            return None, f"{label} 미이탈 (close {_fmt(close)} >= {label} {_fmt(base)})"
    else:
        base = Decimal(str(mid)) if long_trend else Decimal(str(up))
        label = "중단" if long_trend else "상단"
        if close <= base:
            return None, f"{label} 미이탈 (close {_fmt(close)} <= {label} {_fmt(base)})"
    return base, f"{label} 이탈 (close {_fmt(close)} / {label} {_fmt(base)})"


def _build_template(db, symbol: str, side: str, base: Decimal) -> StrategyTemplate:
    """100/200/300 3단계 + TP 25%×4 + 트레일링 -3% 템플릿."""
    now = datetime.now(timezone.utc)
    # 2·3차 트리거 = 기준선 대비 -1%, -2% (SHORT 는 반대)
    trig = [None, float(SPLIT_STEP_PCT[1]), float(SPLIT_STEP_PCT[2])]
    tpl = StrategyTemplate(
        name=f"PUMPSPLIT_{symbol}_{side}_{now.strftime('%Y%m%d_%H%M%S')}",
        strategy_type=STRATEGY_TYPE,
        side=side,
        leverage=LEVERAGE,
        total_capital=sum(CAPITALS),
        stages_config={
            "capitals": [float(c) for c in CAPITALS],
            "trigger_percents": trig,
            "stages_count": 3,
            "base_price": float(base),
            "split_entry": True,
        },
        stage1_capital=CAPITALS[0],
        stage2_capital=CAPITALS[1],
        stage3_capital=CAPITALS[2],
        stage4_capital=None,
        # 기준선 대비 이탈 심도 = 가격 트리거 % (stage_trigger_worker 가 처리)
        stage2_trigger_percent=SPLIT_STEP_PCT[1],
        stage3_trigger_percent=SPLIT_STEP_PCT[2],
        stage4_trigger_percent=None,
        tp1_percent=Decimal(str(TP_PERCENTS[0])),
        tp2_percent=Decimal(str(TP_PERCENTS[1])),
        tp3_percent=Decimal(str(TP_PERCENTS[2])),
        tp4_percent=Decimal(str(TP_PERCENTS[3])),
        tp1_qty_ratio=Decimal(str(TP_QTY_RATIOS[0])),
        tp2_qty_ratio=Decimal(str(TP_QTY_RATIOS[1])),
        tp3_qty_ratio=Decimal(str(TP_QTY_RATIOS[2])),
        tp4_qty_ratio=Decimal(str(TP_QTY_RATIOS[3])),
        stop_loss_percent_of_capital=Decimal("90"),
        is_active=True,
    )
    db.add(tpl)
    db.flush()
    return tpl


def run_pump_split_entry_once() -> dict:
    """15분 주기. 급등락 심볼의 볼밴 이탈에 100/200/300 분할 진입."""
    db = SessionLocal()
    stat: dict = {"scanned": 0, "entered": 0, "skipped": {}}

    def _skip(why: str) -> None:
        stat["skipped"][why] = stat["skipped"].get(why, 0) + 1

    try:
        # ⚠️ 기본 OFF. 새로 돈을 넣는 전략이므로 사장님이 **명시적으로 켜야** 돈다.
        #   심볼당 600 USDT × 후보 다수 = 노출이 순식간에 커질 수 있다.
        #   켜기: SystemSetting `pump_split_enabled` = "1"
        from app.models.system_setting import SystemSetting
        _sw = db.get(SystemSetting, "pump_split_enabled")
        if _sw is None or str(_sw.value).strip() != "1":
            logger.info(
                "[pump_split] ⏹️ OFF (pump_split_enabled != 1) — 켜려면 이 설정을 1 로",
            )
            return {"note": "OFF (기본값)", **stat}

        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            logger.warning("[pump_split] mainnet 계정 없음")
            return stat

        from app.core.api_backoff import is_account_banned
        if is_account_banned(account.id):
            logger.info("[pump_split] API ban 중 = skip")
            return stat

        from app.core.crypto import decrypt_text
        from app.integrations.binance.client import BinanceClient
        from app.services.chart_analyzer import ChartAnalyzer
        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )

        # 1) 급등락 후보 (24h 변동 절대값 기준)
        tickers = bc.get_24hr_ticker()
        if isinstance(tickers, dict):
            tickers = [tickers]
        cands = []
        for t in (tickers or []):
            sym = t.get("symbol") or ""
            if not sym.endswith("USDT"):
                continue
            try:
                chg = float(t.get("priceChangePercent") or 0)
            except Exception:
                continue
            if abs(chg) >= MIN_ABS_24H_CHANGE:
                cands.append((sym, chg))
        cands.sort(key=lambda x: -abs(x[1]))
        cands = cands[:MAX_CANDIDATES]
        stat["scanned"] = len(cands)
        if not cands:
            logger.info("[pump_split] 급등락 후보 0건 (|24h| >= %.0f%%)", MIN_ABS_24H_CHANGE)
            return stat

        # 2) 활성 심볼 (중복 진입 금지)
        active = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.status.in_(list(ACTIVE_LIKE)))
            .where(StrategyInstance.is_archived.is_(False))
        ).scalars().all()
        active_keys = {(s.symbol, s.side) for s in active}

        from app.services.position_limit import check_position_slot
        from app.services.strategy_service import StrategyService

        for sym, chg in cands:
            # 방향 = 급등이면 LONG(눌림목 매수) / 급락이면 SHORT(반등 매도)
            side = "LONG" if chg > 0 else "SHORT"
            if (sym, side) in active_keys:
                _skip("already_active")
                continue

            # 상한은 **진입 직전마다** 재확인 (헌법 119)
            try:
                slot_ok, slot_why, _a, _c = check_position_slot(db, "pump_split")
            except Exception as e:
                logger.error("[pump_split] 상한 검사 실패 → 보류: %s", e)
                _skip("slot_error")
                break
            if not slot_ok:
                logger.info("[pump_split] SKIP: %s", slot_why)
                _skip("slot_full")
                break

            try:
                a15 = ChartAnalyzer.analyze_timeframe(bc, sym, "15m", limit=KLINE_15M)
                a4 = ChartAnalyzer.analyze_timeframe(bc, sym, LONG_TREND_TF, limit=40)
            except Exception as e:
                logger.warning("[pump_split] %s 분석 실패: %s", sym, e)
                _skip("analyze_error")
                continue
            if not a15 or not a4:
                _skip("no_analysis")
                continue

            long_trend, trend_why = _is_long_trend(a4, side)
            base, why = _entry_plan(a15, side, long_trend)
            if base is None:
                _skip("no_break")
                continue

            logger.info(
                "[pump_split] 🎯 %s %s 24h=%+.1f%% | %s | %s | 기준선=%s",
                sym, side, chg, trend_why, why, _fmt(base),
            )

            # 3) 전략 생성 — 1차는 MARKET 즉시, 2·3차는 가격 트리거로 대기
            try:
                tpl = _build_template(db, sym, side, base)
                strategy = StrategyService(db).create_strategy_instance(
                    user_id=1,
                    exchange_account_id=account.id,
                    strategy_template_id=tpl.id,
                    symbol=sym,
                    side=side,
                    start_price=base,             # 기준선 = 트리거 계산 기준
                    leverage_override=LEVERAGE,
                    capital_management_mode=MODE_MARKER,   # Fix 178 마커
                )
                # -5% 전량 손절 강제 + 트레일링 -3%
                strategy.force_sl_enabled_override = True
                strategy.force_sl_roi_override = FORCE_SL_ROI
                strategy.trailing_retrace_pct = TRAILING_RETRACE_PCT
                db.commit()

                # 1차 = MARKET 즉시 진입 (지정가로 걸어두면 미체결 위험)
                from app.models.strategy_stage_plan import StrategyStagePlan
                s1 = db.execute(
                    select(StrategyStagePlan)
                    .where(StrategyStagePlan.strategy_instance_id == strategy.id)
                    .where(StrategyStagePlan.stage_no == 1)
                ).scalar_one_or_none()
                if s1 is not None:
                    s1.trigger_price = None
                    db.commit()

                from app.services.execution_service import ExecutionService
                ExecutionService(
                    db,
                    api_key=decrypt_text(account.api_key_enc),
                    api_secret=decrypt_text(account.api_secret_enc),
                    is_testnet=account.is_testnet,
                ).start_stage1(strategy.id)

                active_keys.add((sym, side))
                stat["entered"] += 1
                logger.warning(
                    "[pump_split] ✅ 진입! #%s %s %s 1차 %s USDT "
                    "(2차 %s@-%s%% / 3차 %s@-%s%%) SL -%s%% TP %s%% 25%%×4 트레일 -%s%%",
                    strategy.id, sym, side, CAPITALS[0], CAPITALS[1], SPLIT_STEP_PCT[1],
                    CAPITALS[2], SPLIT_STEP_PCT[2], FORCE_SL_ROI, TP_PERCENTS[0],
                    TRAILING_RETRACE_PCT,
                )
            except Exception as e:
                db.rollback()
                logger.error("[pump_split] ❌ %s %s 진입 실패: %s", sym, side, e)
                _skip("create_failed")

        logger.info(
            "[pump_split] 완료: 후보=%d 진입=%d 사유=%s",
            stat["scanned"], stat["entered"], stat["skipped"],
        )
        return stat
    except Exception as e:
        logger.exception("[pump_split] 실패: %s", e)
        return stat
    finally:
        db.close()
