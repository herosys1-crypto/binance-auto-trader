"""🌟 v224 (2026-08-23 사장님 통합 요구!): 모든 자동매매 = 15m 급등/급락 심볼 통합!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 verbatim (2026-08-23):
  "지금까지 모든 자동매매는 오늘 15분 차트 급등과 급락한 심볼만
   자동매매를 하는걸로 통합해서 운영할수 있게 하나도 통합정리해줘"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

= 15분 차트 급등/급락 = 유일한 진입 유니버스!
= 모든 자동매매 진입 소스 (BB SUSTAINED / PENDING_HC / OBV_REVERSE /
  pump_top / pending_hc_fast) = 이 워커 하나로 통합!

로직 (매 30초 실행!):
  1. 상위 거래대금 심볼 (top ~40) + 24h |변동| ≥ 3% 후보!
  2. 각 심볼 15m 캔들 조회 (analyze_timeframe → Redis 캐시!)
  3. 오늘 15m 급등/급락 = A OR B 트리거!
     A. 4봉 (1시간) 변동 ≥ ±unified_15m_1h_pct (default 5%!)
     B. 12봉 (3시간) 변동 ≥ ±unified_15m_3h_pct (default 10%!)
  4. 방향 = 급등→SHORT (정점 반전!) / 급락→LONG (저점 반등!)
  5. v223 = 15m score ≥3/5 + 1h/4h 반대 방향 <3/5!
  6. 필터: 활성 심볼 / 최근 48h 손실 / 학습된 실패 조건!
  7. 통과 = _create_auto_bb_strategy = 실 주문!
  8. suggestion_type="unified_15m_entry" 저장!

daily_limit = SystemSetting "auto_bb_break_daily_limit" 공유!
(v219 통합 사상 유지 = _count_used_slots가 이미 unified_15m_entry 포함!)

이 워커가 켜지면 (unified_entry_enabled=1) 아래 워커는 disable!
  - auto_bb_breakdown (BB 4H!)
  - pump_top_detector (v219/v222/v223!)
  - auto_short_at_top (정점 SHORT!)
  - pending_hc_fast (PENDING_HC 85%+!)

후속 대응 워커는 유지 (통합 아님!):
  - realtime_reentry (마틴게일 재진입!)
  - success_pyramiding (익절중 추가!)
  - auto_add_margin (증거금 추가!)
  - reentry_alert_watcher (OBV 알람 저장 = 학습용!)

헌법 70 (2026-08-23): 15m 급등/급락 = 유일 진입 유니버스 (사장님 통합!)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_suggestion import StrategySuggestion
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

# ─── 상수 (SystemSetting 없을 시 default!) ─────────────────────────────
MAX_SYMBOLS = 40                    # 스캔 상한 (API Ban 방지!)
MIN_24H_CHANGE_PREFILTER = 3.0      # 24h |변동| ≥ 3% pre-filter!
DEFAULT_1H_PCT = 5.0                # 4봉 (1시간) 변동 ≥ ±5% (사장님 core!)
DEFAULT_3H_PCT = 10.0               # 12봉 (3시간) 변동 ≥ ±10%
DEFAULT_LEVERAGE = 2                # 사장님 default!
V223_MIN_SCORE = 3                  # 15m score 최소치
V223_OPP_SKIP = 3                   # 1h/4h 반대 score >= 이 값 = skip!
SUGGESTION_TYPE = "unified_15m_entry"  # 통합 마커!


# ─── SystemSetting 로더 ────────────────────────────────────────────────
def _get_setting_int(db: Session, key: str, default: int) -> int:
    try:
        row = db.get(SystemSetting, key)
        if row and row.value:
            return int(row.value)
    except Exception:
        pass
    return default


def _get_setting_float(db: Session, key: str, default: float) -> float:
    try:
        row = db.get(SystemSetting, key)
        if row and row.value:
            return float(row.value)
    except Exception:
        pass
    return default


# ─── 트리거 판정 ───────────────────────────────────────────────────────
def _detect_15m_surge(
    closes: list[float],
    pct_1h: float,
    pct_3h: float,
) -> tuple[bool, str | None, dict[str, float]]:
    """오늘 15m 급등/급락 감지!

    Returns:
        (matched, side, meta)
        - matched=True: 15m 급등/급락!
        - side="SHORT" (급등!) or "LONG" (급락!)
        - meta = {change_1h_pct, change_3h_pct, matched_window}
    """
    if not closes or len(closes) < 13:
        return False, None, {}
    last = closes[-1]
    c1h = ((last / closes[-5]) - 1.0) * 100.0    # 4봉 이전 = 1시간!
    c3h = ((last / closes[-13]) - 1.0) * 100.0   # 12봉 이전 = 3시간!
    meta = {"change_1h_pct": round(c1h, 3), "change_3h_pct": round(c3h, 3)}

    # A. 4봉 트리거!
    if abs(c1h) >= pct_1h:
        side = "SHORT" if c1h > 0 else "LONG"
        meta["matched_window"] = "1h"
        meta["matched_pct"] = round(c1h, 3)
        return True, side, meta
    # B. 12봉 트리거!
    if abs(c3h) >= pct_3h:
        side = "SHORT" if c3h > 0 else "LONG"
        meta["matched_window"] = "3h"
        meta["matched_pct"] = round(c3h, 3)
        return True, side, meta
    meta["matched_window"] = None
    return False, None, meta


# ─── 메인 워커 ─────────────────────────────────────────────────────────
def run_unified_15m_entry() -> dict:
    """🌟 v224: 15m 급등/급락 통합 진입 워커! (매 30초!)"""
    db: Session = SessionLocal()
    entered = 0
    skipped = 0                 # 대상 심볼 (surge 감지!) 중 skip 카운트!
    scanned = 0
    surges_found = 0
    no_candles = 0              # 15m 캔들 없음 (대상 아님!)
    no_surge = 0                # 급등/급락 없음 (대상 아님!)
    # 🔎 Fix 255: Fix254(지지 붕괴) 관측 카운터.
    #   옛 코드는 **전환에 성공했을 때만** 로그를 남겨서,
    #   「평가를 아예 안 한 것」과 「평가했는데 조건 미달」이 구별되지 않았다.
    #   = 이 프로젝트가 반복해서 당한 「조용한 실패」 형태다 (헌법 93).
    sb_evaluated = 0            # 급락 LONG 후보 중 지지붕괴 판정을 돌린 수
    sb_matched = 0              # 그중 5개 조건을 전부 만족한 수
    sb_error = 0                # 판정 자체가 실패한 수
    skip_reasons: dict[str, int] = {}   # 사장님 검증용!
    results: list[dict] = []
    surges: list[dict] = []             # 감지된 급등/급락 심볼 = UI 모니터링용!

    def _skip(reason: str, symbol: str, side: str | None, extra: str = "") -> None:
        """대상 심볼 skip 헬퍼 = 카운트 + INFO 로그 + 이유 집계!"""
        nonlocal skipped
        skipped += 1
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
        _side_str = side or "?"
        logger.info(
            "[unified_15m_v224] skip %s %s reason=%s%s",
            symbol, _side_str, reason,
            (" " + extra) if extra else "",
        )
    try:
        # 1. 활성화 여부!
        if not _get_setting_int(db, "unified_entry_enabled", 1):
            return {"note": "unified_entry_enabled=0 (OFF!)", "entered": 0}

        # 2. daily_limit = auto_bb_break_daily_limit 공유! (v219 통합!)
        daily_limit = _get_setting_int(db, "auto_bb_break_daily_limit", 0)
        if daily_limit <= 0:
            return {"note": "daily_limit=0 (OFF!)", "entered": 0}

        # 3. used slots = 통합 카운터 (v219 통합 유지!)
        from app.workers.auto_bb_breakdown_worker import (
            _count_used_slots,
            _get_active_symbol_keys,
            _get_recent_loss_symbol_keys,
            _matches_failure_condition,
            _create_auto_bb_strategy,
        )
        # 🎯 Fix 112 (2026-08-26 사장님 "일 20개 최대 20개"): 동시 보유 상한!
        from app.services.position_limit import check_position_slot
        _slot_ok, _slot_why, used, daily_limit = check_position_slot(db, "unified_15m")
        if not _slot_ok:
            logger.warning("[unified_15m+Fix112] SKIP: %s", _slot_why)
            return {"note": _slot_why, "entered": 0}
        remaining = daily_limit - used

        # 4. mainnet 계정 + API Ban!
        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            return {"error": "mainnet 계정 없음!", "entered": 0}
        from app.core.api_backoff import is_account_banned
        if is_account_banned(account.id):
            return {"note": "API Ban 중 = skip!", "entered": 0}

        # 5. BinanceClient!
        from app.integrations.binance.client import BinanceClient
        from app.core.crypto import decrypt_text
        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )

        # 6. 세팅 로드!
        pct_1h = _get_setting_float(db, "unified_15m_1h_pct", DEFAULT_1H_PCT)
        pct_3h = _get_setting_float(db, "unified_15m_3h_pct", DEFAULT_3H_PCT)

        # 7. 24h ticker → pre-filter!
        tickers = bc.get_24hr_ticker()
        if not isinstance(tickers, list):
            return {"error": "ticker 실패!", "entered": 0}
        usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
        try:
            usdt.sort(key=lambda x: float(x.get("quoteVolume", 0) or 0), reverse=True)
        except Exception:
            pass
        candidates = [
            t for t in usdt[:MAX_SYMBOLS * 2]
            if abs(float(t.get("priceChangePercent", 0) or 0)) >= MIN_24H_CHANGE_PREFILTER
        ][:MAX_SYMBOLS]
        if not candidates:
            return {"note": "24h 후보 없음!", "entered": 0}

        # 8. 활성 + 손실 심볼!
        active_keys = _get_active_symbol_keys(db)
        recent_loss_keys = _get_recent_loss_symbol_keys(db)

        # 9. default profile!
        from app.api.v1.suggestion_profiles import _load_profiles
        profiles, default_name = _load_profiles(db)
        default_profile = next(
            (p for p in profiles if p.get("name") == default_name), None,
        )
        if not default_profile:
            return {"error": "default profile 없음!", "entered": 0}
        cfg_base = default_profile.get("config", {})

        # 10. 자본 = 사장님 default (300 USDT!)
        from app.services.sajangnim_capital import compute_stage1_capital
        base_capital = float(compute_stage1_capital(bc, db))

        # 11. v223 검사기!
        from app.services.chart_analyzer import ChartAnalyzer
        from app.workers.pump_top_detector_worker import PumpTopDetector

        # 12. 심볼 순회!
        for t in candidates:
            if entered >= remaining:
                break
            symbol = str(t.get("symbol", ""))
            if not symbol:
                continue
            scanned += 1

            try:
                # 12a. 15m 분석! (Redis 캐시 재사용!)
                a15 = ChartAnalyzer.analyze_timeframe(bc, symbol, "15m", limit=60)
                if not a15:
                    # 대상 심볼 아님! (surge 판정 전!) = skipped++ X, debug만!
                    no_candles += 1
                    logger.debug("[unified_15m_v224] %s: 15m 분석 없음(캔들 부족?)", symbol)
                    continue
                closes = a15.get("closes") or []
                matched, side, surge_meta = _detect_15m_surge(closes, pct_1h, pct_3h)

                # ═══════════════════════════════════════════════════════════
                # 📉 Fix 254 (2026-09-01) — 「급락 = LONG」을 뒤집는다 (사장님 사상 ③).
                #
                #   위 _detect_15m_surge 는 방향을 **부호만으로** 정한다:
                #       side = "SHORT" if c1h > 0 else "LONG"
                #   그래서 BTRUSDT 가 -44% 붕괴하면 「급락」으로 보고 **LONG 을 산다.**
                #
                #   사장님 사상 ③: "급락한것은 이전급등에 대한 급락이라 **확실한 숏**"
                #                  "볼밴 **지지선 붕괴**와 지속하락을 찾아서 분할 진입"
                #
                #   BTR #1488 (단일 최대 손실 -6,552.45):
                #     0.0138 -> 0.224 (+1,523%) -> 4~5일 횡보 -> 0.0823 (-44%)
                #     정점과 붕괴 사이가 4~5일. 기다렸어야 할 자리가 **붕괴**다.
                #
                #   -> 급락으로 잡힌 심볼이 「선행 급등 + 지지선 붕괴 + 거래량 + OBV 하락」
                #      **전부**를 만족하면 방향을 SHORT 로 뒤집는다.
                #      (다수결이 아니라 전부 — 방향을 뒤집는 판정이다. Fix 250 의 교훈)
                #
                #   ⚠️ 기본 OFF. OFF 여도 「뒤집었을 것」 로그는 남긴다.
                #      켜기: SystemSetting support_breakdown_short_enabled = 1
                # ═══════════════════════════════════════════════════════════
                if matched and side == "LONG":
                    try:
                        from app.services.obv_metrics import obv_direction_ratio as _obv254
                        from app.services.support_breakdown import (
                            evaluate_support_breakdown as _sb254,
                        )
                        _a1h = ChartAnalyzer.analyze_timeframe(bc, symbol, "1h", limit=80) or {}
                        _c1 = _a1h.get("closes") or []
                        try:
                            _od254 = _obv254(_a1h.get("obv"), _a1h.get("volumes"), 20)
                        except Exception:
                            _od254 = None
                        sb_evaluated += 1
                        _v254 = _sb254(
                            closes=[float(x) for x in _c1] if _c1 else None,
                            volumes=_a1h.get("volumes"),
                            obv_dir=_od254,
                        )
                        if _v254.ok:
                            sb_matched += 1
                            _on254 = _get_setting_int(db, "support_breakdown_short_enabled", 0)
                            if _on254:
                                logger.warning(
                                    "[Fix254] 📉 %s 지지 붕괴 = LONG -> **SHORT** 전환 (%s) "
                                    "선행급등 %.0f%% 지지 %s -> %s 거래량 %.1fx OBV %s",
                                    symbol, _v254.reason,
                                    _v254.detail.get("prior_rally_pct") or 0,
                                    _v254.detail.get("support"), _v254.detail.get("now"),
                                    _v254.detail.get("vol_ratio") or 0,
                                    _v254.detail.get("obv_dir"),
                                )
                                side = "SHORT"
                                surge_meta["flipped_by"] = "Fix254_support_breakdown"
                            else:
                                logger.warning(
                                    "[Fix254] ⚠️ %s 지지 붕괴 = LONG 이 아니라 SHORT 였을 것 "
                                    "(%s) — 설정 OFF 라 LONG 유지. "
                                    "켜기: support_breakdown_short_enabled=1",
                                    symbol, _v254.reason,
                                )
                    except Exception as _e254:
                        sb_error += 1
                        logger.warning("[Fix254] %s 지지붕괴 판정 실패 = 원 방향 유지: %s",
                                       symbol, _e254)

                if not matched or side is None:
                    # 대상 심볼 아님! = 무로그 (40개 = 노이즈!)
                    no_surge += 1
                    continue
                surges_found += 1
                logger.info(
                    "[unified_15m_v224] 🎯 surge 감지: %s side=%s window=%s pct=%+.2f%%",
                    symbol, side, surge_meta.get("matched_window"),
                    surge_meta.get("matched_pct", 0),
                )
                surges.append({
                    "symbol": symbol,
                    "side": side,
                    "window": surge_meta.get("matched_window"),
                    "matched_pct": surge_meta.get("matched_pct", 0),
                    "change_1h_pct": surge_meta.get("change_1h_pct"),
                    "change_3h_pct": surge_meta.get("change_3h_pct"),
                    "change_24h_pct": float(t.get("priceChangePercent", 0) or 0),
                })

                key = f"{symbol}:{side}"

                # 12b. 활성 심볼 skip!
                if key in active_keys:
                    _skip("active_symbol", symbol, side, "중복 진입 방지")
                    continue

                # 12c. 최근 48h 손실 skip! (마틴게일은 realtime_reentry_worker 담당!)
                if key in recent_loss_keys:
                    _skip("recent_loss_48h", symbol, side, "재진입은 realtime_reentry!")
                    continue

                # 12d. v223 = 15m score + 1h/4h 역방향!
                v = PumpTopDetector.check_v223_15m_primary(bc, symbol, side)
                # v223 relax override = SystemSetting "unified_v223_min_score" (default 3)
                _min_score = _get_setting_int(db, "unified_v223_min_score", V223_MIN_SCORE)
                _s15 = int(v.get("score_15m") or 0)
                _detected_relaxed = bool(v.get("detected")) or (_s15 >= _min_score)
                if not _detected_relaxed:
                    _skip(
                        "v223_fail", symbol, side,
                        f"v223={v.get('reason')} score_15m={_s15}(min={_min_score}) "
                        f"opp_1h={v.get('opp_score_1h')} opp_4h={v.get('opp_score_4h')} "
                        f"conf={v.get('confidence')}",
                    )
                    continue
                confidence = float(v.get("confidence", 0) or 0)
                if confidence <= 0:
                    # relaxed 통과 + confidence 없음 → score 비례 fallback
                    confidence = min(0.60, 0.20 + 0.10 * _s15)

                # 12e. 학습된 실패 조건 skip! (BTC 방향 + WORST 시나리오 포함!)
                snap15 = (v.get("entry_snapshot") or {}).get("15m") or {}
                _filter_it = {
                    "symbol": symbol,
                    "rsi": snap15.get("rsi_now"),
                    "cci": snap15.get("cci_now"),
                    # 🚨 Fix 228: 옛 코드는 None 이라 **현재 주 진입 워커가 OBV 를**
                    #   **한 번도 기록하지 않았다.** 사장님이 OBV 를 최종 판단으로
                    #   올리셨는데 정작 매매를 만드는 자리에 값이 없었다.
                    #   detector 의 entry_snapshot 이 이제 obv_dir(-1~+1)을 담는다.
                    "obv_slope_pct": snap15.get("obv_dir"),
                    "regime": "NEUTRAL",     # 15m 기반 = regime 판정 X → NEUTRAL로 fail-open!
                    "change_24h": float(t.get("priceChangePercent", 0) or 0),
                    "source": "UNIFIED_15M",
                    "suggestion_type": SUGGESTION_TYPE,
                }
                if _matches_failure_condition(_filter_it, side):
                    _skip(
                        "learned_failure", symbol, side,
                        f"rsi={snap15.get('rsi_now')} cci={snap15.get('cci_now')} "
                        f"24h={float(t.get('priceChangePercent', 0) or 0):+.1f}%",
                    )
                    continue

                # 🚨🚨 Fix 106 (2026-08-26 CRITICAL): SHORT 정점 확인 게이트!
                #
                # 이 워커의 side 결정 = `side = "SHORT" if c1h > 0` (L116)
                #   = 「1시간 올랐으면 무조건 SHORT」 = 지표 검증 0!
                #   = TACUSDT(1H +154%) / STARUSDT(24h +41%) 사고의 직접 주범!
                #
                # 사장님 verbatim: "한번올랐다 다시 내려오고 이렇게 2-3번 반복하면
                #                  rsi macd obv cci 등등 고점에 이란 신호를 보고 진입"
                #   = 단순 「올랐다」가 아니라 「반복 상승 소진 + 지표 꺾임」!
                #
                # ⚠️ Fix 111 (2026-08-26): 4H → 15m 정정 + 4H MACD 하드차단 제거!
                #   (사장님 龙虾USDT 「이런 진입은 왜 없냐」 지적 = 4H 게이트가 과차단!)
                #   이제 LONG/SHORT 대칭 적용 = 저점도 같은 기준으로 확인!
                from app.services.peak_confirmation import confirm_peak
                _pk_ok, _pk_why, _pk_det = confirm_peak(bc, symbol, side)
                if not _pk_ok:
                    _skip("fix111_no_peak_confirm", symbol, side, _pk_why)
                    continue

                # 12f. 실 진입!
                entry_cfg = dict(cfg_base)
                entry_cfg["capitals"] = [base_capital]
                entry_cfg["leverage"] = int(cfg_base.get("leverage", DEFAULT_LEVERAGE))
                new_strategy = _create_auto_bb_strategy(
                    db, symbol, side, entry_cfg,
                    strategy_type_suffix="_UNIFIED_15M",
                )
                if not new_strategy:
                    _skip(
                        "create_strategy_failed", symbol, side,
                        f"capital={base_capital:.2f} lev={entry_cfg['leverage']}x (재시도!)",
                    )
                    continue

                # 12g. StrategySuggestion 저장 (학습!)
                _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
                entry_snapshot = {
                    "rsi": snap15.get("rsi_now"),
                    "cci": snap15.get("cci_now"),
                    "obv_slope_pct": snap15.get("obv_dir"),   # Fix 228
                    "regime": "NEUTRAL",
                    "sustained_bars": 0,
                    "change_24h": float(t.get("priceChangePercent", 0) or 0),
                    "source": "UNIFIED_15M",
                    "kst_hour": _kst_hour,
                    "confidence": confidence,
                    "score_15m": v.get("score_15m"),
                    "opp_score_1h": v.get("opp_score_1h"),
                    "opp_score_4h": v.get("opp_score_4h"),
                    "surge_meta": surge_meta,
                    "spec_version": "v224",
                    "entered_at": datetime.now(timezone.utc).isoformat(),
                }
                sugg = StrategySuggestion(
                    symbol=symbol, side=side,
                    suggestion_type=SUGGESTION_TYPE,
                    strategy_config={
                        **entry_cfg,
                        "symbol": symbol, "side": side,
                        "unified_15m": True,
                        "entry_snapshot": entry_snapshot,
                    },
                    confidence_score=Decimal(str(round(confidence, 4))),
                    reason=(
                        f"🌟 통합 15m 진입 (v224)! "
                        f"급등/급락={surge_meta.get('matched_window')} "
                        f"({surge_meta.get('matched_pct', 0):+.2f}%) "
                        f"conf={confidence*100:.0f}% "
                        f"15m={v.get('score_15m')}/5 "
                        f"opp(1h={v.get('opp_score_1h')},4h={v.get('opp_score_4h')}) "
                        f"24h={float(t.get('priceChangePercent', 0) or 0):+.1f}% "
                        f"RSI={snap15.get('rsi_now')} CCI={snap15.get('cci_now')} "
                        f"KST={_kst_hour:02d}h"
                    ),
                    status="EXECUTED",
                    execution_mode="AUTO",
                    executed_at=datetime.now(timezone.utc),
                    executed_strategy_id=new_strategy.id,
                    outcome_status="PENDING",
                )
                db.add(sugg)
                db.commit()

                entered += 1
                results.append({
                    "symbol": symbol, "side": side,
                    "confidence": confidence,
                    "capital": base_capital,
                    "strategy_id": new_strategy.id,
                    "surge": surge_meta,
                })

                logger.warning(
                    "[unified_15m_v224] ✅ 통합 진입: #%d %s %s "
                    "conf=%.2f 급등/급락=%s(%+.2f%%) 15m=%d/5",
                    new_strategy.id, symbol, side, confidence,
                    surge_meta.get("matched_window"),
                    surge_meta.get("matched_pct", 0),
                    v.get("score_15m", 0),
                )

                # 12h. 텔레그램!
                try:
                    from app.services.notification_service import NotificationService
                    _db_n = SessionLocal()
                    try:
                        _ns = NotificationService(_db_n)
                        emoji = "🐻" if side == "SHORT" else "🐂"
                        _ns.send_system_alert(
                            title=(
                                f"🌟 [v224 통합] {symbol} {side} 진입! "
                                f"({confidence*100:.0f}%)"
                            ),
                            body=(
                                f"{emoji} 15m 급등/급락 통합 자동 진입!\n"
                                f"심볼: {symbol} {side}\n"
                                f"자본: {base_capital:.2f} USDT × {int(entry_cfg['leverage'])}x\n"
                                f"신뢰도: {confidence*100:.0f}% "
                                f"(15m={v.get('score_15m')}/5)\n"
                                f"트리거: {surge_meta.get('matched_window')} "
                                f"= {surge_meta.get('matched_pct', 0):+.2f}%\n"
                                f"24h: {float(t.get('priceChangePercent', 0) or 0):+.1f}%\n"
                                f"오늘 {used + entered}/{daily_limit}"
                            ),
                        )
                    finally:
                        try:
                            _db_n.close()
                        except Exception:
                            pass
                except Exception as _te:
                    logger.warning("[unified_15m_v224] telegram 실패: %s", _te)

                # 12i. 오케스트라 EventBus!
                try:
                    from app.agents.orchestrator.event_bus import get_event_bus
                    from app.agents.orchestrator.event_types import EventType
                    get_event_bus().publish(EventType.AUTO_ENTRY_TRIGGERED, {
                        "strategy_id": new_strategy.id,
                        "symbol": symbol, "side": side,
                        "prob": confidence,
                        "source": "UNIFIED_15M",
                        "surge": surge_meta,
                    })
                except Exception as _be:
                    logger.debug("[unified_15m_v224] EventBus 실패: %s", _be)

            except Exception as e:
                # 예외 = 대상 심볼 skip으로 집계 (재시도 대상!)
                _skip("exception", symbol, None, f"err={e!r}")
                logger.warning(
                    "[unified_15m_v224] %s 처리 예외 상세: %s", symbol, e,
                )
                db.rollback()
                continue

        # 사장님 검증용 완료 로그 = 대상 심볼 skip 이유 breakdown!
        _reasons_str = " ".join(f"{k}={v}" for k, v in sorted(skip_reasons.items())) or "-"
        logger.info(
            "[unified_15m_v224] 완료: scanned=%d no_candles=%d no_surge=%d "
            "surges=%d entered=%d skipped=%d [%s] (daily %d/%d) "
            "| Fix254 평가=%d 전환=%d 오류=%d",
            scanned, no_candles, no_surge, surges_found, entered, skipped,
            _reasons_str, used + entered, daily_limit,
            sb_evaluated, sb_matched, sb_error,
        )
        payload = {
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "daily_limit": daily_limit,
            "used_before": used,
            "remaining_before": remaining,
            "entered_today": used + entered,
            "scanned": scanned,
            "no_candles": no_candles,
            "no_surge": no_surge,
            "surges_found": surges_found,
            "sb_evaluated": sb_evaluated,
            "sb_matched": sb_matched,
            "sb_error": sb_error,
            "entered": entered,
            "skipped": skipped,
            "skip_reasons": skip_reasons,
            "surges": surges,
            "results": results,
            "spec_version": "v224",
        }
        # 🌟 사장님 요구 (2026-08-23): Redis 저장 = UI 실시간 모니터링용!
        # Key: unified_15m:monitoring / TTL: 60s (매 30초 실행 = 항상 fresh!)
        try:
            import json as _json
            from app.core.redis_client import get_redis_client
            _r = get_redis_client()
            _r.setex(
                "unified_15m:monitoring",
                60,
                _json.dumps(payload, ensure_ascii=False, default=str),
            )
        except Exception as _re:
            logger.debug("[unified_15m_v224] Redis 저장 실패(무시): %s", _re)
        return payload
    except Exception as e:
        logger.exception("[unified_15m_v224] 예외: %s", e)
        return {"error": str(e), "entered": entered}
    finally:
        try:
            db.close()
        except Exception:
            pass
