"""🤝 전략 합의(Confluence) 판정 (v138 신!)

spec: docs/SAR_ICHIMOKU_MTF_STRATEGY_SPEC.md
사장님 요청 2026-08-14: 「이것도 분석해서 **같이** 적용할 수 있게 만들어줘」

두 전략은 성격이 다릅니다:
  📐 EMA/VCP     = **돌파형** (변동성 수축 후 터지는 첫 순간을 노림)
  ☁️ SAR/구름대  = **추세추종형** (이미 난 추세에 올라타서 꺾일 때까지)

= 서로 다른 시점을 보므로 **둘이 동시에 OK** 하면 신뢰도가 올라가고,
  **한쪽이 금지** 하면 그건 경고입니다 (= 사장님이 놓칠 뻔한 반대 근거!).

헌법 v138:
  '두 전략이 충돌하면 = 안 좋은 신호! 합의만 신뢰하고, 충돌은 경고로 남긴다!'
  (= 한쪽만 보고 진입하면 다른 쪽이 반대하는 걸 모른 채 들어감!)
"""
from __future__ import annotations

from typing import Any

# 등급 → 숫자 (평균/비교용)
_GRADE_RANK = {"A": 3, "B": 2, "C": 1, "D": 0}

LEVEL_COLOR = {
    "STRONG_AGREE": "#22c55e",
    "AGREE": "#4ade80",
    "PARTIAL": "#f59e0b",
    "CONFLICT": "#f97316",
    "AVOID": "#ef4444",
    "NONE": "#94a3b8",
}


def _grade(result: dict | None) -> str | None:
    """분석 결과에서 등급 추출 (판정 불가 = None)."""
    if not result or not result.get("available"):
        return None
    g = result.get("grade")
    return g if g in _GRADE_RANK else None


def evaluate(
    ema_vcp: dict | None,
    sar_ichimoku: dict | None,
    side: str = "LONG",
) -> dict[str, Any]:
    """두 전략 결과 → 합의 판정.

    Returns:
        {
          available, level, verdict, color, score,
          grades: {ema_vcp, sar_ichimoku},
          agree: bool, conflict: bool,
          signals: [...],
        }
    """
    g_ema = _grade(ema_vcp)
    g_sar = _grade(sar_ichimoku)
    signals: list[str] = []

    # --- 판정 불가 처리 ---
    if g_ema is None and g_sar is None:
        return {
            "available": False,
            "level": "NONE",
            "verdict": "➖ 두 전략 모두 판정 불가",
            "color": LEVEL_COLOR["NONE"],
            "score": 0,
            "grades": {"ema_vcp": None, "sar_ichimoku": None},
            "agree": False,
            "conflict": False,
            "signals": ["➖ 캔들 부족 or 조회 실패 = 합의 판정 불가"],
        }
    if g_ema is None or g_sar is None:
        only = "☁️ SAR/구름대" if g_ema is None else "📐 EMA/VCP"
        alive = sar_ichimoku if g_ema is None else ema_vcp
        return {
            "available": False,
            "level": "NONE",
            "verdict": f"➖ 한쪽만 판정됨 ({only} 단독)",
            "color": LEVEL_COLOR["NONE"],
            "score": int((alive or {}).get("score") or 0),
            "grades": {"ema_vcp": g_ema, "sar_ichimoku": g_sar},
            "agree": False,
            "conflict": False,
            "signals": [
                f"⚠️ 한쪽 전략만 판정 가능 = 합의 없음! {only} 단독 판단은 신중히!"
            ],
        }

    # --- 양쪽 다 판정됨 ---
    s_ema = int(ema_vcp.get("score") or 0)
    s_sar = int(sar_ichimoku.get("score") or 0)
    avg_score = round((s_ema + s_sar) / 2)
    blocked = False   # v139: 「진입하지 마세요」 수준의 신호인가?

    signals.append(f"📐 EMA/VCP(돌파형) = {g_ema}등급 ({s_ema}점)")
    signals.append(f"☁️ SAR/구름대(추세추종) = {g_sar}등급 ({s_sar}점)")

    d_ema = g_ema == "D"
    d_sar = g_sar == "D"

    if d_ema and d_sar:
        level = "AVOID"
        verdict = "🚫 양쪽 전략 모두 진입 금지!"
        signals.append("🚫 두 전략이 「동시에」 금지 = 이 방향은 건드리지 않는 게 맞습니다!")
        # v139 실측: 실매매 309건 중 AVOID 227건이 총 -19,207 USDT
        #            = 전체 손실 -22,068 의 **87%** 를 이 구간이 만들었습니다!
        signals.append(
            "📉 v139 실측: 과거 실매매에서 이 구간 227건이 전체 손실의 87%(-19,207 USDT)를 차지!"
        )
        score = 0
        blocked = True
    elif d_ema or d_sar:
        level = "CONFLICT"
        blocker = "📐 EMA/VCP" if d_ema else "☁️ SAR/구름대"
        other = "☁️ SAR/구름대" if d_ema else "📐 EMA/VCP"
        verdict = f"🚫 충돌! {blocker}가 금지 신호 = 진입 비권장"
        signals.append(
            f"🚫 {other}는 진입 가능이라 하지만 {blocker}는 「금지」입니다. "
            "= 한쪽만 보고 들어가면 반대 근거를 모른 채 진입하는 셈!"
        )
        # 🚨 v139 실측 (추천 761건 백테스트) = 충돌이 **최악의 구간**이었습니다:
        #     AGREE      40건 → 4h 적중률 57.5% / 평균 +2.00%
        #     PARTIAL   253건 → 38.7% / +0.86%
        #     AVOID     399건 → 32.8% /  0.00%
        #     CONFLICT   67건 → **16.4% / -1.86%**  ← 금지(AVOID)보다도 나쁨!
        #   충돌은 「애매한 상태」가 아니라 **적극적인 위험 신호**입니다.
        #   → v138 의 0.5배 감점 → v139 는 0.3배 + blocked 플래그로 격상!
        score = round(avg_score * 0.3)
        blocked = True
    elif g_ema == "A" and g_sar == "A":
        level = "STRONG_AGREE"
        verdict = "🔥 양쪽 모두 A등급 = 최상위 합의!"
        signals.append("🔥 돌파형·추세추종형이 「동시에 방아쇠」 = 가장 강한 신호!")
        score = avg_score
    elif "A" in (g_ema, g_sar) and "B" in (g_ema, g_sar):
        level = "AGREE"
        verdict = "⭐ 합의! 한쪽 방아쇠 + 한쪽 셋업 완성"
        signals.append("⭐ 한쪽은 진입 시점, 다른 쪽은 셋업 완성 = 방향은 일치!")
        score = avg_score
    elif g_ema == "B" and g_sar == "B":
        level = "AGREE"
        verdict = "⭐ 합의! 양쪽 셋업 완성, 방아쇠 대기"
        signals.append("⭐ 양쪽 다 준비 완료 = 트리거만 기다리면 됩니다!")
        score = avg_score
    else:
        level = "PARTIAL"
        verdict = "👀 부분 합의 = 관망 권장"
        signals.append("👀 방향은 안 막혔지만 양쪽 다 셋업 미완성 = 서두를 이유 없음!")
        score = avg_score

    return {
        "available": True,
        "level": level,
        "verdict": verdict,
        "color": LEVEL_COLOR[level],
        "score": score,
        "grades": {"ema_vcp": g_ema, "sar_ichimoku": g_sar},
        "agree": level in ("STRONG_AGREE", "AGREE"),
        "conflict": level == "CONFLICT",
        "blocked": blocked,   # v139: True = 실측상 진입 비권장 구간!
        "side": (side or "LONG").upper(),
        "signals": signals,
    }


def to_learning_context(result: dict | None) -> dict[str, Any]:
    """학습 저장용 압축 스냅샷."""
    if not result:
        return {}
    return {
        "available": bool(result.get("available")),
        "level": result.get("level"),
        "score": result.get("score"),
        "grades": result.get("grades") or {},
        "agree": bool(result.get("agree")),
        "conflict": bool(result.get("conflict")),
        "blocked": bool(result.get("blocked")),
    }
