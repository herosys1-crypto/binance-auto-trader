"""🎯 Fix 111 (2026-08-26): 정점 판정 단일 진실 서비스 (헌법 6!)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 verbatim (2026-08-26):
  "한번올랐다 다시 내려오고 이렇게 2-3번 반복하면
   rsi macd obv cci 등등 고점에 이란 신호를 보고 진입을 해야 하는 로직이야"
  ※ 사장님이 보여주신 차트 = 「15분 차트」!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Fix 106 의 잘못 (사장님 龙虾USDT 지적으로 발견!):
  (1) peak 카운트를 4H 로 했음 → 사장님 기준은 15m!
      → 龙虾USDT 처럼 4H 폭발 캔들 1~2개인 급등은 peak 0~1 = 무조건 차단
      → 15m 로 보면 계단식 2~3회 상승이 뚜렷했는데 놓침!
  (2) 4H MACD Hist 「양수 상승 중이면 금지」 하드 차단
      → 4H 는 후행지표! 급등 직후엔 항상 양수 상승 중!
      → 헌법 72 (급등 + BB 상단돌파 마틴게일 = 확실한 수익) 를 영구 봉쇄!

Fix 111 신 기준 (3중, 전부 통과해야 SHORT 허용):
  [A] 15m 반복 상승: swing peak >= MIN_PEAK_COUNT_15M (2회!)
      → STARUSDT(24h +41% 단일 상승) / TACUSDT(1H +154% 단일) 차단 유지!
      → 龙虾USDT(계단식 다중 상승) 는 통과!
  [B] 15m 지표 「극단 후 꺾임」: RSI / MACD Hist / CCI 중 MIN_TURNS(2) 이상
      → 「아직 오르는 중」과 「정점 지나 꺾임」을 구별하는 핵심!
      → TACUSDT(지표 꺾임 없음) 차단 / 龙虾(3개 다 꺾임) 통과!
  [C] 4H = 참고 정보만 (차단 X!)
      → macd_hist_4h 를 detail 에 담아 학습/로그용으로만 사용

LONG 대칭(confirm_long_bottom) 도 동일 구조 = 반복 하락 + 지표 저점 반등.

fail-open 원칙: 데이터 부족/조회 실패 = (True, "...") 통과!
  (게이트 오류가 기존 동작을 막지 않도록 = 헌법 대칭)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ─── 스펙 상수 (사장님 사상 = 15m 기준!) ────────────────────────────
PEAK_TF = "15m"              # 사장님이 보시는 차트!
PEAK_KLINE_LIMIT = 80        # 15m × 80 = 20시간
PEAK_LOOKBACK_BARS = 40      # 최근 10시간 창에서 반복 상승 카운트
PEAK_MIN_GAP = 3             # pivot 좌우 확인 봉수
MIN_PEAK_COUNT_15M = 2       # 사장님 verbatim = 최소 2회 반복!
MIN_TURNS = 2                # RSI/MACD/CCI 중 최소 2개 「꺾임」

RSI_HIGH = 65.0              # SHORT: 이 위에서 꺾여야 「고점 신호」
RSI_LOW = 35.0               # LONG: 이 아래에서 반등해야 「저점 신호」
CCI_HIGH = 80.0
CCI_LOW = -80.0


def count_swing_peaks(closes: list, lookback: int = PEAK_LOOKBACK_BARS,
                      min_gap: int = PEAK_MIN_GAP) -> int:
    """최근 lookback 봉에서 swing high(국지 고점) 개수.

    peak = 좌우 min_gap 봉 모두보다 높은 봉.
    사장님 「한번올랐다 다시 내려오고」 = 이 pivot 이 여러 개라는 뜻!
    """
    if not closes or len(closes) < min_gap * 2 + 1:
        return 0
    w = closes[-lookback:] if len(closes) > lookback else list(closes)
    n = 0
    for i in range(min_gap, len(w) - min_gap):
        try:
            c = float(w[i])
            if c > max(float(x) for x in w[i - min_gap:i]) and \
               c > max(float(x) for x in w[i + 1:i + min_gap + 1]):
                n += 1
        except Exception:
            continue
    return n


def count_swing_valleys(closes: list, lookback: int = PEAK_LOOKBACK_BARS,
                        min_gap: int = PEAK_MIN_GAP) -> int:
    """LONG 대칭 = swing low(국지 저점) 개수."""
    if not closes or len(closes) < min_gap * 2 + 1:
        return 0
    w = closes[-lookback:] if len(closes) > lookback else list(closes)
    n = 0
    for i in range(min_gap, len(w) - min_gap):
        try:
            c = float(w[i])
            if c < min(float(x) for x in w[i - min_gap:i]) and \
               c < min(float(x) for x in w[i + 1:i + min_gap + 1]):
                n += 1
        except Exception:
            continue
    return n


def _turns_for_short(a15: dict) -> tuple[int, dict]:
    """SHORT = 「극단 고점 + 꺾임」 카운트 (RSI / MACD Hist / CCI)."""
    d: dict[str, Any] = {}
    turns = 0

    rsi_now, rsi_prev = a15.get("rsi_now"), a15.get("rsi_prev")
    if rsi_now is not None and rsi_prev is not None:
        rn, rp = float(rsi_now), float(rsi_prev)
        ok = rp >= RSI_HIGH and rn < rp        # 고점 찍고 내려옴!
        d["rsi"] = {"now": rn, "prev": rp, "turn": ok}
        turns += 1 if ok else 0

    hist = a15.get("macd_hist") or []
    if len(hist) >= 2:
        hn, hp = float(hist[-1]), float(hist[-2])
        ok = hp > 0 and hn < hp                # 양수 peak 지나 감소!
        d["macd"] = {"now": hn, "prev": hp, "turn": ok}
        turns += 1 if ok else 0

    cci_now, cci_prev = a15.get("cci_now"), a15.get("cci_prev")
    if cci_now is not None and cci_prev is not None:
        cn, cp = float(cci_now), float(cci_prev)
        ok = cp >= CCI_HIGH and cn < cp
        d["cci"] = {"now": cn, "prev": cp, "turn": ok}
        turns += 1 if ok else 0

    return turns, d


def _turns_for_long(a15: dict) -> tuple[int, dict]:
    """LONG = 「극단 저점 + 반등」 카운트 (SHORT 대칭)."""
    d: dict[str, Any] = {}
    turns = 0

    rsi_now, rsi_prev = a15.get("rsi_now"), a15.get("rsi_prev")
    if rsi_now is not None and rsi_prev is not None:
        rn, rp = float(rsi_now), float(rsi_prev)
        ok = rp <= RSI_LOW and rn > rp
        d["rsi"] = {"now": rn, "prev": rp, "turn": ok}
        turns += 1 if ok else 0

    hist = a15.get("macd_hist") or []
    if len(hist) >= 2:
        hn, hp = float(hist[-1]), float(hist[-2])
        ok = hp < 0 and hn > hp                # 음수 바닥 지나 증가!
        d["macd"] = {"now": hn, "prev": hp, "turn": ok}
        turns += 1 if ok else 0

    cci_now, cci_prev = a15.get("cci_now"), a15.get("cci_prev")
    if cci_now is not None and cci_prev is not None:
        cn, cp = float(cci_now), float(cci_prev)
        ok = cp <= CCI_LOW and cn > cp
        d["cci"] = {"now": cn, "prev": cp, "turn": ok}
        turns += 1 if ok else 0

    return turns, d


def confirm_peak(bc, symbol: str, side: str) -> tuple[bool, str, dict]:
    """🎯 정점(SHORT) / 저점(LONG) 확인 = 모든 진입 경로 공통 게이트!

    Returns:
        (allowed, reason, detail)
        allowed=False → 진입 금지! reason 을 로그/skip 사유로 사용.

    fail-open: 데이터 부족·예외 = (True, "faildata_open", ...) 통과!
    """
    detail: dict[str, Any] = {"tf": PEAK_TF, "side": side}
    try:
        from app.services.chart_analyzer import ChartAnalyzer
        a15 = ChartAnalyzer.analyze_timeframe(bc, symbol, PEAK_TF, limit=PEAK_KLINE_LIMIT)
        if not a15:
            return True, "no_15m_analysis(fail-open)", detail

        closes = a15.get("closes") or []

        # ── [A] 반복 상승/하락 (사장님 「2-3번 반복」!) ──
        if side == "SHORT":
            swings = count_swing_peaks(closes)
            label = "반복상승"
        else:
            swings = count_swing_valleys(closes)
            label = "반복하락"
        detail["swings_15m"] = swings
        if swings < MIN_PEAK_COUNT_15M:
            return False, f"{label} {swings}회 < {MIN_PEAK_COUNT_15M} (단일 추세 = 초입!)", detail

        # ── [B] 지표 「극단 + 꺾임」 (사장님 「고점에 이란 신호」!) ──
        if side == "SHORT":
            turns, tdet = _turns_for_short(a15)
        else:
            turns, tdet = _turns_for_long(a15)
        detail["turns"] = turns
        detail["indicators"] = tdet
        if turns < MIN_TURNS:
            return False, f"지표 꺾임 {turns}/{MIN_TURNS} (아직 진행 중 = 정점 아님!)", detail

        # ── [C] 4H = 참고 정보만! (Fix 106 의 하드 차단 제거!) ──
        #   4H 는 후행지표라 급등 직후엔 항상 양수 상승 중 →
        #   차단 조건으로 쓰면 헌법 72(급등 BB상단돌파 마틴게일) 가 영구 봉쇄됨!
        try:
            a4 = ChartAnalyzer.analyze_timeframe(bc, symbol, "4h", limit=60)
            if a4:
                h4 = a4.get("macd_hist") or []
                detail["macd_hist_4h"] = float(h4[-1]) if h4 else None
                detail["rsi_4h"] = a4.get("rsi_now")
                detail["bb_up_4h"] = a4.get("bb_up_last")
                # 헌법 72 참고: 4H BB 상단 돌파 = 급등 정점 = 오히려 긍정 신호!
                try:
                    if closes and a4.get("bb_up_last"):
                        detail["bb4h_broken"] = float(closes[-1]) > float(a4["bb_up_last"])
                except Exception:
                    pass
        except Exception:
            pass

        return True, f"정점확인 OK ({label} {swings}회, 꺾임 {turns}/{MIN_TURNS})", detail

    except Exception as e:
        logger.warning("[Fix111/peak] %s %s 판정 예외 (fail-open): %s", symbol, side, e)
        return True, f"exception(fail-open): {e}", detail
