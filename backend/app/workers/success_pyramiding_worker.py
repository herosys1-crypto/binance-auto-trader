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
# 🎯 Fix 134 (2026-08-26 사장님 지시): "수익일떄 10 +5% 마틴게일 300 진입"
#   손절이 -5% ROI(레버리지 반영) 이므로 익절 트리거도 「같은 자」로 재야 대칭이다.
#   옛 값 2.0 은 raw 가격 변동률이라 2x 레버리지에서 ROI 4% 를 뜻했다 = 기준 불일치.
MIN_UNREALIZED_ROI_PCT = 5.0       # ROI 기준 (= 가격변동 × 레버리지)
MIN_UNREALIZED_PNL_PCT = 2.0       # (레거시 상수 = 다른 곳 참조 방지 위해 유지)
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
MAX_PYRAMID_COUNT = 2              # 🌟 Fix 98 (2026-08-25 사장님 verbatim!): "tp1 익절후 추가 진입은 최대 2번까지만" = 3 → 2!
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


def _strategy_type_of(si) -> str:
    """🚨 Fix 142 (2026-08-26): 관계명이 틀려 피라미딩이 100% 차단되고 있었다.

    옛 코드: `si.template if hasattr(si, "template") else None`
      StrategyInstance 의 관계명은 `strategy_template` 이다 (`template` 아님,
      models/strategy_instance.py:113). → hasattr False → tpl None → stype ""
      → AUTO_ENTRY_TYPES_PYRAMID 매칭 전멸 → 후보 전원 탈락.
      실 로그: "완료: entered=0 skipped=9 | 사유: not_auto_entry_type=9"
      strategy_type 실제 값은 auto_bb_break{suffix} 라 원래 통과했어야 한다.

    Fix 138(남의 스위치) 을 고쳐 워커가 돌기 시작하자 비로소 드러난 3번째 층이다.
    """
    tpl = getattr(si, "strategy_template", None)
    if tpl is None:
        tpl = getattr(si, "template", None)          # 혹시 모를 별칭 대비
    return getattr(tpl, "strategy_type", "") or "" if tpl is not None else ""


def run_success_pyramiding() -> dict:
    """매 30초 = 익절중 심볼 = 강한 지속 신호 시 = 원 자본으로 추가 진입!"""
    db: Session = SessionLocal()
    entered = 0
    skipped = 0
    results: list[dict] = []
    # 🎯 Fix 140: skip 사유 집계 — "왜 0건이지?" 에 로그만 보고 답할 수 있게.
    #   (realtime_reentry 의 _bump 와 같은 패턴 = 헌법 93 차단 사유 기록)
    _reasons: dict[str, int] = {}

    def _bump(reason: str) -> None:
        _reasons[reason] = _reasons.get(reason, 0) + 1
    try:
        # ═══════════════════════════════════════════════════════════════════
        # 🚨 Fix 138 (2026-08-26): 피라미딩이 남의 스위치에 물려 꺼져 있었다
        #
        # 사장님 질문: "이익일때 추가 300씩 두번 진입도 하는거지?"
        # 확인 결과 = 아니오. 이 워커 첫 줄이 auto_bb_break_daily_limit 을 보는데
        # 사장님이 「BB 이탈 자동진입」을 끄려고 그 값을 0 으로 두셨기 때문에
        # 별개 기능인 수익 피라미딩까지 통째로 꺼져 있었다.
        #   (두 기능이 스위치를 공유한 것 자체가 설계 실수 = 헌법 83 정신 위반)
        #
        # 또한 Fix 112 로 실질 상한이 「동시 보유 수」가 되었으므로,
        # 하루 카운터는 더 이상 이 워커의 예산이 아니다 (아래 check_position_slot 이 담당).
        #
        # 신: 전용 스위치 sajangnim_pyramid_enabled (기본 ON = 사장님이 원하는 기능).
        #     0 을 넣으면 피라미딩만 정확히 꺼진다.
        # ═══════════════════════════════════════════════════════════════════
        from app.models.system_setting import SystemSetting
        _pyr_row = db.get(SystemSetting, "sajangnim_pyramid_enabled")
        if _pyr_row is not None and str(_pyr_row.value).strip() not in ("", None):
            try:
                if int(str(_pyr_row.value).strip()) <= 0:
                    logger.warning(
                        "[success_pyramiding+Fix138] SKIP: sajangnim_pyramid_enabled=0 "
                        "= 사장님 명시 OFF"
                    )
                    return {"note": "pyramid_enabled=0 (사장님 명시 OFF)", "entered": 0}
            except (TypeError, ValueError):
                pass    # 손상값이면 켜진 것으로 본다 (사장님이 원하는 기본 동작)

        from app.workers.auto_bb_breakdown_worker import (
            _count_used_slots, _create_auto_bb_strategy,
        )
        # 🎯 Fix 112b (2026-08-26): 동시 보유 상한 = 이 워커도 신규 포지션을 만든다!
        #   최초 Fix 112 는 4개 워커에만 걸었는데, 이 워커는 30초마다 돌면서
        #   _create_auto_bb_strategy 로 「새 StrategyInstance」를 만든다 = 상한 우회!
        #   특히 사장님이 상한을 0으로 내려도 이 워커는 auto_bb_break_daily_limit 만
        #   보므로 계속 진입 = 정지 스위치까지 우회 (헌법 83 위반!)
        from app.services.position_limit import check_position_slot
        _slot_ok, _slot_why, _act, _cap = check_position_slot(db, "success_pyramiding")
        if not _slot_ok:
            logger.warning("[success_pyramiding+Fix112b] SKIP: %s", _slot_why)
            return {"note": _slot_why, "entered": 0}

        # Fix 138: 예산 = 동시 보유 여유 (하루 카운터는 Fix 112 로 의미가 바뀌어 제외)
        used = _count_used_slots(db)     # 참고 로그용
        remaining = _cap - _act
        if remaining <= 0:
            # Fix 139: 무로그 return 금지 (헌법 80)
            logger.info(
                "[success_pyramiding] SKIP: 동시보유 여유 없음 %d/%d (오늘 신규 %d)",
                _act, _cap, used,
            )
            return {
                "note": f"동시보유 {_act}/{_cap} (오늘 신규 {used})",
                "entered": 0,
            }

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
            stype = _strategy_type_of(si)      # Fix 142
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
                _bump("already_pyramid_active")
                continue

            # pyramid strategy 자체 = 재 pyramid 금지!
            stype = _strategy_type_of(si)      # Fix 142
            if "_pyramid" in stype:
                skipped += 1
                _bump("is_pyramid_strategy")
                continue

            # 🚨 v220 사장님 (2026-08-22): 자동 진입 소스 확장! (root cause fix!)
            # 이전: auto_bb_break* 만 = sajangnim_top_short 등 = 100% skip!
            # 신: 모든 자동 진입 소스 = pyramid 가능!
            if not any(stype.startswith(t) for t in AUTO_ENTRY_TYPES_PYRAMID):
                skipped += 1
                _bump("not_auto_entry_type")
                continue

            # cooldown 체크
            if _cooldown_active(si.symbol, si.side):
                skipped += 1
                _bump("cooldown")
                continue

            # pyramid count 체크
            pyr_count = _get_pyramid_count(si.symbol, si.side)
            if pyr_count >= MAX_PYRAMID_COUNT:
                skipped += 1
                _bump("max_pyramid_count")
                continue

            # unrealized ROI 판정 (익절중?)
            avg = float(si.avg_entry_price or 0)
            if avg <= 0:
                continue
            mp = _get_mark_price(si.symbol)
            if mp is None:
                continue

            # 🎯 Fix 134: ROI = 가격변동률 × 레버리지 (손절 -5% 와 동일한 자!)
            if si.side == "LONG":
                price_pct = (mp - avg) / avg * 100
            else:
                price_pct = (avg - mp) / avg * 100
            try:
                _lev = float(si.leverage or 1) or 1.0
            except Exception:
                _lev = 1.0
            roi_pct = price_pct * _lev

            if roi_pct < MIN_UNREALIZED_ROI_PCT:
                skipped += 1
                _bump("no_avg_or_mark")
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
                _bump("roi_below_5pct")
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
                    _bump("peak_not_sustained")
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
                            _bump("chg24_extreme")
                            continue
                        if si.side == "LONG" and ch < -15.0:
                            skipped += 1
                            _bump("regime_block")
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
                _bump("capital_invalid")
                continue
            # 🎯 Fix 134 (사장님 지시): 추가 금액은 「사다리 2번째 칸」 = 300
            #   사장님 verbatim: "10 +5% 마틴게일 300 진입 ... 300한번더 포지션 진입"
            #   옛 로직은 capitals[0](= 최초 진입금)을 그대로 추가했는데,
            #   Fix 133 으로 1단계가 10 USDT(탐색 진입)가 되어 그대로 두면 10 만 추가된다.
            try:
                from app.services.sajangnim_capital import get_pyramid_capital
                base_capital = float(get_pyramid_capital(db))
            except Exception as _pe:
                logger.warning("[Fix134] 피라미딩 자본 조회 실패 → 최초 진입금 사용: %s", _pe)
                base_capital = _initial_capital
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
                    _bump("create_failed")
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
                _bump("exception")
                db.rollback()

        _reason_str = " ".join(
            f"{k}={v}" for k, v in sorted(_reasons.items(), key=lambda x: -x[1])
        ) or "-"
        logger.info(
            "[SUCCESS_PYRAMID] 완료: entered=%d skipped=%d | 사유: %s "
            "(트리거 ROI>=%.1f%% 추가자본=사다리2칸 최대%d회)",
            entered, skipped, _reason_str, MIN_UNREALIZED_ROI_PCT, MAX_PYRAMID_COUNT,
        )
        return {"entered": entered, "skipped": skipped, "results": results}
    except Exception as e:
        logger.exception("[SUCCESS_PYRAMID] 실행 실패: %s", e)
        return {"error": str(e), "entered": 0}
    finally:
        db.close()
