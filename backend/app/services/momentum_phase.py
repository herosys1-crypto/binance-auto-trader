"""📈 국면 판정 — 「가격은 고점인데 보조지표는 상승 초입」 (Fix 346).

## 사장님 지시 (2026-09-04, MINIMAXUSDT #2755)
  "그런데 차트는 고점인데 다른 보조지표는 상승초입니다. 이건 롱으로 들어가야 승률이 높을
   지점인것 같아 분석해서 수정해줘 보조지표를 적용할수 있게 개선해줘"

#2755 는 v219 정점 SHORT 가 「15m 지표 꺾임 2/2」(RSI 78.08→76.1 한 봉 하락 + CCI 한 봉 하락)로
잡은 자리였다. 그런데 같은 순간 15m·1H·4H MACD 히스토그램은 0선을 막 넘어 **커지는 중**이고
OBV 는 신고점, 거래량은 급증이었다 — 사장님이 보신 「상승 초입」. 한 봉 틱은 정점이 아니다.

## 실측 (2026-09-04, 상승50+하락50 96종목, 15m 완성봉 10일, 레버 2, SL −5%/TP +15% ROI, 12h)
    자리 = 40봉 신고점 + 15m hist 3봉 연속 증가 + hist > 0 + OBV 40봉 신고점   (n=592)
                 LONG              SHORT
    평균 ROI     **+1.64**         **−0.88**
    승률          43.6%            32.9%
    TP 도달       21.1%            6.8%
    SL            44.4%            57.9%
    기준선(무작위 봉 2,233)  LONG +0.26 / SHORT −0.40
    교차검증: 심볼 홀/짝 LONG +0.97/+2.38, 시간 전/후 +0.67/+2.34 — 네 조각 모두 LONG 양수, SHORT 음수.
    4H hist 방향으로 갈라도 LONG +1.57(4H↑) / +1.80(4H↓) = 4H 는 결과를 안 바꾼다 (사장님 「4H 참고」).
    ⚠️ 종목을 「오늘 상승50·하락50」으로 골라 과거를 봤으므로 LONG 이 부풀 수 있다 → 대조군:
    거래대금 상위 100 (변동률 무관, n=632): LONG **+1.32** / SHORT **−0.76**, 기준선 LONG +0.23 / SHORT −0.36.
    대조군에서는 4H hist 방향이 갈랐다 — 4H↑ LONG +1.59 (홀/짝 +1.04/+2.01, 전/후 +1.25/+1.78 전부 양수)
    / 4H↓ LONG +0.67 (홀/짝 −0.3/+1.83 = 불안정). SHORT 는 어느 조각에서도 양수가 없다.
    → SHORT 보류는 4H 무관하게 근거가 있고, LONG 은 4H↑ 일 때 강하다 (4H 는 로그·detail 에 참고로 남긴다).
    24h 변동(이벤트 시점, 96봉 전 대비)으로 가르면 — Fix 347 의 근거:
        24h < 15% (n=505)  LONG **+1.66** / SHORT −0.94      ← Fix 274 가 롱을 막던 구간
        24h < 10% (n=447)  LONG +1.65 / SHORT −0.99
        24h ≥ 15% (n=69)   LONG +0.97 (SL 68%) / SHORT −2.23
      상승 초입 롱의 우위는 「아직 24h 15% 가 안 된」 자리에 있다. 사장님 "올라가면 롱으로 진입을 해야지".
    스크립트: scratchpad/measure_surge_start.py (미래참조 없음: 완성봉만, 4H 는 닫힌 봉만)

## 규칙 (숫자는 Claude 가 정함 — 전부 설정키, 사장님 값으로 바꿀 수 있다)
    surge_start_accel_bars    = 3    hist[-1] > hist[-2] > hist[-3] (가속)
    surge_start_high_lookback = 40   종가가 최근 40봉 최고 (신고점)
    surge_start_obv_lookback  = 40   OBV 가 최근 40봉 최고
    hist > 0                         상승 국면의 부호 (0선 돌파 이후)
  적용:
    ① v219 정점 SHORT 1단계 진입 직전 — 이 국면이면 SHORT 를 **넣지 않는다**
       (surge_start_short_veto_enabled, 기본 ON)
    ② 같은 자리에 LONG 알람을 넘긴다 (sajangnim:bottom_long:{symbol}, pattern=SURGE_START)
       → auto_long_at_bottom 이 v219 사다리(10/300/600)로 LONG 진입. 저점 게이트는 건너뛴다
       (surge_start_long_handoff_enabled, 기본 ON)
  판정 불가(데이터 부족·예외)는 「상승 초입 아님」= 기존 흐름 유지 (fail-open).
  진행중 봉은 쓰지 않는다 (마지막 봉 제거).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SETTING_SHORT_VETO = "surge_start_short_veto_enabled"
SETTING_LONG_HANDOFF = "surge_start_long_handoff_enabled"
SETTING_ACCEL_BARS = "surge_start_accel_bars"
SETTING_HIGH_LOOKBACK = "surge_start_high_lookback"
SETTING_OBV_LOOKBACK = "surge_start_obv_lookback"

ACCEL_BARS_DEFAULT = 3
HIGH_LOOKBACK_DEFAULT = 40
OBV_LOOKBACK_DEFAULT = 40
KLINE_LIMIT = 90
PATTERN = "SURGE_START"


def _setting(db: Any, key: str) -> str | None:
    if db is None:
        return None
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        if row is None or row.value is None:
            return None
        v = str(row.value).strip()
        return v or None
    except Exception as e:  # noqa: BLE001
        logger.warning("[Fix346] %s 조회 실패 → 기본값: %s", key, e)
        return None


def _bool(db: Any, key: str, default: bool) -> bool:
    v = _setting(db, key)
    if v is None:
        return default
    return v.lower() in ("1", "true", "on", "yes")


def _int(db: Any, key: str, default: int, lo: int, hi: int) -> int:
    v = _setting(db, key)
    if v is None:
        return default
    try:
        n = int(float(v))
    except Exception:
        return default
    return n if lo <= n <= hi else default


def short_veto_enabled(db: Any) -> bool:
    return _bool(db, SETTING_SHORT_VETO, True)


def long_handoff_enabled(db: Any) -> bool:
    return _bool(db, SETTING_LONG_HANDOFF, True)


def _ema(v: list[float], n: int) -> list[float]:
    k = 2.0 / (n + 1)
    out = [v[0]]
    for x in v[1:]:
        out.append(out[-1] + k * (x - out[-1]))
    return out


def macd_hist(closes: list[float]) -> list[float] | None:
    if len(closes) < 40:
        return None
    e12, e26 = _ema(closes, 12), _ema(closes, 26)
    m = [a - b for a, b in zip(e12, e26)]
    s = _ema(m, 9)
    return [a - b for a, b in zip(m, s)]


def obv_series(closes: list[float], vols: list[float]) -> list[float]:
    out = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            out.append(out[-1] + vols[i])
        elif closes[i] < closes[i - 1]:
            out.append(out[-1] - vols[i])
        else:
            out.append(out[-1])
    return out


def classify_surge_start(closes: list[float], vols: list[float], *,
                         accel_bars: int = ACCEL_BARS_DEFAULT,
                         high_lookback: int = HIGH_LOOKBACK_DEFAULT,
                         obv_lookback: int = OBV_LOOKBACK_DEFAULT) -> tuple[bool, dict[str, Any]]:
    """순수 판정 (I/O 없음). closes/vols 는 **완성봉만**.

    Returns:
        (상승 초입인가, detail). 데이터 부족이면 (False, {"decided": False, ...}).
    """
    d: dict[str, Any] = {"decided": False}
    need = max(high_lookback, obv_lookback, 40) + accel_bars
    if len(closes) < need or len(vols) != len(closes):
        d["reason"] = f"봉 부족 ({len(closes)} < {need})"
        return False, d
    h = macd_hist(closes)
    if h is None or len(h) < accel_bars + 1:
        d["reason"] = "MACD 계산 불가"
        return False, d
    ob = obv_series(closes, vols)
    new_high = closes[-1] >= max(closes[-high_lookback:])
    accel = all(h[-i] > h[-i - 1] for i in range(1, accel_bars))   # h[-1] > h[-2] > ... (accel_bars 개)
    positive = h[-1] > 0
    obv_high = ob[-1] >= max(ob[-obv_lookback:])
    d.update(decided=True, new_high=new_high, hist_accel=accel, hist_positive=positive,
             obv_high=obv_high, hist_last=[round(x, 6) for x in h[-accel_bars:]],
             close=closes[-1], high_lookback=high_lookback, obv_lookback=obv_lookback)
    ok = bool(new_high and accel and positive and obv_high)
    d["checks"] = {"신고점": new_high, "hist 가속": accel, "hist > 0": positive, "OBV 신고점": obv_high}
    return ok, d


def is_surge_start(bc: Any, symbol: str, *, db: Any = None) -> tuple[bool, str, dict[str, Any]]:
    """거래소에서 15m 봉을 받아 판정. 진행중 봉은 버린다. 예외/부족 = (False, ...) = 기존 흐름 유지."""
    try:
        accel = _int(db, SETTING_ACCEL_BARS, ACCEL_BARS_DEFAULT, 2, 10)
        hl = _int(db, SETTING_HIGH_LOOKBACK, HIGH_LOOKBACK_DEFAULT, 10, 200)
        ol = _int(db, SETTING_OBV_LOOKBACK, OBV_LOOKBACK_DEFAULT, 10, 200)
        kl = bc.get_klines(symbol=symbol, interval="15m", limit=KLINE_LIMIT)
        if not kl or len(kl) < 45:
            return False, "15m 봉 부족 (판정 안 함)", {"decided": False}
        kl = kl[:-1]                                   # 진행중 봉 제거
        closes = [float(k[4]) for k in kl]
        vols = [float(k[5]) for k in kl]
        ok, d = classify_surge_start(closes, vols, accel_bars=accel, high_lookback=hl, obv_lookback=ol)
        if not d.get("decided"):
            return False, f"판정 안 함: {d.get('reason')}", d
        why = ("상승 초입 (신고점 + 15m hist 가속 + OBV 신고점) = 정점 아님"
               if ok else "상승 초입 아님: " + ", ".join(k for k, v in d["checks"].items() if not v))
        return ok, why, d
    except Exception as e:  # noqa: BLE001
        logger.warning("[Fix346] %s 국면 판정 실패 (기존 흐름 유지): %s", symbol, e)
        return False, f"판정 실패 (fail-open): {e}", {"decided": False}
