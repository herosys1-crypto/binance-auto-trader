"""📐 볼밴 중단선 4종 전략 워커 — 별도 전략 (Fix 278).

사장님 (2026-09-02):
  "상승중 볼밴 중단지지와 중단저항 그리고 중단돌파 중단하락돌파에도
   우리 시스템로직이 상승과 하락이 판단되면 이것도 포지션에 진입해줘 **이전략은 빼줘**"
  "이전략은 **15분 차트를 기준**이야 **1시간과 4시간은 참고용**으로 사용해줘"

판정 본체는 `app/services/bb_mid_line.py` (순수 함수). 실측 근거도 거기 있다.

## 모드 (설정 `bb_mid_line_mode`)

    off     아무것도 안 한다
    shadow  **기본값** — 판정만 하고 로그·Redis 에 남긴다 (자금 안 나감)
    on      실제 진입

  🚨 기본 shadow 인 이유: 이 규칙은 신호가 **많다**. 실측 10.4일/130심볼에서
     중단 저항만 1188건(≈114건/일) 이다. 한 번도 안 돌아본 경로로 실자금이
     그만큼 나가면 안 된다 (헌법 161). 전용 동시 상한도 함께 건다.
     사장님이 실적 보고 `on` 으로 바꾸시면 된다.

## 「15분 기준 / 1H·4H 참고」를 어떻게 구현했나

  • **자리(트리거)는 전부 15분봉**이다 — 중단선 터치·돌파 판정에 다른 봉을 안 쓴다.
  • **1H·4H 는 매 신호마다 계산해 기록**한다 (로그·Redis = 참고).
  • 4H 확인을 **진입 조건으로 거는 것은 「중단 하락돌파」 하나뿐**이다.
    실측이 명확히 요구한다 (없으면 전반 -166.11 = 과적합 실패 / 넣으면 +89.10).
    규칙마다 `bb_mid_line_{패턴}_need_4h` 로 끌 수 있다.

  🚨 방향 판정을 **15m MACD 로 하면 전부 나빠진다** (실측):
       중단 지지 LONG +214 -> **-294** / 중단 저항 +785 -> +634
     사장님 사상 ⑥ 「4H = 확정된 흐름 / 15m = 진입 타이밍」이 여기서도 맞다.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SPEC = "bb_mid_line_v1_fix278_2026-09-02"

MODE_KEY = "bb_mid_line_mode"                  # off | shadow | on
MODE_DEFAULT = "shadow"
MAX_CONCURRENT_KEY = "bb_mid_line_max_concurrent"
MAX_CONCURRENT_DEFAULT = 3                     # 표본 없음 — 보수적. 실적 보고 조정.
CAPITAL_KEY = "bb_mid_line_capital"
CAPITAL_DEFAULT = 100.0
SL_PRICE_PCT_KEY = "bb_mid_line_sl_price_pct"
SL_PRICE_PCT_DEFAULT = 5.0                     # 가격 -5% = 레버 2 에서 ROI -10%
TOP_N_KEY = "bb_mid_line_top_n"
TOP_N_DEFAULT = 30
LEVERAGE = 2
# 🚨 Fix 281: 백테스트 가정(TP +5% ROI)에 맞춘다. pump_split(Fix 205)과 같은 모양.
TP_PERCENTS = (5.0, 10.0, 15.0, 20.0)
TRAILING_PCT = 3.0
# 🚨 Fix 287 (2026-09-02, 감사 발견): 백테스트는 **최대 48시간 보유**를 가정했는데
#   시스템에 시간 기반 청산이 하나도 없다 (time_reverse_exit 는 스케줄러에서 주석 처리).
#   TP(+5%)에도 SL(-10%)에도 안 닿는 포지션이 전용 슬롯 3개를 영구 점유한다.
MAX_HOLD_HOURS_KEY = "bb_mid_line_max_hold_hours"
MAX_HOLD_HOURS_DEFAULT = 48.0
# 🚨 Fix 288: 백테스트 하네스는 같은 심볼 재진입에 **32봉(=8시간) 쿨다운**을 뒀다.
#   실서비스에 그게 없으면 손절당한 심볼에 다음 15분봉에서 곧바로 다시 들어간다
#   = 측정한 표본과 다른 매매가 된다.
COOLDOWN_HOURS_KEY = "bb_mid_line_cooldown_hours"
COOLDOWN_HOURS_DEFAULT = 8.0

STRATEGY_TYPE = "bb_mid_line"
TEMPLATE_PREFIX = "BB_MIDLINE"

REDIS_KEY = "bb_mid_line:signal:{sym}"
REDIS_TTL = 3600


def _setting(db, key: str, default):
    from app.models.system_setting import SystemSetting
    try:
        row = db.get(SystemSetting, key)
        if row is None or row.value is None or not str(row.value).strip():
            return default
        raw = str(row.value).strip()
        if isinstance(default, bool):
            return raw.lower() in ("1", "true", "on", "yes")
        if isinstance(default, int):
            return int(float(raw))
        if isinstance(default, float):
            return float(raw)
        return raw
    except Exception as e:
        logger.warning("[bb_mid] %s 조회 실패 → 기본 %r: %s", key, default, e)
        return default


def _mode(db) -> str:
    v = str(_setting(db, MODE_KEY, MODE_DEFAULT)).lower()
    return v if v in ("off", "shadow", "on") else MODE_DEFAULT


def _close_expired(db, max_hold_hours: float) -> int:
    """Fix 287 — 보유 시간이 지난 BB_MIDLINE 포지션을 전량 시장가 청산한다.

    ⚠️ **이 전략 전용**이다. time_reverse_exit(4시간)를 그냥 켜면 전 전략에 적용돼
       다른 전략들이 통째로 다른 매매가 된다 (그래서 꺼져 있다 — Fix 198).
    """
    if not max_hold_hours or max_hold_hours <= 0:
        return 0
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.core.strategy_status import ACTIVE_LIKE
    from app.models.strategy_instance import StrategyInstance
    from app.models.strategy_template import StrategyTemplate

    cutoff = datetime.now(timezone.utc) - timedelta(hours=float(max_hold_hours))
    closed = 0
    try:
        rows = db.execute(
            select(StrategyInstance)
            .join(StrategyTemplate,
                  StrategyTemplate.id == StrategyInstance.strategy_template_id)
            .where(StrategyTemplate.name.ilike(f"{TEMPLATE_PREFIX}%"))
            .where(StrategyInstance.status.in_(tuple(ACTIVE_LIKE)))
            .where(StrategyInstance.current_position_qty.isnot(None))
            .where(StrategyInstance.current_position_qty != 0)
        ).scalars().all()
    except Exception as e:
        logger.warning("[bb_mid] Fix287 조회 실패: %s", e)
        return 0

    for si in rows:
        started = getattr(si, "started_at", None)
        if started is None:
            continue                       # 아직 체결 전 = 시간 판정 불가
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if started > cutoff:
            continue
        qty = abs(float(si.current_position_qty or 0))
        if qty <= 0:
            continue
        try:
            from decimal import Decimal

            from app.services.execution_service import ExecutionService
            ExecutionService(db).emergency_close_position(
                si.id, quantity=Decimal(str(qty)))
            si.last_error_message = (
                f"[Fix287] 최대 보유 {max_hold_hours:g}시간 초과 청산 ({SPEC})")
            db.commit()
            closed += 1
            logger.warning("[bb_mid] ⏰ #%s %s %s — 보유 %.1f시간 초과 전량 청산",
                           si.id, si.symbol, si.side,
                           (datetime.now(timezone.utc) - started).total_seconds() / 3600)
        except Exception as e:
            db.rollback()
            logger.warning("[bb_mid] Fix287 #%s 청산 실패: %s", si.id, e)
    return closed


def _in_cooldown(db, symbol: str, side: str, hours: float) -> bool:
    """Fix 288 — 같은 심볼·방향에 최근 진입이 있었는가 (하네스의 32봉 쿨다운)."""
    if not hours or hours <= 0:
        return False
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.models.strategy_instance import StrategyInstance
    from app.models.strategy_template import StrategyTemplate

    cutoff = datetime.now(timezone.utc) - timedelta(hours=float(hours))
    try:
        row = db.execute(
            select(StrategyInstance.created_at)
            .join(StrategyTemplate,
                  StrategyTemplate.id == StrategyInstance.strategy_template_id)
            .where(StrategyTemplate.name.ilike(f"{TEMPLATE_PREFIX}%"))
            .where(StrategyInstance.symbol == symbol)
            .where(StrategyInstance.side == side)
            .order_by(StrategyInstance.id.desc()).limit(1)
        ).scalar_one_or_none()
    except Exception as e:
        # 🚨 조회 실패 = 쿨다운 중으로 간주 (fail-closed). 자본이 나가는 판정이다.
        logger.warning("[bb_mid] Fix288 조회 실패 = 쿨다운으로 간주: %s", e)
        return True
    if row is None:
        return False
    if row.tzinfo is None:
        row = row.replace(tzinfo=timezone.utc)
    return row > cutoff


def run_bb_mid_line_once() -> dict:
    """한 사이클. 15분봉 중단선 4종을 판정한다."""
    from app.core.database import SessionLocal
    from app.services import bb_mid_line as M

    out: dict[str, Any] = {
        "spec": SPEC, "mode": "off", "scanned": 0, "signals": 0,
        "entered": 0, "blocked": {}, "errors": 0,
    }

    def _blk(k: str):
        out["blocked"][k] = out["blocked"].get(k, 0) + 1

    db = SessionLocal()
    try:
        mode = _mode(db)
        out["mode"] = mode
        if mode == "off":
            return out

        from sqlalchemy import select

        from app.core.crypto import decrypt_text
        from app.integrations.binance.client import BinanceClient
        from app.models.exchange_account import ExchangeAccount
        from app.services.market_movers import rank_map

        acc = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if acc is None:
            logger.warning("[bb_mid] mainnet 계정 없음")
            return out
        bc = BinanceClient(api_key=decrypt_text(acc.api_key_enc),
                           api_secret=decrypt_text(acc.api_secret_enc),
                           is_testnet=False)

        top_n = int(_setting(db, TOP_N_KEY, TOP_N_DEFAULT))
        capital = float(_setting(db, CAPITAL_KEY, CAPITAL_DEFAULT))
        sl_price = float(_setting(db, SL_PRICE_PCT_KEY, SL_PRICE_PCT_DEFAULT))
        cap_n = int(_setting(db, MAX_CONCURRENT_KEY, MAX_CONCURRENT_DEFAULT))
        max_hold = float(_setting(db, MAX_HOLD_HOURS_KEY, MAX_HOLD_HOURS_DEFAULT))
        cool_h = float(_setting(db, COOLDOWN_HOURS_KEY, COOLDOWN_HOURS_DEFAULT))
        # Fix 287: 보유 시간 초과분을 **먼저** 정리한다 (슬롯을 비우고 시작)
        out["closed_expired"] = _close_expired(db, max_hold) if mode == "on" else 0

        # 패턴별 스위치 — 실측 통과분만 기본 ON (bb_mid_line.PATTERN_DEFAULT_ON)
        on_map = {p: bool(_setting(db, f"bb_mid_line_{p}_enabled",
                                   M.PATTERN_DEFAULT_ON[p])) for p in M.PATTERNS}
        need4h = {p: bool(_setting(db, f"bb_mid_line_{p}_need_4h",
                                   M.PATTERN_NEEDS_4H[p])) for p in M.PATTERNS}
        if not any(on_map.values()):
            out["blocked"]["all_patterns_off"] = 1
            return out

        try:
            tickers = bc.get_24hr_ticker()
        except Exception as e:
            logger.warning("[bb_mid] 티커 조회 실패: %s", e)
            out["errors"] += 1
            return out
        # 🚨 rank_map 은 (심볼이 아니라) **티커 dict** 를 돌려준다
        symbols = [str(t.get("symbol") or "")
                   for (t, _sd, _rk) in rank_map(tickers, top_n)]
        symbols = [x for x in symbols if x]
        # Fix 336: 이미 받아 둔 24h 티커에서 심볼별 변동률을 뽑는다 (추가 API 호출 0)
        _chg24_map: dict[str, float] = {}
        for _t in (tickers or []):
            try:
                _chg24_map[str(_t.get("symbol") or "")] = float(_t.get("priceChangePercent") or 0)
            except Exception:
                continue
        _resist_4h_ref = bool(_setting(db, "bb_mid_resist_4h_ref_enabled", True))

        from app.services.bb_entry_rules import band_series
        from app.services.trend_4h_gate import check_hist_rising

        for sym in symbols:
            out["scanned"] += 1
            try:
                kl = bc.get_klines(symbol=sym, interval="15m", limit=120)
            except Exception as e:
                logger.debug("[bb_mid] %s 캔들 실패: %s", sym, e)
                out["errors"] += 1
                continue
            if not kl or len(kl) < 40:
                _blk("kline_short")
                continue

            closes = [float(k[4]) for k in kl]
            highs = [float(k[2]) for k in kl]
            lows = [float(k[3]) for k in kl]
            mid, _up, _lo = band_series(closes)
            if not mid:
                _blk("band_fail")
                continue

            res = M.evaluate_mid_line(closes, highs, lows, mid)
            hits = [h for h in res.get("hits", []) if on_map.get(h)]
            if not hits:
                continue

            for pat in hits:
                side = M.PATTERN_SIDE[pat]
                label = M.PATTERN_LABEL[pat]
                out["signals"] += 1

                # ── 1H·4H = 참고 (항상 계산해 기록한다) ──────────────────
                ref: dict[str, Any] = {}
                for tf in ("1h", "4h"):
                    try:
                        # Fix 291: 15m 트리거와 같이 **완료봉**으로 본다
                        ok, d = check_hist_rising(bc, sym, side, tf,
                                                  use_completed=True)
                        ref[tf] = {"my_side_rising": ok, **(d or {})}
                    except Exception as e:
                        ref[tf] = {"error": str(e)[:120]}

                # ── 4H 확인을 **필수**로 거는 패턴만 차단한다 ────────────
                if need4h.get(pat):
                    ok4 = ref.get("4h", {}).get("my_side_rising")
                    # 🚨 Fix 286 (2026-09-02): **fail-CLOSED** 로 바꾼다.
                    #   이 패턴은 4H 확인이 없으면 실측 전반이 -166.11 = 과적합 실패다
                    #   (이 파일 윗부분에 그렇게 적어 뒀다). 그런데 옛 코드는 4H 판정이
                    #   None(캔들 부족·API 실패·MACD 계산 불가)이면 통과시켰다 =
                    #   API 가 흔들리는 순간마다 「측정에서 탈락한 규칙」으로 실자금이 나간다.
                    #   자본이 나가는 판정은 모르면 **안 하는** 쪽이 맞다.
                    if ok4 is not True:
                        _blk(f"{pat}_no_4h" if ok4 is False else f"{pat}_4h_unknown")
                        logger.info("[bb_mid] ⏳ %s %s %s — 4H %s (필수 규칙)",
                                    sym, side, label,
                                    "미지지" if ok4 is False else "판정 불가")
                        continue

                logger.info(
                    "[bb_mid] 🎯 %s %s **%s** | %s | 참고 1H=%s 4H=%s | mode=%s",
                    sym, side, label, res.get("why"),
                    ref.get("1h", {}).get("my_side_rising"),
                    ref.get("4h", {}).get("my_side_rising"), mode,
                )

                # ── Redis 기록 (shadow 에서도 화면에 보이게) ─────────────
                try:
                    import json

                    from app.core.redis_client import get_redis_client
                    get_redis_client().setex(
                        REDIS_KEY.format(sym=sym), REDIS_TTL,
                        json.dumps({
                            "symbol": sym, "side": side, "pattern": pat,
                            "label": label, "why": res.get("why"),
                            "mid": res.get("mid"), "close": res.get("close"),
                            "ref_1h": ref.get("1h", {}).get("my_side_rising"),
                            "ref_4h": ref.get("4h", {}).get("my_side_rising"),
                            "mode": mode, "spec": SPEC,
                        }, ensure_ascii=False, default=str))
                except Exception as e:
                    logger.debug("[bb_mid] redis 기록 실패: %s", e)

                if mode != "on":
                    _blk("shadow")
                    continue

                # Fix 288: 같은 심볼 재진입 쿨다운 (하네스가 32봉 = 8시간을 뒀다)
                if _in_cooldown(db, sym, side, cool_h):
                    _blk("cooldown")
                    logger.info("[bb_mid] ⏳ %s %s — 최근 %g시간 내 진입 있음 (쿨다운)",
                                sym, side, cool_h)
                    continue

                # ── 실제 진입 ────────────────────────────────────────────
                # ═══════════════════════════════════════════════════════════
                # 🚨 Fix 336-a (2026-09-03): 「중단 저항」SHORT 에 **4H 참고**를 넣는다.
                #
                #   실측: 오늘 bb_mid_line 29건 **전부 SHORT, 합계 -29.12**.
                #   PYTHUSDT — 4H RSI 68/69/64, MACD hist 양수 확대, OBV 상승 = 명확한
                #   상승인데 15분 중단선 터치 하나만 보고 SHORT 가 나갔다.
                #   **상승 추세에서 중단선은 저항이 아니라 지지다.**
                #
                #   이 파일 헤더가 스스로 적어 놓았다: "4H 확인을 진입 조건으로 거는 것은
                #   「중단 하락돌파」 하나뿐". mid_resist 는 4H 를 전혀 안 봤다.
                #
                #   ⚠️ 패턴을 **끄지 않는다** — +785.11 (전 +294 / 후 +558, 양쪽 절반 양수).
                #   사장님 정정 「15분이 기준, 4시간은 참고」대로: 4H 가 **명확한 상승**
                #   (hist 가 LONG 편으로 커지는 중)일 때만 SHORT 를 내지 않는다.
                #   판정 함수는 trend_4h_gate.check_hist_rising 재사용 (중복 정의 금지).
                #   되돌리기: bb_mid_resist_4h_ref_enabled = 0
                # ═══════════════════════════════════════════════════════════
                if pat == "mid_resist" and side == "SHORT" and _resist_4h_ref:
                    try:
                        _up4h, _d4h = check_hist_rising(bc, sym, "LONG", "4h")
                    except Exception as _e336:
                        _up4h, _d4h = None, {"reason": str(_e336)[:80]}
                    if _up4h is True:
                        _blk("resist_4h_uptrend")
                        logger.info("[bb_mid/Fix336] ⏸ %s 중단저항 SHORT 보류 — 4H 가 명확한 상승 "
                                    "(hist LONG 편으로 확대 중) | %s", sym, _d4h)
                        continue
                # ═══════════════════════════════════════════════════════════
                # 🎯 Fix 336-b: 적응 TP (Fix 299) 를 이 워커에도 배선한다.
                #   감사 실측: adaptive_tp 호출처가 auto_bb_breakdown_worker **단 1개**였다.
                #   이 워커는 TP_PERCENTS(15%) 고정 → 안정 종목에서 절대 안 닿는다
                #   (607건 중 ROI +15% 도달 3건 = 0.5%). 사장님 사양: 급등락 15 / 안정 3~5.
                #   auto_bb 와 같은 pick_tp1 + tp_ladder_from_tp1 을 쓴다.
                # ═══════════════════════════════════════════════════════════
                _tp_percents = TP_PERCENTS
                try:
                    from app.services.adaptive_tp import (
                        adaptive_tp_enabled as _atp_on, pick_tp1 as _atp_pick,
                        tp_ladder_from_tp1 as _atp_ladder,
                    )
                    if _atp_on(db):
                        _tp1, _why299, _d299 = _atp_pick(db, _chg24_map.get(sym))
                        _tp_percents = _atp_ladder(_tp1, len(TP_PERCENTS) or 4)
                        logger.info("[Fix299/적응TP] %s %s — %s | 사다리 %s",
                                    sym, side, _why299, _tp_percents)
                except Exception as _e299:
                    logger.warning("[Fix299] 적응 TP 오류 (기존 TP 유지): %s", _e299)
                    _tp_percents = TP_PERCENTS
                try:
                    from app.services.surge_ladder_entry import create_surge_position
                    st = create_surge_position(
                        db, symbol=sym, capital=capital, sl_price_pct=sl_price,
                        attempt_no=1, leverage=LEVERAGE, side=side,
                        template_prefix=TEMPLATE_PREFIX, strategy_type=STRATEGY_TYPE,
                        cap_key=MAX_CONCURRENT_KEY, cap_default=cap_n,
                        # 🚨 Fix 281: 백테스트가 **TP +5% ROI** 가정이었다.
                        #   기본값(15/20/25/30)을 그대로 두면 측정한 규칙과 다른 매매가
                        #   된다 (+15% 를 가야 첫 익절 = 레버 2 에서 가격 7.5%).
                        #   pump_split 과 같은 검증된 모양(5/10/15/20 + 트레일링 -3%)을 쓴다.
                        tp_percents=_tp_percents, trailing_pct=TRAILING_PCT,
                    )
                    if st is not None:
                        out["entered"] += 1
                        logger.warning("[bb_mid] ✅ 진입 #%s %s %s %s (자본 %.0f)",
                                       st.id, sym, side, label, capital)
                    else:
                        _blk("entry_declined")
                except Exception as e:
                    out["errors"] += 1
                    logger.warning("[bb_mid] %s 진입 예외: %s", sym, e)

        return out
    except Exception as e:
        out["errors"] += 1
        logger.exception("[bb_mid] 사이클 실패: %s", e)
        return out
    finally:
        try:
            logger.warning("[bb_mid] DONE: %s", out)
        finally:
            db.close()
