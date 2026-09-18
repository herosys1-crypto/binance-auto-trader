"""🗺 Fix 379 (2026-09-19 사장님) — 기회 지도의 두 구간을 **가상매매 규칙**으로 등록해 새 데이터로 검증한다. 주문 0건.

사장님: "차트들을 분석해봐 그냥 모든 들어가는 포지션말고 들어가면 이익은 극대화되는 구간을 찾아줘"
        → "가상매매 규칙으로 추가해서 검증해줘"

근거 (docs/learning/OPPORTUNITY_ZONES_2026-09-19.md · 404종목 × 매 1시간 마감 83,927 자리 · 실매매 청산 규칙 24h):
  🟢 zone_l1_rebound_long  = 4시간 볼밴 하단 밖 종가 뒤 1~7봉(4~28시간) = 급락 뒤 반등 초입
       무작위 대비 10일 중 10일 우세 · 승률 64% · 손절률 3% · ROI 발견 +1.58 / 검증 +4.48
  🔴 zone_s4_spike_top_short = 하락 추세(일봉 하단권) 속 짧은 급반등의 꼭대기
       (4시간 저점 대비 +8% 초과 또는 1시간봉 16개 저점 대비 +12% 초과) & 1시간 ATR > 2.5% & 일봉 %B 하단권
       ROI 발견 +5.00 / 검증 +2.49 · 승률 72% · 손절률 15% · 표본 작음(404종목에서 하루 20종목 정도)

⚠️ 두 구간은 9일 전체를 보고 골랐다 → 이 규칙으로 **9/19 이후 새로 쌓이는 가상 진입**이 진짜 검증이다.
   그래서 아래 숫자는 **사전등록**이다 (모두 「Claude가 정함」). 검증 중에 바꾸면 그때까지 표본이 무효가 되므로
   설정키로 빼지 않고 여기 고정한다 — 바꿀 땐 규칙 키를 새로 만든다.

재현 원칙 (분석 스크립트 scripts/entry_condition_study/opportunity_scan.py 와 같은 계산):
  · 1시간 마감 봉에서만 판정한다 (분석이 매 1시간 마감 자리를 쟀다).
  · 지표는 운영 chart_state 와 같은 함수(bb_state · tf_indicators · hilo_position) · 기본 문턱(THRESHOLDS).
  · 「4시간 저점」 = 15분봉 16개 저점 = 분석의 5분봉 48개 저점과 같은 구간.
"""
from __future__ import annotations

from typing import Any, Sequence

from app.services import chart_state as CS

FIX = "Fix379"
MS_15M = 900_000
MS_1H = 3_600_000
TH: dict[str, float] = dict(CS.THRESHOLDS)

# ── 사전등록 숫자 (Claude가 정함 · 2026-09-19) ─────────────────────────────
L1_SINCE_MIN = 1                 # 4시간 하단 밖 종가가 최소 1봉 전 (0 = 지금 막 이탈 중 = 제외)
L1_SINCE_MAX = 7                 # 최대 7봉(28시간) 전까지
S4_LO4H_PCT = 8.0                # 최근 4시간 저점 대비 +8% 초과
S4_H1_LO_PCT = 12.0              # 1시간봉 16개 저점 대비 +12% 초과
S4_H1_BARS = 16
S4_ATR_1H_PCT = 2.5              # 1시간 ATR14 > 2.5%
S4_D1_POS = ("LOWER_HALF", "BELOW_LOWER")   # 일봉 볼밴 중단선 아래
MIN_BARS = 30                    # 볼밴·ATR 계산 최소 봉 (분석과 같음)

RULE_L1 = "zone_l1_rebound_long"
RULE_S4 = "zone_s4_spike_top_short"


def on_hour(kl15: Sequence[Sequence[float]]) -> bool:
    """마지막 15분봉이 1시간 마감 봉인가 (분석은 매 1시간 마감에서만 쟀다)."""
    return bool(kl15) and (int(kl15[-1][0]) + MS_15M) % MS_1H == 0


def h4_since_below_lower(kl4h: Sequence[Sequence[float]]) -> int | None:
    """4시간 볼밴 하단 밖 종가가 몇 봉 전인가 (없으면 None = 최근 창 안에 이탈 없음). chart_state._block('4h') 와 같은 값."""
    if len(kl4h) < MIN_BARS:
        return None
    bb = CS.bb_state(list(kl4h)[-60:], tol_pct=TH["tol_pct_4h"], lookback=TH["lookback_4h"],
                     slope_pct=TH["trend_slope_4h"], th=TH)
    return bb.get("bars_since_below_lower")


def l1_rebound(kl4h: Sequence[Sequence[float]]) -> bool:
    s = h4_since_below_lower(kl4h)
    return s is not None and L1_SINCE_MIN <= s <= L1_SINCE_MAX


def s4_spike(kl15: Sequence[Sequence[float]], kl1h: Sequence[Sequence[float]]) -> bool:
    """봉만으로 되는 부분 (급반등 + 변동성). 이게 참일 때만 일봉을 조회한다."""
    if len(kl15) < 16 or len(kl1h) < MIN_BARS:
        return False
    c = float(kl15[-1][4])
    lo4h = min(float(b[3]) for b in kl15[-16:])
    lo4h_pct = (c / lo4h - 1) * 100 if lo4h > 0 else None
    h1_lo = CS.hilo_position(list(kl1h), S4_H1_BARS).get("from_lo_pct")
    spike = (lo4h_pct is not None and lo4h_pct > S4_LO4H_PCT) or (h1_lo is not None and h1_lo > S4_H1_LO_PCT)
    if not spike:
        return False
    atr = CS.tf_indicators(list(kl1h)[-60:], TH).get("atr14_pct")
    return atr is not None and atr > S4_ATR_1H_PCT


def d1_low_half(kl1d: Sequence[Sequence[float]] | None) -> bool:
    if not kl1d or len(kl1d) < MIN_BARS:
        return False
    bb = CS.bb_state(list(kl1d)[-60:], tol_pct=TH["tol_pct_1d"], lookback=TH["lookback_1d"],
                     slope_pct=TH["trend_slope_1d"], th=TH)
    return bb.get("pos") in S4_D1_POS


def needs_daily(kl15: Sequence[Sequence[float]], kl1h: Sequence[Sequence[float]]) -> bool:
    """워커가 일봉을 받아야 하나 = S4 의 봉 조건이 이 1시간 마감에서 참. (조회 줄이기 — 대부분 False)"""
    return on_hour(kl15) and s4_spike(kl15, kl1h)


def _r_l1(ctx: Any) -> bool:
    return on_hour(ctx.kl15) and l1_rebound(ctx.kl4h)


def _r_s4(ctx: Any) -> bool:
    return on_hour(ctx.kl15) and s4_spike(ctx.kl15, ctx.kl1h) and d1_low_half(getattr(ctx, "kl1d", None))


# (key, side, label, fn) — chart_learning.RULES 가 Rule 로 감싼다 (external_strategies.PAPER_RULES 와 같은 방식)
PAPER_RULES: tuple[tuple[str, str, str, Any], ...] = (
    (RULE_L1, "LONG", "기회지도 L1: 4H 볼밴 하단 이탈 뒤 1~7봉 반등 초입 (Fix 379, 가상만)", _r_l1),
    (RULE_S4, "SHORT", "기회지도 S4: 하락추세 속 급반등 꼭대기 + 1H ATR>2.5 (Fix 379, 가상만)", _r_s4),
)
