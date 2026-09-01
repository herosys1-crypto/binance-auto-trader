"""🎯 볼밴 1차 진입 = 「밴드 밖으로 나갔다가 **극값에서 꺾일 때**」 (Fix 276).

## 사장님 원문 (2026-09-02, 네 번에 걸쳐 확정)

  (1) "롱은 지지받는 지점과 볼밴 하단 -10% 전후로 큰하락에 무조건진입"
  (2) "숏은 볼밴 최상단 +10%전후면 무조건 포지션 진입"
  (3) "볼밴 상단을 돌파하면 **우리로직이 고점이라 판단되면** 포지션에 진입"
  (4) "볼밴 하단 3-5번 지속 되면 무조건 진입 / 볼밴 최상단 2-4번 지속 되면 숏진입"
  (5) 🌟 **"꼭 3-5번 2-4번 -10% +10% 고정은 아니야. 이렇게 급락과 급등하면
         우리 시스템 로직이 최고점 최저점이라 판단되면 진입하고
         정말 그렇게 되면 무조건 포지션 진입하는거야"**

(5) 가 나머지를 지배한다. 봉수·심도는 **후보 감지**일 뿐이고, 진입을 결정하는 것은
**「최고점/최저점 판단」**이다. 그래서 규칙은 하나로 합쳐진다:

    ① 밴드 밖으로 나간다        <- 「급등/급락」 (지속 N봉 **또는** 심도 D%)
    ② 그 구간의 극값을 기록한다  <- SHORT=신고점 / LONG=신저점 (**불리 방향** 극값)
    ③ 극값에서 꺾인다           <- **「최고점/최저점이라 판단」**
    ④ 그러면 무조건 진입        <- 다른 게이트 없음

이 하나가 (1)(2)(3)(4) 를 전부 덮는다. (3) 「상단 돌파 후 고점 판단」은
「상단 밖에 머물다가 꺾임」과 같은 사건이다.

극값을 **불리 방향**으로 잡는 것은 Fix 260(peak_stall) 과 같은 사상이다 —
SHORT 은 신고점, LONG 은 **신저점**. 여기에 조건을 더하면 수학적으로 불가능해진다.

## 실측 (130심볼 x 15m 1000봉 = 10.4일, TP +5%/SL -10% ROI, 자본 100, 레버 2)

**🌟 「꺾임」이 만드는 차이 (SHORT, 상단 밖 4봉 이상):**

    꺾임 판정 없음   413건 승률 70.0%  +276.44  건당 +0.673
    **꺾임 판정 있음   174건 승률 77.0%  +313.16  건당 +1.800  <- 2.7배**

  건수는 절반 이하로 줄지만 건당 수익이 2.7배다. 사장님 「최고점이라 판단되면」이
  실측으로 확인된다. **되돌림을 더 기다리면 오히려 나빠진다** (= 늦는다):

    되돌림 0.0%(꺾이기만)  174건 77.0% +313.16 | 전 +134.11 후 +179.03  OK  <- 채택
    되돌림 0.3%             69건 72.5%  +65.91 | 전  +30.00 후  +35.91  OK
    되돌림 0.6%             31건 71.0%  +20.00 | 전   +5.00 후  +15.00  OK
    되돌림 1.0%             16건 56.2%  -25.00 | 전  -20.00 후   -5.00

**SHORT — 지속봉수별 (되돌림 0%):**

    밖 2봉+  487건 70.4% +374.94  건당 +0.770 | 전 +111.77 후 +289.52  OK
    밖 3봉+  322건 70.8% +286.72  건당 +0.890 | 전  +87.32 후 +193.22  OK
    **밖 4봉+  174건 77.0% +313.16  건당 +1.800 | 전 +134.11 후 +179.03  OK  <- 채택**

  건당이 가장 높고 과적합 검사(전/후반 모두 양수)를 통과한다. 사장님 "2-4번"의 상한.

**LONG — 지속봉수 x 되돌림 (전부 약하다):**

    밖 2봉+ 되돌림 0.0%  439건 62.9%  +34.08 | 전 +153.61 후 -117.77
    **밖 2봉+ 되돌림 0.6%   72건 66.7%  +17.87 | 전   +9.15 후   +8.71  OK  <- 채택**
    밖 3봉+ 되돌림 0.0%  297건 64.0% +100.52 | 전 +206.55 후  -81.03
    밖 3봉+ 되돌림 0.3%  105건 63.8%   -4.05 | 전  -15.85 후  +16.79
    밖 4봉+ 되돌림 0.0%  131건 58.8%  -20.28 | 전  +75.86 후  -91.14

  🚨 **LONG 은 과적합 검사를 통과하는 조합이 이것 하나뿐**이고 건당 +0.248 로 약하다.
     (SHORT 는 +1.800) 사장님 「실패가 많은 롱」이 여기서도 그대로 나온다.
     사장님이 "봉수는 고정 아니다"라고 하셨으므로 실측 최선(2봉/0.6%)을 기본으로 쓴다.

**참고 — 심도 경로는 거의 안 걸린다 (그래도 「큰 하락」 안전망으로 남긴다):**

    하단 -10%  3건 / 상단 +10%  2건  (10.4일 x 130심볼)
    현행 3% :  하단 36건 0.00 / 상단 66건 -30.00   <- 지킬 이유가 없다

## ⚠️ 이 측정의 한계 (반드시 같이 읽을 것)

10.4일 **한 구간**이다. 전/후반으로 갈랐지만 **같은 장세 안**이라 국면 분리가 안 된다.
이 기간 SHORT 은 거의 전부 양수 / LONG 은 거의 전부 음수였다 = 하락장이었다는 뜻이다.
「SHORT 이 좋다」가 아니라 「이 규칙이 이 장세에서 이랬다」로만 읽어야 한다.
상승장이 오면 LONG/SHORT 이 뒤집힐 수 있으므로 **봉수·되돌림은 전부 설정값**으로 둔다.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "band_series", "outside_run", "extreme_of", "evaluate_first_entry",
    "PERSIST_BARS_LONG", "PERSIST_BARS_SHORT",
    "RETRACE_PCT_LONG", "RETRACE_PCT_SHORT",
    "DEPTH_PCT", "LONG_MIN_CHG24", "MIN_BARS",
]

# ── 후보 감지 (사장님 "고정은 아니야" — 전부 설정으로 덮인다) ──────────────
PERSIST_BARS_LONG: int = 2       # 사장님 "3-5번" / 실측 최선 2
PERSIST_BARS_SHORT: int = 4      # 사장님 "2-4번" / 실측 최선 4
DEPTH_PCT: float = 10.0          # 사장님 "-10%/+10% 전후"
# ── 최고점/최저점 판단 ────────────────────────────────────────────────────
RETRACE_PCT_LONG: float = 0.6    # 실측: LONG 은 0.6% 반등을 기다려야 흑자
RETRACE_PCT_SHORT: float = 0.0   # 실측: SHORT 은 꺾이기만 하면 된다 (기다리면 늦다)
# ── 선택 (기본 미적용) ────────────────────────────────────────────────────
LONG_MIN_CHG24: float = 0.0      # >0 이면 사상 ② 「급등 후 조정」 조건을 건다
MIN_BARS: int = 30               # 밴드 20 + 판정 여유


def band_series(closes: list) -> tuple[list, list, list]:
    """(mid, up, lo) 시계열. 실패하면 ([], [], [])."""
    try:
        from app.services.bb_4h_band_analyzer import BB4HBandAnalyzer
        return BB4HBandAnalyzer.bollinger([float(x) for x in closes])
    except Exception as e:                        # pragma: no cover - 방어
        logger.warning("[Fix276] 밴드 계산 실패: %s", e)
        return [], [], []


def outside_run(closes: list, band: list, side: str, end_idx: int) -> int:
    """end_idx 봉에서 거슬러 올라가며 **연속으로** 밴드 밖인 봉수.

    LONG = 종가 < 하단, SHORT = 종가 > 상단.
    밴드가 None 인 봉을 만나면 멈춘다 (없는 값을 「밖」으로 세지 않는다).
    """
    n = 0
    i = end_idx
    while 0 <= i < len(band):
        b = band[i]
        if b is None:
            break
        c = float(closes[i])
        out = (c < float(b)) if side == "LONG" else (c > float(b))
        if not out:
            break
        n += 1
        i -= 1
    return n


def extreme_of(closes: list, side: str, start: int, end: int) -> float | None:
    """구간의 **불리 방향** 극값. SHORT=최고 종가 / LONG=최저 종가 (Fix 260 사상)."""
    seg = [float(x) for x in closes[max(0, start):end + 1]]
    if not seg:
        return None
    return min(seg) if side == "LONG" else max(seg)


def evaluate_first_entry(
    closes: list,
    side: str,
    *,
    persist_bars: int | None = None,
    retrace_pct: float | None = None,
    depth_pct: float = DEPTH_PCT,
    chg_24h: float | None = None,
    long_min_chg24: float = LONG_MIN_CHG24,
) -> tuple[Decimal | None, str, str, dict[str, Any]]:
    """1차 진입 판정. 반환 = (기준선, 경로, 사유, 상세). 미충족이면 기준선 None.

    기준선은 **밴드값**(LONG=하단 / SHORT=상단)이다 — 2·3차 트리거가 여기에 앵커된다
    (Fix 209 가 1차 체결 후 실체결가로 재앵커한다).

    🚨 **완료봉으로만 판정한다** (Fix 216 교훈).
       chart_analyzer 는 klines 를 자르지 않으므로 closes[-1] 은 **진행 중인 봉**이다.
       진행 중 봉으로 「밖 4봉 + 꺾임」을 세면 그 봉이 되돌릴 때 없던 신호가 되고,
       그 위에 2·3차 트리거와 손절이 앵커된다 (= 가짜 신호에 자본이 물린다).
       → 판정봉 = closes[-2].
    """
    d: dict[str, Any] = {"side": side, "chg_24h": chg_24h}
    side = str(side).upper()
    n_all = len(closes) if closes else 0
    if n_all < MIN_BARS:
        return None, "", f"15m 봉 부족({n_all})", d

    mid, up, lo = band_series(closes)
    if not mid or len(mid) < n_all:
        return None, "", "밴드 계산 실패", d

    i = n_all - 2                                  # 마지막 **완료봉**
    band = lo if side == "LONG" else up
    b = band[i]
    if b is None:
        return None, "", "밴드값 없음(완료봉)", d

    base = Decimal(str(b))
    close = float(closes[i])
    label = "하단" if side == "LONG" else "상단"
    d.update(base=float(base), close=close, label=label)

    pb = int(persist_bars if persist_bars is not None else (
        PERSIST_BARS_LONG if side == "LONG" else PERSIST_BARS_SHORT))
    rt = float(retrace_pct if retrace_pct is not None else (
        RETRACE_PCT_LONG if side == "LONG" else RETRACE_PCT_SHORT))
    d.update(persist_need=pb, retrace_need=rt)

    # ── ① 밖으로 나갔는가 (지속 N봉 **또는** 심도 D%) ─────────────────────
    run = outside_run(closes, band, side, i)
    d["persist_run"] = run
    path = ""
    if pb > 0 and run >= pb:
        path = "persist"
    if not path and depth_pct and depth_pct > 0:
        dp = float(depth_pct) / 100.0
        need = float(base) * ((1 - dp) if side == "LONG" else (1 + dp))
        d["depth_need"] = need
        # 심도는 지금 봉이 아니라 **밖에 머문 구간 전체**에서 봐야 한다.
        # 급락 바닥을 찍고 되돌리는 중이면 지금 종가는 이미 목표 위일 수 있다.
        seg_ext = extreme_of(closes, side, i - max(run, 1) + 1, i)
        if seg_ext is not None:
            deep = (seg_ext <= need) if side == "LONG" else (seg_ext >= need)
            d["depth_extreme"] = seg_ext
            if deep and run >= 1:
                path = "depth"

    if not path:
        return None, "", (
            f"{label} 밖 {run}봉 (필요 {pb}봉) / 종가 {close:g} / {label} {float(base):g}"
            + (f" / 심도목표 {d['depth_need']:g}" if "depth_need" in d else "")
        ), d

    # ── ② 그 구간의 극값 (불리 방향) ────────────────────────────────────
    if run < 2:
        # 밖에 나간 봉이 하나뿐이면 「극값에서 꺾였다」를 말할 수 없다.
        return None, "", f"{label} 밖 {run}봉 = 극값 판단 불가(2봉 이상 필요)", d
    ext = extreme_of(closes, side, i - run + 1, i)
    if ext is None or ext <= 0:
        return None, "", "극값 계산 실패", d
    d["extreme"] = ext

    # ── ③ 극값에서 꺾였는가 = 「최고점/최저점이라 판단」 ──────────────────
    #   SHORT: 종가가 신고점보다 **아래**  /  LONG: 종가가 신저점보다 **위**
    turned = (close > ext) if side == "LONG" else (close < ext)
    back = ((close - ext) / ext * 100.0) if side == "LONG" else ((ext - close) / ext * 100.0)
    d["retrace_pct"] = back
    if not turned or back < rt:
        return None, "", (
            f"{label} 밖 {run}봉이지만 아직 극값 갱신 중 "
            f"({'신저점' if side == 'LONG' else '신고점'} {ext:g} / 종가 {close:g} "
            f"/ 되돌림 {back:+.2f}% < {rt:g}%)"
        ), d

    # ── ④ 무조건 진입 ──────────────────────────────────────────────────
    if side == "LONG" and long_min_chg24 and long_min_chg24 > 0:
        if chg_24h is None:
            logger.debug("[Fix276] 24h 없음 = 통과 (fail-open)")
        elif float(chg_24h) < float(long_min_chg24):
            d["blocked_by"] = "chg24"
            return None, "", (
                f"{label} 밖 {run}봉 + 최저점 확인이지만 "
                f"24h {float(chg_24h):+.1f}% < {long_min_chg24:g}% (급등 중 아님)"
            ), d

    peak_word = "최저점" if side == "LONG" else "최고점"
    return base, path, (
        f"🎯 {label} 밖 {run}봉({path}) → **{peak_word} 확인** "
        f"({peak_word} {ext:g} → 종가 {close:g} / 되돌림 {back:+.2f}% >= {rt:g}%"
        + (f" / 24h {float(chg_24h):+.1f}%" if chg_24h is not None else "")
        + ")"
    ), d
