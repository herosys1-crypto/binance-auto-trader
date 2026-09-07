"""🕯 Fix 360 (2026-09-07) — v2.20 「캔들 세력 공방」 수치화: 몸통·꼬리 → 진입 신호 / 추가(피라미딩) 지속 판정.

사장님이 주신 기획서 v2.20 (유튜브 캔들 공방 분석) 의 **새 내용**을 우리 잣대로 옮긴 것:
  * 캔들 = 매수·매도 세력의 실시간 승패 결과판. 몸통(시가↔종가) = 주도권의 크기, 꼬리 = 도달했다가 밀려난 흔적.
  * LONG  = 지지/전환 구역에서 **긴 아래꼬리** 봉 뒤에 **양봉 몸통**으로 전환되는 시점 (매수세 유입).
  * SHORT = 저항/오버슈팅 구역에서 **긴 윗꼬리** 봉(매도 폭탄) 뒤에 **음봉 몸통이 길게** 떨어지는 시점.
  * 노이즈 필터 = **15분 완성봉**만, 몸통/꼬리 비율이 임계를 넘을 때만 트리거.
  * 피라미딩 = 수익 구간에서 **몸통이 추세 방향으로 계속 커질 때만** 추가(최대 2회), 작은 반대 꼬리는 무시.

측정 (학습 일지 2,992 심볼-일 2026-08-16~09-05 + 실매매 추가 188건, docs/spec/V220_CANDLE_BATTLE_INTEGRATION_2026-09-07.md):
  * LONG  — 기획서의 두 봉 형태(꼬리봉 → 확인봉)는 약하다(확인봉을 기다리면 반등을 돌려준다). **단일 봉 해머**(아래꼬리 ≥ 0.5,
            범위 ≥ 0.8×ATR14, 양봉, 저가가 24h 최저의 3% 안) 가 DOWN n=814 +0.68 Δ+0.42 CV 4/4. 그러나 **꼬리 없이 「구역 + 양봉 종가」만
            써도 같거나 낫고**(Δ+0.71), 기존 bottom_331(Δ+0.89) 을 못 넘는다 → **일지 후보 규칙(기록)**, 실매매 게이트 아님.
  * SHORT — 두 봉 형태(윗꼬리 ≥ 0.5 · 꼬리 ≥ 몸통 · 범위 ≥ 0.8×ATR14 · %B ≥ 0.85 · 음봉 몸통 ≥ 0.3 · 종가 < 꼬리봉 중간)
            UP 첫 발동 n=637 **+0.44**(기준선 −0.65) CV 4/4 — 이 일지에서 처음으로 채택 문턱을 넘은 기계적 SHORT 규칙. 다만 180셀 중 2셀,
            약한 CV 셀 +0.10/+0.12, 전체 발동 +0.23(1셀 음수), 중앙값 −3.1 (평균은 10% TP 가 만든다).
            **실매매 confirm_peak 위에 필터로**: 발동 봉 포함 5봉(직전 4봉 + 발동 봉) 안에 「윗꼬리 ≥ 0.4 꼬리봉 + %B 구역」이 있으면
            +0.10(n=437) / 없으면 −0.59(n=611). (반박 검증이 잡음: 처음엔 0.5·4봉으로 배선해 인용 숫자와 달랐다 — 그 정의는 +0.05/−0.45.)
            → 기본 **shadow**(기록만). `candle_battle_mode_short=gate` 로 켜면 confirm_peak 통과 신호 중 꼬리봉 없는 것을 거른다.
  * 피라미딩 「몸통 성장」— 어떤 정의도 채택 문턱을 못 넘고, 엄격한 「몸통이 커지는 중」은 가장 나쁨. 덜 나쁜 정의(G3A: 마지막 완성봉
            몸통 ≥ 0.5 범위·≥ 0.5×ATR14·반대 꼬리 ≤ 0.3) 도 배포된 15m hist 가속(Fix 348) 보다 못 가른다 → **shadow 표식만**.
  * 「꼬리 노이즈에 조기 청산 금지」— 종가 기준 트레일링(E2/E3)은 틱 기준(E1)을 못 이긴다(LONG 동률, SHORT 더 나쁨) → 변경 없음.

원칙 (헌법):
  * 판정은 **완성봉**만 본다 — 호출자는 진행중 봉을 빼고 넘긴다 (`bars[-1]` 이 마지막 완성봉, `completed_only` 사용).
  * 여기 숫자는 전부 Claude 가 정한 것이라 설정키로 뺀다 (`candle_battle_*`). 기본값 = 위 측정값.
  * 새 배선의 기본 = shadow (헌법 161). 되돌리기 = `candle_battle_mode_short=off` / `pyramid_body_growth_mode=off`.
  * 비율은 chart_events._body_ratio/_lwick_ratio 와 같은 정의(범위 대비). **절대 크기**(범위 ≥ R×ATR14)를 더해 도지를 뺀다.
  * 이 모듈은 순수 함수 + DB 설정 읽기 + 봉 조회만 한다. 주문·전략 상태는 건드리지 않는다.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import Any, Sequence

logger = logging.getLogger(__name__)

FIX = "Fix360"

# ── 설정키 (전부 Claude 가 정함 — 기본값은 측정값) ───────────────────────────────
S_WICK_RATIO_MIN = "candle_battle_wick_ratio_min"            # 꼬리/범위 ≥            (0.5)
S_WICK_BODY_MULT = "candle_battle_wick_body_mult_min"        # 꼬리 ≥ k × 몸통       (1.0)
S_RANGE_ATR_MULT = "candle_battle_range_atr_mult_min"        # 범위 ≥ R × ATR14      (0.8 — 1.2 는 일관되게 더 나쁨)
S_ZONE_LONG = "candle_battle_zone_long"                      # extreme24h | bb | none (extreme24h)
S_ZONE_SHORT = "candle_battle_zone_short"                    # extreme24h | bb | none (bb)
S_ZONE_PCT = "candle_battle_zone_pct"                        # 24h 극값 대비 허용 %  (3.0)
S_ZONE_PCTB_LONG = "candle_battle_zone_pctb_long"            # %B ≤ (LONG bb 구역)   (0.15)
S_ZONE_PCTB_SHORT = "candle_battle_zone_pctb_short"          # %B ≥ (SHORT bb 구역)  (0.85)
S_FORM_LONG = "candle_battle_form_long"                      # hammer | two_bar      (hammer)
S_FORM_SHORT = "candle_battle_form_short"                    # hammer | two_bar      (two_bar)
S_CONFIRM_BODY_MIN = "candle_battle_confirm_body_ratio_min"  # 확인봉 몸통/범위 ≥    (0.3)
S_CONFIRM_MODE = "candle_battle_confirm_mode"                # mid | extreme         (mid — 「꼬리봉 저가 아래」는 더 낫지 않았다)
S_ADDON_LOOKBACK = "candle_battle_short_addon_lookback"      # confirm_peak 필터: 발동 봉 포함 N 봉 안에 꼬리봉 (5 = 측정 창)
S_ADDON_WICK_RATIO = "candle_battle_short_addon_wick_ratio_min"  # confirm_peak 필터의 꼬리/범위 ≥ (0.4 = 측정 셀 「loose」)
S_GROWTH_BARS = "candle_battle_growth_bars"                  # 피라미딩 지속 = 마지막 N 완성봉 (1)
S_GROWTH_STRICT = "candle_battle_growth_strict"              # 몸통이 봉마다 커져야 함 (0 — 측정에서 가장 나쁨)
S_GROWTH_BODY_MIN = "candle_battle_growth_body_ratio_min"    # 마지막 봉 몸통/범위 ≥  (0.5)
S_GROWTH_BODY_ATR = "candle_battle_growth_body_atr_mult_min" # 마지막 봉 몸통 ≥ m×ATR14 (0.5)
S_GROWTH_OPP_WICK_MAX = "candle_battle_growth_opp_wick_max"  # 마지막 봉 반대 꼬리/범위 ≤ (0.3)
S_MODE_LONG = "candle_battle_mode_long"                      # off | shadow | gate   (shadow, 현재 배선 없음 — 일지 규칙만)
S_MODE_SHORT = "candle_battle_mode_short"                    # off | shadow | gate   (shadow)
S_MODE_PYRAMID = "pyramid_body_growth_mode"                  # off | shadow | gate   (shadow)

MODES = ("off", "shadow", "gate")
ZONES = ("extreme24h", "bb", "none")
FORMS = ("hammer", "two_bar")
CONFIRM_MODES = ("mid", "extreme")
ZONE_LOOKBACK = 96          # 24h of 15m bars
ATR_N = 14
BB_N = 20
KLINE_LIMIT = 130           # 96 구역 + 14 ATR + 여유


@dataclass(frozen=True)
class CandleCfg:
    """임계값 묶음. 기본값 = 측정에서 확정한 값 (V220 문서). 여기 숫자를 바꾸기 전에 문서의 n/CV 를 읽어라."""
    wick_ratio_min: float = 0.5
    wick_body_mult_min: float = 1.0
    range_atr_mult_min: float = 0.8
    zone_long: str = "extreme24h"
    zone_short: str = "bb"
    zone_pct: float = 3.0
    zone_pctb_long: float = 0.15
    zone_pctb_short: float = 0.85
    form_long: str = "hammer"
    form_short: str = "two_bar"
    confirm_body_ratio_min: float = 0.3
    confirm_mode: str = "mid"
    short_addon_lookback: int = 5
    addon_wick_ratio_min: float = 0.4
    growth_bars: int = 1
    growth_strict: bool = False
    growth_body_ratio_min: float = 0.5
    growth_body_atr_mult_min: float = 0.5
    growth_opp_wick_max: float = 0.3

    def zone(self, side: str) -> str:
        return self.zone_long if str(side).upper() == "LONG" else self.zone_short

    def form(self, side: str) -> str:
        return self.form_long if str(side).upper() == "LONG" else self.form_short


DEFAULT_CFG = CandleCfg()


# ── 봉 하나의 수치 ─────────────────────────────────────────────────────────────

def metrics(bar: Sequence[float]) -> dict[str, float | bool] | None:
    """bar = [t, o, h, l, c, ...]. 범위 0 이면 None."""
    try:
        o, h, l, c = float(bar[1]), float(bar[2]), float(bar[3]), float(bar[4])
    except (TypeError, ValueError, IndexError):
        return None
    rng = h - l
    if rng <= 0:
        return None
    body = abs(c - o)
    up = h - max(o, c)
    lo = min(o, c) - l
    return {
        "range": rng, "body": body, "upper_wick": up, "lower_wick": lo,
        "body_ratio": body / rng, "uwick_ratio": up / rng, "lwick_ratio": lo / rng,
        "bullish": c > o, "bearish": c < o,
    }


def atr_range(bars: Sequence[Sequence[float]], n: int = ATR_N) -> float | None:
    """마지막 n 봉 범위(h−l)의 단순 평균 (측정 스크립트와 같은 정의: 판정 봉 **이전** 14봉). 봉 부족이면 None."""
    tail = bars[-n:]
    if len(tail) < n:
        return None
    vals = [float(b[2]) - float(b[3]) for b in tail]
    return sum(vals) / n if vals else None


def true_range_atr(bars: Sequence[Sequence[float]], n: int = ATR_N) -> float | None:
    """마지막 n 봉의 TR(max(h−l, |h−이전종가|, |l−이전종가|)) 평균 — **판정 봉 포함** (몸통 성장 측정 G3A 와 같은 정의).
    이전 종가가 필요하므로 n+1 봉이 없으면 None."""
    if len(bars) < n + 1:
        return None
    tail = bars[-(n + 1):]
    trs = []
    for i in range(1, len(tail)):
        h, l, pc = float(tail[i][2]), float(tail[i][3]), float(tail[i - 1][4])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / n if trs else None


def _pctb(closes: Sequence[float], n: int = BB_N) -> float | None:
    if len(closes) < n:
        return None
    w = [float(x) for x in closes[-n:]]
    m = sum(w) / n
    sd = (sum((x - m) ** 2 for x in w) / n) ** 0.5
    return (w[-1] - (m - 2 * sd)) / (4 * sd) if sd else 0.5


# ── 구역 판정 (꼬리봉 = bars[idx]) ────────────────────────────────────────────

def zone_ok(bars: Sequence[Sequence[float]], idx: int, side: str, cfg: CandleCfg) -> tuple[bool, str]:
    side = str(side).upper()
    z = cfg.zone(side)
    if z == "none":
        return True, "zone=none"
    if idx <= 0:
        return False, "구역 판정 봉 부족"
    long = side == "LONG"
    if z == "extreme24h":
        prior = bars[max(0, idx - ZONE_LOOKBACK):idx]
        if len(prior) < ZONE_LOOKBACK:
            return False, f"24h 극값 봉 부족 ({len(prior)}/{ZONE_LOOKBACK})"
        if long:
            ref = min(float(b[3]) for b in prior)
            ok = float(bars[idx][3]) <= ref * (1 + cfg.zone_pct / 100)
            return ok, f"저가 {float(bars[idx][3]):.6g} vs 24h 최저 {ref:.6g} (+{cfg.zone_pct}%)"
        ref = max(float(b[2]) for b in prior)
        ok = float(bars[idx][2]) >= ref * (1 - cfg.zone_pct / 100)
        return ok, f"고가 {float(bars[idx][2]):.6g} vs 24h 최고 {ref:.6g} (−{cfg.zone_pct}%)"
    if z == "bb":
        pb = _pctb([float(b[4]) for b in bars[:idx + 1]])
        if pb is None:
            return False, "%B 봉 부족"
        ok = pb <= cfg.zone_pctb_long if long else pb >= cfg.zone_pctb_short
        return ok, f"%B {pb:.2f}"
    return False, f"zone 값 오류 {z!r}"


# ── 꼬리봉 / 확인봉 ───────────────────────────────────────────────────────────

def wick_bar_ok(bar: Sequence[float], side: str, cfg: CandleCfg, atr: float | None) -> tuple[bool, str, dict[str, Any]]:
    m = metrics(bar)
    if m is None:
        return False, "범위 0", {}
    long = str(side).upper() == "LONG"
    wick = m["lwick_ratio"] if long else m["uwick_ratio"]
    wick_abs = m["lower_wick"] if long else m["upper_wick"]
    if wick < cfg.wick_ratio_min:
        return False, f"꼬리 {wick:.2f} < {cfg.wick_ratio_min}", m
    if wick_abs < cfg.wick_body_mult_min * m["body"]:
        return False, f"꼬리 < {cfg.wick_body_mult_min}×몸통", m
    if atr is None or atr <= 0:
        return False, "ATR 봉 부족/0", m
    if m["range"] < cfg.range_atr_mult_min * atr:
        return False, f"범위 {m['range']:.6g} < {cfg.range_atr_mult_min}×ATR {atr:.6g} (도지)", m
    return True, f"꼬리 {wick:.2f}", m


def confirm_bar_ok(wick_bar: Sequence[float], bar: Sequence[float], side: str, cfg: CandleCfg) -> tuple[bool, str, dict[str, Any]]:
    m = metrics(bar)
    if m is None:
        return False, "범위 0", {}
    long = str(side).upper() == "LONG"
    if long and not m["bullish"]:
        return False, "확인봉이 양봉 아님", m
    if not long and not m["bearish"]:
        return False, "확인봉이 음봉 아님", m
    if m["body_ratio"] < cfg.confirm_body_ratio_min:
        return False, f"확인봉 몸통 {m['body_ratio']:.2f} < {cfg.confirm_body_ratio_min}", m
    wh, wl = float(wick_bar[2]), float(wick_bar[3])
    c = float(bar[4])
    if cfg.confirm_mode == "extreme":
        ok = c > wh if long else c < wl
        return ok, ("확인봉 종가가 꼬리봉 " + ("고가 위" if long else "저가 아래") + ("" if ok else " 아님")), m
    mid = (wh + wl) / 2
    ok = c > mid if long else c < mid
    return ok, ("확인봉 종가가 꼬리봉 중간 " + ("위" if long else "아래") + ("" if ok else " 아님")), m


# ── 반전 신호 ─────────────────────────────────────────────────────────────────

def reversal_signal(bars: Sequence[Sequence[float]], side: str, cfg: CandleCfg = DEFAULT_CFG) -> tuple[bool, str, dict[str, Any]]:
    """`bars` 는 **완성봉**만, 시간순. 형태는 cfg.form(side):
      * hammer  = 마지막 봉 하나가 꼬리봉이면서 스스로 방향 종가(LONG 양봉 / SHORT 음봉). 진입 = 그 봉 종가.
      * two_bar = 꼬리봉(bars[-2]) → 확인봉(bars[-1]). 진입 = 확인봉 종가.
    반환 (신호, 사유, 상세). 상세에는 봉 수치가 들어가 기록·학습에 쓴다."""
    side = str(side).upper()
    if side not in ("LONG", "SHORT"):
        return False, f"side 오류 {side!r}", {}
    form = cfg.form(side)
    detail: dict[str, Any] = {"side": side, "form": form, "zone": cfg.zone(side)}
    if form == "hammer":
        if len(bars) < 2:
            return False, "봉 부족", detail
        bar = bars[-1]
        m = metrics(bar)
        if m is None:
            return False, "범위 0", detail
        if side == "LONG" and not m["bullish"]:
            return False, "해머봉이 양봉 아님", detail
        if side == "SHORT" and not m["bearish"]:
            return False, "역해머봉이 음봉 아님", detail
        atr = atr_range(bars[:-1], ATR_N)
        ok_w, why_w, mw = wick_bar_ok(bar, side, cfg, atr)
        detail.update({"wick_bar": mw, "atr": atr})
        if not ok_w:
            return False, f"꼬리봉 ✗ {why_w}", detail
        ok_z, why_z = zone_ok(bars, len(bars) - 1, side, cfg)
        detail["zone_why"] = why_z
        if not ok_z:
            return False, f"구역 ✗ {why_z}", detail
        return True, f"{side} 세력공방 반전(단일봉): {why_w} · {why_z}", detail
    # two_bar
    if len(bars) < 3:
        return False, "봉 부족", detail
    wick_bar, conf_bar = bars[-2], bars[-1]
    atr = atr_range(bars[:-2], ATR_N)
    ok_w, why_w, mw = wick_bar_ok(wick_bar, side, cfg, atr)
    detail.update({"wick_bar": mw, "atr": atr})
    if not ok_w:
        return False, f"꼬리봉 ✗ {why_w}", detail
    ok_z, why_z = zone_ok(bars, len(bars) - 2, side, cfg)
    detail["zone_why"] = why_z
    if not ok_z:
        return False, f"구역 ✗ {why_z}", detail
    ok_c, why_c, mc = confirm_bar_ok(wick_bar, conf_bar, side, cfg)
    detail["confirm_bar"] = mc
    if not ok_c:
        return False, f"확인봉 ✗ {why_c}", detail
    return True, f"{side} 세력공방 반전: 꼬리봉({why_w}) → {why_c} · {why_z}", detail


def recent_wick_bar(bars: Sequence[Sequence[float]], side: str, cfg: CandleCfg = DEFAULT_CFG,
                    lookback: int | None = None) -> tuple[bool, str, dict[str, Any]]:
    """confirm_peak 위에 얹는 필터. 측정 셀 = 「loose」 꼬리봉(꼬리/범위 ≥ **0.4**·꼬리 ≥ 몸통·범위 ≥ 0.8×ATR14) + %B ≥ 0.85 가
    **발동 봉 포함 5봉**(직전 4봉 + 발동 봉) 안에 있으면 +0.10(n=437) / 없으면 −0.59(n=611).
    `bars` 마지막 = confirm_peak 가 본 마지막 완성봉(발동 봉). 꼬리봉 하나라도 있으면 True (확인봉은 confirm_peak 가 대신한다).
    detail["checked"] == 0 이면 봉이 모자라 판정 자체를 못 한 것 — 호출자는 gate 에서 fail-open."""
    side = str(side).upper()
    n = int(lookback if lookback is not None else cfg.short_addon_lookback)
    n = max(1, n)
    acfg = replace(cfg, wick_ratio_min=cfg.addon_wick_ratio_min)
    detail: dict[str, Any] = {"side": side, "lookback": n, "checked": 0, "wick_ratio_min": acfg.wick_ratio_min}
    for k in range(1, n + 1):
        idx = len(bars) - k
        if idx < ATR_N:
            break
        detail["checked"] += 1
        atr = atr_range(bars[:idx], ATR_N)
        ok_w, why_w, mw = wick_bar_ok(bars[idx], side, acfg, atr)
        if not ok_w:
            continue
        ok_z, why_z = zone_ok(bars, idx, side, cfg)
        if ok_z:
            detail.update({"bars_ago": k - 1, "wick_bar": mw, "zone_why": why_z})
            return True, f"{k - 1}봉 전 꼬리봉 ({why_w}, {why_z})", detail
    return False, f"직전 {detail['checked']}봉 안에 꼬리봉+구역 없음", detail


# ── 피라미딩 지속 판정: 몸통이 추세 방향으로 커지는 중 ────────────────────────

def body_growth(bars: Sequence[Sequence[float]], side: str, cfg: CandleCfg = DEFAULT_CFG) -> tuple[bool, str, dict[str, Any]]:
    """마지막 N 완성봉이 전부 추세 방향(SHORT=음봉, LONG=양봉)이고, 마지막 봉 몸통이 범위·ATR 대비 충분히 크며
    반대 꼬리(SHORT=아래꼬리, LONG=윗꼬리)가 작을 때 True. growth_strict 면 몸통이 봉마다 커져야 한다(기획서 원문,
    측정에서는 가장 나쁨이라 기본 OFF). 「작은 반대 꼬리 노이즈는 무시」= 꼬리 ≤ growth_opp_wick_max."""
    side = str(side).upper()
    n = max(1, int(cfg.growth_bars))
    if len(bars) < n:
        return False, "봉 부족", {}
    tail = bars[-n:]
    ms = [metrics(b) for b in tail]
    if any(m is None for m in ms):
        return False, "범위 0 봉", {}
    long = side == "LONG"
    bodies = [float(m["body"]) for m in ms]     # type: ignore[index]
    detail: dict[str, Any] = {"bodies": bodies, "n": n, "strict": bool(cfg.growth_strict)}
    for m in ms:
        if long and not m["bullish"]:            # type: ignore[index]
            return False, "추세 반대 봉 포함(음봉)", detail
        if not long and not m["bearish"]:        # type: ignore[index]
            return False, "추세 반대 봉 포함(양봉)", detail
    if cfg.growth_strict and any(bodies[i] <= bodies[i - 1] for i in range(1, len(bodies))):
        return False, "몸통이 커지지 않음", detail
    last = ms[-1]
    br = float(last["body_ratio"])               # type: ignore[index]
    detail["body_ratio"] = br
    if br < cfg.growth_body_ratio_min:
        return False, f"마지막 봉 몸통 {br:.2f} < {cfg.growth_body_ratio_min}", detail
    atr = true_range_atr(bars, ATR_N)             # 판정 봉 포함 TR14 (측정 정의)
    detail["atr"] = atr
    if atr is None or atr <= 0:
        return False, "ATR 봉 부족/0", detail
    if bodies[-1] < cfg.growth_body_atr_mult_min * atr:
        return False, f"몸통 {bodies[-1]:.6g} < {cfg.growth_body_atr_mult_min}×ATR {atr:.6g}", detail
    opp = float(last["uwick_ratio"] if long else last["lwick_ratio"])   # type: ignore[index]
    detail["opp_wick_ratio"] = opp
    if opp > cfg.growth_opp_wick_max:
        return False, f"반대 꼬리 {opp:.2f} > {cfg.growth_opp_wick_max}", detail
    return True, f"몸통 {n}봉 추세 방향 (몸통/범위 {br:.2f}, 반대 꼬리 {opp:.2f})", detail


# ── 설정 읽기 ─────────────────────────────────────────────────────────────────

def _setting(db: Any, key: str) -> str | None:
    if db is None:
        return None
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        v = None if row is None else row.value
        return None if v is None or not str(v).strip() else str(v).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s 조회 실패 → 기본: %s", FIX, key, e)
        return None


def _float_setting(db: Any, key: str, default: float, lo: float, hi: float) -> float:
    v = _setting(db, key)
    if v is None:
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        logger.warning("[%s] %s=%r 파싱 실패 → 기본 %s", FIX, key, v, default)
        return default
    if x < lo or x > hi:
        logger.warning("[%s] %s=%s 범위밖(%s~%s) → 기본 %s", FIX, key, x, lo, hi, default)
        return default
    return x


def _bool_setting(db: Any, key: str, default: bool) -> bool:
    v = _setting(db, key)
    if v is None:
        return default
    return v.lower() in ("1", "true", "on", "yes")


def _choice_setting(db: Any, key: str, default: str, allowed: Sequence[str]) -> str:
    v = _setting(db, key)
    if v is None:
        return default
    v = v.lower()
    if v not in allowed:
        logger.warning("[%s] %s=%r 허용값 아님 %s → 기본 %s", FIX, key, v, list(allowed), default)
        return default
    return v


def cfg_from_db(db: Any) -> CandleCfg:
    """DB 설정으로 덮은 임계값. 행 없음 = 코드 기본(측정값)."""
    if db is None:
        return DEFAULT_CFG
    d = DEFAULT_CFG
    return replace(
        d,
        wick_ratio_min=_float_setting(db, S_WICK_RATIO_MIN, d.wick_ratio_min, 0.1, 0.95),
        wick_body_mult_min=_float_setting(db, S_WICK_BODY_MULT, d.wick_body_mult_min, 0.0, 10.0),
        range_atr_mult_min=_float_setting(db, S_RANGE_ATR_MULT, d.range_atr_mult_min, 0.0, 5.0),
        zone_long=_choice_setting(db, S_ZONE_LONG, d.zone_long, ZONES),
        zone_short=_choice_setting(db, S_ZONE_SHORT, d.zone_short, ZONES),
        zone_pct=_float_setting(db, S_ZONE_PCT, d.zone_pct, 0.0, 30.0),
        zone_pctb_long=_float_setting(db, S_ZONE_PCTB_LONG, d.zone_pctb_long, -1.0, 1.0),
        zone_pctb_short=_float_setting(db, S_ZONE_PCTB_SHORT, d.zone_pctb_short, 0.0, 2.0),
        form_long=_choice_setting(db, S_FORM_LONG, d.form_long, FORMS),
        form_short=_choice_setting(db, S_FORM_SHORT, d.form_short, FORMS),
        confirm_body_ratio_min=_float_setting(db, S_CONFIRM_BODY_MIN, d.confirm_body_ratio_min, 0.0, 0.95),
        confirm_mode=_choice_setting(db, S_CONFIRM_MODE, d.confirm_mode, CONFIRM_MODES),
        short_addon_lookback=int(_float_setting(db, S_ADDON_LOOKBACK, float(d.short_addon_lookback), 1, 12)),
        addon_wick_ratio_min=_float_setting(db, S_ADDON_WICK_RATIO, d.addon_wick_ratio_min, 0.1, 0.95),
        growth_bars=int(_float_setting(db, S_GROWTH_BARS, float(d.growth_bars), 1, 6)),
        growth_strict=_bool_setting(db, S_GROWTH_STRICT, d.growth_strict),
        growth_body_ratio_min=_float_setting(db, S_GROWTH_BODY_MIN, d.growth_body_ratio_min, 0.0, 0.95),
        growth_body_atr_mult_min=_float_setting(db, S_GROWTH_BODY_ATR, d.growth_body_atr_mult_min, 0.0, 5.0),
        growth_opp_wick_max=_float_setting(db, S_GROWTH_OPP_WICK_MAX, d.growth_opp_wick_max, 0.0, 0.95),
    )


def mode(db: Any, key: str, default: str = "shadow") -> str:
    """off = 아무것도 안 함 / shadow = 판정만 기록 / gate = 판정이 진입·추가를 막는다. 조회 실패 = 기본(shadow)."""
    return _choice_setting(db, key, default, MODES)


# ── 봉 조회 보조 ──────────────────────────────────────────────────────────────

def completed_only(klines: Sequence[Sequence[Any]], now_ms: int | None = None) -> list[list[float]]:
    """바이낸스 12필드 봉(문자열) 또는 6필드 봉을 float 6필드로 바꾸고, `now_ms` 가 있으면
    마감 시각(close_time = 7번째 필드, 없으면 open+15m−1)이 지난 봉만 남긴다 = 완성봉."""
    out: list[list[float]] = []
    for b in klines:
        try:
            t = int(b[0])
            row = [float(t), float(b[1]), float(b[2]), float(b[3]), float(b[4]), float(b[5]) if len(b) > 5 else 0.0]
        except (TypeError, ValueError, IndexError):
            continue
        if now_ms is not None:
            close_t = int(b[6]) if len(b) > 6 and b[6] not in (None, "") else t + 15 * 60 * 1000 - 1
            if close_t >= now_ms:
                continue
        out.append(row)
    return out


def completed_15m(bc: Any, symbol: str, limit: int = KLINE_LIMIT) -> list[list[float]]:
    """워커용: 15m 봉을 받아 진행중 봉을 뺀 완성봉만 돌려준다. 조회 실패 = 빈 리스트 (호출자는 fail-open)."""
    try:
        kl = bc.get_klines(symbol=symbol, interval="15m", limit=int(limit))
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s 15m 봉 조회 실패: %s", FIX, symbol, e)
        return []
    return completed_only(kl or [], int(time.time() * 1000))


def compact(ok: bool, why: str, detail: dict[str, Any] | None) -> dict[str, Any]:
    """기록용 축약 (entry_snapshot / 추가 스냅샷에 넣는다)."""
    d = detail or {}
    out: dict[str, Any] = {"ok": bool(ok), "why": str(why)[:160]}
    for k in ("form", "zone", "bars_ago", "body_ratio", "opp_wick_ratio", "strict"):
        if k in d:
            out[k] = d[k]
    wb = d.get("wick_bar")
    if isinstance(wb, dict):
        out["wick"] = {k: (round(float(v), 4) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
                       for k, v in wb.items() if k in ("body_ratio", "uwick_ratio", "lwick_ratio", "bullish")}
    return out
