"""🎯 v219 (2026-08-22 사장님!) + Fix 51 (2026-08-24!): 정점 감지 자동 SHORT 진입 워커!

사장님 verbatim (실 성공 로직!):
"급등하는 심볼 4시간봉 최상단 볼밴 최상단밖 obv 최고점 macd rsi cci 모든 지표가
 최고점일때 포지션 진입 전체자산에 1-2% 진입"

사장님 verbatim (Fix 49 위험 정책!):
"v219 단계별 진입후 -5% 손실이면 청산하고 대기 모니터링"

사장님 verbatim (Fix 51 P2 일 진입수 통합!):
"일 진입수는 급등락 실시간과 같이 세팅"

로직:
1. Redis `pump_top:alert:*` 스캔 (pump_top_detector_worker가 저장!)
2. daily_limit 체크 = _get_daily_limit (Fix 51 P2!):
   sajangnim_top_short_daily_limit → auto_bb_break_daily_limit → 20 fallback!
3. 활성 심볼 skip!
4. 자본 = compute_stage1_capital (전체 자산 × 1~2%!)
5. SHORT 자동 진입 (레버리지 2x!)
6. Fix 49 (P1): 신 진입만 force_sl_override = -5% (짧은 손절!)
7. entry_snapshot 저장 (학습!)
8. 헌법 64 예외 (사장님 실 성공 로직!)

안전:
- daily_limit fallback chain (v219 전용 → 공유 → default!)
- 소액 자본 (1~2%!)
- 7중 정점 확인 후만!
- 신 진입 = -5% SL (Fix 49 대칭 정책!)
- API Ban 체크!

SPEC: auto_short_at_top_v2_fix51_2026-08-24
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_suggestion import StrategySuggestion
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

SPEC_VERSION = "auto_short_at_top_v3_fix72_2026-08-25"
DEFAULT_LEVERAGE = 2      # 사장님 default!
DEFAULT_DAILY_LIMIT = 20  # sajangnim_top_short_daily_limit fallback!
ALERT_PATTERN = "pump_top:alert:*"


def _get_daily_limit(db) -> int:
    """🎯 v219 통합 (2026-08-22 사장님!) + Fix 51 P2 fallback 강화!:
    급등락 실시간과 같은 daily_limit 공유 = auto_bb_break_daily_limit!
    사장님 verbatim: "일 진입수는 급등락 실시간과 같이 세팅"

    LONG (auto_long_at_bottom) 동일 패턴 = 헌법 6 (단일 진실!):
    1) sajangnim_top_short_daily_limit (v219 정점 전용)
    2) auto_bb_break_daily_limit       (급등락 실시간 공유!)
    3) DEFAULT_DAILY_LIMIT (fallback = 20)
    """
    # 🚨🚨 Fix 108 (2026-08-26 CRITICAL): 「0 = OFF」 가 20 으로 둔갑하던 버그!
    #
    # 사장님 실측: 4개 설정 전부 0 인데 오늘 137건 진입! 활성 47건 전부 SHORT!
    #
    # 옛 로직: `if v > 0: return v` → 0 이면 return 안 하고 루프 계속
    #          → 전 키가 0 이면 마지막에 DEFAULT_DAILY_LIMIT(20) 반환!
    #          → 사장님이 「끄기」 하려고 0 을 넣어도 시스템은 20건씩 진입!
    #          = 정지 스위치가 작동하지 않는 상태 (자본 위험!)
    #
    # 신 로직: 값이 존재하면 0 이어도 그대로 존중 = 「명시적 0 = 완전 OFF」!
    #          키 자체가 없을 때만 DEFAULT 사용.
    for key in ("sajangnim_top_short_daily_limit", "auto_bb_break_daily_limit"):
        try:
            row = db.get(SystemSetting, key)
            if row and row.value is not None and str(row.value).strip() != "":
                v = int(row.value)
                if v <= 0:
                    logger.warning(
                        "[sajangnim_top_v219+Fix108] %s=%d → 자동 진입 완전 OFF (사장님 명시 정지!)",
                        key, v,
                    )
                    return 0        # 🚨 명시적 0 = OFF! (옛: 무시하고 20 으로 진행!)
                return v
        except Exception:
            continue
    return DEFAULT_DAILY_LIMIT


def run_auto_short_at_top() -> dict:
    """매 30초 = 정점 알람 확인 → 자동 SHORT 진입!"""
    db = SessionLocal()
    entered = 0
    skipped = 0
    results: list[dict] = []
    try:
        # 1. daily_limit 체크! (v219 통합 = auto_bb_break_daily_limit 공유!)
        # 🚨 Fix 109 (2026-08-26 헌법 80): 조기 return 무로그 금지!
        #   사장님 실측: 「[sajangnim_top_v219] 완료」 로그가 30초마다 나오다가
        #   갑자기 0건 = 워커가 죽은 건지 조기 종료인지 구별 불가!
        #   → realtime_reentry 와 똑같은 silent bug (Fix 103 에서 겪은 것!)
        #   → 모든 조기 return 에 반드시 사유 로그!
        # 🎯 Fix 112 (2026-08-26 사장님 verbatim):
        #   "일 20개로 하지말고 일 20개 최대 20개 수정해줘"
        #   = 「하루 신규 20건」이 아니라 「동시 보유 최대 20건」!
        #   옛 로직은 KST 자정마다 카운터가 리셋돼서 활성이 20→44 로 계속 누적됨!
        #   신 로직 = 지금 열려 있는 포지션이 상한이면 신규 진입 X (노출 고정!)
        from app.services.position_limit import check_position_slot
        _ok, _why, active_cnt, daily_limit = check_position_slot(db, "sajangnim_top_v219")
        if not _ok:
            logger.warning("[sajangnim_top_v219+Fix112] SKIP: %s", _why)
            return {"note": _why, "entered": 0, "active": active_cnt, "limit": daily_limit}

        used = active_cnt                      # 「지금 보유 중」 = 소진 슬롯!
        remaining = daily_limit - active_cnt   # 남은 동시보유 여유
        logger.info("[sajangnim_top_v219+Fix112] %s", _why)

        # 2. Redis 알람 조회!
        from app.core.redis_client import get_redis_client
        r = get_redis_client()

        alert_keys = list(r.scan_iter(ALERT_PATTERN))
        if not alert_keys:
            logger.info(
                "[sajangnim_top_v219] 완료: 정점 알람 0건 (슬롯 %d/%d 여유 %d)",
                used, daily_limit, remaining,
            )
            return {"note": "정점 알람 없음!", "entered": 0}

        # 3. 활성 심볼 skip!
        active_syms = set()
        try:
            active = db.execute(
                select(StrategyInstance).where(StrategyInstance.status.in_(list(ACTIVE_LIKE)))
            ).scalars().all()
            active_syms = {r_.symbol for r_ in active}
        except Exception:
            pass

        # 4. mainnet 계정!
        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            return {"error": "mainnet 계정 없음!", "entered": 0}

        from app.integrations.binance.client import BinanceClient
        from app.core.crypto import decrypt_text
        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )

        # 5. 자본 계산 (사장님 초기 금액 = default 300 USDT!)
        # 사장님 규정: 전체 자산 무관! 1단계 = 초기 금액!
        from app.services.sajangnim_capital import compute_stage1_capital
        base_capital = compute_stage1_capital(bc, db)
        capital_float = float(base_capital)

        # 6. 각 알람 처리!
        from app.workers.auto_bb_breakdown_worker import _create_auto_bb_strategy
        for key in alert_keys:
            if remaining <= 0:
                break

            key_str = key.decode() if isinstance(key, bytes) else key
            try:
                raw = r.get(key_str)
                if not raw:
                    continue
                alert = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                symbol = alert.get("symbol")
                side = alert.get("side", "SHORT")
                if not symbol or side != "SHORT":
                    continue
                if symbol in active_syms:
                    skipped += 1
                    continue

                confidence = float(alert.get("confidence", 0))
                if confidence < 0.85:
                    continue

                # Fix 65: OBV 절대값 검증 (사장님 사상!)
                try:
                    from app.services.obv_gate import check_obv_gate
                    obv_pass, obv_reason = check_obv_gate(bc, symbol, "SHORT")
                    if not obv_pass:
                        logger.info("[auto_short_top+Fix65] %s skip: %s", symbol, obv_reason)
                        continue
                except Exception as _obv_exc:
                    logger.warning("[auto_short_top+Fix65] %s obv_gate error: %s (fail-open)", symbol, _obv_exc)

                # Fix 66 P1: 양방향 실패 blocklist!
                try:
                    from app.services.bidirectional_blocklist import is_bidirectional_blocked
                    blocked, block_reason = is_bidirectional_blocked(db, symbol)
                    if blocked:
                        logger.info("[auto_short_top+Fix66] %s skip: %s", symbol, block_reason)
                        continue
                except Exception as _bl_exc:
                    logger.warning("[auto_short_top+Fix66] blocklist error: %s", _bl_exc)

                # Fix 66 P2: pump_dump_regime (SHORT!)
                try:
                    from app.services.pump_dump_regime import is_regime_blocked_for_short
                    regime_blocked, regime_reason = is_regime_blocked_for_short(bc, symbol)
                    if regime_blocked:
                        logger.info("[auto_short_top+Fix66] %s skip: %s", symbol, regime_reason)
                        continue
                except Exception as _rg_exc:
                    logger.warning("[auto_short_top+Fix66] regime error: %s", _rg_exc)

                # 🚨🚨 Fix 106 (2026-08-26 CRITICAL): 정점 확인 병목 게이트!
                #
                # 사장님 실측 사고 3연속 (전부 「아직 상승 중」인데 SHORT!):
                #   STARUSDT 24h +41% 상승 초입 / TACUSDT 1H +154% 상승 지속
                #   (TACUSDT 4H MACD Hist = +0.000110 = 양수 상승 중이었음!)
                #
                # 사장님 verbatim: "한번올랐다 다시 내려오고 이렇게 2-3번 반복하면
                #                  rsi macd obv cci 등등 고점에 이란 신호를 보고 진입"
                #
                # 감사 결과 (Fix 106): SHORT 진입 경로 15개 중 12개가 Fix 100 미적용!
                #   그런데 alert 경로 5개(pump_top v219/v222/v223 + bb_upper_breakout
                #   + pump_dump_early + macd_reversal_15m)는 전부 이 소비자를 통과!
                #   → 여기 게이트 1개 = 5개 경로 동시 커버 (헌법 6 단일 진실!)
                #
                # ⚠️ Fix 111 (2026-08-26): Fix 106 이 틀렸음 — 사장님 龙虾USDT 지적!
                #   옛 [A] = 4H peak 카운트 → 사장님 기준은 「15분 차트」!
                #            4H 급등은 폭발 캔들 1~2개라 peak 0~1 = 전부 차단됨!
                #   옛 [B] = 4H MACD 양수 상승 중 금지 → 4H 는 후행지표!
                #            급등 직후엔 언제나 양수 상승 중 →
                #            헌법 72(급등 BB상단돌파 마틴게일)를 영구 봉쇄!
                #   신 = peak_confirmation.confirm_peak (15m 기준, 헌법 6 단일 진실!)
                #        [A] 15m 반복 상승 >= 2회  [B] 15m 지표 꺾임 >= 2/3
                #        [C] 4H = 참고 정보만 (차단 X!)
                from app.services.peak_confirmation import confirm_peak
                _pk_ok, _pk_why, _pk_det = confirm_peak(bc, symbol, "SHORT")
                if not _pk_ok:
                    logger.warning(
                        "[auto_short_top+Fix111] %s SKIP: %s | %s", symbol, _pk_why, _pk_det,
                    )
                    continue
                logger.info("[auto_short_top+Fix111] %s %s | %s", symbol, _pk_why, _pk_det)

                # 7. 자동 진입!
                cfg = {"capitals": [capital_float], "leverage": DEFAULT_LEVERAGE}
                new_strategy = _create_auto_bb_strategy(
                    db, symbol, side, cfg,
                    strategy_type_suffix="_SAJANGNIM_TOP",
                )
                if not new_strategy:
                    skipped += 1
                    logger.info(
                        "[sajangnim_top_v219] ❌ %s 진입 실패 = 알람 유지 (재시도!)",
                        symbol,
                    )
                    continue

                # Fix 49 (2026-08-24 사장님 위험 정책!): 정점 SHORT = -5% 짧은 손절!
                # 사장님 verbatim: "v219 단계별 진입후 -5% 손실이면 청산하고 대기 모니터링"
                # LONG (auto_long_at_bottom L800-812) 대칭 패턴!
                # 기존 활성 전략은 그대로! 신 진입만 -5%!
                try:
                    new_strategy.force_sl_enabled_override = True
                    new_strategy.force_sl_roi_override = Decimal("5")
                    db.commit()
                    logger.info(
                        "[sajangnim_top_v219] 🛡️ %s SL override -5%% 적용 (strategy_id=%s)",
                        symbol, new_strategy.id,
                    )
                except Exception as _sl_exc:
                    logger.warning(
                        "[sajangnim_top_v219] ⚠️ %s SL override 실패: %s (진입은 유지)",
                        symbol, _sl_exc,
                    )
                    db.rollback()

                # 8. entry_snapshot 저장 (학습!)
                # Fix 72 (2026-08-25): rich upstream snapshot 우선 사용!
                #  - bb_upper_breakout_short_worker / pump_dump_early_detector_worker /
                #    pump_top_detector_worker가 alert.entry_snapshot에 저장한
                #    breakout_snapshot / martingale_signals / trend_strength / rsi/cci/obv/macd/bb
                #    실 값을 그대로 학습 DB까지 전달!
                #  - 없으면 legacy Fix 20 v219 재구축 (하위 호환!)
                _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
                _entered_iso = datetime.now(timezone.utc).isoformat()
                upstream_snapshot = alert.get("entry_snapshot") if isinstance(alert, dict) else None
                if isinstance(upstream_snapshot, dict) and upstream_snapshot:
                    # Fix 72: upstream rich snapshot 채택 + 진입 메타만 덧붙임!
                    entry_snapshot = dict(upstream_snapshot)
                    entry_snapshot.setdefault("regime", "TOP_REVERSAL")
                    entry_snapshot.setdefault("source", "SAJANGNIM_TOP")
                    entry_snapshot.setdefault("change_24h", alert.get("change_24h") or alert.get("chg_24h"))
                    entry_snapshot.setdefault("signals_passed", alert.get("signals"))
                    entry_snapshot["kst_hour"] = _kst_hour
                    entry_snapshot["confidence"] = confidence
                    entry_snapshot["entered_at"] = _entered_iso
                    entry_snapshot.setdefault("sustained_bars", 0)
                else:
                    # Legacy fallback (Fix 20 v219 하위 호환!)
                    entry_snapshot = {
                        "rsi": alert.get("rsi"),
                        "cci": alert.get("cci_last"),
                        "obv_slope_pct": None,
                        "regime": "TOP_REVERSAL",
                        "source": "SAJANGNIM_TOP",
                        "sustained_bars": 0,
                        "change_24h": alert.get("change_24h") or alert.get("chg_24h"),
                        "kst_hour": _kst_hour,
                        "confidence": confidence,
                        "signals_passed": alert.get("signals"),
                        "entered_at": _entered_iso,
                    }
                sugg = StrategySuggestion(
                    symbol=symbol, side=side,
                    suggestion_type="sajangnim_top_short",
                    strategy_config={
                        "capitals": cfg["capitals"],
                        "symbol": symbol, "side": side,
                        "sajangnim_top": True,
                        "confidence": confidence,
                        "signals": alert.get("signals"),
                        "entry_snapshot": entry_snapshot,
                    },
                    confidence_score=Decimal(str(round(confidence, 4))),
                    reason=(
                        f"🎯 사장님 정점 SHORT (v219)! "
                        f"7중 통과 (conf={confidence*100:.0f}%) "
                        f"24h=+{alert.get('change_24h', 0):.1f}% "
                        f"RSI={alert.get('rsi', 0):.1f} "
                        f"CCI={alert.get('cci_last', 0):.0f}"
                    ),
                    status="EXECUTED",
                    execution_mode="AUTO",
                    executed_at=datetime.now(timezone.utc),
                    executed_strategy_id=new_strategy.id,
                    outcome_status="PENDING",
                )
                db.add(sugg)
                db.commit()

                # 알람 삭제 (중복 진입 방지!)
                r.delete(key_str)

                remaining -= 1
                entered += 1
                results.append({
                    "symbol": symbol, "side": side,
                    "capital": capital_float,
                    "confidence": confidence,
                    "strategy_id": new_strategy.id,
                })
                logger.warning(
                    "[sajangnim_top_v219] ✅ 자동 SHORT: %s cap=%.2f conf=%.2f (id=%d)",
                    symbol, capital_float, confidence, new_strategy.id,
                )

                # 텔레그램! (fix: NotificationService!)
                try:
                    from app.services.notification_service import NotificationService
                    _db_n = SessionLocal()
                    _ns = NotificationService(_db_n)
                    _ns.send_system_alert(
                        title=f"✅ [v219 자동] {symbol} SHORT 진입! ({confidence*100:.0f}%)",
                        body=(
                            f"✅ 사장님 정점 자동 진입! (v219)\n"
                            f"심볼: {symbol} SHORT\n"
                            f"자본: {capital_float:.2f} USDT × 2x\n"
                            f"신뢰도: {confidence*100:.0f}%\n"
                            f"오늘 {daily_limit - remaining}/{daily_limit}"
                        ),
                    )
                    try:
                        _db_n.close()
                    except Exception:
                        pass
                except Exception as _te:
                    logger.warning("[sajangnim_top_v219] telegram 실패: %s", _te)

            except Exception as e:
                logger.warning("[sajangnim_top_v219] %s 처리 실패: %s", key_str, e)
                skipped += 1
                db.rollback()
                continue

        logger.info(
            "[sajangnim_top_v219] 완료: entered=%d skipped=%d",
            entered, skipped,
        )
        return {
            "entered": entered,
            "skipped": skipped,
            "results": results,
        }
    except Exception as e:
        logger.exception("[sajangnim_top_v219] 실행 실패: %s", e)
        return {"error": str(e), "entered": 0}
    finally:
        db.close()


def _count_v219_used_slots(db) -> int:
    """🎯 Fix 34: v219 전용 카운터 (auto_bb_breakdown과 완전 분리!)
    🚨 Fix 101 (2026-08-26 사장님 verbatim CRITICAL!):
    > "설정해도 그수량을 넘어서 자동진입포지션이 발생하고 있어"

    Root cause: 옛 로직 = 'sajangnim_top_short' suggestion_type만 카운트!
                → bb4h_auto_entry, chart_pattern, realtime_reentry_short,
                  sajangnim_multi_pump_peak_v226 등 = 카운트 X!
                → 30 초과 진입 발생!

    신 로직: 오늘 진입한 모든 SHORT AUTO 진입 카운트! (헌법 6 = 단일 진실!)
    """
    try:
        from app.models.strategy_suggestion import StrategySuggestion
        from app.models.strategy_instance import StrategyInstance
        from app.workers.auto_bb_breakdown_worker import _auto_bb_reset_at
        from sqlalchemy import and_
        today_start = _auto_bb_reset_at(db)
        # Fix 101: 모든 SHORT AUTO 진입 카운트 (suggestion_type 무관!)
        count = db.query(StrategySuggestion).filter(
            and_(
                StrategySuggestion.execution_mode == 'AUTO',
                StrategySuggestion.status == 'EXECUTED',
                StrategySuggestion.executed_at >= today_start,
                StrategySuggestion.outcome_status != 'SUCCESS',
                StrategySuggestion.side == 'SHORT',
            )
        ).count()
        return count
    except Exception:
        return 0
