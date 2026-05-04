"""Strategy status 분류 — 시스템 전반에서 한 곳에서 정의.

이전 (audit 2026-05-04): 같은 set 이 strategy_service.py / strategies.py /
admin.py / zombie_guardian.py / reconcile_worker.py 등 5+ 곳에 inline 으로
반복돼 있었고, 일부는 항목이 빠지거나 STOPPING 포함 여부가 달라 미묘한 버그
유발 (commit 89f779d, b28c92f, 8b521a3, 9611304 가 일부 fix). 이 module 이
single source of truth.
"""
from __future__ import annotations


# 거래소 포지션 / 신규 주문 영향이 모두 끝난 "완전 종료" status.
# 새 strategy 진입 시 중복 가드의 _CLOSED_STATUSES, DELETE 가드 등 모두 이 set 사용.
# STOPPING 은 의도적으로 제외 — 거래소에 포지션 잔재 가능 (closing in progress).
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
# (UI 의 종료 숨김 필터는 STOPPING 도 포함하지만 그건 view-only 영역.)
DELETABLE_STATUSES: frozenset[str] = TERMINAL_STATUSES


# Active = 진행 중 / 거래소 포지션 보유 / 닫는 중 — 모든 비-종료 status.
# 정확한 set 은 reconcile_worker / zombie_guardian 의 동적 생성 set 참고
# (옵션 C 1~10 단계 / TP1~5 동적 — frozenset 으로 못 쓰므로 거기서 별도 빌드).
