"""🎯 Fix 173 (2026-08-27): 단계 진입 신호 = 「지금 새로 진입한다면 통과할 조건」과 동일.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 verbatim (2026-08-27):
  "여기에 세팅으로 하면 단계별로 지정된 금액으로 포지션에 진입하게해줘
   기본에는 트리거%를 내가 임의로 정했는데 지금부터는 지금 운영중인 로직으로
   포지션에 들어가게 해줘 트리거 obv 전략이 이런 로직인데 지금까지 다음 포지션
   진입에 대한 신뢰가 없어서 사용하지 못했는데 가능할까? 일단 obv 로직에 만들어줘"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

■ 옛 OBV 트리거(ChartAnalyzer.check_obv_reverse_signal)가 신뢰를 못 받은 이유 4가지

  1. **SHORT 전용 하드코딩** — check_4h_first_bear_bar / check_15m_1h_bearish_trend
     둘 다 「하락」만 본다. LONG 전략에 걸면 방향이 반대라 사실상 발동하지 않는다.
  2. **3중 AND 가 지나치게 좁다** — (4H OBV 첫 하락봉) AND (15m+1h 하락추세)
     AND (손절가 대비 10% 이상 이동). 세 개가 동시에 성립하는 창이 매우 짧다.
  3. **운영 로직과 다르다** — 실제 자동 진입 워커는 obv_gate + confirm_peak 를 쓴다.
     즉 「자동 진입이 옳다고 판단하는 기준」과 「단계 진입이 판단하는 기준」이 **서로 달랐다.**
     사장님이 신뢰할 수 없던 근본 원인이 이것이다.
  4. **차단 사유가 남지 않는다** — 왜 안 들어갔는지 볼 수 없으니 신뢰가 생길 수 없다.

■ 이 모듈이 하는 일

  자동 진입 워커(auto_short_at_top / auto_long_at_bottom)가 쓰는 게이트를
  **같은 함수로, 같은 순서로** 호출한다. 새 판정 로직을 만들지 않는다.
  (헌법 6 = 단일 진실 / 헌법 101 = 읽는 함수가 여러 개면 반드시 어긋난다)

      ① check_obv_gate       (Fix 65/141)  — 4H OBV 극단 = 세력 반대 방향이면 차단
      ② is_bidirectional_blocked (Fix 66 P1) — 양방향 연속 실패 종목 차단
      ③ is_regime_blocked_for_short (Fix 66 P2) — SHORT 에만 적용
      ④ confirm_peak         (Fix 111)     — 핵심. 사장님 「2-3번 반복」 사상
                                             15m 반복 정점/저점 >= 2회
                                             + 지표(RSI/MACD/CCI) 꺾임 >= 2/3

  방향(LONG/SHORT)에 따라 자동으로 정점/저점을 판정한다 — 옛 로직의 1번 문제 해소.

■ 실패 처리 방향

  각 게이트는 **워커와 똑같이 fail-open** 한다 (게이트 자체 오류로 전 종목이
  멈추면 안 되므로). 대신 fail-open 했다는 사실을 detail 에 남겨 사장님이
  「통과인지 / 못 본 것인지」 구별할 수 있게 한다 (헌법 118).

  ⚠️ 여기서 fail-open 은 「신호 판정」에 한정된다. 상한·자본 게이트는
     여전히 fail-SAFE 다 (헌법 87) — 그건 호출부(stage_trigger_worker)가 맡는다.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["check_stage_entry_signal", "SIGNAL_MODE_LABEL"]

SIGNAL_MODE_LABEL = "운영 진입 로직 (obv_gate + 15m 정점확인)"


def check_stage_entry_signal(
    bc, db, symbol: str, side: str, *, min_swings: int | None = None,
) -> tuple[bool, str, dict]:
    """단계 진입 가능 여부 — 자동 진입 워커와 동일한 게이트.

    Args:
        bc: BinanceClient
        db: SQLAlchemy Session (blocklist 조회용. None 이면 그 게이트만 건너뛴다)
        symbol: 예 "BTCUSDT"
        side: "LONG" | "SHORT"

    Returns:
        (ok, reason, detail)
        ok=False → 아직 진입 시점이 아니다. reason 을 차단 사유로 기록할 것.
    """
    _side = (side or "").upper()
    detail: dict[str, Any] = {"side": _side, "symbol": symbol, "gates": {}}

    # ── ① OBV 게이트 (Fix 65/141) ──
    try:
        from app.services.obv_gate import check_obv_gate
        _ok, _why = check_obv_gate(bc, symbol, _side)
        detail["gates"]["obv_gate"] = {"ok": bool(_ok), "why": _why}
        if not _ok:
            return False, f"OBV 게이트: {_why}", detail
    except Exception as e:
        detail["gates"]["obv_gate"] = {"ok": None, "why": f"오류 fail-open: {e}"}
        logger.warning("[stage_entry_signal] %s obv_gate 오류 (fail-open): %s", symbol, e)

    # ── ② 양방향 실패 blocklist (Fix 66 P1) ──
    if db is not None:
        try:
            from app.services.bidirectional_blocklist import is_bidirectional_blocked
            _blocked, _why = is_bidirectional_blocked(db, symbol)
            detail["gates"]["blocklist"] = {"ok": not _blocked, "why": _why}
            if _blocked:
                return False, f"양방향 차단: {_why}", detail
        except Exception as e:
            detail["gates"]["blocklist"] = {"ok": None, "why": f"오류 fail-open: {e}"}
            logger.warning("[stage_entry_signal] %s blocklist 오류 (fail-open): %s", symbol, e)

    # ── ③ 급등/급락 regime (SHORT 전용, Fix 66 P2) ──
    if _side == "SHORT":
        try:
            from app.services.pump_dump_regime import is_regime_blocked_for_short
            _blocked, _why = is_regime_blocked_for_short(bc, symbol)
            detail["gates"]["regime"] = {"ok": not _blocked, "why": _why}
            if _blocked:
                return False, f"regime 차단: {_why}", detail
        except Exception as e:
            detail["gates"]["regime"] = {"ok": None, "why": f"오류 fail-open: {e}"}
            logger.warning("[stage_entry_signal] %s regime 오류 (fail-open): %s", symbol, e)

    # ── ③-b 진입 창 (SHORT 전용, Fix 248) — 「너무 빨리」와 「너무 늦게」를 둘 다 막는다 ──
    #
    #   사장님 verbatim (2026-08-31, SKRUSDT 차트를 보여주시며):
    #     "이렇게 큰하락에 포지션진입을 해야 하는데 **너무 빨리 진입하여 큰손실**을 본거야"
    #
    #   #1873 실측: 평단 0.019818 에 SHORT -> 정점 0.034856 (+75.9%) -> -724.80 청산.
    #   그 뒤 실제로 0.023 까지 (-33.8%) 내려왔다. **방향은 맞았고 타이밍만 일렀다.**
    #
    #   반대쪽 실패도 있다 (사장님 사상 ④):
    #     "볼밴 하단까지 갔다가도 obv가 강하면 이것도 다시 상승으로 전환된다고 봐야해"
    #
    #   두 실패는 정반대라 **양쪽 끝을 각각 막고 그 사이만 남긴다**.
    #   기본 OFF — 얼마나 막는지 먼저 본다. OFF 여도 「막았을 것」 로그는 남긴다.
    if _side == "SHORT":
        try:
            from app.services.chart_analyzer import ChartAnalyzer as _CA248
            from app.services.obv_metrics import obv_direction_ratio as _obv248
            from app.services.peak_drop_short import evaluate_peak_drop_short as _pd248
            from app.services.system_settings_service import SystemSettingsService as _SS248

            _a1 = _CA248.analyze_timeframe(bc, symbol, "1h", limit=120) or {}
            _c1 = _a1.get("closes") or []
            _bp248 = None
            _up248, _lo248 = _a1.get("bb_up_last"), _a1.get("bb_lo_last")
            try:
                if _c1 and _up248 is not None and _lo248 is not None and float(_up248) != float(_lo248):
                    _bp248 = (float(_c1[-1]) - float(_lo248)) / (float(_up248) - float(_lo248))
            except (TypeError, ValueError, ZeroDivisionError):
                _bp248 = None
            _mh248 = None
            _hl248 = _a1.get("macd_hist") or []
            if _hl248:
                try:
                    _mh248 = float(_hl248[-1])
                except (TypeError, ValueError):
                    _mh248 = None
            try:
                _od248 = _obv248(_a1.get("obv"), _a1.get("volumes"), 20)
            except Exception:
                _od248 = None

            _v248 = _pd248(
                closes=[float(x) for x in _c1] if _c1 else None,
                bb_pos=_bp248, macd_hist=_mh248, obv_dir=_od248,
            )
            detail["gates"]["entry_window"] = {
                "ok": bool(_v248.allow), "why": _v248.reason, **_v248.detail,
            }
            if not _v248.allow:
                _on248 = False
                try:
                    _on248 = _SS248(db).get_bool("entry_window_short_enabled", False) if db else False
                except Exception:
                    _on248 = False
                if _on248:
                    return False, f"진입창 차단: {_v248.reason}", detail
                logger.warning(
                    "[Fix248] ⚠️ %s SHORT 이 진입은 **막았을 것** — %s "
                    "(설정 OFF 이라 그대로 진행. 켜기: entry_window_short_enabled=1)",
                    symbol, _v248.reason,
                )
        except Exception as e:
            detail["gates"]["entry_window"] = {"ok": None, "why": f"오류 fail-open: {e}"}
            logger.warning("[Fix248] %s 진입창 판정 오류 (fail-open): %s", symbol, e)

    # ── ④ 정점/저점 확인 (Fix 111) = 핵심 ──
    #     사장님 사상: "한번올랐다 다시 내려오고 이렇게 2-3번 반복하면
    #                  rsi macd obv cci 등등 고점에 이란 신호를 보고 진입"
    try:
        from app.services.peak_confirmation import confirm_peak
        _ok, _why, _det = confirm_peak(bc, symbol, _side, min_swings=min_swings)
        detail["gates"]["confirm_peak"] = {"ok": bool(_ok), "why": _why}
        detail["peak_detail"] = _det
        if not _ok:
            return False, f"정점확인 미충족: {_why}", detail
        return True, f"진입 조건 충족 ({_why})", detail
    except Exception as e:
        # 핵심 게이트가 죽으면 판정 불가 — 여기서는 **진입하지 않는다**.
        # confirm_peak 내부는 데이터 부족 시 스스로 fail-open 하므로,
        # 여기까지 예외가 올라온 건 진짜 이상 상황이다 (헌법 118).
        detail["gates"]["confirm_peak"] = {"ok": None, "why": f"오류: {e}"}
        logger.error("[stage_entry_signal] %s confirm_peak 오류 → 진입 보류: %s", symbol, e)
        return False, f"정점확인 오류로 보류: {e}", detail
