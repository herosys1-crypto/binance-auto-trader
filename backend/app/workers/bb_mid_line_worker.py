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
                        ok, d = check_hist_rising(bc, sym, side, tf)
                        ref[tf] = {"my_side_rising": ok, **(d or {})}
                    except Exception as e:
                        ref[tf] = {"error": str(e)[:120]}

                # ── 4H 확인을 **필수**로 거는 패턴만 차단한다 ────────────
                if need4h.get(pat):
                    ok4 = ref.get("4h", {}).get("my_side_rising")
                    if ok4 is False:          # None = 판정 불가 → fail-open
                        _blk(f"{pat}_no_4h")
                        logger.info("[bb_mid] ⏳ %s %s %s — 4H 미지지 (참고 필수 규칙)",
                                    sym, side, label)
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

                # ── 실제 진입 ────────────────────────────────────────────
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
                        tp_percents=TP_PERCENTS, trailing_pct=TRAILING_PCT,
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
