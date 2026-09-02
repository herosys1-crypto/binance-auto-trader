"""🎯 변동성 연동 TP1 — 사장님 2026-09-02 지시 (Fix 299).

## 사장님 원문

  "급등락하는 심볼투자는 tp1 +15%,
   매우 안정적은 상위심볼은 +5%나 +3% 등등 **낮은 익절을 만들어 경우의 수를 가져가야해**"

  (앞선 맥락) "볼밴 처음에는 tp1 +5%에서 시작을 제안했었어. 시스템이 제대로 운영이
   되지않아 로직을 변경하고 tp1 +15% 유지한거야"

즉 TP1 15% 는 **사장님의 원래 뜻이 아니라 시스템 문제를 우회하려던 임시값**이었다.
원래 사상은 「종목의 변동성에 맞는 익절」이다.

## 왜 이게 결정적인가 — 실측

30일 자동매매 실적을 보면 설계와 실제가 완전히 다르다:

    설계: TP1 15% / 손절 -5%  →  손익비 R = 3.00, 손익분기 승률 25%
    실제: 승자 평균 ROI +3.97% / 패자 -3.93%  →  **R = 1.01**, 손익분기 49.7%
          (실제 승률 26.7% → 구조상 진다)

원인은 **TP1 에 닿지 않는 것**이다. 607건 중 ROI +15% 에 도달한 것은 **3건(0.5%)** 뿐이다.
나머지는 트레일링·시간청산으로 ±4% 에서 끝난다. 닿지 않는 TP1 은 R 이 커도 소용없다.

## 실측 — 변동성 구간별 도달률과 기대값

상승 50위 ∪ 하락 50위(99심볼) x 15m 1000봉, 레버 2, 손절 ROI -10% 선도달 시 중단,
48시간 안에 도달 가능한 최대 유리 ROI:

    구간                표본    TP3     TP5     TP8    TP15    TP20
    |24h| <5% (안정)   3874    75%     63%     48%     23%     15%
    5~10%             1020    79%     67%     52%     30%     21%
    10~15%             342    81%     69%     55%     36%     28%
    15~30% (급등락)      302    76%     68%     56%     42%     34%
    30%+               148    80%     70%     56%     39%     34%

기대값 (도달률 x TP + 미도달 x 손절 -10%):

    구간                 TP3     TP5     TP8    TP15    TP20   최선
    |24h| <5% (안정)   -0.30   -0.61   -1.33  **-4.30** -5.42   TP3
    5~10%             +0.27   +0.06   -0.63   -2.43   -3.76   TP3
    10~15%            +0.53   +0.31   -0.16   -0.94   -1.49   TP3
    **15~30%**        -0.06   +0.23   +0.07  **+0.51** +0.33   **TP15**
    30%+              +0.45   +0.54   +0.09   -0.20   +0.34   TP5

🚨 **TP15 가 최선인 구간은 「15~30% 급등락」 하나뿐이다.** 나머지 구간에서는
   기대값이 -0.94 ~ -4.30 으로 전부 음수다. 그런데 지금 시스템은 **전 종목에
   TP1 15%** 를 쓴다 — 이것이 실효 손익비를 3.00 에서 1.01 로 무너뜨린 원인이다.

## 규칙 (단순하게 둔다)

    |24h| >= 15%  →  TP1 **15%**   (급등락 = 사장님 「그 한계점을 공략」하는 자리)
    |24h| <  15%  →  TP1 **3%**    (안정 = 「낮은 익절로 경우의 수를 가져간다」)

30%+ 구간에서 TP5 가 근소하게 앞서지만 표본이 148 로 작고 TP20(+0.34)과도
차이가 작아 노이즈로 본다. 구간을 늘리면 규칙만 복잡해지고 검증이 어려워진다.

⚠️ **임계값은 전부 설정으로 뺀다** — 이 측정은 한 장세(10.4일)의 것이다.

## ⚠️ 이 측정의 한계

- 「도달 가능한 최대 유리 ROI」는 **상한**이다. 실제로는 트레일링·부분익절 때문에
  그만큼 다 못 먹는다. 구간 **비교**에는 유효하지만 절대 수익 예측이 아니다.
- 손절을 ROI -10% 로 고정해 쟀다. 실제 SHORT 은 -5% 라 도달률이 더 낮을 수 있다.
  그 방향은 **낮은 TP 를 더 유리하게** 만들므로 결론을 뒤집지 않는다.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "SETTING_ENABLED", "SETTING_SURGE_CHG", "SETTING_TP_SURGE", "SETTING_TP_CALM",
    "SURGE_CHG_DEFAULT", "TP_SURGE_DEFAULT", "TP_CALM_DEFAULT",
    "adaptive_tp_enabled", "pick_tp1", "tp_ladder_from_tp1",
]

SETTING_ENABLED = "adaptive_tp_enabled"
SETTING_SURGE_CHG = "adaptive_tp_surge_chg24"    # 이 이상이면 「급등락」
SETTING_TP_SURGE = "adaptive_tp_surge_tp1"       # 급등락 TP1
SETTING_TP_CALM = "adaptive_tp_calm_tp1"         # 안정 TP1

SURGE_CHG_DEFAULT: float = 15.0
TP_SURGE_DEFAULT: float = 15.0
TP_CALM_DEFAULT: float = 3.0


def _f(db, key: str, default: float, lo: float, hi: float) -> float:
    """설정 하나를 float 로. 손상/범위밖이면 기본값 (fail-SAFE, 헌법 167)."""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        if row is None or row.value is None or not str(row.value).strip():
            return default
        v = float(str(row.value).strip())
        if v < lo or v > hi:
            logger.warning("[Fix299] %s=%s 범위밖(%s~%s) → 기본 %s", key, v, lo, hi, default)
            return default
        return v
    except Exception as e:
        logger.warning("[Fix299] %s 조회 실패 → 기본 %s: %s", key, default, e)
        return default


def adaptive_tp_enabled(db) -> bool:
    """기본 OFF. 익절 구조를 바꾸는 큰 변경이라 명시적으로 켠다 (헌법 161)."""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, SETTING_ENABLED)
        if row is None or row.value is None:
            return False
        return str(row.value).strip().lower() in ("1", "true", "on", "yes")
    except Exception as e:
        logger.warning("[Fix299] %s 조회 실패 = OFF: %s", SETTING_ENABLED, e)
        return False


def pick_tp1(db, chg_24h: float | None) -> tuple[float, str, dict[str, Any]]:
    """진입 시점 24h 변동으로 TP1 을 고른다.

    Returns:
        (tp1_percent, 사유, 상세)

    ⚠️ **fail-safe** — 24h 를 못 받으면 급등락 쪽(높은 TP)을 쓴다.
       낮은 TP 로 잘못 내리면 큰 파도를 조기 익절해 버리는데, 그건 되돌릴 수 없다.
       반대로 높은 TP 는 트레일링이 받쳐 준다.
    """
    surge_chg = _f(db, SETTING_SURGE_CHG, SURGE_CHG_DEFAULT, 1.0, 100.0)
    tp_surge = _f(db, SETTING_TP_SURGE, TP_SURGE_DEFAULT, 1.0, 100.0)
    tp_calm = _f(db, SETTING_TP_CALM, TP_CALM_DEFAULT, 0.5, 100.0)
    d: dict[str, Any] = {
        "chg_24h": chg_24h, "surge_chg": surge_chg,
        "tp_surge": tp_surge, "tp_calm": tp_calm,
    }
    if chg_24h is None:
        d["fallback"] = True
        return tp_surge, f"24h 없음 → 급등락 기준 TP1 {tp_surge:g}% (fail-safe)", d
    a = abs(float(chg_24h))
    d["abs_chg"] = a
    if a >= surge_chg:
        return tp_surge, (
            f"|24h| {a:.1f}% >= {surge_chg:g}% = **급등락** → TP1 {tp_surge:g}%"
        ), d
    return tp_calm, (
        f"|24h| {a:.1f}% < {surge_chg:g}% = 안정 → TP1 {tp_calm:g}% "
        f"(낮은 익절로 경우의 수를 가져간다)"
    ), d


def tp_ladder_from_tp1(tp1: float, levels: int = 4) -> list[float]:
    """TP1 에서 사다리를 만든다. 간격은 TP1 과 같게 두어 비율을 유지한다.

    TP1 15% → 15/30/45/60      (급등락: 큰 파도를 끝까지 탄다)
    TP1  3% → 3/6/9/12         (안정: 촘촘하게 여러 번)

    🚨 기존 사다리(15/20/25/30)는 간격이 5%p 로 좁아 TP1 만 닿고 나머지는 거의 못 닿았다.
       비율을 유지하면 TP1 이 낮아질 때 사다리 전체가 같이 내려와 실제로 도달한다.
    """
    tp1 = max(0.5, float(tp1))
    return [round(tp1 * (i + 1), 2) for i in range(max(1, levels))]
