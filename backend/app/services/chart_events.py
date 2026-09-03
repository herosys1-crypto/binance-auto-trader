"""📊 차트 국면 판정식 — 「차트와 보조지표로 알 수 있잖아」 (Fix 331).

## 사장님 지시 (2026-09-03)

  "지금까지 학습을 통해서 **최고점의 차트와 보조지표로 알수 있잖아**
   첫진입은 그렇게 하고 그것이 실패하면 10usdt 남기고 부분손절하고
   **차트와 보조지표가 다시 최고점에서 하락으로 보이는 지표 15분과 4시간일때
   2단계 진입**하는 거잖아. **최저점도 같은 전략**이고"

  "차트와 보조지표로 **포지션 진입**과 **부분손절후 재진입**에서 성공할수 있는
   데이터를 만들고 활용해서 학습한건 **꼭 메모리 저장**해서 활용할수 있게 해줘"

## 🚨🚨 사장님 정정 — 15분이 기준, 4시간은 「참고」

  "**15분이 기준이고 4시간을 참고**하고 4시간 장기 흐름을 판단하는 차트라고
   그렇게 이야기를 했으고 차트전문가라면 **4시간 차트의 의미는 중단기 지속적인
   흐름을 판단하는 정도** 차트라는걸 알잖아"

**이 모듈에는 4H 거부권(veto)이 없다.** 4H 조건은 전부 「점수 1점」이고,
어느 판정도 4H 없이 통과할 수 있는 15분 단독 경로를 가진다.
(유일한 예외는 `is_restage_top` 의 S2 금지 규칙 — 진입 게이트가 아니라
 **자본 30배 증액 금지**다. 아래 그 함수 주석에 근거와 반증 이력을 남겼다.)

현행 `trend_4h_gate.py`(Fix 270)가 「4H hist 가 내 편 방향으로 상승중」을
**통과 조건**으로 걸어 6시간 1,546건 차단 / 52건 통과(3.3%) 를 만들었다.
그것과 같은 실수를 여기서 반복하지 마라.

## 🚨 이 모듈의 숫자를 함부로 바꾸지 마라

모든 규칙에 **학습 표본 실측치**(n / 승률 / 효과크기 / 두 그룹)를 적어 두었다.
그리고 **반증관이 무너뜨린 규칙은 넣지 않고, 왜 안 넣었는지를 남겼다.**
다음 사람이 「좋아 보이는데 왜 없지?」 하고 다시 넣는 것을 막기 위해서다.

원자료: `top100_klines.json` (24h 상승50 + 하락50 = 100종목, 97종목 완전)
      15m 500봉(5.2일) / 1h 500봉(21일) / 4h 500봉(83일)
상세  : `docs/spec/CHART_EVENT_*_2026-09-03.json|md`

### 🚨 표본의 근본 한계 (반증관 공통 지적 — 반드시 읽어라)

97종목이지만 **시장은 하나이고 15m 은 3.5~5일뿐**이다. 심볼 홀/짝 교차검증은
「시각으로 키가 잡히는 변수」(4H 슬롯, market breadth)에 대해 **검정력이 0**이다.
실제로 시간축으로 자르자 아래 규칙들이 죽었다:

    TOPREV_S1_STRICT_OBV   구간0 80.6% / 구간1 86.1% / 구간2 33.3%  → 기각
    R1~R5 breadth SHORT    15m 창 안 +25.8%p / 창 밖 11.5일 -0.4%p → 기각
    TREND_4H_SUSTAINED     15m 창 3등분 +27.9 / +25.2 / -3.1%p     → 기각

**따라서 살아남은 규칙의 기대치도 공표 승률(67~79%)이 아니라
「기준선 +5pp 안팎」으로 잡고 시작하라.** 배포 후 최소 100건으로 재측정할 것.

## 이 모듈이 답하는 것 / 답하지 않는 것

**「여기가 그 자리인가」만 답한다.** 「얼마를」은 자본 사다리(10/300/600),
「언제 파는가」는 적응 TP 가 정한다.

## ⚠️ fail-open

데이터 부족·계산 실패면 `detail["decided"] = False` 로 「판정 안 함」을 돌려준다.
이건 **좋은 자리를 고르는 필터이지 안전장치가 아니다.** 호출자는 절대
`ok is False` 를 「차단」으로 해석하지 마라 — `decided` 를 먼저 보라.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

FIX = "Fix331"


# ══════════════════════════════════════════════════════════════════════
# 설정 키 — 전부 chart_events_* 접두어
# ══════════════════════════════════════════════════════════════════════

SETTING_ENABLED = "chart_events_enabled"

# ① 정점 반전 (SHORT 1단계)
S_TOPREV_MIN_POINTS = "chart_events_toprev_min_points"
S_TOPREV_HIGH_LOOKBACK = "chart_events_toprev_high_lookback"
S_TOPREV_RUN24_MAX = "chart_events_toprev_run24_max"
S_TOPREV_OBV_SLOPE_MAX = "chart_events_toprev_obv_slope_max"
S_TOPREV_TOUCH_MIN = "chart_events_toprev_touch_min"

# ①-2 정점 재진입 (SHORT 2단계)
S_RESTAGE_TOP_MIN_POINTS = "chart_events_restage_top_min_points"
S_RESTAGE_TOP_VETO = "chart_events_restage_top_veto_enabled"
S_RESTAGE_TOP_HIGHER = "chart_events_restage_top_require_higher_peak"

# ② 저점 반전 (LONG 1단계)
S_BOTTOM_MIN_POINTS = "chart_events_bottom_min_points"
S_BOTTOM_BODY_MAX = "chart_events_bottom_body_ratio_max"
S_BOTTOM_ATR_LO = "chart_events_bottom_atr_pct_lo"
S_BOTTOM_ATR_HI = "chart_events_bottom_atr_pct_hi"
S_BOTTOM_PCTB_MAX = "chart_events_bottom_pctb_max"

# ②-2 저점 재진입 (LONG 2단계)
S_RESTAGE_BOTTOM_MIN_POINTS = "chart_events_restage_bottom_min_points"
S_RESTAGE_BOTTOM_MIN_DROP = "chart_events_restage_bottom_min_drop"

# ③④ 상승중 조정 → 반등 (LONG 주력)
S_PB_MIN_POINTS = "chart_events_pullback_min_points"
S_PB_MIN_DEPTH = "chart_events_pullback_min_depth"
S_PB_DEEP_DEPTH = "chart_events_pullback_deep_depth"
S_PB_MIN_LEG = "chart_events_pullback_min_leg"
S_PB_RSI24_MAX = "chart_events_pullback_rsi24_max"
S_PB_PCTB_MAX = "chart_events_pullback_pctb_max"
S_PB_VRATIO_MIN = "chart_events_pullback_vratio_min"

# ⑦ 4H 맥락 / 시장 폭
S_TREND4H_SHORT_MULT = "chart_events_trend4h_short_mult"
S_BREADTH_LONG_MAX = "chart_events_breadth_long_max"
S_BREADTH_LONG_MULT = "chart_events_breadth_long_mult"


@dataclass(frozen=True)
class Thresholds:
    """모든 임계값. 기본값 = 학습값(반증 통과분).

    🚨 여기 숫자를 바꾸기 전에 각 규칙 주석의 n / 승률 / 두 그룹을 읽어라.
       임계값을 조일수록 좋아 보이는 것은 이 표본에서 이미 함정이었다
       (TOPREV_S1_STRICT_OBV: 전반 90.2% / 후반 44.4%).
    """

    # ① 정점 반전
    toprev_min_points: int = 2
    toprev_high_lookback: int = 20
    toprev_run24_max: float = 0.03
    toprev_obv_slope_max: float = -0.15
    toprev_touch_min: int = 2
    # ①-2
    restage_top_min_points: int = 2
    restage_top_veto: bool = True
    restage_top_require_higher_peak: bool = True
    # ②
    bottom_min_points: int = 3
    bottom_body_ratio_max: float = 0.45
    bottom_atr_pct_lo: float = 0.0049
    bottom_atr_pct_hi: float = 0.0139
    bottom_pctb_max: float = 0.30
    # ②-2
    restage_bottom_min_points: int = 3
    restage_bottom_min_drop: float = 0.027
    # ③④
    pb_min_points: int = 3
    pb_min_depth: float = 0.03
    pb_deep_depth: float = 0.05
    pb_min_leg: float = 0.05
    pb_rsi24_max: float = 50.0
    pb_pctb_max: float = 0.25
    pb_vratio_min: float = 1.5
    # ⑦
    trend4h_short_mult: float = 1.08
    breadth_long_max: float = 0.40
    breadth_long_mult: float = 1.10

    @classmethod
    def load(cls, db: Any = None) -> "Thresholds":
        """DB 설정으로 덮어쓴다. db 가 None 이면 학습 기본값 그대로."""
        cfg = cls()
        if db is None:
            return cfg
        try:
            return replace(
                cfg,
                toprev_min_points=_int_setting(db, S_TOPREV_MIN_POINTS, cfg.toprev_min_points, 0, 4),
                toprev_high_lookback=_int_setting(db, S_TOPREV_HIGH_LOOKBACK, cfg.toprev_high_lookback, 5, 200),
                toprev_run24_max=_float_setting(db, S_TOPREV_RUN24_MAX, cfg.toprev_run24_max, 0.0, 1.0),
                toprev_obv_slope_max=_float_setting(db, S_TOPREV_OBV_SLOPE_MAX, cfg.toprev_obv_slope_max, -10.0, 10.0),
                toprev_touch_min=_int_setting(db, S_TOPREV_TOUCH_MIN, cfg.toprev_touch_min, 1, 10),
                restage_top_min_points=_int_setting(db, S_RESTAGE_TOP_MIN_POINTS, cfg.restage_top_min_points, 0, 2),
                restage_top_veto=_bool_setting(db, S_RESTAGE_TOP_VETO, cfg.restage_top_veto),
                restage_top_require_higher_peak=_bool_setting(
                    db, S_RESTAGE_TOP_HIGHER, cfg.restage_top_require_higher_peak),
                bottom_min_points=_int_setting(db, S_BOTTOM_MIN_POINTS, cfg.bottom_min_points, 0, 4),
                bottom_body_ratio_max=_float_setting(db, S_BOTTOM_BODY_MAX, cfg.bottom_body_ratio_max, 0.0, 1.0),
                bottom_atr_pct_lo=_float_setting(db, S_BOTTOM_ATR_LO, cfg.bottom_atr_pct_lo, 0.0, 1.0),
                bottom_atr_pct_hi=_float_setting(db, S_BOTTOM_ATR_HI, cfg.bottom_atr_pct_hi, 0.0, 1.0),
                bottom_pctb_max=_float_setting(db, S_BOTTOM_PCTB_MAX, cfg.bottom_pctb_max, 0.0, 1.0),
                restage_bottom_min_points=_int_setting(
                    db, S_RESTAGE_BOTTOM_MIN_POINTS, cfg.restage_bottom_min_points, 0, 4),
                restage_bottom_min_drop=_float_setting(
                    db, S_RESTAGE_BOTTOM_MIN_DROP, cfg.restage_bottom_min_drop, 0.0, 1.0),
                pb_min_points=_int_setting(db, S_PB_MIN_POINTS, cfg.pb_min_points, 0, 7),
                pb_min_depth=_float_setting(db, S_PB_MIN_DEPTH, cfg.pb_min_depth, 0.0, 1.0),
                pb_deep_depth=_float_setting(db, S_PB_DEEP_DEPTH, cfg.pb_deep_depth, 0.0, 1.0),
                pb_min_leg=_float_setting(db, S_PB_MIN_LEG, cfg.pb_min_leg, 0.0, 10.0),
                pb_rsi24_max=_float_setting(db, S_PB_RSI24_MAX, cfg.pb_rsi24_max, 0.0, 100.0),
                pb_pctb_max=_float_setting(db, S_PB_PCTB_MAX, cfg.pb_pctb_max, 0.0, 2.0),
                pb_vratio_min=_float_setting(db, S_PB_VRATIO_MIN, cfg.pb_vratio_min, 0.0, 100.0),
                trend4h_short_mult=_float_setting(db, S_TREND4H_SHORT_MULT, cfg.trend4h_short_mult, 1.0, 3.0),
                breadth_long_max=_float_setting(db, S_BREADTH_LONG_MAX, cfg.breadth_long_max, 0.0, 1.0),
                breadth_long_mult=_float_setting(db, S_BREADTH_LONG_MULT, cfg.breadth_long_mult, 1.0, 3.0),
            )
        except Exception as e:  # pragma: no cover - 설정 조회 전면 실패
            logger.warning("[%s] 설정 로드 실패 → 학습 기본값 사용: %s", FIX, e)
            return cfg


def _setting(db: Any, key: str) -> str | None:
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        if row is None or getattr(row, "value", None) is None:
            return None
        return str(row.value).strip() or None
    except Exception as e:
        logger.warning("[%s] %s 조회 실패: %s", FIX, key, e)
        return None


def _int_setting(db: Any, key: str, default: int, lo: int, hi: int) -> int:
    v = _setting(db, key)
    if v is None:
        return default
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        logger.warning("[%s] %s=%r 파싱 실패 → 기본 %s", FIX, key, v, default)
        return default
    if n < lo or n > hi:
        logger.warning("[%s] %s=%s 범위밖(%s~%s) → 기본 %s", FIX, key, n, lo, hi, default)
        return default
    return n


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


def module_enabled(db: Any) -> bool:
    """모듈 전체 스위치. 기본 ON (이 모듈 자체는 아무것도 차단하지 않는다).

    🚨 실제 진입 경로에 배선할 때는 **그 배선마다 별도의 OFF 기본 토글**을
       두어라 (헌법 161). 이 플래그는 「계산을 할 것인가」일 뿐이다.
    """
    v = _setting(db, SETTING_ENABLED)
    if v is None:
        return True
    return v.lower() in ("1", "true", "on", "yes")


# ══════════════════════════════════════════════════════════════════════
# 지표 — 이 모듈 안에서 독립 구현
#   support_score.py 의 _ema/_macd_hist/_rsi/_atr 를 참고해 **복사**했다.
#   순환 import 를 만들지 않기 위해서다 (의도적 중복).
# ══════════════════════════════════════════════════════════════════════

def _ema(v: Sequence[float], n: int) -> list[float]:
    if not v:
        return []
    k = 2.0 / (n + 1)
    out = [float(v[0])]
    for x in v[1:]:
        out.append(float(x) * k + out[-1] * (1 - k))
    return out


def _sma(v: Sequence[float], n: int) -> float | None:
    if len(v) < n or n <= 0:
        return None
    return sum(float(x) for x in v[-n:]) / n


def _macd_hist(closes: Sequence[float]) -> list[float] | None:
    """MACD(12,26,9) hist. 40봉 미만이면 신뢰할 수 없어 None.

    🚨 **원시값을 쓰지 마라.** 가격 단위라 심볼마다 스케일이 다르다.
       원시값 효과크기 0.01 → 「방향」(hist[i] vs hist[i-1])으로 바꾸니 2.08.
    """
    if len(closes) < 40:
        return None
    fast, slow = _ema(closes, 12), _ema(closes, 26)
    macd = [a - b for a, b in zip(fast, slow)]
    sig = _ema(macd, 9)
    return [a - b for a, b in zip(macd, sig)]


def _rsi(closes: Sequence[float], period: int) -> float | None:
    """Wilder RSI. 마지막 값만."""
    if len(closes) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = float(closes[i]) - float(closes[i - 1])
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / period, losses / period
    for i in range(period + 1, len(closes)):
        d = float(closes[i]) - float(closes[i - 1])
        ag = (ag * (period - 1) + max(d, 0.0)) / period
        al = (al * (period - 1) + max(-d, 0.0)) / period
    if al == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + (ag / al)))


def _atr(highs: Sequence[float], lows: Sequence[float],
         closes: Sequence[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(
            float(highs[i]) - float(lows[i]),
            abs(float(highs[i]) - float(closes[i - 1])),
            abs(float(lows[i]) - float(closes[i - 1])),
        ))
    if len(trs) < n:
        return None
    return sum(trs[-n:]) / n


def _cci(highs: Sequence[float], lows: Sequence[float],
         closes: Sequence[float], n: int = 9) -> float | None:
    """CCI(9). 표시·기록용 (채택 규칙에는 쓰지 않는다)."""
    if len(closes) < n:
        return None
    tp = [(float(highs[i]) + float(lows[i]) + float(closes[i])) / 3.0
          for i in range(len(closes))]
    win = tp[-n:]
    ma = sum(win) / n
    md = sum(abs(x - ma) for x in win) / n
    if md == 0:
        return 0.0
    return (tp[-1] - ma) / (0.015 * md)


def _obv(closes: Sequence[float], vols: Sequence[float]) -> list[float]:
    out = [0.0]
    for i in range(1, len(closes)):
        c, p = float(closes[i]), float(closes[i - 1])
        v = float(vols[i])
        out.append(out[-1] + (v if c > p else (-v if c < p else 0.0)))
    return out


def _obv_slope_norm(closes: Sequence[float], vols: Sequence[float], k: int) -> float | None:
    """🚨 OBV 기울기는 **반드시 거래량으로 정규화**한다.

        (obv[i] - obv[i-k]) / sum(volume[i-k+1..i])

    원시값을 쓰면 폭주한다 — 과거 `obv_slope_pct` 최대 **2,249,160** 사고로
    게이트가 통째로 무력화된 전력이 있다.
    """
    if len(closes) < k + 1 or len(vols) < k:
        return None
    ob = _obv(closes, vols)
    denom = sum(float(x) for x in vols[-k:])
    if denom <= 0:
        return None
    return (ob[-1] - ob[-1 - k]) / denom


def _bb(closes: Sequence[float], n: int = 20, k: float = 2.0
        ) -> tuple[float, float, float] | None:
    """볼린저(20,2) → (mid, upper, lower). 마지막 값만."""
    if len(closes) < n:
        return None
    win = [float(x) for x in closes[-n:]]
    mid = sum(win) / n
    var = sum((x - mid) ** 2 for x in win) / n
    sd = var ** 0.5
    return mid, mid + k * sd, mid - k * sd


def _pctb(closes: Sequence[float], n: int = 20, k: float = 2.0) -> float | None:
    b = _bb(closes, n, k)
    if b is None:
        return None
    _mid, up, lo = b
    if up <= lo:
        return None
    return (float(closes[-1]) - lo) / (up - lo)


def _bb_width_rank(closes: Sequence[float], n: int = 20, look: int = 200) -> float | None:
    """🚨 밴드폭은 **절대값 대신 자기 순위(percentile)**로 쓴다.

    절대 임계값을 쓰면 종목 스케일이 달라 무력해진다 (오늘만 세 번 걸린 함정).
    """
    if len(closes) < n + 10:
        return None
    widths: list[float] = []
    start = max(n, len(closes) - look)
    for i in range(start, len(closes) + 1):
        b = _bb(closes[:i], n)
        if b is None:
            continue
        mid, up, lo = b
        if mid > 0:
            widths.append((up - lo) / mid)
    if len(widths) < 10:
        return None
    cur = widths[-1]
    return sum(1 for w in widths if w <= cur) / len(widths)


def _body_ratio(o: float, h: float, low: float, c: float) -> float | None:
    rng = h - low
    if rng <= 0:
        return None
    return abs(c - o) / rng


def _lwick_ratio(o: float, h: float, low: float, c: float) -> float | None:
    rng = h - low
    if rng <= 0:
        return None
    return (min(o, c) - low) / rng


def _vol_ratio(vols: Sequence[float], n: int = 20) -> float | None:
    m = _sma(vols, n)
    if not m:
        return None
    return float(vols[-1]) / m


def _consec(closes: Sequence[float], opens: Sequence[float], up: bool) -> int:
    """연속 양봉(또는 음봉) 수."""
    n = 0
    for i in range(len(closes) - 1, -1, -1):
        green = float(closes[i]) > float(opens[i])
        if green == up:
            n += 1
        else:
            break
    return n


# ══════════════════════════════════════════════════════════════════════
# 캔들 처리
# ══════════════════════════════════════════════════════════════════════

class _Bars:
    """kline 리스트 → o/h/l/c/v 배열.

    6필드([open_time, o, h, l, c, v])와 바이낸스 12필드 둘 다 받는다.
    """

    __slots__ = ("o", "h", "l", "c", "v", "t", "n")

    def __init__(self, kl: Sequence[Sequence[Any]]):
        self.t = [k[0] for k in kl]
        self.o = [float(k[1]) for k in kl]
        self.h = [float(k[2]) for k in kl]
        self.l = [float(k[3]) for k in kl]
        self.c = [float(k[4]) for k in kl]
        self.v = [float(k[5]) for k in kl]
        self.n = len(kl)


def trim_open_bar(kl: Sequence[Sequence[Any]] | None,
                  keep_min: int = 2) -> list[Sequence[Any]] | None:
    """🚨 **진행 중인 마지막 봉을 잘라낸다.**

    봉 중간에 판정이 뒤집히면 안 된다 — 「꺾임 확인」·「MACD 방향」은
    현재 봉이 움직이는 동안 계속 켜졌다 꺼진다.
    4H 도 마찬가지다: 판정 시각에 **이미 완전히 닫힌** 4H 봉만 본다.
    """
    if not kl:
        return None
    if len(kl) <= keep_min:
        return list(kl)
    return list(kl[:-1])


def _bars(kl: Sequence[Sequence[Any]] | None, need: int,
          trim: bool) -> _Bars | None:
    if not kl:
        return None
    seq = trim_open_bar(kl, keep_min=need) if trim else list(kl)
    if seq is None or len(seq) < need:
        return None
    try:
        return _Bars(seq)
    except (TypeError, ValueError, IndexError) as e:
        logger.warning("[%s] 캔들 파싱 실패: %s", FIX, e)
        return None


def _undecided(_reason: str, **extra: Any) -> tuple[bool, float, dict[str, Any]]:
    """fail-open — 「판정 안 함」.

    ⚠️ 호출자는 `ok is False` 를 차단으로 읽지 마라. `detail["decided"]` 를 보라.

    🚨 파라미터 이름이 `_reason` 인 이유: 하위 판정 함수가 돌려주는 detail 에도
       `reason` 키가 들어 있어서 `_undecided(msg, **detail)` 이 「인자 중복」으로
       터진다. extra 를 먼저 펼치고 **바깥 사유가 이기게** 덮어쓴다.
    """
    d: dict[str, Any] = {}
    d.update(extra)
    d["decided"] = False
    d["reason"] = _reason
    return False, 0.0, d


def is_decided(detail: Mapping[str, Any] | None) -> bool:
    """판정이 실제로 내려졌는가 (데이터 부족/후보 아님이 아니라)."""
    return bool(detail) and bool(detail.get("decided"))


def _finish(rules: dict[str, bool], min_points: int,
            **extra: Any) -> tuple[bool, float, dict[str, Any]]:
    """점수 집계. score = 획득점수 / 계산가능한 최대점수 (0.0~1.0)."""
    avail = {k: v for k, v in rules.items() if v is not None}
    points = sum(1 for v in avail.values() if v)
    maxp = len(avail)
    score = (points / maxp) if maxp else 0.0
    ok = points >= min_points
    # extra 를 먼저 펼치고 집계 결과가 이기게 한다 (_undecided 와 같은 이유).
    d: dict[str, Any] = {}
    d.update(extra)
    d.update(decided=True, ok=ok, points=points, max_points=maxp,
             min_points=min_points, rules=rules)
    return ok, score, d


# ══════════════════════════════════════════════════════════════════════
# 공통 부품
# ══════════════════════════════════════════════════════════════════════

def _peak_touch_count(b: _Bars, window: int = 30, ratio: float = 0.99) -> int:
    """15m 고점터치 수 — 사장님 「지지 여러번 반복 후 하락 시작」.

    최근 30봉 중 **창 최고가의 99% 이상**인 스윙 고점의 수(현재 봉 포함).
    스윙 고점 = 좌우 1봉보다 높은 봉.

    근거: TOPREV_S1_TOUCH_1H (n=88 / 70.5% / d=0.282 / A 77.6% B 61.5%)
          TOPREV_S2_GATE_TOUCH (n=109 / 63.3% / d=0.363 / A 60.8% B 65.5%)
    """
    if b.n < 5:
        return 0
    seg = b.h[-window:]
    hi = max(seg)
    if hi <= 0:
        return 0
    lvl = hi * ratio
    cnt = 0
    for i in range(len(seg)):
        if seg[i] < lvl:
            continue
        left_ok = (i == 0) or seg[i] >= seg[i - 1]
        right_ok = (i == len(seg) - 1) or seg[i] >= seg[i + 1]
        if left_ok and right_ok:
            cnt += 1
    return cnt


def _low_touch_count(b: _Bars, window: int = 40, ratio: float = 1.01) -> int:
    """저점 터치 수 (기록용). 판정에는 쓰지 않는다 — 아래 사유 참조.

    🚨 BOTTOM_L2_TOUCH_VETO(「저점 2회 이상은 나쁘다」)는 **넣지 않았다.**
       심볼+블록 고정효과 보정 후 raw -0.149 → -0.053 으로 2/3 가 사라지고
       CI [-0.039,+0.144] 로 0 을 포함하며, 지정가 진입에서는 더 약해진다.
       사장님 「최저점 여러번 반복」을 뒤집을 근거가 못 된다.
    """
    if b.n < 5:
        return 0
    seg = b.l[-window:]
    lo = min(seg)
    if lo <= 0:
        return 0
    lvl = lo * ratio
    cnt = 0
    for i in range(len(seg)):
        if seg[i] > lvl:
            continue
        left_ok = (i == 0) or seg[i] <= seg[i - 1]
        right_ok = (i == len(seg) - 1) or seg[i] <= seg[i + 1]
        if left_ok and right_ok:
            cnt += 1
    return cnt


def _h4_hist_pair(b4: _Bars) -> tuple[float, float] | None:
    """마지막 **완전히 닫힌** 4H 봉의 MACD hist 와 그 직전 값."""
    mh = _macd_hist(b4.c)
    if not mh or len(mh) < 2:
        return None
    return mh[-1], mh[-2]


def _h4_ctx_score(b4: _Bars) -> tuple[int | None, dict[str, Any]]:
    """4H 맥락 점수 0~4 (LONG 우호도).

        (4H 최근6봉 양봉>=4) + (4H RSI12 > 55) + (4H %B > 0.6) + (4H OBV기울기 > 0)

    근거: 살아남은 조정 규칙 6개 중 4개가 `h4_ctx_score >= 2`,
          1개가 `>= 3` 을 조건으로 가진다 (PB_S3_*_H4S2 / PB_S2_VOLSPIKE_H4S3).

    🚨 **거부권 아님.** 아래 `is_pullback_entry` 에서 점수 1~2점으로만 쓴다.
    """
    d: dict[str, Any] = {}
    if b4.n < 40:
        return None, {"reason": "4h 봉 부족"}
    green6 = sum(1 for i in range(-6, 0) if b4.c[i] > b4.o[i]) if b4.n >= 6 else 0
    r12 = _rsi(b4.c, 12)
    pb = _pctb(b4.c)
    ob = _obv_slope_norm(b4.c, b4.v, 20)
    parts = {
        "h4_green6_ge4": green6 >= 4,
        "h4_rsi12_gt55": bool(r12 is not None and r12 > 55),
        "h4_pctb_gt06": bool(pb is not None and pb > 0.6),
        "h4_obv_up": bool(ob is not None and ob > 0),
    }
    d.update(parts, h4_green6=green6, h4_rsi12=r12, h4_pctb=pb, h4_obv_slope20=ob)
    return sum(1 for v in parts.values() if v), d


# ══════════════════════════════════════════════════════════════════════
# ⑦ 4H 「참고」 맥락 — 🚨 거부권이 아니다
# ══════════════════════════════════════════════════════════════════════

def trend_4h_context(kl_4h: Sequence[Sequence[Any]] | None,
                     *, db: Any = None, cfg: Thresholds | None = None,
                     trim: bool = True) -> tuple[str, float, dict[str, Any]]:
    """4H 중단기 흐름 — bias("up"|"down"|"range") + confidence(0.0~1.0).

    사장님: "4시간 차트의 의미는 **중단기 지속적인 흐름을 판단하는 정도**".
    → 이 함수는 **아무것도 막지 않는다.** 자본 배수(`capital_mult`)와
      점수 가점으로만 쓰라.

    ## 채택: TREND_4H_SHORT_STRONG (SHORT 쪽만)

        ema20_4h < ema50_4h AND close_4h < bb_mid_4h AND NOT(hist[-1] < hist[-2])

        n=93 / 승률 75.27% / 기준선 57.49% / 효과크기 0.447
        그룹 A 64.3% / 그룹 B 84.3%  ← 편차가 크다
        기간 밖 재현: 1h 21일 +13.2%p(4분기 전부 양수),
                     15m 창 이전 16일 50.0% vs 39.7% = +10.3%p
        lag 스캔으로 미래참조 없음 확인(미래로 밀면 70.1%→58.2% 로 **하락**)

    🚨 **숫자를 그대로 쓰지 마라.** 유효표본(Kish) 28.4, 심볼 짝지음 t=1.31(무의),
       15m 창 마지막 1/3 은 -9.5%p. 반증관 권고 = 배수 1.309 가 아니라
       부트스트랩 하한 61.8% 기준 **1.05~1.10**. 기본값 1.08 을 그대로 둘 것.

    ## 넣지 않은 것 — 반드시 읽어라 (다시 넣지 마라)

    * `TREND_4H_SHORT_SUSTAINED` (n=157/70.1%) — **기간 밖에서 부호 반전.**
      1h 21일 -1.8%p, 15m 창 밖 16일 -4.3%p, 15m 창 3등분 +27.9/+25.2/**-3.1**%p.
      게다가 SHORT_STRONG 의 상위집합일 뿐이고 잔차(n=64)의 CI 는 0 을 포함한다.
    * `TREND_4H_LONG_STRONG` (n=126/61.1%) — **Simpson 효과.** 같은 심볼 안에서
      짝지어 비교하면 -9.4~-11.3%p, CI [-2.3,+21.3] 로 0 포함. 학습자의 교차검증이
      통과한 이유는 그룹 승률을 그 그룹 기준이 아니라 **전체 기준 53.99%** 와
      비교했기 때문이다. → **LONG 은 4H 조건 없이 간다.**
    * 4단계 연속 가중치 [0.842, 0.917, 0.966, 1.309] — 앞의 세 등급은 서로
      구별되지 않는다(1점-0점 P(<=0)=30.2%, 2점-1점 34.0%). 「3점이냐 아니냐」의
      2단계일 뿐이다.
    * **현행 `trend_4h_gate.py`(Fix 270) 방식의 통과조건** — SHORT 통과군 52.1% vs
      차단군 58.8%, 무작위 심볼분할 200회 중 성립 **0회**, 마크투마켓 효과 -0.001.
      급등 구간(+10%↑) 통과율 **0.0%** = 정점 SHORT 를 정의상 전멸시킨다.
      정확한 표현은 「해롭다」가 아니라 **「이롭다는 근거가 전혀 없다」**.
      🚨 다만 그 파일 안의 실거래 실측(158건/10일, SHORT +12.74/건)과는
         모집단이 다르다. **이 모듈은 그 게이트를 건드리지 않는다.**
    """
    cfg = cfg or Thresholds.load(db)
    b4 = _bars(kl_4h, 60, trim)
    if b4 is None:
        return "range", 0.0, {"decided": False, "reason": "4h 봉 부족 (60봉 필요)"}

    try:
        e20 = _ema(b4.c, 20)[-1]
        e50 = _ema(b4.c, 50)[-1]
        bb = _bb(b4.c)
        pair = _h4_hist_pair(b4)
        ctx_score, ctx_d = _h4_ctx_score(b4)
    except Exception as e:  # pragma: no cover
        logger.warning("[%s] 4H 맥락 계산 실패: %s", FIX, e)
        return "range", 0.0, {"decided": False, "reason": f"계산 실패: {e}"}

    if bb is None or pair is None:
        return "range", 0.0, {"decided": False, "reason": "4h MACD/BB 계산 불가"}

    mid = bb[0]
    hist, hist_prev = pair
    short_strong = bool(e20 < e50 and b4.c[-1] < mid and not (hist < hist_prev))

    d: dict[str, Any] = {
        "decided": True,
        "ema20_4h": e20,
        "ema50_4h": e50,
        "bb_mid_4h": mid,
        "close_4h": b4.c[-1],
        "macd_hist_4h": hist,
        "macd_hist_4h_prev": hist_prev,
        "hist_rising": hist > hist_prev,
        "hist_positive": hist > 0,
        "short_strong": short_strong,
        "h4_ctx_score": ctx_score,
        "veto": False,          # 🚨 이 함수는 영원히 거부권을 갖지 않는다
    }
    d.update(ctx_d)

    if short_strong:
        d["capital_mult"] = cfg.trend4h_short_mult
        d["basis"] = "TREND_4H_SHORT_STRONG n=93 75.3% (기준 57.5%) d=0.447"
        return "down", 0.60, d

    d["capital_mult"] = 1.0
    if ctx_score is not None and ctx_score >= 3:
        # 🚨 LONG 방향 4H 는 **단독 근거가 없다**(LONG_STRONG 기각).
        #    조정 규칙(PB_*_H4S2/S3)의 구성요소로서만 의미가 있으므로
        #    confidence 를 낮게 준다.
        d["basis"] = "h4_ctx_score>=3 (조정 규칙 구성요소로만 유효)"
        return "up", 0.35, d
    return "range", 0.0, d


def market_breadth_context(breadth: float | None, *, db: Any = None,
                           cfg: Thresholds | None = None) -> tuple[str, float, dict[str, Any]]:
    """시장 폭(top100 중 15m close > EMA50 비율) → LONG 국면 가중치.

    ## 채택: R6_long_breadth_low (breadth <= 0.40 → LONG 우호)

        15m 2.83일 +9.2%p / 1h 창 안 +7.2%p / 1h 창 밖 **독립 11.5일 +10.9%p**
        / 4h 60일 +3.9%p(시간 5분할 5/5) / 심볼 76종목 중 56종목(74%) 같은 방향
        진입가정 3종 전부 부호 유지 (+10.9 종가 / +6.5 저항선지정가 / +8.7 봉중간)

    🚨 크기는 깎아서 잡아라. 최장 창(60일)에서는 +3.9%p, 「저항 고유 기여」는
       독립창에서 +4.1%p 뿐이다(나머지는 국면). 기대 기여 **+4%p 안팎**.

    ## 넣지 않은 것

    * R1~R5 (breadth 높음 → SHORT) 5종 전부 — **효과가 15m 연구창 3일에만 갇혀 있다.**
      1h 창 안 +25.8%p → 창 밖 11.5일 **-0.4%p**. R5 는 72.1%(최고)에서
      독립창 40.5% (기저 44.6%) 로 부호 반전. 게다가 breadth>=0.65 는 273봉 중
      단 **10봉**에서만 발생 = n=560 이 아니라 실질 10관측.
    * R7 (breadth <= 0.33) — 조여도 이득이 없다(4h 60일 +0.0%p). R6 로 흡수.
    * 🚨 breadth 는 **타임스탬프만의 함수**라 심볼 홀/짝 교차검증의 검정력이 0이다.
      같은 봉의 100종목이 전부 같은 값을 공유한다.

    ⚠️ **결손이면 「통과」로 두지 마라** — 이 프로젝트는 결손 fallback 이 판정을
       뒤집은 전력이 있다(Fix 296). 결손이면 mult 1.0 + decided=False.
    """
    cfg = cfg or Thresholds.load(db)
    if breadth is None:
        return "range", 1.0, {"decided": False, "reason": "market_breadth 결손 — 판정 안 함"}
    try:
        br = float(breadth)
    except (TypeError, ValueError):
        return "range", 1.0, {"decided": False, "reason": f"breadth 파싱 실패: {breadth!r}"}
    if not (0.0 <= br <= 1.0):
        return "range", 1.0, {"decided": False, "reason": f"breadth 범위밖: {br}"}

    d: dict[str, Any] = {"decided": True, "breadth": br,
                         "threshold": cfg.breadth_long_max, "veto": False}
    if br <= cfg.breadth_long_max:
        d["capital_mult"] = cfg.breadth_long_mult
        d["basis"] = "R6_long_breadth_low n=2236 59.8% (기저 50.6%) — 독립 11.5일 +10.9%p"
        return "long_favorable", cfg.breadth_long_mult, d
    d["capital_mult"] = 1.0
    return "neutral", 1.0, d


# ══════════════════════════════════════════════════════════════════════
# ① 최고점에서 하락 시점 (정점 반전) — SHORT 1단계
# ══════════════════════════════════════════════════════════════════════

def _toprev_base(b15: _Bars, lookback: int) -> tuple[bool, int | None, dict[str, Any]]:
    """15m 주축 후보 — TOPREV_S1_TURN_BASE (꺾임 확인).

        high[i-3..i] 중 하나가 20봉 신고가 AND close[i] < open[i]
        AND close[i] < close[i-1] AND high[i] 는 신고가 아님

    n=762 / 승률 54.33% / A 55.25% B 53.31% / 97종목 / 건당 +0.124%
    🚨 **단독 사용 절대 금지.** 기준선(54.3%) 수준이고, 왕복 수수료 0.10% 를
       반영하면 건당 +0.024% = 사실상 0 이다. 반드시 아래 점수와 함께 쓴다.
    """
    d: dict[str, Any] = {}
    if b15.n < lookback + 6:
        return False, None, {"reason": "15m 봉 부족"}
    i = b15.n - 1

    def _is_new_high(t: int) -> bool:
        s = max(0, t - (lookback - 1))
        return b15.h[t] >= max(b15.h[s:t + 1])

    pk: int | None = None
    for t in range(max(0, i - 3), i + 1):
        if _is_new_high(t) and (pk is None or b15.h[t] >= b15.h[pk]):
            pk = t
    d["peak_idx"] = pk
    d["peak_high"] = b15.h[pk] if pk is not None else None
    if pk is None:
        return False, None, {**d, "reason": f"최근 4봉에 {lookback}봉 신고가 없음"}
    if _is_new_high(i):
        return False, pk, {**d, "reason": "현재 봉이 아직 신고가 (꺾임 아님)"}
    if not (b15.c[i] < b15.o[i]):
        return False, pk, {**d, "reason": "현재 봉이 음봉이 아님"}
    if not (b15.c[i] < b15.c[i - 1]):
        return False, pk, {**d, "reason": "종가가 직전 종가보다 낮지 않음"}
    return True, pk, d


def _run24_from_peak(b15: _Bars, pk: int) -> float | None:
    """정점봉까지의 6시간(24봉) 상승폭.

        (high[pk] - min(low[pk-24..pk])) / min(low[pk-24..pk])

    🚨 **수식 주의.** 공표 스펙에는 `close[i]` 로 적혀 있으나, n=114 / 74.6% 를
       만든 실제 학습 코드는 `high[pk]`(정점봉 고가)다. 반증관이 잡았다 —
       문서식으로 구현하면 n=149 / 72.5% 로 **다른 규칙**이 된다.
       여기서는 실측을 만든 코드식을 쓴다.
    """
    s = max(0, pk - 24)
    lo = min(b15.l[s:pk + 1])
    if lo <= 0:
        return None
    return (b15.h[pk] - lo) / lo


def is_top_reversal(kl_15m: Sequence[Sequence[Any]] | None,
                    kl_4h: Sequence[Sequence[Any]] | None,
                    *, kl_1h: Sequence[Sequence[Any]] | None = None,
                    db: Any = None, cfg: Thresholds | None = None,
                    trim: bool = True) -> tuple[bool, float, dict[str, Any]]:
    """정점 반전 — SHORT 1단계 진입 자리인가.

    사장님: "최고점의 차트와 보조지표로 알 수 있잖아. 첫 진입은 그렇게 하고".

    ## 구조 — 15분이 주축, 4시간은 점수 1점씩

        [필수] TOPREV_S1_TURN_BASE (15m 꺾임 확인)   ← 이게 없으면 후보가 아니다
        [+1]   run24_peak <= 3%       (15m)
        [+1]   4H MACD hist 상승중     (4h 참고)
        [+1]   4H OBV 기울기 <= -0.15  (4h 참고)
        [+1]   고점터치>=2 AND 1H hist 안오름 (15m+1h)
        기본 통과선 = 2점

    **4H 없이도 통과 가능**(run24 + 고점터치 = 2점) → 거부권이 아니다.

    ## 각 점수의 실측

    * `run24_peak <= 3%` — 직전 6시간 상승폭이 작다 = 「이미 크게 오른 것」이
      아니라 **「조용히 고점을 다지던 것」**.
      TOPREV_S1_STRICT_RUN: n=114 / 74.6% / d=0.445 / A 77.9% B 67.6%
      🚨 반증관 권고: 표본이 얇은 STRICT_RUN 대신
         **`4H hist 상승중 AND run24<=3%`(n=234 / 64.5% / 3분할 +10·+8·+10pp)**
         를 기본으로 검토하라 — 표본 2배에 똑같이 안정적이다.
         이 함수의 2점 통과선이 정확히 그 조합이다.
    * `4H hist 상승중` — TOPREV_S1_4H_DIR: n=458 / 57.9% / d=0.174 /
      A 58.7% B 56.9% (기준선 54.3%). 층화 순열검정 p=0.029.
      🚨 라벨 2%/2%/32봉에서는 51.7% vs 기준 52.0% = **16시간 지평에서만** 산다.
    * `4H OBV <= -0.15` — TOPREV_S1_4H_OBV: n=209 / 67.0% / d=0.366 /
      A 66.9% B 67.1%. 순열 p=0.0002.
      🚨 시간 3분할 +9.3 / +19.5 / **+1.8**%p — 가장 최근 구간에서 사실상 0이다.
    * `고점터치>=2 + 1H hist 안오름` — TOPREV_S1_TOUCH_1H: n=88 / 70.5% /
      d=0.282 / A 77.6% B 61.5%. 순열 p=0.0028.
      사장님 「지지 여러번 반복 후 하락 시작」이 실측으로 확인된 자리.

    ## 넣지 않은 것 (다시 넣지 마라)

    * `TOPREV_S1_STRICT_OBV` (OBV <= **-0.30**, n=122 / 73.0%) —
      🚨 **시간축에서 완전히 뒤집힌다.** 구간0 80.6% / 구간1 86.1% / 구간2 **33.3%**
      (그 구간 기준선 44.4%). 시간전진 홀드아웃에서 후반 45.5%/33건 = 기준선 아래.
      「임계값 -0.05~-0.30 단조 증가 = 절벽 없음」이라는 유일한 방어 논거도 반증됐다:
      단조성은 **전반부에만** 있고 후반부는 정확히 반대로 단조 **감소**한다
      (임계값 0.00→64.9/59.3, -0.15→73.0/54.4, -0.30→83.1/45.5, -0.40→90.2/44.4).
      = 전형적인 임계값 과적합. **OBV 임계값을 -0.15 보다 조이지 마라.**
    * 4H 를 통과조건으로 만드는 어떤 형태든 — 후보 762건 중 304건(40%)을 버리면서
      `trend_4h_gate.py` 안의 실거래 실측(SHORT 게이트 적용 +12.74/건)을 정면으로
      거스른다. 두 측정은 모집단이 다르므로 「참고로만 쓴다」가 유일하게 양립한다.

    ## 기대치

    공표 승률 67~75% 를 그대로 믿지 마라. 학습자 자신의 일반화 진단이 상한을
    **기준선 +5pp(≈59%)** 로 못박았다. 배포 후 최소 100건으로 재측정할 것.
    """
    cfg = cfg or Thresholds.load(db)
    b15 = _bars(kl_15m, cfg.toprev_high_lookback + 30, trim)
    if b15 is None:
        return _undecided("15m 봉 부족")

    try:
        base_ok, pk, bd = _toprev_base(b15, cfg.toprev_high_lookback)
        if not base_ok:
            return _undecided(f"정점 반전 후보 아님: {bd.get('reason')}", **bd)

        rules: dict[str, bool] = {}
        d: dict[str, Any] = dict(bd)

        # ── 15m 축 ────────────────────────────────────────────────
        run24 = _run24_from_peak(b15, pk) if pk is not None else None
        d["run24_peak"] = run24
        rules["m15_run24_le_3pct"] = bool(run24 is not None and run24 <= cfg.toprev_run24_max)

        touch = _peak_touch_count(b15)
        d["peak_touch"] = touch
        d["cci9_15m"] = _cci(b15.h, b15.l, b15.c, 9)
        d["rsi12_15m"] = _rsi(b15.c, 12)

        # ── 4H 참고 ───────────────────────────────────────────────
        b4 = _bars(kl_4h, 40, trim)
        if b4 is not None:
            pair = _h4_hist_pair(b4)
            obv4 = _obv_slope_norm(b4.c, b4.v, 14)
            d.update(h4_hist=(pair[0] if pair else None),
                     h4_hist_prev=(pair[1] if pair else None),
                     h4_obv_slope14=obv4)
            if pair is not None:
                rules["h4_hist_rising"] = bool(pair[0] > pair[1])
            if obv4 is not None:
                rules["h4_obv_le_neg015"] = bool(obv4 <= cfg.toprev_obv_slope_max)
        else:
            d["h4"] = "4h 봉 부족 — 4H 점수 없이 15m 만으로 판정 (거부권 아님)"

        # ── 15m + 1H ──────────────────────────────────────────────
        b1 = _bars(kl_1h, 40, trim)
        if b1 is not None:
            mh1 = _macd_hist(b1.c)
            if mh1 and len(mh1) >= 2:
                d.update(h1_hist=mh1[-1], h1_hist_prev=mh1[-2])
                rules["m15_touch_and_h1_not_rising"] = bool(
                    touch >= cfg.toprev_touch_min and mh1[-1] <= mh1[-2])

        return _finish(rules, cfg.toprev_min_points, side="SHORT", stage=1, **d)
    except Exception as e:  # pragma: no cover
        logger.warning("[%s] is_top_reversal 실패 → 판정 안 함: %s", FIX, e)
        return _undecided(f"계산 실패: {e}")


def is_restage_top(kl_15m: Sequence[Sequence[Any]] | None,
                   kl_4h: Sequence[Sequence[Any]] | None,
                   prev: Mapping[str, Any] | None = None,
                   *, kl_1h: Sequence[Sequence[Any]] | None = None,
                   db: Any = None, cfg: Thresholds | None = None,
                   trim: bool = True) -> tuple[bool, float, dict[str, Any]]:
    """🚨 정점 2단계 재진입 — 「다시 최고점에서 하락으로 보이는 지표」.

    사장님: "그것이 실패하면 10usdt 남기고 부분손절하고 **차트와 보조지표가
             다시 최고점에서 하락으로 보이는 지표 15분과 4시간일때 2단계 진입**".

    `prev` 에 1단계 정보를 넘긴다: `{"peak": 1단계 정점가}`
    (`peak` / `high` / `peak_price` / `stage1_peak` 중 아무 키나 인식).

    ## 구조

        [필수] 15m 꺾임 확인 (1단계와 같은 판정)
        [필수·사장님 지시] 새 정점 > 이전 정점        ← 「다시 최고점」
        [금지]  4H MACD hist <= 0 이면 2단계 금지
        [+1]   4H hist > 0 AND 상승중
        [+1]   고점터치 >= 2
        기본 통과선 = 2점 (= TOPREV_S2_GATE_TOUCH)

    ## 🚨 「금지」가 4H 거부권 아닌가?

    아니다 — **진입 판정이 아니라 자본 30배 증액(10 → 300 USDT) 판정**이다.
    사장님 정정(「15분이 기준」)은 진입 자리를 고르는 주축에 관한 것이고,
    여기서 막는 것은 「이 자리에 300 USDT 를 실을 것인가」다.
    끄고 싶으면 `chart_events_restage_top_veto_enabled=false`.

    TOPREV_S2_VETO: n=69 / 승률 **37.7%** / d=-0.301 / A 41.0% B 33.3% /
      36종목 / 건당 -0.661%. 반증관이 던진 모든 검정을 견뎠다 —
      시간 2분할 48.4%/28.9%(기준 57.5%/44.2%), 라벨 5종 전부 -12~-18pp,
      진입가 3종 동일, 심볼 부트 CI [26.8,49.3], 4H슬롯 부트 CI [27.8,47.1].
    ⚠️ 경고 두 가지(반증관): ① n=69 이고 효과가 하락종목에 몰려 있다
       (하락 25건 28.0% vs 모집단 63.0% = -35pp / 상승 44건 43.2% vs 47.9% = -4.7pp).
       ② 「1단계는 방향, 2단계는 수준」이라는 설명은 기전이 아니라 상호작용이다
       (같은 조건이 1단계 266건 60.2%(최고) / 2단계 53건 34.0%(최저)).
       → **금지까지만 쓰고, 자본 증액의 근거로는 쓰지 마라.** 실거래 100건으로 재확인.

    ## 넣지 않은 것

    * `TOPREV_S2_GATE` 단독 (4H hist>0 AND 상승중, n=230 / 58.3%) —
      🚨 **300 USDT 를 실을 근거로는 부족.** 4H슬롯 부트스트랩 95%CI [50.5, 64.9]
      가 2단계 기준선 50.8% 를 **배제하지 못한다**(자매 규칙 S2_VETO [27.8,47.1],
      S2_GATE_TOUCH [51.5,72.7] 는 배제함). 부 후보군 재현도 +5.3pp 로 절반.
      → 고점터치를 **함께** 요구하는 GATE_TOUCH 만 채택. 통과선 2점 = 둘 다.
      TOPREV_S2_GATE_TOUCH: n=109 / 63.3% / d=0.363 / A 60.8% B 65.5%.
      ⚠️ 이 규칙의 익절 목표는 **3% 로 낮출 것**(5% 목표로 재면 45%로 떨어진다).
    * 「단계가 깊어질수록 승률이 낮아진다」는 경고 — **라벨 의존**이다.
      7개 라벨·진입가 변형 중 3개에서 비단조로 무너진다(2%/3%/64봉에서는
      1단계 60.5% < 2단계 62.5%). 자기모순이기도 하다 — 같은 문서가
      「2단계는 TP 를 3% 이하로」라고 권하는데 그 낮은 TP 라벨로 재면 뒤집힌다.
      → **자본 사다리(10/300/600) 자체를 이 데이터로 부정하지 마라.**
    """
    cfg = cfg or Thresholds.load(db)
    b15 = _bars(kl_15m, cfg.toprev_high_lookback + 30, trim)
    if b15 is None:
        return _undecided("15m 봉 부족")

    try:
        base_ok, pk, bd = _toprev_base(b15, cfg.toprev_high_lookback)
        if not base_ok:
            return _undecided(f"정점 반전 후보 아님: {bd.get('reason')}", **bd)

        d: dict[str, Any] = dict(bd, stage=2, side="SHORT")

        # ── 사장님 지시: 「다시 최고점」 = 이전 정점보다 높아야 한다 ──
        #    (실측이 아니라 지시다. 설정으로 끌 수 있게 두었다.)
        prev_peak = _prev_num(prev, "peak", "high", "peak_price", "stage1_peak")
        new_peak = b15.h[pk] if pk is not None else None
        d.update(prev_peak=prev_peak, new_peak=new_peak)
        if cfg.restage_top_require_higher_peak:
            if prev_peak is None:
                d["higher_peak"] = None
                logger.info("[%s] 이전 정점 미상 — 「다시 최고점」 조건 생략", FIX)
            elif new_peak is None or not (new_peak > prev_peak):
                return False, 0.0, {
                    "decided": True, "ok": False,
                    "reason": "새 정점이 이전 정점보다 높지 않음 "
                              "(사장님 「다시 최고점에서 하락」)",
                    **d,
                }
            else:
                d["higher_peak"] = True

        # ── 4H ────────────────────────────────────────────────────
        rules: dict[str, bool] = {}
        b4 = _bars(kl_4h, 40, trim)
        pair = _h4_hist_pair(b4) if b4 is not None else None
        if pair is not None:
            d.update(h4_hist=pair[0], h4_hist_prev=pair[1])
            if cfg.restage_top_veto and not (pair[0] > 0):
                return False, 0.0, {
                    "decided": True, "ok": False, "veto": True,
                    "reason": "TOPREV_S2_VETO — 4H MACD hist <= 0 이면 2단계 금지 "
                              "(n=69 승률 37.7%, 건당 -0.661%)",
                    **d,
                }
            rules["h4_hist_pos_and_rising"] = bool(pair[0] > 0 and pair[0] > pair[1])
        else:
            d["h4"] = "4h 봉 부족 — 금지·가점 모두 미적용"

        touch = _peak_touch_count(b15)
        d["peak_touch"] = touch
        rules["m15_touch_ge2"] = bool(touch >= cfg.toprev_touch_min)

        b1 = _bars(kl_1h, 40, trim)
        if b1 is not None:
            mh1 = _macd_hist(b1.c)
            if mh1 and len(mh1) >= 2:
                d.update(h1_hist=mh1[-1], h1_hist_prev=mh1[-2])

        d["tp_hint_pct"] = 3.0  # ⚠️ 5% 목표로 재면 63.3% → 45% 로 떨어진다
        return _finish(rules, cfg.restage_top_min_points, **d)
    except Exception as e:  # pragma: no cover
        logger.warning("[%s] is_restage_top 실패 → 판정 안 함: %s", FIX, e)
        return _undecided(f"계산 실패: {e}")


# ══════════════════════════════════════════════════════════════════════
# ② 하락 후 반등 시점 (저점 반전) — LONG 1단계
# ══════════════════════════════════════════════════════════════════════

def _bottom_base(b15: _Bars) -> tuple[bool, dict[str, Any]]:
    """15m 저점 반전 후보.

        low[i] <= min(low[i-11..i]) + 0.25 * ATR14   AND   close[i] > open[i]

    (학습 표본: 후보 간 최소 4봉 간격. 실시간에서는 워커의 중복 진입 가드가
     같은 역할을 하므로 여기서는 판정만 한다.)
    """
    d: dict[str, Any] = {}
    if b15.n < 40:
        return False, {"reason": "15m 봉 부족"}
    atr = _atr(b15.h, b15.l, b15.c, 14)
    if atr is None:
        return False, {"reason": "ATR 계산 불가"}
    lo12 = min(b15.l[-12:])
    d.update(atr=atr, low12=lo12, low=b15.l[-1])
    if not (b15.l[-1] <= lo12 + 0.25 * atr):
        return False, {**d, "reason": "최근 12봉 저점영역이 아님"}
    if not (b15.c[-1] > b15.o[-1]):
        return False, {**d, "reason": "양봉이 아님"}
    return True, d


def _bottom_rules(b15: _Bars, cfg: Thresholds) -> tuple[dict[str, bool], dict[str, Any]]:
    """저점 반전 4점 채점 (15m 단독 — 4H 는 쓰지 않는다).

    ## 🚨 왜 4H 가 없는가

    반증관 재계산: Fix 270 게이트 통과쪽(4H hist>0 & 상승중)이 LONG 저점에서
    raw -0.025 / **심볼+블록 고정효과 -0.052** / 지정가 -0.037.
    게이트가 막는 쪽(4H hist 하락중)은 +0.023 / +0.027 / +0.042.
    세 라벨 모두 같은 방향 = **4H 조건은 LONG 저점에서 해롭다.**
    사장님 정정(「15분이 기준, 4시간은 참고」)이 재계산으로도 지지된다.

    ## 🚨 왜 `chg48_pit > -8%`(BOTTOM_NO_DUMP_48H)가 없는가 — 가장 중요한 반증

    채택 규칙 3개 전부가 이 조건을 포함했는데, **그 우위 전량이 종목 선택
    편향**이었다. 유니버스가 「수집시점 24h 상승/하락 50위」라서 상승군 기저
    승률 0.553 vs 하락군 0.435(+0.118)가 구성만으로 생긴다. 이 조건은
    상승군을 57.9% 뽑고 여집합은 19.0% 만 뽑는다.
    심볼 고정효과를 빼면 lift **+0.119 → -0.029** 로 소멸·역전하고,
    심볼 내부 짝지은 비교에서 9개 심볼 중 1개만 양수(부호검정 p=0.020).

    → 반증관 실행 권고: **오염된 조건을 빼면 표본은 2배, 효과는 더 크다.**
       `smallbody + atr_mid + pb_low` : n=304 / FE **+0.119** /
       CI [+0.056,+0.177] p=0.000 / 세 진입가정 +0.117~+0.119
       (vs BOTTOM_L1_STRICT n=167 / FE +0.102 / CI [+0.028,+0.169])
       기본 통과선 3점이 정확히 그 조합이다.

    ## 각 점수 (심볼+블록 고정효과 보정치)

        body_ratio < 0.45   raw +0.103  FE **+0.094**   ← 진짜 신호
        pctB < 0.30         raw +0.066  FE +0.059
        low < bb_lower      raw +0.040  FE +0.047
        0.49% <= atr% < 1.39%  raw +0.111  FE +0.022

    원 규칙(참고): BOTTOM_L1_STRICT n=167 / 68.9% / lift +0.192 / A 66.0 B 72.6
                  BOTTOM_L1_BB     n=169 / 65.1% / lift +0.154 / A 64.9 B 65.3
                  BOTTOM_L1_CORE   n=230 / 65.2% / lift +0.156 / A 64.9 B 65.6
                  (CORE 는 CI 하한 +0.004 로 간신히 생존 = 셋 중 가장 약하다)
    ⚠️ 기대치는 승률 0.65~0.71 이 아니라 **기저 대비 +0.06~+0.12**.
    """
    o, h, low, c = b15.o[-1], b15.h[-1], b15.l[-1], b15.c[-1]
    body = _body_ratio(o, h, low, c)
    lw = _lwick_ratio(o, h, low, c)
    atr = _atr(b15.h, b15.l, b15.c, 14)
    atr_pct = (atr / c) if (atr and c) else None
    pb = _pctb(b15.c)
    bb = _bb(b15.c)

    rules: dict[str, bool] = {}
    if body is not None:
        rules["m15_smallbody"] = bool(body < cfg.bottom_body_ratio_max)
    if atr_pct is not None:
        rules["m15_atr_mid"] = bool(cfg.bottom_atr_pct_lo <= atr_pct < cfg.bottom_atr_pct_hi)
    if pb is not None:
        rules["m15_pctb_low"] = bool(pb < cfg.bottom_pctb_max)
    if bb is not None:
        rules["m15_below_bb_lower"] = bool(low < bb[2])

    d: dict[str, Any] = {
        "body_ratio": body, "lwick_ratio": lw, "atr_pct": atr_pct, "pctb": pb,
        "bb_lower": (bb[2] if bb else None),
        "rsi24_15m": _rsi(b15.c, 24),
        "cci9_15m": _cci(b15.h, b15.l, b15.c, 9),
        "low_touch_40": _low_touch_count(b15),
    }
    return rules, d


def is_bottom_reversal(kl_15m: Sequence[Sequence[Any]] | None,
                       kl_4h: Sequence[Sequence[Any]] | None,
                       *, market_breadth: float | None = None,
                       db: Any = None, cfg: Thresholds | None = None,
                       trim: bool = True) -> tuple[bool, float, dict[str, Any]]:
    """저점 반전 — LONG 1단계 진입 자리인가. 사장님 「최저점도 같은 전략」.

    15m 단독 판정이다. `kl_4h` 는 **기록용으로만** 받는다(위 `_bottom_rules`
    주석 참조 — 4H 조건은 LONG 저점에서 해롭다는 것이 재계산 결과다).

    채점 근거(상세는 `_bottom_rules`): BOTTOM_L1_STRICT n=167 / BOTTOM_L1_BB n=169 /
    BOTTOM_L1_CORE n=230, 그리고 반증관 권고형 `smallbody+atr_mid+pb_low` n=304.
    기본 통과선 3점 = 그 권고형.

    `market_breadth`(top100 중 15m close>EMA50 비율)를 주면 R6 국면 가중치를
    `detail["capital_mult"]` 로 돌려준다. **막지 않는다.**
    """
    cfg = cfg or Thresholds.load(db)
    b15 = _bars(kl_15m, 40, trim)
    if b15 is None:
        return _undecided("15m 봉 부족 (40봉 필요)")

    try:
        ok_base, bd = _bottom_base(b15)
        if not ok_base:
            return _undecided(f"저점 반전 후보 아님: {bd.get('reason')}", **bd)

        rules, rd = _bottom_rules(b15, cfg)
        d: dict[str, Any] = {**bd, **rd, "side": "LONG", "stage": 1}

        b4 = _bars(kl_4h, 40, trim)
        if b4 is not None:
            pair = _h4_hist_pair(b4)
            if pair is not None:
                # 🚨 기록만 한다. 판정에 쓰지 마라 (FE -0.052).
                d.update(h4_hist=pair[0], h4_hist_prev=pair[1],
                         h4_note="4H 는 LONG 저점 판정에 쓰지 않는다 (FE -0.052)")

        bias, mult, brd = market_breadth_context(market_breadth, cfg=cfg)
        d.update(breadth_bias=bias, capital_mult=mult, breadth_detail=brd)

        return _finish(rules, cfg.bottom_min_points, **d)
    except Exception as e:  # pragma: no cover
        logger.warning("[%s] is_bottom_reversal 실패 → 판정 안 함: %s", FIX, e)
        return _undecided(f"계산 실패: {e}")


def is_restage_bottom(kl_15m: Sequence[Sequence[Any]] | None,
                      kl_4h: Sequence[Sequence[Any]] | None,
                      prev: Mapping[str, Any] | None = None,
                      *, market_breadth: float | None = None,
                      db: Any = None, cfg: Thresholds | None = None,
                      trim: bool = True) -> tuple[bool, float, dict[str, Any]]:
    """🚨 저점 2단계 재진입 — 「다시 최저점」. 사장님 「최저점도 같은 전략」.

    `prev` 에 1단계 저점을 넘긴다: `{"low": 1단계 저점}`
    (`low` / `stage1_low` / `bottom` / `low_price` 중 아무 키나 인식).

    ## 구조

        [필수] 15m 저점 반전 후보 (1단계와 같은 판정)
        [필수] 1단계 저점보다 **2.7% 이상** 더 내려간 새 저점  ← BOTTOM_L2_MIN_DROP
        [점수] 1단계와 **완전히 같은 4점 채점**

    ## 🚨 2단계 전용 규칙을 만들지 않은 이유 — 탐색 잡음이었다

    반증관이 라벨을 (심볼 × 8시간블록) 안에서 섞어 귀무분포를 만들고
    학습자와 **똑같은 탐색**(11조건, 최대 4조합, minn=30, 홀/짝 cv_ok)을
    300회 돌린 결과:

        단계   실측 최고 min(A,B)lift   귀무 중앙   귀무 p95    p
        1단계        +0.174            +0.141     +0.167    p=0.003
        2단계        +0.218            **+0.238**  +0.257    p=1.000

    **2단계는 귀무 중앙값보다도 낮다.** 561개 조합을 훑고 두 그룹 다 양수인
    것만 고르면 이 정도 숫자는 순수 우연으로 더 잘 나온다.
    → `BOTTOM_L2_CORE`(0.710) / `L2_SMALLBODY` / `L2_NO_DUMP` / `L2_4H_DOWN` /
      `L2_TOUCH_VETO` 전부 **넣지 않았다.** 심볼FE 보정 후 -0.039~-0.010 이다.
    → `support_score.py` 와 같은 결론: **재진입도 같은 점수로 판정한다.**

    ## 살아남은 유일한 2단계 조건

    BOTTOM_L2_MIN_DROP `(low1 - low2)/low1 >= 0.027`
      n=430 / 57.9% / 기저 54.6% / 심볼+블록FE **+0.065** /
      CI [+0.006,+0.122] p=0.018 / 9개 분할 9/9 / 세 진입가정 +0.055~+0.077
      간발의 신저점(0~2.7%)은 승률 0.474 로 최악.

    ## 🚨 「2단계가 1단계보다 낫다」(0.546 vs 0.497)는 국면 아티팩트

    2단계 표본의 23.8% 가 블록3 한 곳(08-30 22h, 시장 전체 폭락 직후 반등,
    기저 0.644)에 몰려 있다(1단계는 5.2%). 8시간 블록 내부에서 비교하면
    2단계 - 1단계 = **-0.019**, 11블록 중 6개만 양수.
    손절이 시장 전체 급락에 몰리므로 2단계가 구조적으로 반등 구간에 놓일 뿐이다.
    → **2단계에 자본을 더 싣는 근거로 이 숫자를 쓰지 마라.**
    """
    cfg = cfg or Thresholds.load(db)
    b15 = _bars(kl_15m, 40, trim)
    if b15 is None:
        return _undecided("15m 봉 부족 (40봉 필요)")

    try:
        ok_base, bd = _bottom_base(b15)
        if not ok_base:
            return _undecided(f"저점 반전 후보 아님: {bd.get('reason')}", **bd)

        d: dict[str, Any] = {**bd, "side": "LONG", "stage": 2}

        prev_low = _prev_num(prev, "low", "stage1_low", "bottom", "low_price")
        new_low = b15.l[-1]
        d.update(prev_low=prev_low, new_low=new_low)
        if prev_low is None:
            d["min_drop"] = None
            logger.info("[%s] 이전 저점 미상 — MIN_DROP 조건 생략", FIX)
        else:
            drop = (prev_low - new_low) / prev_low if prev_low > 0 else None
            d["min_drop"] = drop
            d["min_drop_required"] = cfg.restage_bottom_min_drop
            if drop is None or drop < cfg.restage_bottom_min_drop:
                return False, 0.0, {
                    "decided": True, "ok": False,
                    "reason": f"1단계 저점 대비 하락 {(_pct(drop))} < "
                              f"{cfg.restage_bottom_min_drop:.1%} "
                              "(BOTTOM_L2_MIN_DROP — 간발의 신저점은 승률 47.4%)",
                    **d,
                }

        rules, rd = _bottom_rules(b15, cfg)
        d.update(rd)

        bias, mult, brd = market_breadth_context(market_breadth, cfg=cfg)
        d.update(breadth_bias=bias, capital_mult=mult, breadth_detail=brd)

        return _finish(rules, cfg.restage_bottom_min_points, **d)
    except Exception as e:  # pragma: no cover
        logger.warning("[%s] is_restage_bottom 실패 → 판정 안 함: %s", FIX, e)
        return _undecided(f"계산 실패: {e}")


# ══════════════════════════════════════════════════════════════════════
# ③④ 상승 중 조정 → 다시 반등 (사장님 주력 LONG)
# ══════════════════════════════════════════════════════════════════════

def _pullback_episode(b15: _Bars) -> tuple[int | None, float, float, dict[str, Any]]:
    """조정 에피소드 — 기준 고점 p / leg / depth.

        p    = 최근 24봉(6h) 러닝 하이를 갱신한 마지막 봉
        leg  = (high[p] - min(low[p-96..p])) / min(...)   >= 5% 여야 유효
        depth= (high[p] - close[i]) / high[p]
    """
    d: dict[str, Any] = {}
    i = b15.n - 1
    p: int | None = None
    for t in range(i, max(0, i - 96) - 1, -1):
        s = max(0, t - 23)
        if b15.h[t] >= max(b15.h[s:t + 1]):
            p = t
            break
    if p is None:
        return None, 0.0, 0.0, {"reason": "24봉 러닝 하이 갱신 봉 없음"}
    s = max(0, p - 96)
    lo = min(b15.l[s:p + 1])
    leg = ((b15.h[p] - lo) / lo) if lo > 0 else 0.0
    depth = ((b15.h[p] - b15.c[i]) / b15.h[p]) if b15.h[p] > 0 else 0.0
    d.update(peak_idx=p, peak_high=b15.h[p], leg=leg, depth=depth,
             bars_since_peak=i - p)
    return p, leg, depth, d


def is_pullback_entry(kl_15m: Sequence[Sequence[Any]] | None,
                      kl_4h: Sequence[Sequence[Any]] | None,
                      *, market_breadth: float | None = None,
                      db: Any = None, cfg: Thresholds | None = None,
                      trim: bool = True) -> tuple[bool, float, dict[str, Any]]:
    """상승 중 조정 진입 — 사장님 주력 LONG.

    사장님: "LONG=급등후 **큰 조정** + 몇일 이상 지속상승 심볼",
            "조정 구간에 **미리미리 분할**".

    ## 🚨🚨 「미리 깔기」를 지정가 사다리로 구현하지 마라 — 최대 반증

    학습자의 「미리 깔기 우세」는 실제로는 **「15분 종가가 깊이선 아래로 마감한
    것을 보고 그 종가에 시장가」**였다. 진짜 지정가(고점×(1-깊이))로 재계산하면:

        깊이   종가확인(실제 학습식)   **진짜 지정가**      반등확인
        2%     +0.213% (52.7%)      **-0.985% (33.1%)**  +0.046%
        3%     +0.357% (55.7%)      **-0.958% (33.2%)**  -0.127%
        5%     +0.440% (56.5%)      **-0.638% (39.8%)**  +0.130%

    지정가 체결가는 평균 **+1.59~+1.86% 불리**하다. A·L·B 순서는 전부 진입가
    차이만으로 설명된다 = **타이밍 알파가 없고 가격만 있다.**

    → 올바른 배선: **「15분 종가가 깊이선 아래로 마감」을 확인하고 그 자리에서
      시장가.** 반등은 기다리지 않는다(반등 확인은 진입가만 +0.25~1.91% 비싸게 한다).
      `detail["entry_style"] = "market_on_closed_bar"`.

    ## 🚨 깊이 2% 진입을 넣지 마라

    같은 심볼·기간 무작위 진입 대조군(n=4,980)이 승률 53.6% / +0.233%
    (상승군만 58.9% / +0.540%). 깊이 2% 무조건 조정매수는 +0.184% =
    **무작위보다 나쁘다**(상승군 안에서는 -0.196%p).
    → `pb_min_depth` 기본 0.03. 이 값을 0.02 로 내리지 마라.

    ## 구조 — 15m 5점 + 4H 2점, 통과선 3점

        [필수] leg >= 5% (직전 24h 저점 대비 상승) AND depth >= 3%
        [+1] depth >= 5%
        [+1] %B < 0.25            (15m)
        [+1] RSI(24) < 50         (15m)
        [+1] 거래량 >= 20봉평균 1.5배 (15m)
        [+1] OBV 정규화기울기 < 0  (15m)
        [+1] h4_ctx_score >= 2    (4h 참고)
        [+1] h4_ctx_score >= 3    (4h 참고, 누적)

    통과선 3점이 살아남은 6개 규칙을 **정확히 재현**한다:

        PB_S3_PCTB_H4S2   depth>=5% + %B<0.25 + h4>=2   n=39 79.5% d=0.591 14/14축
        PB_S3_RSI24_H4S2  depth>=5% + RSI24<50 + h4>=2  n=37 78.4% d=0.544 14/14
        PB_S2_VOLSPIKE_H4S3 depth>=3% + vol1.5 + h4>=3  n=55 74.6% d=0.530 14/14
        PB_S3_VOLSPIKE_H4S2 depth>=5% + vol1.5 + h4>=2  n=50 72.0% d=0.450 13/14
        PB_S3_OBVNEG_H4S2 depth>=5% + OBV<0 + h4>=2     n=49 71.4% d=0.427 14/14
        PB_S3_OBVNEG_RSI24 depth>=5% + OBV<0 + RSI24<50 n=80 63.8% d=0.371 14/14
                                                        ↑ **4H 없이 통과하는 경로**

    ## 4H 를 컷으로 만들지 않은 이유

    반증관은 「깊이 3% 이상에서 h4_score>=2~3 컷」을 권했다(슬롯당 +0.3~0.4%p).
    그러나 사장님 정정(「15분이 기준, 4시간은 참고」)이 우선이므로 **점수**로
    넣었다. 대신 배점을 2점으로 두어 기본 통과선에서 사실상 필요하게 했고,
    `PB_S3_OBVNEG_RSI24`(15m 단독 3점) 경로를 남겨 거부권이 되지 않게 했다.
    🚨 학습자의 `capital *= 0.4` 가중치는 **넣지 않았다** — `h4_ctx_score` 는
       단조가 아니고(깊이 2/3% 에서 점수0 > 점수1·2) 최선 구간을 깎는다.

    ## 🚨 절대 승률을 인용하지 마라

    표본이 「수집시점 24h 상승/하락 50위」로 뽑혔다 = 표본 끝의 정보.
    문서의 79.5% / 74.5% 는 실거래 기대값이 아니다 — **최소 20~25%p 를
    드리프트가 먹고 있다.** 무작위 대조군 대비 비용후 초과분은 +0.6~+1.3%p 다.
    또 「깊이 2/3/5% 세 번 재현」은 독립 축이 아니다(깊이5% 161건이 100%
    깊이2/3% 집합에 포함, 자카드 0.84) = 유사 반복.
    """
    cfg = cfg or Thresholds.load(db)
    b15 = _bars(kl_15m, 120, trim)
    if b15 is None:
        return _undecided("15m 봉 부족 (120봉 필요)")

    try:
        p, leg, depth, ed = _pullback_episode(b15)
        d: dict[str, Any] = dict(ed, side="LONG",
                                 entry_style="market_on_closed_bar")
        if p is None:
            return _undecided(str(ed.get("reason")), **d)
        if leg < cfg.pb_min_leg:
            return _undecided(
                f"직전 상승 leg {leg:.1%} < {cfg.pb_min_leg:.0%} — 조정 에피소드 아님", **d)
        if depth < cfg.pb_min_depth:
            return _undecided(
                f"조정 깊이 {depth:.2%} < {cfg.pb_min_depth:.0%} "
                "(깊이 2%대는 무작위 진입보다 나쁘다)", **d)

        pb = _pctb(b15.c)
        r24 = _rsi(b15.c, 24)
        vr = _vol_ratio(b15.v, 20)
        ob = _obv_slope_norm(b15.c, b15.v, 20)
        d.update(pctb=pb, rsi24_15m=r24, vol_ratio=vr, obv_slope20=ob,
                 cci9_15m=_cci(b15.h, b15.l, b15.c, 9))

        rules: dict[str, bool] = {"m15_depth_ge_deep": bool(depth >= cfg.pb_deep_depth)}
        if pb is not None:
            rules["m15_pctb_low"] = bool(pb < cfg.pb_pctb_max)
        if r24 is not None:
            rules["m15_rsi24_low"] = bool(r24 < cfg.pb_rsi24_max)
        if vr is not None:
            rules["m15_volspike"] = bool(vr >= cfg.pb_vratio_min)
        if ob is not None:
            rules["m15_obv_neg"] = bool(ob < 0)

        b4 = _bars(kl_4h, 40, trim)
        if b4 is not None:
            ctx, ctx_d = _h4_ctx_score(b4)
            d.update(ctx_d, h4_ctx_score=ctx)
            if ctx is not None:
                rules["h4_ctx_ge2"] = bool(ctx >= 2)
                rules["h4_ctx_ge3"] = bool(ctx >= 3)
        else:
            d["h4"] = "4h 봉 부족 — 15m 단독 경로로 판정 (거부권 아님)"

        bias, mult, brd = market_breadth_context(market_breadth, cfg=cfg)
        d.update(breadth_bias=bias, capital_mult=mult, breadth_detail=brd)

        return _finish(rules, cfg.pb_min_points, **d)
    except Exception as e:  # pragma: no cover
        logger.warning("[%s] is_pullback_entry 실패 → 판정 안 함: %s", FIX, e)
        return _undecided(f"계산 실패: {e}")


# ══════════════════════════════════════════════════════════════════════
# ⑦ 지속 상승 / 지속 하락 — 🚨 추가 진입(피라미딩) 조건
# ══════════════════════════════════════════════════════════════════════

def is_continuation(kl_15m: Sequence[Sequence[Any]] | None,
                    kl_4h: Sequence[Sequence[Any]] | None,
                    side: str,
                    *, db: Any = None, cfg: Thresholds | None = None,
                    trim: bool = True) -> tuple[bool, float, dict[str, Any]]:
    """🚨🚨 지속 상승/하락 — **결론 못 냄. 이 함수는 절대 True 를 돌려주지 않는다.**

    사장님이 두 번 강조한 정정:

      "익절중 추가 포지션 ... **+2%가 아니야** 수익중에 **차트와 보조지표가
       지속 상승이나 하락이 데이터를 보이면 포지션 추가**하는거야"
      "이것도 몇번을 강조해야 하는거야"

    사장님 지시는 명확하다. **그런데 이 데이터로는 그 「지속」을 판정할
    지표 조합을 찾지 못했다.** 없는 것을 있다고 코딩하는 것이 훨씬 나쁘므로,
    이 함수는 지표를 **관측만** 하고 `decided=False` 로 돌려준다.

    ## 왜 아무것도 채택하지 않았나

    학습자가 9개 규칙을 채택했고 반증관이 **8개를 죽였다.**
    결정적 검정: 라벨을 심볼별 순환이동(시간 자기상관 보존, 피처-라벨 관계만
    파괴)으로 무작위화한 **신호 없는 데이터** 200회에 학습자와 **동일한 게이트**
    (홀/짝 양쪽개선 + 시간 전후반 양쪽개선 + 고정%·ATR 양 라벨 + n>=100)를 적용:

        SHORT: 5게이트를 전부 통과한 조합이 순열당 **중앙 107개**(90%분위 197개),
               통과조합이 0개인 순열은 **0%**
        LONG : 중앙 129개
        귀무 통과조합의 최대 R갭 중앙값 = SHORT +0.259 / LONG +0.195
               → 채택안 9개 중 8개보다 **좋다**

    즉 **「6개 게이트를 통과했다」는 안심의 근거가 되지 못한다.**
    41개 불리언 × 2~3중 조합(약 880~11,500 후보)의 탐색 편향을
    홀/짝·시간분할·부트스트랩이 걸러내지 못한다.

    개별 사망 원인:
      S_H4_ACCEL_EMA4H  보정 p=0.850 / S_H4_ACCEL_OBV4H  p=0.975
      S_H4_ACCEL_RSI_BAND p=0.885 / S_ATR_LO_H4_CONSEC2 p=0.902
      S_ATR_RANK_LO  심볼 내부 페어 양수심볼 **50%**(정확히 동전) p=0.554
      L_BODY_H4_ACCEL p=0.762
      L_OBV_DIVERGE   진입 **1봉(15분) 지연**만으로 R +0.284 → +0.116(기저 +0.101)
      L_PX_EXT        보정 p=1.000, 심볼단위 +0.019 = 아무 정보 없음
                      (「15m 종가가 10봉 신고가」는 아무 정보도 없다)

    ## 유일한 생존자를 넣지 않은 이유 — 🚨 사장님 사상의 정반대다

    `L_BW_OBV_DIVERGE` 는 통계는 견뎠다(보정 p=0.005, H16/32/64 안정,
    LOSO 60심볼 최악 +0.424). 그런데 내용이 **「가격은 10봉 신고가인데 OBV 는
    신고가가 아님」= 약세 다이버전스**다. 사장님 지시는 「지속 상승 데이터가
    보이면 추가」인데 이 규칙은 **「거래량이 안 따라오는 상승에 추가하라」**다.
    게다가 1봉 지연으로 +0.458 → +0.189 (승률 55.6→45.4%) 로 60% 증발하는데,
    피라미딩 워커는 루프 주기로 돈다 = **실행 자체가 불가능**하다.
    → 「과적합 혐의」는 벗었지만 「사장님 사상 ⑦의 답」은 아니다. 넣지 않는다.

    ## 견딘 관측 (참고용으로 detail 에 넣는다 — 판정에는 쓰지 않는다)

      * `vol_hold`(거래량 유지)는 SHORT 에서 **진짜 역효과**
        (-0.005 vs 반대군 +0.122, 승률 37.8 vs 43.9)
      * `obv_conf`(OBV 가 방향과 같은 부호)는 **방향 비대칭**:
        SHORT +0.081 vs +0.017(확인이 좋다) / LONG +0.053 vs +0.099(확인이 나쁘다)
      * `consec3`(연속 3봉)·`bw_expand`(밴드폭 확장) 무효과
      * 전 지표 단독 |d| < 0.13 = **지속을 혼자 말해주는 지표는 없다**

    ## 🚨 현행 코드를 이 분석으로 바꾸지 마라

    학습자의 「현행 Fix 273 이 SHORT 에서 나쁘다」는 **과장**이다 — ATR 라벨로
    재면 SHORT +0.069 vs 기저 +0.074 = 사실상 동률, LONG 은 오히려 낫다.
    「나쁘다」가 아니라 **「무효과」**다. 프로덕션 Fix 273 관측(n=45,
    -91.32 → +99.28/건)도 이 데이터의 귀무 최대통계량 폭 안에 들어간다
    = **양쪽 다 우연으로 설명 가능 = 둘 다 결론 못 냄.**
    또 「4H 동의가 많을수록 나쁘다」도 과대해석이다 — 실제 분포는
    SHORT 0:+0.200 / 1:+0.035 / 2:+0.111 / 3:+0.113 / 4:-0.048 로 **비단조**다.
    정확한 진술은 「4H 동의 개수와 성과 사이에 단조 관계가 없다」뿐이고,
    이것은 4H 를 거부권으로 쓰지 말라는 사장님 정정을 지지하지만
    「4H 를 무시할수록 좋다」는 지지하지 않는다.

    ## 다음 단계 (규칙 채택이 아니다)

      1. 표본 확대 — 5일 → 최소 60~90일 15m, 또는 실거래 로그 결합
      2. 채택 전 **순열 귀무 최대통계량 대비 검정**을 파이프라인에 상설화
    """
    cfg = cfg or Thresholds.load(db)
    s = str(side).upper()
    d: dict[str, Any] = {
        "decided": False,
        "side": s,
        "verdict": "결론 못 냄",
        "reason": "97종목 5일치 15m 로는 「지속」을 판정할 지표 조합을 찾지 못했다. "
                  "채택 9개 중 8개가 무작위 라벨 귀무분포에서 재현되고, "
                  "유일한 생존자는 약세 다이버전스(사장님 사상의 반대) + "
                  "15분 지연으로 60% 증발한다.",
        "next_step": "표본 60~90일 확대 또는 실거래 로그 결합 후 재측정. "
                     "순열 귀무 최대통계량 대비 검정을 상설화할 것.",
    }

    b15 = _bars(kl_15m, 60, trim)
    if b15 is None:
        d["observations"] = None
        return False, 0.0, d

    try:
        obs: dict[str, Any] = {}
        up = (s == "LONG")
        obs["consec_same_dir"] = _consec(b15.c, b15.o, up)          # 무효과
        e20, e50 = _ema(b15.c, 20)[-1], _ema(b15.c, 50)[-1]
        obs["m15_ema20"] = e20
        obs["m15_ema50"] = e50
        obs["m15_ema_aligned"] = bool(e20 > e50) if up else bool(e20 < e50)
        ob = _obv_slope_norm(b15.c, b15.v, 20)
        obs["m15_obv_slope20"] = ob
        # obv_conf 방향 비대칭: SHORT 는 확인이 좋고 LONG 은 확인이 나쁘다
        obs["obv_confirms"] = None if ob is None else (ob > 0 if up else ob < 0)
        obs["vol_ratio"] = _vol_ratio(b15.v, 20)                    # SHORT 역효과
        obs["bb_width_rank"] = _bb_width_rank(b15.c)                # 무효과
        atr = _atr(b15.h, b15.l, b15.c, 14)
        obs["atr_pct"] = (atr / b15.c[-1]) if (atr and b15.c[-1]) else None
        obs["rsi12_15m"] = _rsi(b15.c, 12)

        b4 = _bars(kl_4h, 40, trim)
        if b4 is not None:
            pair = _h4_hist_pair(b4)
            if pair is not None:
                obs.update(h4_hist=pair[0], h4_hist_prev=pair[1],
                           h4_hist_rising=bool(pair[0] > pair[1]))
        d["observations"] = obs
    except Exception as e:  # pragma: no cover
        logger.warning("[%s] is_continuation 관측 실패: %s", FIX, e)
        d["observations"] = None

    # 🚨 어떤 설정으로도 True 가 되지 않는다. 근거가 없기 때문이다.
    return False, 0.0, d


# ══════════════════════════════════════════════════════════════════════
# 잡부
# ══════════════════════════════════════════════════════════════════════

def _prev_num(prev: Mapping[str, Any] | None, *keys: str) -> float | None:
    if not prev:
        return None
    for k in keys:
        v = prev.get(k)
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f > 0:
            return f
    return None


def _pct(x: float | None) -> str:
    return "미상" if x is None else f"{x:.2%}"
