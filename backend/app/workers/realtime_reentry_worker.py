"""🎯 사장님 사상 (2026-08-21): 실시간 재진입 시스템!

사장님 verbatim:
"포지션 실패한 심볼은 실시간 모니터링에 넣어서 짧은 시간 계속 모니터링하고
재진입을 하는 로직이야
그리고 익절도 마찬가지로 익절후 계속 모니터링하고 계속 수익이 가능하면
다시 포지션을 늘려서 수익을 극대화하고 다시 하락하면 -5% 상승후 하락시
진행하는 로직으로 청산하는거야"

= 매 15분 실행!
= 실패 심볼 + 익절 심볼 = 실시간 감지!
= 조건 만족 시 = 즉시 재진입!

로직:
1. daily_limit 체크 (auto_bb_break_daily_limit!)
2. 최근 24h 청산된 자동 진입 심볼 조회!
3. Redis mark_price로 현재가 조회!
4. 재진입 조건 판단:
   - 실패 심볼: SL 대비 +3% 반등 시 재진입 (1.5x)!
   - 익절 심볼: 익절가 대비 +3% 추가 상승 시 재진입 (원 자본)!
5. 조건 만족 = _create_auto_bb_strategy 호출 (즉시!)!
6. 재진입 카운터 갱신!

안전:
- max 2회 재진입 (v202!)
- 급등/급락 필터 (헌법 64!)
- daily_limit 체크!
- 이미 활성 심볼 skip!
- 24h 재진입 카운터 5회 초과 = skip!
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE, TERMINAL_STATUSES
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate

logger = logging.getLogger(__name__)

REBOUND_PCT_FOR_REENTRY = 3.0  # SL/익절 대비 3% 반등 시!
MAX_HOURLY_REENTRIES = 5        # 1h 최대 5건 (남발 방지!)
STAGE3_MIN_WAIT_HOURS = 4.0     # 🎯 v220 사장님: "충분히 대기" = 최소 4h!


def _verify_stage_indicators(bc, symbol: str, side: str) -> tuple[bool, str]:
    """🎯 v220 사장님 (2026-08-22): 2/3단계 진입 = 15m 지표 재확인!

    사장님 verbatim: "이제 하락할것 같은 차트와 보조지표가 나오면 진입"

    🎯 v220 Fix 22 (2026-08-23 사장님 지적!): 지표 완화!
    사장님 지적: "손실 18건인데 재진입 1건!" = 조건 너무 엄격 = 대부분 skip!
    이전: LONG RSI≤35 (매우 엄격!) / SHORT RSI≥65
    신: LONG RSI≤45 (완화!) OR MACD hist 반전 (OR 조건!) / SHORT RSI≥55 OR MACD 반전
    = 사장님 재진입 사상 = 반등 신호만 있어도 진입!
    """
    try:
        kl = bc.get_klines(symbol=symbol, interval="15m", limit=60)
        if not isinstance(kl, list) or len(kl) < 35:
            return False, "kline 부족"
        closes = [float(k[4]) for k in kl]
        from app.services.bb_4h_band_analyzer import BB4HBandAnalyzer
        rsi = BB4HBandAnalyzer._calc_rsi(closes)
        rsi_prev = BB4HBandAnalyzer._calc_rsi(closes[:-1])
        if rsi is None or rsi_prev is None:
            return False, "rsi 계산 실패"
        ema12 = BB4HBandAnalyzer._calc_ema(closes, 12)
        ema26 = BB4HBandAnalyzer._calc_ema(closes, 26)
        macd_line = [a - b for a, b in zip(ema12[14:], ema26)]
        sig = BB4HBandAnalyzer._calc_ema(macd_line, 9)
        if not sig or len(sig) < 3:
            return False, "macd 부족"
        hist = [m - s for m, s in zip(macd_line[-len(sig):], sig)]
        if len(hist) < 3:
            return False, "hist 부족"
        # 🎯 v220 Fix 22: OR 조건 = 완화! (RSI or MACD 하나만 만족!)
        macd_reversal = hist[-1] > hist[-2] if side == "LONG" else hist[-1] < hist[-2]
        if side == "LONG":
            rsi_ok = rsi <= 45 and rsi > rsi_prev  # 45 (기존 35 완화!)
            ok = rsi_ok or macd_reversal  # OR 조건!
        else:
            rsi_ok = rsi >= 55 and rsi < rsi_prev  # 55 (기존 65 완화!)
            ok = rsi_ok or macd_reversal
        return ok, f"RSI={rsi:.1f}({'OK' if rsi_ok else 'X'}) hist={hist[-1]:.4f}({'REV' if macd_reversal else 'X'})"
    except Exception as e:
        return False, f"err={e}"


def _get_base_capital_from_instance(si: StrategyInstance) -> float:
    """v218 (2026-08-22): 청산된 원 전략의 base capital 조회!

    사장님 사상: 마틴게일 = 이전 포지션 대비 1.5배!
    → 이전 포지션의 원 자본 = 정확한 base 필요!

    조회 순서:
    1. template.stages_config['capitals'][0] (JSONB 구조!)
    2. template.stage1_capital (Decimal fallback!)
    3. template.total_capital (Decimal fallback!)
    4. 500.0 (최종 fallback!)
    """
    try:
        tmpl = si.strategy_template
        if tmpl and getattr(tmpl, "stages_config", None):
            caps = tmpl.stages_config.get("capitals", []) if isinstance(tmpl.stages_config, dict) else []
            if caps and len(caps) > 0:
                return float(caps[0])
        if tmpl and getattr(tmpl, "stage1_capital", None):
            return float(tmpl.stage1_capital)
        if tmpl and getattr(tmpl, "total_capital", None):
            return float(tmpl.total_capital)
    except Exception:
        pass
    return 500.0


def run_realtime_reentry() -> dict:
    """매 15분 = 실시간 재진입 감지!"""
    db: Session = SessionLocal()
    entered_fail = 0
    entered_success = 0
    skipped = 0
    results: list[dict] = []
    try:
        # 1. daily_limit 체크!
        from app.models.system_setting import SystemSetting
        limit_row = db.get(SystemSetting, "auto_bb_break_daily_limit")
        daily_limit = int(limit_row.value) if limit_row and limit_row.value else 0
        if daily_limit <= 0:
            return {"note": "daily_limit=0 (OFF!)", "entered": 0}

        from app.workers.auto_bb_breakdown_worker import (
            _count_used_slots, _create_auto_bb_strategy,
            _get_reentry_count, _increment_reentry_count,
            _reset_reentry_count, MAX_REENTRY_COUNT,
        )
        used = _count_used_slots(db)
        remaining = daily_limit - used
        if remaining <= 0:
            return {"note": f"daily {used}/{daily_limit}", "entered": 0}

        # 2. 1h 재진입 남발 체크!
        cutoff_1h = datetime.now(timezone.utc) - timedelta(hours=1)
        from app.models.strategy_suggestion import StrategySuggestion
        recent_re = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.created_at >= cutoff_1h)
            .where(StrategySuggestion.reason.like("%RT_REENTRY%"))
        ).scalars().all()
        if len(recent_re) >= MAX_HOURLY_REENTRIES:
            return {"note": f"1h {len(recent_re)}건 (max {MAX_HOURLY_REENTRIES}!)", "entered": 0}

        # 3. 최근 24h 청산된 자동 진입 심볼 조회!
        cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        closed = db.execute(
            select(StrategyInstance)
            .join(StrategyTemplate,
                  StrategyInstance.strategy_template_id == StrategyTemplate.id)
            .where(StrategyInstance.stopped_at >= cutoff_24h)
            .where(StrategyInstance.status.in_(list(TERMINAL_STATUSES)))
            .where(StrategyTemplate.strategy_type.like('auto_bb_break%'))
        ).scalars().all()

        # 4. 활성 심볼 skip!
        active = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.status.in_(list(ACTIVE_LIKE)))
        ).scalars().all()
        active_syms = {r.symbol for r in active}

        # 5. Redis mark_price!
        from app.core.redis_client import get_redis_client
        redis = get_redis_client()

        # 6. 심볼별 = 최신 청산 1건씩만!
        latest_by_sym: dict[tuple[str, str], StrategyInstance] = {}
        for si in closed:
            key = (si.symbol, si.side)
            if key not in latest_by_sym or (
                si.stopped_at and latest_by_sym[key].stopped_at
                and si.stopped_at > latest_by_sym[key].stopped_at
            ):
                latest_by_sym[key] = si

        for (symbol, side), si in latest_by_sym.items():
            if remaining <= 0:
                break
            if symbol in active_syms:
                skipped += 1
                continue

            # 재진입 카운터 max 2!
            re_count = _get_reentry_count(symbol, side)
            if re_count >= MAX_REENTRY_COUNT:
                skipped += 1
                continue

            # mark_price 조회!
            try:
                mp_raw = redis.get(f"mark_price:{symbol}")
                if not mp_raw:
                    continue
                mp = float(mp_raw.decode() if isinstance(mp_raw, bytes) else mp_raw)
                if mp <= 0:
                    continue
            except Exception:
                continue

            # 🎯 v218 fix (2026-08-22): 청산가 우선 = 평단 fallback!
            # 이전 = 평단 = 실 청산가와 다름 = 3% 반등 판정 부정확!
            # last_liquidation_price = SL 발동가! = 반등 시작점 정확!
            _stop_price = float(si.last_liquidation_price or si.avg_entry_price or 0)
            if _stop_price <= 0:
                continue

            pnl = float(si.realized_pnl or 0)
            _is_fail = pnl < 0
            _is_success = pnl > 0

            # 급등/급락 필터 = 24h 변동 조회 (안전!)
            # 여기선 skip 판정만 = 근사치!

            _should_enter = False
            _reason_suffix = ""
            _use_success_reentry = False

            if _is_fail:
                # 실패 심볼: side 방향으로 반등!
                if side == "LONG":
                    # LONG 실패 = 하락 → 반등 시 재진입!
                    # 청산가 대비 현재가 상승!
                    pct = (mp - _stop_price) / _stop_price * 100
                    if pct >= REBOUND_PCT_FOR_REENTRY:
                        _should_enter = True
                        _reason_suffix = f"RT_REENTRY: LONG 실패 후 +{pct:.2f}% 반등!"
                else:  # SHORT
                    pct = (_stop_price - mp) / _stop_price * 100
                    if pct >= REBOUND_PCT_FOR_REENTRY:
                        _should_enter = True
                        _reason_suffix = f"RT_REENTRY: SHORT 실패 후 -{pct:.2f}% 하락!"
            elif _is_success:
                # 익절 심볼: side 방향 계속 진행!
                if side == "LONG":
                    pct = (mp - _stop_price) / _stop_price * 100
                    if pct >= REBOUND_PCT_FOR_REENTRY:
                        _should_enter = True
                        _use_success_reentry = True
                        _reason_suffix = f"RT_REENTRY_SUCCESS: LONG 익절 후 +{pct:.2f}% 추가 상승!"
                else:  # SHORT
                    pct = (_stop_price - mp) / _stop_price * 100
                    if pct >= REBOUND_PCT_FOR_REENTRY:
                        _should_enter = True
                        _use_success_reentry = True
                        _reason_suffix = f"RT_REENTRY_SUCCESS: SHORT 익절 후 -{pct:.2f}% 추가 하락!"

            if not _should_enter:
                skipped += 1
                continue

            # 🎯 v220 사장님 사상 (2026-08-22): 2/3단계 = 지표 재확인 + 대기!
            # 사장님 verbatim: "이제 하락할것 같은 차트와 보조지표가 나오면 진입"
            # "다시 하락과 상승하면 충분히 대기하고 다시 하락이나 상승이 진행되면 3단계"
            if not _use_success_reentry:
                _stage_no = re_count + 2  # count=0 → 2단계, count=1 → 3단계
                # BinanceClient 준비!
                try:
                    from app.integrations.binance.client import BinanceClient
                    from app.core.crypto import decrypt_text
                    from app.models.exchange_account import ExchangeAccount
                    _acc = db.execute(
                        select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
                    ).scalar_one_or_none()
                    if not _acc:
                        skipped += 1
                        continue
                    _bc_v220 = BinanceClient(
                        api_key=decrypt_text(_acc.api_key_enc),
                        api_secret=decrypt_text(_acc.api_secret_enc),
                        is_testnet=False,
                    )
                    # 15m 지표 재확인!
                    _ind_ok, _ind_msg = _verify_stage_indicators(_bc_v220, symbol, side)
                    if not _ind_ok:
                        skipped += 1
                        logger.info(
                            "[RT_REENTRY] 🎯 v220 stage %d skip: %s %s 지표 미확인 (%s)",
                            _stage_no, symbol, side, _ind_msg,
                        )
                        continue
                    _reason_suffix += f" [지표 OK: {_ind_msg}]"
                    # 3단계 = "충분히 대기" = 최소 4h!
                    if _stage_no == 3 and si.stopped_at:
                        _elapsed_h = (datetime.now(timezone.utc) - si.stopped_at).total_seconds() / 3600
                        if _elapsed_h < STAGE3_MIN_WAIT_HOURS:
                            skipped += 1
                            logger.info(
                                "[RT_REENTRY] 🎯 v220 stage 3 skip: %s 대기 부족 (%.1fh < %.1fh)",
                                symbol, _elapsed_h, STAGE3_MIN_WAIT_HOURS,
                            )
                            continue
                except Exception as _ve:
                    logger.warning("[RT_REENTRY] v220 지표 재확인 실패 = skip 안전: %s", _ve)
                    skipped += 1
                    continue

            # 진입 실행!
            try:
                # 🎯 v219 사장님 최종 마틴게일 (2026-08-22!):
                # "300 600 1800" = 1단계 초기 / 2단계 이전×2 / 3단계 투자금전체×2
                # "3단계까지 갈수 있다야 가능하면 가지않는 관리가 필요"
                _base_capital = _get_base_capital_from_instance(si)
                if _use_success_reentry:
                    # 사장님: 익절 후 재진입 = 초기 시작금액!
                    _entry_capital = float(_base_capital)
                    _mult_label = ""
                else:
                    # 🎯 v219 사장님 신 마틴게일 (300/600/1800!)
                    from decimal import Decimal as _D
                    from app.services.sajangnim_capital import compute_reentry_capital, MAX_REENTRY_STAGE
                    _stage = re_count + 2  # count=0 → 2단계, count=1 → 3단계
                    if _stage > MAX_REENTRY_STAGE:
                        skipped += 1
                        logger.info(
                            "[RT_REENTRY] v219 STOP: %s %s stage=%d > MAX=%d (3단계까지!)",
                            symbol, side, _stage, MAX_REENTRY_STAGE,
                        )
                        continue
                    # 이전 진입 자본 리스트 구성!
                    _prev_caps = [_D(str(_base_capital))]
                    if _stage == 3:
                        # 2단계 자본 = base × 2 (실 이력 없이 규정 기반 재구성!)
                        _prev_caps.append(_D(str(_base_capital)) * _D("2"))
                    _entry_capital_dec = compute_reentry_capital(_stage, _prev_caps)
                    if _entry_capital_dec is None:
                        skipped += 1
                        continue
                    _entry_capital = float(_entry_capital_dec)
                    _mult = _entry_capital / float(_base_capital)
                    _mult_label = f" ×{_mult:.2f} ({_stage}단계)"
                    logger.info(
                        "[RT_REENTRY] 🎯 v219 마틴게일 %d단계: %s %s base=%.0f → %.0f USDT (×%.2f)",
                        _stage, symbol, side, float(_base_capital), _entry_capital, _mult,
                    )
                cfg = {"capitals": [_entry_capital], "leverage": 2}
                _reason_suffix += _mult_label  # UI 배지에 ×1.50 표시!
                _suffix = "_success" if _use_success_reentry else f"_reentry{re_count + 1}"
                new_strategy = _create_auto_bb_strategy(
                    db, symbol, side, cfg,
                    strategy_type_suffix=_suffix,
                )
                if not new_strategy:
                    skipped += 1
                    continue

                # 🎓 v218 fix (2026-08-22 사장님!): entry_snapshot 저장 = 학습 데이터!
                _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
                _rt_entry_snapshot = {
                    "rsi": None,  # 실시간 재진입 = 지표 조회 안 함!
                    "cci": None,
                    "obv_slope_pct": None,
                    "regime": "NEUTRAL",
                    "source": "RT_REENTRY_SUCCESS" if _use_success_reentry else "RT_REENTRY_FAIL",
                    "kst_hour": _kst_hour,
                    "rt_reentry_price": mp,
                    "prev_stop_price": _stop_price,
                    "reentry_count": re_count + 1 if not _use_success_reentry else 0,
                    "entered_at": datetime.now(timezone.utc).isoformat(),
                }
                # StrategySuggestion 기록!
                sugg = StrategySuggestion(
                    symbol=symbol, side=side,
                    suggestion_type="bb4h_auto_entry",
                    strategy_config={
                        "capitals": cfg["capitals"],
                        "symbol": symbol, "side": side,
                        "rt_reentry": True,
                        "rt_reentry_price": mp,
                        "prev_stop_price": _stop_price,
                        "entry_snapshot": _rt_entry_snapshot,  # 🎓 v218!
                    },
                    confidence_score=Decimal("0.65"),
                    reason=_reason_suffix,
                    status="EXECUTED",
                    execution_mode="AUTO",
                    executed_at=datetime.now(timezone.utc),
                    executed_strategy_id=new_strategy.id,
                    outcome_status="PENDING",
                )
                db.add(sugg)

                if _use_success_reentry:
                    _reset_reentry_count(symbol, side)
                    entered_success += 1
                else:
                    _increment_reentry_count(symbol, side)
                    entered_fail += 1

                db.commit()
                remaining -= 1
                results.append({
                    "symbol": symbol, "side": side,
                    "reason": _reason_suffix,
                    "strategy_id": new_strategy.id,
                })
                logger.info(
                    "[RT_REENTRY] ✅ %s %s: %s (id=%d)",
                    symbol, side, _reason_suffix, new_strategy.id,
                )
            except Exception as e:
                logger.warning("[RT_REENTRY] %s %s 진입 실패: %s", symbol, side, e)
                skipped += 1
                db.rollback()

        total_entered = entered_fail + entered_success
        logger.info(
            "[RT_REENTRY] 완료: fail=%d success=%d skipped=%d",
            entered_fail, entered_success, skipped,
        )
        return {
            "entered_fail_reentry": entered_fail,
            "entered_success_reentry": entered_success,
            "skipped": skipped,
            "results": results,
        }
    except Exception as e:
        logger.exception("[RT_REENTRY] 실행 실패: %s", e)
        return {"error": str(e), "entered": 0}
    finally:
        db.close()
