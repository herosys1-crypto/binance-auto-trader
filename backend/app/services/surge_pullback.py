"""🎯 「급등 중 조정 → 다시 급등」 판정 — 사장님 LONG 주력 자리 (Fix 243).

## 사장님 verbatim (2026-08-31)

  "**급등중에 조정은 다시 급등으로 간다**고 했어 **바로 수익을 많이 낼수 있고** 했고
   급락한건 언제 어떤 심볼이 급등하는 찾는게 힘들다고 헀어
   **포지션 진입을 하지 않는다고 안헀어**"

⇒ 급락 진입을 막는 것이 아니라, **급등 중 조정을 1순위로 추가**한다.

## 이 숫자들은 어디서 왔나 (추측 아님)

수동 LONG 120건(이긴 12 / 진 13)의 **진입 시점 지표를 캔들에서 복원**해
승패 중앙값을 비교한 실측이다 (`scripts/analyze_entry_patterns.py`, Fix 242):

    지표            이긴 진입    진 진입     차이
    ─────────────────────────────────────────────
    CCI 15m          +110.6     +36.9    +73.7   ← 가장 강한 판별자
    CCI 4H           +144.5     +93.6    +50.9
    3일 변동%          +65.5%    +35.5%   +30.0   ← 급등 중일수록 이긴다
    RSI 15m            67.4      53.9    +13.4
    볼밴위치 15m        0.877     0.611   +0.266
    되돌림 4H           0.083     0.580   -0.497   ← 얕은 조정일수록 이긴다
    OBV방향 4H         +0.168    +0.020   +0.148   ← 사장님 사상 ④

그리고 되돌림 구간별 성적:

    0.30~0.60 (추세중 조정)    4건  승률 75.0%   +684.76
    0.70~1.00 (원점 회귀)      1건  승률  0.0%   -247.34
    1.00 초과 (원점 아래)      6건  승률 33.3%  -1845.38   ← 최악

## 왜 이게 중요한가

현재 자동 LONG(`auto_long_at_bottom`)은 **CCI 15m 약 -78 / RSI 39 / 볼밴 0.28** 에서
진입한다 = **과매도 바닥**. 위 표와 정반대 자리다.
그래서 승률 **16.1%** 이고, 어떤 지표도 승패를 가르지 못한다(최대 차이 RSI 4H +7.8).

⚠️ 이 모듈은 **판정만** 한다. 주문도 DB 쓰기도 하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from app.services.retracement import retracement_ratio

__all__ = ["SurgePullbackScore", "evaluate_surge_pullback", "THRESHOLDS"]


# ── 실측에서 유도한 임계값 ──────────────────────────────────────────
#   승/패 중앙값 사이에서 **패자 쪽에 가깝게** 잡았다.
#   승자 중앙값에 붙이면 표본(12건)에 과적합되고 진입이 거의 안 난다.
#   🚨 반드시 **패자 중앙값보다 위, 승자 중앙값보다 아래**여야 한다.
#      패자 아래로 잡으면 걸러내지 못하고(내 첫 시도가 그랬다 — 테스트가 잡았다),
#      승자에 붙이면 표본 12건에 과적합된다.
THRESHOLDS: dict[str, float] = {
    "chg_3d_min": 45.0,      # 패 35.5 < 45.0 < 승 65.5   → 급등 중일 것
    "cci_15m_min": 60.0,     # 패 36.9 < 60.0 < 승 110.6  → 15분 강세
    "rsi_15m_min": 58.0,     # 패 53.9 < 58.0 < 승 67.4
    "bb_pos_15m_min": 0.70,  # 패 0.611 < 0.70 < 승 0.877 → 밴드 위쪽
    "retrace_max": 0.35,     # 승 0.083 / 패 0.580 (낮을수록 좋다) → 얕은 조정만
    "retrace_hard_block": 1.00,   # 원점 아래 = 실측 6건 -1,845 = 절대 금지
    # 사장님 ④ 는 「OBV 가 안 꺾였으면」 = >= 0 인데, 실측 패자 중앙값이 0.020 이라
    # 0 으로는 걸러지지 않는다. 데이터가 말하는 실효 경계는 0.08 이다.
    "obv_4h_min": 0.08,      # 패 0.020 < 0.08 < 승 0.168
}

# 🚨 Fix 250 (2026-08-31) — **정의 조건은 필수**로 바꾼다.
#
#   배포 첫날 실측 로그:
#     [Fix244] LIGHTUSDT 급등중 조정 = LONG 1순위 (4/6 통과)
#              3일 **-18.0%**  되돌림 **0.568**  볼밴 **1.18**  CCI 240  RSI 69
#
#   3일 -18% 는 급등이 아니라 **하락 중**이고, 되돌림 0.568 은 얕은 조정이 아니다.
#   즉 「급등 중 조정」을 **정의하는 두 조건을 둘 다 실패**했는데,
#   타이밍 지표 4개(CCI/RSI/볼밴/OBV)만으로 4/6 을 채워 통과했다.
#   볼밴 1.18 = 상단 **밖** = 추격매수 자리이기도 하다.
#
#   -> 두 축을 나눈다:
#        필수(둘 다) : 급등 중(3일)  +  얕은 조정(되돌림)   = 「어떤 자리인가」
#        선택(4중 3) : CCI / RSI / 볼밴 / OBV               = 「지금 들어갈 때인가」
MIN_PASSED: int = 3          # 선택 4개 중 3개

# 상단 밖에서 사는 것은 추격매수다. 실측 승자 중앙값은 0.877 이었다.
BB_POS_CHASE_MAX: float = 1.05


@dataclass
class SurgePullbackScore:
    passed: int = 0
    total: int = 0
    ok: bool = False
    blocked: str | None = None          # 하드 차단 사유 (있으면 ok=False 확정)
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def reason(self) -> str:
        if self.blocked:
            return f"차단: {self.blocked}"
        return f"{self.passed}/{self.total} 통과"


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def evaluate_surge_pullback(
    *,
    closes_4h: Sequence[Any] | None,
    chg_3d_pct: Any = None,
    cci_15m: Any = None,
    rsi_15m: Any = None,
    bb_pos_15m: Any = None,
    obv_dir_4h: Any = None,
    thresholds: dict[str, float] | None = None,
) -> SurgePullbackScore:
    """「급등 중 조정 → 재상승」 자리인가.

    Args:
        closes_4h: 4시간봉 종가 (되돌림 계산용 — 사장님 사상 ⑥ 「4H = 확정된 흐름」)
        chg_3d_pct: 3일 변동률 %
        cci_15m / rsi_15m / bb_pos_15m: 15분 지표 (진입 타이밍)
        obv_dir_4h: 4H OBV 방향 -1~+1 (obv_metrics.obv_direction_ratio)

    Returns:
        SurgePullbackScore. `ok=True` 면 사장님이 말한 그 자리다.

    ⚠️ 결측값은 **통과로 세지 않는다** (fail-closed).
       「모르는데 통과」는 이 프로젝트에서 반복된 사고 유형이다.
    """
    T = {**THRESHOLDS, **(thresholds or {})}
    s = SurgePullbackScore()
    d = s.detail

    # ── 하드 차단: 원점 아래로 내려간 종목 (실측 6건 -1,845) ──
    retrace, rdet = retracement_ratio(closes_4h, 60)
    d["retrace"] = retrace
    d["retrace_why"] = rdet.get("reason")
    if retrace is not None and retrace >= T["retrace_hard_block"]:
        s.blocked = (
            f"되돌림 {retrace:.2f} >= {T['retrace_hard_block']:.2f} "
            "= 상승 시작가 아래 (원점 아래)"
        )
        return s

    # ── 필수 ① 급등 중인가 (3일) ──
    c3 = _f(chg_3d_pct)
    d["chg_3d_pct"] = c3
    if c3 is not None and c3 < T["chg_3d_min"]:
        s.blocked = (
            f"급등 중이 아니다 — 3일 {c3:+.1f}% < {T['chg_3d_min']:.0f}%"
        )
        return s

    # ── 필수 ② 얕은 조정인가 (되돌림) ──
    if retrace is not None and retrace > T["retrace_max"]:
        s.blocked = (
            f"조정이 깊다 — 되돌림 {retrace:.3f} > {T['retrace_max']:.2f} "
            "(실측 패자 중앙값 0.580)"
        )
        return s

    # ── 필수 ③ 추격매수 금지 (상단 밖) ──
    bb = _f(bb_pos_15m)
    if bb is not None and bb > BB_POS_CHASE_MAX:
        s.blocked = (
            f"추격매수 — 볼밴 {bb:.3f} > {BB_POS_CHASE_MAX:.2f} (상단 밖). "
            "실측 승자 중앙값 0.877"
        )
        return s

    checks: list[tuple[str, bool | None]] = []

    v = _f(cci_15m)
    d["cci_15m"] = v
    checks.append(("CCI 15m 강세", None if v is None else v >= T["cci_15m_min"]))

    v = _f(rsi_15m)
    d["rsi_15m"] = v
    checks.append(("RSI 15m 강세", None if v is None else v >= T["rsi_15m_min"]))

    v = _f(bb_pos_15m)
    d["bb_pos_15m"] = v
    checks.append(("볼밴 위쪽", None if v is None else v >= T["bb_pos_15m_min"]))

    v = _f(obv_dir_4h)
    d["obv_dir_4h"] = v
    checks.append(("OBV 안 꺾임", None if v is None else v >= T["obv_4h_min"]))

    s.total = len(checks)
    s.passed = sum(1 for _n, r in checks if r is True)
    d["checks"] = {n: r for n, r in checks}
    d["missing"] = [n for n, r in checks if r is None]
    s.ok = s.passed >= MIN_PASSED
    return s
