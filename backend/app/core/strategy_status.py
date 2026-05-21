"""Strategy status 분류 — 시스템 전반에서 한 곳에서 정의.

이전 (audit 2026-05-04): 같은 set 이 strategy_service.py / strategies.py /
admin.py / zombie_guardian.py / reconcile_worker.py 등 5+ 곳에 inline 으로
반복돼 있었고, 일부는 항목이 빠지거나 STOPPING 포함 여부가 달라 미묘한 버그
유발 (commit 89f779d, b28c92f, 8b521a3, 9611304 가 일부 fix). 이 module 이
single source of truth.

2026-05-14 Phase 1 centralize (사용자 「지속적 문제」 지적 후속):
TERMINAL_STATUSES 외에도 ACTIVE 계열을 모두 여기로 이동.
이전엔 zombie_guardian / reconcile_worker / daily_loss_aggregator 4곳에
inline build (range(1,11)) 돼 있어, 5-06 TP10 확장 시 3곳 누락 → recurring bug.
이제 stage/TP 범위 변경 시 이 파일 1곳만 수정 → 모든 worker 자동 적용.
"""
from __future__ import annotations


# ===== 핵심 차원 상수 =====
# 옵션 C 1~10단계 / TP1~10. 변경 시 이 값만 갱신하면 모든 set 자동 재계산.
TOTAL_STAGES_MAX = 10
TOTAL_TP_LEVELS = 10


# ===== TERMINAL =====
# 거래소 포지션 / 신규 주문 영향이 모두 끝난 "완전 종료" status.
# 새 strategy 진입 시 중복 가드의 _CLOSED_STATUSES, DELETE 가드 등 모두 이 set 사용.
# STOPPING / MANUAL_CLEANUP_REQUIRED 는 의도적으로 제외 — 거래소에 포지션 잔재 가능.
TERMINAL_STATUSES: frozenset[str] = frozenset({
    "STOPPED",
    "COMPLETED",
    "CLOSED",
    "CLOSED_BY_TP",
    "CLOSED_BY_SL",
    "REENTRY_READY",
    "KILL_SWITCH_TRIGGERED",
})


# 운영자가 영구 삭제 (DELETE) 가능한 status — TERMINAL 과 동일.
DELETABLE_STATUSES: frozenset[str] = TERMINAL_STATUSES


# ===== MANUAL CLEANUP =====
# 2026-05-21 #77/#78 사례 후 신규 (사장님 요구 — Phase 2):
#   emergency_close 검증 실패 또는 STOPPING 5분 초과 시 자동 STOPPED 안 함.
#   사장님이 거래소에서 직접 청산 → UI 「✅ 처리 완료」 클릭 → 명시적 STOPPED 전환.
# 이유: 자동 STOPPED 처리되면 사장님이 「내가 책임지고 처리한 건」 vs 「자동 정리된 건」
# 구분 못 함. 자금 흐름 추적 / 책임 명확화 위해 사장님 확인 통해서만 종료.
#
# - 거래소 포지션은 잔재 가능 (또는 사장님이 이미 거래소 UI 로 청산했을 수도)
# - TP/SL 평가 대상 X (_NOT_FOR_TP_SL 에 포함)
# - reconcile 자동 STOPPED 전환 X (사장님 ack 없이는 status 유지)
# - 같은 symbol+side 신규 strategy 진입 차단 대상 (ACTIVE_LIKE 포함)
# - 「종료 숨김」 토글 영향 X (STOPPING 과 동일하게 항상 보임)
MANUAL_CLEANUP_REQUIRED: str = "MANUAL_CLEANUP_REQUIRED"


# ===== ACTIVE 계열 =====
# 거래소에 실제 포지션이 있어야 하는 active 상태 (PENDING 제외, STOPPING 포함).
# zombie_guardian / reconcile_worker / daily_loss_aggregator 모두 이걸 import 사용.
ACTIVE_WITH_POSITION: frozenset[str] = frozenset(
    {f"STAGE{n}_OPEN" for n in range(1, TOTAL_STAGES_MAX + 1)}
    | {f"TP{n}_DONE_PARTIAL" for n in range(1, TOTAL_TP_LEVELS + 1)}
    | {"TRAILING_ARMED"}     # 명시적 trailing armed status
    | {"CRISIS_TP1_DONE"}    # 크라이시스 첫 TP 후 잔량 보유 상태
    | {"STOPPING"}           # 청산 진행 중 (포지션 잔재 가능)
    | {MANUAL_CLEANUP_REQUIRED}  # 수동 청산 요청 — 사장님 ack 대기 (포지션 잔재 가능)
)

# 거래소 포지션 미확정 (LIMIT 미체결) — STAGE_n_OPEN_PENDING 모두.
ACTIVE_WAITING: frozenset[str] = frozenset(
    {f"STAGE{n}_OPEN_PENDING" for n in range(1, TOTAL_STAGES_MAX + 1)}
)

# 모든 "active" — 신규 strategy 진입 차단해야 할 상태 (포지션 보유 + 대기 모두).
ACTIVE_LIKE: frozenset[str] = ACTIVE_WITH_POSITION | ACTIVE_WAITING

# PnL 집계 대상 — 활성 포지션 있는 모든 status (PENDING 은 포지션 없으므로 제외).
# daily_loss_aggregator 가 사용. 의미상 ACTIVE_WITH_POSITION 과 동일하지만,
# 별도 alias 로 의도 명확화 (PnL 집계 = "거래소에 실 포지션 있는 것만").
ACTIVE_FOR_PNL: frozenset[str] = ACTIVE_WITH_POSITION


# ===== Reconcile 전용 set =====
# *_OPEN orphan 자동 정리 대상 — 거래소 포지션 0 인데 DB 가 OPEN/TP_PARTIAL 인 케이스.
# STOPPING/TRAILING_ARMED/CRISIS_TP1_DONE 는 별도 처리 → 제외.
OPEN_LIKE_FOR_ORPHAN_CHECK: frozenset[str] = frozenset(
    {f"STAGE{n}_OPEN" for n in range(1, TOTAL_STAGES_MAX + 1)}
    | {f"TP{n}_DONE_PARTIAL" for n in range(1, TOTAL_TP_LEVELS + 1)}
)

# *_OPEN_PENDING + 거래소에 실 포지션 → *_OPEN 자가 회복 mapping.
# Key: PENDING status, Value: (target OPEN status, stage_no)
PENDING_TO_OPEN_MAP: dict[str, tuple[str, int]] = {
    f"STAGE{n}_OPEN_PENDING": (f"STAGE{n}_OPEN", n)
    for n in range(1, TOTAL_STAGES_MAX + 1)
}


# ===== Stage trigger 전용 set =====
# 다음 stage 진입 검사 대상 — STAGE 1~(MAX-1) 가 OPEN 이면 그 다음 stage 진입 검사.
# STAGE_MAX (10) 는 마지막 단계라 다음이 없으므로 제외.
# stage_trigger_worker 가 사용.
STAGES_WITH_NEXT: frozenset[str] = frozenset(
    {f"STAGE{n}_OPEN" for n in range(1, TOTAL_STAGES_MAX)}
)


__all__ = [
    "TOTAL_STAGES_MAX",
    "TOTAL_TP_LEVELS",
    "TERMINAL_STATUSES",
    "DELETABLE_STATUSES",
    "MANUAL_CLEANUP_REQUIRED",
    "ACTIVE_WITH_POSITION",
    "ACTIVE_WAITING",
    "ACTIVE_LIKE",
    "ACTIVE_FOR_PNL",
    "OPEN_LIKE_FOR_ORPHAN_CHECK",
    "PENDING_TO_OPEN_MAP",
    "STAGES_WITH_NEXT",
]
