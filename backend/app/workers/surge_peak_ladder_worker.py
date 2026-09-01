"""🎯 급등 정점 SHORT 사다리 워커 — 이기면 늘리고, 지면 다시 (Fix 267).

사장님 지시 (2026-09-01):
  "당일 급등하는 1위 10위까지만 모니터링하고 우리로직상 최고점에 조정 시작할 심볼에
   1단계 500 진입하고 손절 -5%에서 청산하고 다시 대기모니터링하고 ... 2단계 1000 ... -10%"
  정정: "두번 실패하면 250인거야. **당연히 첫진입부터 성공해서 포지션 추가를 하고 싶은거야**"
  선택: "**C**로 시작해 실적 보고 B → A"   (C = 추가 절반 + 손실 고정)
  "이건 **새로운 전략**이야"

판정식·실측 근거는 app/services/surge_peak_ladder.py 상단에 전부 있다.
기획서: docs/spec/SURGE_TOP10_PEAK_LADDER_SPEC_2026-09-01.md

## 🚨 모드 (기본 off)

    surge_ladder_mode = off      아무것도 안 한다 (기본)
                      = shadow   판정만 하고 **기록**한다 (진입 X)
                      = on       실제로 진입한다

**지금은 shadow 가 실질적인 배포 형태다.** 가용 잔액이 46.73 USDT 이고
1시도 preflight 만 525 USDT 가 필요해서 on 으로 켜도 진입이 되지 않는다.
shadow 로 며칠 돌리면 「켰으면 몇 건이 어떻게 됐나」를 실거래 표본으로 알 수 있다.
합의 게이트(Fix 247)가 정확히 그 경로로 검증됐다.

## 🚨 on 으로 켜기 전에 반드시 해소해야 하는 것 (검증에서 확인된 구조적 차단)

 ① **합의 게이트(Fix 247)가 모집단 자체를 차단한다.** SHORT 이 D등급을 면하려면
    4H EMA50 DOWN + 이치모쿠 구름 아래여야 하는데 급등 종목은 정의상 반대다.
 ② `sajangnim_capital_ladder` 는 **전 시스템 공유** — 이 전략 자본은 전용 키로 둔다.
 ③ `sajangnim_top_short_daily_limit` 은 **계정 전체 동시보유 상한** — 활성 39건이면
    `_create_auto_bb_strategy` 가 이 로직이 돌기 전에 None 을 반환한다.
 ④ `STAGE3_24H_ABS_LIMIT_PCT = 15.0` — 24h ±15% 초과 SHORT 은 3단계 차단(헌법 64).
 ⑤ 템플릿 suffix 는 `_success`/`_reentry*` 만 매핑되고 그 외는 조용히 버려진다.

그래서 `on` 은 **아직 구현하지 않는다** — 위 5건을 풀지 않고 켜면
「켰는데 0건」이 되고 그 이유가 로그에 안 남는다(이 프로젝트가 반복해서 겪은 사고).
shadow 로 표본을 모으고, 그 표본으로 ①~⑤ 해소 우선순위를 정한다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.redis_client import get_redis_client
from app.models.surge_ladder_state import SurgeLadderState
from app.services.market_movers import rank_map
from app.services.surge_peak_ladder import (
    CAPITAL_LADDER,
    MAX_ATTEMPTS,
    SL_PRICE_LADDER,
    cycle_worst_case_loss,
    evaluate_surge_entry,
    sl_roi_for_price_pct,
    update_peak,
)

logger = logging.getLogger(__name__)

SETTING_KEY = "surge_ladder_mode"          # off | shadow | on
DEFAULT_MODE = "off"
TOP_N = 10
MIN_CHG = 15.0
LEVERAGE = 2.0

# 그림자 기록 (며칠 뒤 「켰으면 어땠나」를 계산할 표본)
_SHADOW_KEY = "surge_ladder:shadow:{sym}:{ts}"
_SHADOW_TTL = 60 * 60 * 24 * 14
# 화면 배선 — pump_top_detector 와 **같은 키 모양**이라 /v219-monitoring 이 그대로 읽는다
_SCAN_KEY = "pump_top:scanned:{sym}"
_SCAN_TTL = 1800


def _mode(db) -> str:
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, SETTING_KEY)
        v = str(row.value).strip().lower() if row is not None and row.value else DEFAULT_MODE
    except Exception as e:
        logger.warning("[surge_ladder] 설정 조회 실패 = off: %s", e)
        return DEFAULT_MODE
    return v if v in ("off", "shadow", "on") else DEFAULT_MODE


def _state(db, symbol: str) -> SurgeLadderState:
    row = db.execute(
        select(SurgeLadderState)
        .where(SurgeLadderState.symbol == symbol)
        .where(SurgeLadderState.side == "SHORT")
    ).scalar_one_or_none()
    if row is None:
        row = SurgeLadderState(symbol=symbol, side="SHORT", status="WATCH")
        db.add(row)
        db.flush()
    return row


def _bb4h_broken(bc, symbol: str) -> bool | None:
    """최근 4H 종가가 볼밴 상단 밖이었던 적이 있는가 (사상 ①·⑥).

    ⚠️ 「지금 밖」이 아니라 「최근에 밖이었다」. 「지금 밖」을 요구하면 되돌아온
       자리에서 진입할 수 없어 조건이 서로를 막는다 (Fix 249 함정).
    """
    try:
        from app.services.chart_analyzer import ChartAnalyzer
        a = ChartAnalyzer.analyze_timeframe(bc, symbol, "4h", limit=60)
        if not a:
            return None
        # 🚨 키 이름은 `bb_up_last` 다 (`bb_up` 이 아니다 — chart_analyzer.py:315).
        #   `bb_up` 으로 쓰면 항상 None -> 이 조건이 영원히 미충족 ->
        #   진입이 수학적으로 불가능해진다 (Fix 249 와 같은 함정).
        up = a.get("bb_up_last")
        closes = a.get("closes") or []
        if up is None or len(closes) < 6:
            return None
        # ⚠️ 근사다: `bb_up_last` 는 **마지막 봉의 밴드 하나**이므로 각 봉의 자기 밴드와
        #    비교하지 못한다. 밴드가 넓어지는 국면에서는 과대 판정될 수 있다.
        #    표본이 쌓이면 봉별 밴드로 정밀화할 것.
        return any(float(c) > float(up) for c in closes[-6:])
    except Exception as e:
        logger.debug("[surge_ladder] %s 4H 분석 실패: %s", symbol, e)
        return None


def _obv_extreme_up(bc, symbol: str) -> bool | None:
    """OBV 가 극단 상승인가 (사상 ④ — 그러면 SHORT 자리가 아니다)."""
    try:
        from app.services.obv_gate import check_obv_gate
        ok, why = check_obv_gate(bc, symbol, "SHORT")
        # check_obv_gate 는 통과=True. 우리는 「극단 상승인가」를 원하므로 반전.
        return (not ok), why
    except Exception as e:
        logger.debug("[surge_ladder] %s obv_gate 실패: %s", symbol, e)
        return None


def run_surge_peak_ladder_once() -> dict:
    db = SessionLocal()
    stat = {
        "mode": DEFAULT_MODE, "scanned": 0, "eval": 0, "hit": 0,
        "shadow": 0, "err": 0, "miss": {},
    }
    try:
        mode = _mode(db)
        stat["mode"] = mode
        if mode == "off":
            logger.info(
                "[surge_ladder] OFF — 켜려면 SystemSetting %s = shadow (관측) / on (실진입). "
                "최악 손실 검산: 심볼당 사이클 %.0f USDT (2회 실패 시 250)",
                SETTING_KEY, cycle_worst_case_loss(LEVERAGE),
            )
            return stat

        from app.integrations.binance.client import BinanceClient
        from app.core.crypto import decrypt_text
        from app.models.exchange_account import ExchangeAccount
        acc = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if acc is None:
            return stat
        bc = BinanceClient(
            api_key=decrypt_text(acc.api_key_enc),
            api_secret=decrypt_text(acc.api_secret_enc),
            is_testnet=acc.is_testnet,
        )
        r = get_redis_client()
        now = datetime.now(timezone.utc)

        # ── 급등 1~10위 (market_movers 재사용 — 새로 만들지 않는다) ──
        tickers = bc.get_24hr_ticker()
        movers = [(t, rk) for (t, sd, rk) in rank_map(tickers, TOP_N) if sd == "UP"]
        stat["scanned"] = len(movers)

        for t, rank in movers:
            sym = str(t.get("symbol") or "")
            if not sym:
                continue
            try:
                chg = float(t.get("priceChangePercent") or 0)
                vol = float(t.get("quoteVolume") or 0)
                mk = r.get(f"mark_price:{sym}")
                mark = float(mk) if mk else float(t.get("lastPrice") or 0)
                if mark <= 0:
                    stat["miss"]["mark없음"] = stat["miss"].get("mark없음", 0) + 1
                    continue

                st = _state(db, sym)
                # ── 신고점 추적 (SHORT 이므로 고가) ──
                new_peak, moved = update_peak(st.peak_price, mark)
                if new_peak is not None and (st.peak_price is None or moved):
                    st.peak_price = Decimal(str(new_peak))
                    if moved:
                        st.peak_seen_at = now
                    if st.cycle_started_at is None:
                        st.cycle_started_at = now
                db.commit()

                bb4 = _bb4h_broken(bc, sym)
                obv_res = _obv_extreme_up(bc, sym)
                obv_up = obv_res[0] if isinstance(obv_res, tuple) else obv_res

                v = evaluate_surge_entry(
                    rank=rank, chg_24h=chg, quote_volume=vol,
                    mark=mark, peak=st.peak_price, peak_seen_at=st.peak_seen_at,
                    bb4h_broken=bb4, obv_extreme_up=obv_up,
                    now=now, min_rank=TOP_N, min_chg=MIN_CHG,
                )
                stat["eval"] += 1

                # ── 화면 배선 (기존 키 모양 그대로 = UI 작업 0) ──
                try:
                    r.setex(_SCAN_KEY.format(sym=sym), _SCAN_TTL, json.dumps({
                        "symbol": sym, "change_24h": chg, "rank": rank,
                        "trend": "SURGE_LADDER",
                        "passed_v219": bool(v.ok),
                        "sides_tested": ["SHORT"],
                        "reason": v.reason,
                        "scanned_at": now.isoformat(),
                    }, default=str))
                except Exception:
                    pass

                if not v.ok:
                    for k, res in v.checks.items():
                        if res is not True:
                            stat["miss"][k] = stat["miss"].get(k, 0) + 1
                    continue

                stat["hit"] += 1
                attempt = int(st.attempt_no or 0) + 1
                if attempt > MAX_ATTEMPTS:
                    stat["miss"]["시도 소진"] = stat["miss"].get("시도 소진", 0) + 1
                    continue
                cap = CAPITAL_LADDER[attempt - 1]
                sl_price = SL_PRICE_LADDER[attempt - 1]
                sl_roi = sl_roi_for_price_pct(sl_price, LEVERAGE)

                if mode == "shadow":
                    stat["shadow"] += 1
                    try:
                        r.setex(
                            _SHADOW_KEY.format(sym=sym, ts=int(now.timestamp())),
                            _SHADOW_TTL,
                            json.dumps({
                                "at": now.isoformat(), "symbol": sym, "rank": rank,
                                "chg_24h": chg, "mark": mark,
                                "peak": float(st.peak_price or 0),
                                "attempt": attempt, "capital": cap,
                                "sl_price_pct": sl_price, "sl_roi": sl_roi,
                                "detail": v.detail,
                            }, default=str),
                        )
                    except Exception:
                        pass
                    logger.info(
                        "[surge_ladder/shadow] 🔍 %s (급등 %d위 %+.1f%%) %d시도 "
                        "자본 %.0f SL 가격%.1f%%(ROI %.1f%%) — %s",
                        sym, rank, chg, attempt, cap, sl_price, sl_roi or 0, v.reason,
                    )
                    continue

                # mode == "on"
                # 🚨 아직 구현하지 않는다 — 파일 상단 ①~⑤ 를 풀지 않고 켜면
                #    「켰는데 0건」이 되고 그 이유가 로그에 남지 않는다.
                stat["miss"]["on 미구현"] = stat["miss"].get("on 미구현", 0) + 1
                logger.warning(
                    "[surge_ladder] ⚠️ %s 진입 조건 충족했으나 on 경로는 아직 없다 — "
                    "구조적 차단 5건(합의게이트/자본사다리 공유/동시보유 상한/24h필터/"
                    "템플릿 suffix)을 먼저 풀어야 한다. 지금은 shadow 로 표본을 모은다.",
                    sym,
                )
            except Exception as e:
                stat["err"] += 1
                logger.warning("[surge_ladder] %s 판정 실패: %s", sym, e)
                try:
                    db.rollback()
                except Exception:
                    pass

        miss = " ".join(f"{k}={n}" for k, n in sorted(
            stat["miss"].items(), key=lambda kv: -kv[1]))
        logger.info(
            "[surge_ladder] 완료(mode=%s): 대상=%d 평가=%d 적중=%d 그림자=%d 오류=%d%s",
            mode, stat["scanned"], stat["eval"], stat["hit"],
            stat["shadow"], stat["err"], f" | 미충족: {miss}" if miss else "",
        )
        return stat
    except Exception as e:
        logger.exception("[surge_ladder] 사이클 실패: %s", e)
        stat["err"] += 1
        return stat
    finally:
        db.close()
