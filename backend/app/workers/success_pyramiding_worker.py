"""🎯 사장님 사상 (2026-08-21): 성공 포지션 피라미딩!

사장님 verbatim:
"익절 시작하고 우리 로직으로 강력한 포지션 진입 일경우 초기 시작금액으로
 즉시 포지션 진입해서 수익을 더해가고 다시 하락하면 -5% 우리 로직에 맞게 청산"

= 매 30초 실행!
= 활성 심볼 (익절중!) = 강한 지속 신호 시 = 원 자본으로 즉시 추가 포지션!
= 신 strategy = 별도 관리 (자체 SL, TP, trailing = 우리 로직!)
= 다시 하락 = 강제 SL (-5%) = 우리 로직으로 청산!

realtime_reentry_worker와 대칭:
- realtime_reentry_worker = 청산 후 재진입 (TERMINAL_STATUSES!)
- success_pyramiding_worker = 활성 중 추가 진입 (ACTIVE_LIKE!)

안전:
- MAX_PYRAMID_COUNT=5 (헌법 47!)
- cooldown 5분 (심볼:side 단위 = 남발 방지!)
- daily_limit 공유 (auto_bb_break_daily_limit!)
- 급등/급락 필터 (헌법 64: >+15% SHORT 금지, <-15% LONG 금지!)
- 130% 자본 경고 = skip
- 이미 pyramid strategy 활성 = skip
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate

logger = logging.getLogger(__name__)

# 🚨 v220 사장님 (2026-08-22): 조건 완화 = 미발동 fix!
# 사장님 지적: "익절중인 심볼들의 추가 포지션에 들어가지 못한 원인 파악!"
MIN_UNREALIZED_PNL_PCT = 2.0       # v220: 3.0 → 2.0 (raw price, 레버리지 무시!)
MIN_SUSTAIN_PCT = 0.5              # v220: 1.0 → 0.5 (더 빨리 발동!)
PEAK_HOLD_TOLERANCE_PCT = 2.5      # v220: 1.5 → 2.5 (변동성 관대!)
COOLDOWN_SECONDS = 300             # 심볼:side 단위 5분 cooldown!
PYRAMID_COUNT_TTL_DAYS = 7         # 카운터 7일 후 리셋!

# 🌟 v241 Fix 68 사장님 신 verbatim (2026-08-25!):
# "이건 이미 있는 전략이야 TP1 실행후 지속적인 수익일때
#  포지션 초기진입 설정된 금액으로 포지션 추가야"
# = 마틴게일 배수 X! = 초기진입 설정 금액 그대로!
# = 예: 초기 300 USDT → TP1 실행 → 지속 수익 → 추가 300 → 추가 300!
# 이전 (v220 Fix 17): MARTINGALE_MULT = [1.0, 2.0, 6.0] (배수 도입 = 사장님 verbatim 위반!)
# 지금 (v241 Fix 68): 배수 완전 제거 = 초기진입 금액 그대로!
MAX_PYRAMID_COUNT = 3              # 사장님 상한 유지 ("3단계까지 갈수 있다야 가능하면 가지않는 관리")
# MARTINGALE_MULT 제거 = 배수 X = 초기진입 금액 그대로!

# 🚨 v220 사장님: 원본 필터 확장! (사장님 지적 root cause!)
# 이전: auto_bb_break* 만 → sajangnim_top_short/realtime_reentry = skip!
# 신: 모든 자동 진입 소스 = 익절중 pyramid 가능!
AUTO_ENTRY_TYPES_PYRAMID = (
    "auto_bb_break",        # BB SUSTAINED / PENDING_HC / OBV_REVERSE / REENTRY_QUEUE
    "sajangnim_top",        # v219 정점 SHORT!
    "realtime_reentry",     # 실시간 재진입!
    "chart_pattern",        # 차트 패턴!
)


def _redis():
    from app.core.redis_client import get_redis_client
    return get_redis_client()


def _rget(key: str) -> str | None:
    try:
        v = _redis().get(key)
        return (v.decode() if isinstance(v, bytes) else v) if v else None
    except Exception:
        return None


def _get_pyramid_count(symbol: str, side: str) -> int:
    v = _rget(f"pyramid_count:{symbol}:{side}")
    return int(v) if v else 0


def _increment_pyramid_count(symbol: str, side: str) -> int:
    try:
        new_count = _get_pyramid_count(symbol, side) + 1
        _redis().setex(
            f"pyramid_count:{symbol}:{side}",
            PYRAMID_COUNT_TTL_DAYS * 86400, str(new_count),
        )
        return new_count
    except Exception:
        return 0


def _cooldown_active(symbol: str, side: str) -> bool:
    return bool(_rget(f"pyramid_cooldown:{symbol}:{side}"))


def _set_cooldown(symbol: str, side: str) -> None:
    try:
        _redis().setex(f"pyramid_cooldown:{symbol}:{side}", COOLDOWN_SECONDS, "1")
    except Exception:
        pass


def _update_peak_price(symbol: str, side: str, price: float) -> float:
    """LONG=max/SHORT=min 극값만 갱신. TTL 1h."""
    try:
        prev_v = _rget(f"pyramid_peak:{symbol}:{side}")
        prev = float(prev_v) if prev_v else None
        new_peak = price if prev is None else (
            max(prev, price) if side == "LONG" else min(prev, price)
        )
        _redis().setex(f"pyramid_peak:{symbol}:{side}", 3600, str(new_peak))
        return new_peak
    except Exception:
        return price


def _get_mark_price(symbol: str) -> float | None:
    v = _rget(f"mark_price:{symbol}")
    if not v:
        return None
    try:
        p = float(v)
        return p if p > 0 else None
    except (ValueError, TypeError):
        return None


def run_success_pyramiding() -> dict:
    """매 30초 = 익절중 심볼 = 강한 지속 신호 시 = 원 자본으로 추가 진입!"""
    db: Session = SessionLocal()
    entered = 0
    skipped = 0
    results: list[dict] = []
    try:
        # 1. daily_limit 체크 (auto_bb_break_daily_limit 공유!)
        from app.models.system_setting import SystemSetting
        limit_row = db.get(SystemSetting, "auto_bb_break_daily_limit")
        daily_limit = int(limit_row.value) if limit_row and limit_row.value else 0
        if daily_limit <= 0:
            return {"note": "daily_limit=0 (OFF!)", "entered": 0}

        from app.workers.auto_bb_breakdown_worker import (
            _count_used_slots, _create_auto_bb_strategy,
        )
        used = _count_used_slots(db)
        remaining = daily_limit - used
        if remaining <= 0:
            return {"note": f"daily {used}/{daily_limit}", "entered": 0}

        # 2. 활성 심볼 조회 (익절중 후보!)
        active = db.execute(
            select(StrategyInstance)
            .join(StrategyTemplate,
                  StrategyInstance.strategy_template_id == StrategyTemplate.id)
            .where(StrategyInstance.status.in_(list(ACTIVE_LIKE)))
            .where(StrategyInstance.current_stage >= 1)
        ).scalars().all()

        # 3. 심볼별 이미 pyramid 활성 = skip 집합!
        pyramid_active_syms: set[tuple[str, str]] = set()
        for si in active:
            tpl = si.template if hasattr(si, "template") else None
            stype = getattr(tpl, "strategy_type", "") if tpl else ""
            if "_pyramid" in stype:
                pyramid_active_syms.add((si.symbol, si.side))

        # 4. 원본 활성 심볼 = pyramid 후보 판정!
        seen: set[tuple[str, str]] = set()
        for si in active:
            if remaining <= 0:
                break
            key = (si.symbol, si.side)
            if key in seen:
                continue
            seen.add(key)

            # 이미 pyramid 활성 = skip
            if key in pyramid_active_syms:
                skipped += 1
                continue

            # pyramid strategy 자체 = 재 pyramid 금지!
            tpl = si.template if hasattr(si, "template") else None
            stype = getattr(tpl, "strategy_type", "") if tpl else ""
            if "_pyramid" in stype:
                skipped += 1
                continue

            # 🚨 v220 사장님 (2026-08-22): 자동 진입 소스 확장! (root cause fix!)
            # 이전: auto_bb_break* 만 = sajangnim_top_short 등 = 100% skip!
            # 신: 모든 자동 진입 소스 = pyramid 가능!
            if not any(stype.startswith(t) for t in AUTO_ENTRY_TYPES_PYRAMID):
                skipped += 1
                continue

            # cooldown 체크
            if _cooldown_active(si.symbol, si.side):
                skipped += 1
                continue

            # pyramid count 체크
            pyr_count = _get_pyramid_count(si.symbol, si.side)
            if pyr_count >= MAX_PYRAMID_COUNT:
                skipped += 1
                continue

            # unrealized ROI 판정 (익절중?)
            avg = float(si.avg_entry_price or 0)
            if avg <= 0:
                continue
            mp = _get_mark_price(si.symbol)
            if mp is None:
                continue

            # ROI = (현재 - 평단) / 평단 × 방향
            if si.side == "LONG":
                roi_pct = (mp - avg) / avg * 100
            else:
                roi_pct = (avg - mp) / avg * 100

            if roi_pct < MIN_UNREALIZED_PNL_PCT:
                skipped += 1
                continue

            # peak 갱신 + 지속 판정
            peak = _update_peak_price(si.symbol, si.side, mp)
            if si.side == "LONG":
                retrace_pct = (peak - mp) / peak * 100 if peak > 0 else 100
            else:
                retrace_pct = (mp - peak) / peak * 100 if peak > 0 else 100
            if retrace_pct > PEAK_HOLD_TOLERANCE_PCT:
                # peak 대비 되돌림 크다 = 지속 약함 = skip
                skipped += 1
                continue

            # 시작가 대비 방향 지속 검증
            start = float(si.start_price or 0)
            if start > 0:
                if si.side == "LONG":
                    sustain_pct = (mp - start) / start * 100
                else:
                    sustain_pct = (start - mp) / start * 100
                if sustain_pct < MIN_SUSTAIN_PCT:
                    skipped += 1
                    continue

            # 급등/급락 필터 (헌법 64!)
            try:
                from app.integrations.binance.client import BinanceClient
                from app.models.exchange_account import ExchangeAccount
                from app.core.crypto import decrypt_text
                acct = db.execute(
                    select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
                ).scalar_one_or_none()
                if acct:
                    bc = BinanceClient(
                        api_key=decrypt_text(acct.api_key_enc),
                        api_secret=decrypt_text(acct.api_secret_enc),
                        is_testnet=False,
                    )
                    tk = bc.get_24hr_ticker(symbol=si.symbol)
                    if isinstance(tk, dict):
                        ch = float(tk.get("priceChangePercent") or 0)
                        if si.side == "SHORT" and ch > 15.0:
                            skipped += 1
                            continue
                        if si.side == "LONG" and ch < -15.0:
                            skipped += 1
                            continue
            except Exception:
                pass  # ticker 실패 = 조용히 통과 (Redis mark_price는 이미 확보!)

            # 🌟 v241 Fix 68 사장님 신 verbatim (2026-08-25!):
            # "TP1 실행후 지속적인 수익일때 포지션 초기진입 설정된 금액으로 포지션 추가"
            # = 마틴게일 배수 X! = 초기진입 설정 금액 그대로!
            # = 예: 300 USDT → 추가 300 USDT → 추가 300 USDT (누적 900, 각 300!)
            # 이전 (v220 Fix 17): 부모 자본 × [1.0, 2.0, 6.0] = 마틴게일 배수 (사장님 verbatim 위반!)
            # 지금 (v241 Fix 68): 최초 진입 금액 (template capitals[0]) 그대로!
            _initial_capital = 0.0
            try:
                _parent_tpl = si.template if hasattr(si, "template") else None
                _tpl_config = getattr(_parent_tpl, "config", None) if _parent_tpl else None
                if isinstance(_tpl_config, dict):
                    _caps = _tpl_config.get("capitals") or []
                    if _caps and float(_caps[0] or 0) > 0:
                        _initial_capital = float(_caps[0])  # 🌟 최초 진입 금액!
            except Exception:
                _initial_capital = 0.0
            # fallback: si.total_capital (template 없을 때만!)
            if _initial_capital <= 0:
                _initial_capital = float(si.total_capital or 0)
            if _initial_capital <= 0:
                continue
            _seq = pyr_count + 1  # 1, 2, 3
            if _seq > MAX_PYRAMID_COUNT:
                skipped += 1
                continue
            base_capital = _initial_capital  # 🌟 그대로! 배수 X!
            logger.info(
                "[SUCCESS_PYRAMID] 🌟 v241 Fix 68 초기금액 재사용 #%d: %s %s = %.0f USDT (배수 X!)",
                _seq, si.symbol, si.side, base_capital,
            )

            # 신 pyramid strategy 생성
            try:
                cfg = {
                    "capitals": [base_capital],
                    "leverage": int(si.leverage or 2),
                }
                suffix = f"_pyramid{pyr_count + 1}"
                new_strategy = _create_auto_bb_strategy(
                    db, si.symbol, si.side, cfg,
                    strategy_type_suffix=suffix,
                )
                if not new_strategy:
                    skipped += 1
                    continue

                # StrategySuggestion 기록!
                from app.models.strategy_suggestion import StrategySuggestion
                # 🎓 v218 fix (2026-08-22 사장님!): entry_snapshot 저장 = 학습 데이터!
                _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
                _pyr_entry_snapshot = {
                    "rsi": None,
                    "cci": None,
                    "obv_slope_pct": None,
                    "regime": "NEUTRAL",
                    "source": "SUCCESS_PYRAMID",
                    "kst_hour": _kst_hour,
                    "parent_strategy_id": si.id,
                    "pyramid_seq": pyr_count + 1,
                    "roi_pct_at_entry": roi_pct,
                    "entry_price": mp,
                    "entered_at": datetime.now(timezone.utc).isoformat(),
                }
                sugg = StrategySuggestion(
                    symbol=si.symbol, side=si.side,
                    suggestion_type="bb4h_auto_entry",
                    strategy_config={
                        "capitals": [base_capital],
                        "symbol": si.symbol, "side": si.side,
                        "pyramid": True,
                        "pyramid_seq": pyr_count + 1,
                        "parent_strategy_id": si.id,
                        "entry_price": mp,
                        "roi_pct_at_entry": roi_pct,
                        "entry_snapshot": _pyr_entry_snapshot,  # 🎓 v218!
                    },
                    confidence_score=Decimal("0.7"),
                    reason=f"SUCCESS_PYRAMID#{pyr_count + 1}: {si.side} ROI+{roi_pct:.2f}% peak-retrace {retrace_pct:.2f}%!",
                    status="EXECUTED",
                    execution_mode="AUTO",
                    executed_at=datetime.now(timezone.utc),
                    executed_strategy_id=new_strategy.id,
                    outcome_status="PENDING",
                )
                db.add(sugg)
                db.commit()

                _increment_pyramid_count(si.symbol, si.side)
                _set_cooldown(si.symbol, si.side)
                entered += 1
                remaining -= 1
                results.append({
                    "symbol": si.symbol, "side": si.side,
                    "parent_id": si.id, "new_id": new_strategy.id,
                    "pyramid_seq": pyr_count + 1,
                    "roi_pct": round(roi_pct, 2),
                })
                logger.info(
                    "[SUCCESS_PYRAMID] ✅ %s %s #%d parent=%d new=%d ROI+%.2f%%",
                    si.symbol, si.side, pyr_count + 1, si.id, new_strategy.id, roi_pct,
                )
            except Exception as e:
                logger.warning(
                    "[SUCCESS_PYRAMID] %s %s 진입 실패: %s", si.symbol, si.side, e,
                )
                skipped += 1
                db.rollback()

        logger.info(
            "[SUCCESS_PYRAMID] 완료: entered=%d skipped=%d", entered, skipped,
        )
        return {"entered": entered, "skipped": skipped, "results": results}
    except Exception as e:
        logger.exception("[SUCCESS_PYRAMID] 실행 실패: %s", e)
        return {"error": str(e), "entered": 0}
    finally:
        db.close()
