"""요청 무게 거버너 우선순위 — Fix 416 (Duel weight-priority).

거버너(Fix 124)는 「스캔」 요청을 이번 분 누적 1,500 에서 막는다. 그런데 15분봉 마감 직후 학습 잡과 실매매 스캐너가 겹치면
같은 선에서 경쟁해, 실매매 스캐너가 거절당했다 (2026-10-03 18:46 UTC: 학습 545 · 실매매 437 · 화면 136 … → 실매매 71건 거절).
학습·관측 잡(주문을 절대 내지 않음)은 더 낮은 선(1,100)에서 먼저 물러서고, 남은 400 은 실매매 스캐너 몫이다.
필수 요청(주문·포지션·계정)은 이 판정과 무관하게 항상 통과한다(스캔 엔드포인트가 아니면 None).
"""
from __future__ import annotations

SCAN_WEIGHT_BUDGET_PER_MIN = 1500          # 기존 거버너 상한 (client.py 와 같은 값)
LOW_PRIORITY_SCAN_BUDGET_PER_MIN = 1100    # Claude가 정함 — 학습 잡 상한, 400 = 실매매 스캐너 여유
LOW_PRIORITY_CALLERS = frozenset({         # Claude가 정함 — 주문을 절대 내지 않는 학습·관측 잡만 (잡 이름 정확히 일치)
    "paper_trading", "chart_timing", "market_obs_update", "market_obs_snapshot",
    "chart_learning_snapshot", "chart_learning_outcome", "learning_sync", "learning_team_cycle",
    "pattern_learning", "prediction_outcome", "loss_cause",
    "emapb_watch",                          # 🗓 Fix 424: 알림 전용(주문 없음) — 15분봉 직후 몰릴 때 실매매 스캐너에 양보
})


def is_low_priority(caller: object, low_callers=LOW_PRIORITY_CALLERS) -> bool:
    """정확히 일치하는 문자열만 낮은 등급. 그 밖(빈 값·None·다른 타입·접두사만 같은 이름)은 일반."""
    return isinstance(caller, str) and caller in low_callers


def scan_throttled(path: str, total: object, caller: object, *, scan_endpoints, budget: int = SCAN_WEIGHT_BUDGET_PER_MIN,
                   low_budget: int = LOW_PRIORITY_SCAN_BUDGET_PER_MIN, low_callers=LOW_PRIORITY_CALLERS) -> int | None:
    """막아야 하면 적용 상한(budget 또는 low_budget), 아니면 None. 순수 함수 — 부수효과·로그 없음, 예외를 내지 않는다.

    total 이 숫자가 아니면(카운터 실패 등) None = 막지 않음 — 기존 거버너의 「Redis 실패 = 0 = 막지 않음」과 같은 실패 방향.
    """
    try:
        if path not in scan_endpoints:
            return None                                  # 필수 요청: 어떤 경우에도 통과
        if isinstance(total, bool) or not isinstance(total, (int, float)):
            return None
        if isinstance(total, float) and total != total:  # NaN
            return None
        limit = low_budget if is_low_priority(caller, low_callers) else budget
        return limit if total > limit else None
    except Exception:  # noqa: BLE001 — 판정 실패가 요청을 막지 않게
        return None
