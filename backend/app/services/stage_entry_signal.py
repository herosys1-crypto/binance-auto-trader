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


def check_stage_entry_signal(bc, db, symbol: str, side: str) -> tuple[bool, str, dict]:
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

    # ── ④ 정점/저점 확인 (Fix 111) = 핵심 ──
    #     사장님 사상: "한번올랐다 다시 내려오고 이렇게 2-3번 반복하면
    #                  rsi macd obv cci 등등 고점에 이란 신호를 보고 진입"
    try:
        from app.services.peak_confirmation import confirm_peak
        _ok, _why, _det = confirm_peak(bc, symbol, _side)
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
