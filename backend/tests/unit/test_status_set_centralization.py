"""Lint 테스트 — status set centralize 회귀 방지 (2026-05-14 Phase 1).

배경 (사용자 「지속적 문제」 지적):
- 5-06 TP10 확장 시 zombie_guardian + reconcile_worker + daily_loss_aggregator 3곳
  의 inline `{f"STAGE{n}_OPEN" for n in range(1, 11)}` 패턴 갱신 누락
- 결과: TP6~10_DONE_PARTIAL 인 strategy 가 active 분류에서 빠져
  「외부 청산」 으로 오판되거나 PnL 집계 누락 → KS 오발동
- Phase 1 centralize 후 이 패턴이 다시 inline 으로 되살아나면 즉시 catch.

규칙:
- `app/services/`, `app/workers/` 의 .py 파일에서
  `for n in range(1, 11)` + STAGE{n} 또는 TP{n} pattern 검출 시 실패
- 예외: `app/core/strategy_status.py` (single source) + `app/api/` (요청별 schema 일부 허용)

이 테스트가 실패하면:
1. 해당 파일에서 inline build 를 제거하고
2. `app.core.strategy_status` 의 적절한 set 을 import 해 사용 (또는 새 alias 추가).
"""
from __future__ import annotations

import re
from pathlib import Path


# 검출 대상 패턴: f"STAGE{n}_..." 또는 f"TP{n}_..." + range(1, 1[01])
INLINE_STATUS_RANGE = re.compile(
    r'f["\'](?:STAGE|TP)\{n\}[A-Z_]*["\'].*?for\s+n\s+in\s+range\(\s*1\s*,\s*1[01]\s*\)',
    re.DOTALL,
)
PENDING_TO_OPEN_INLINE = re.compile(
    r'f["\']STAGE\{n\}_OPEN_PENDING["\'].*?:.*?f["\']STAGE\{n\}_OPEN["\']',
    re.DOTALL,
)


def _backend_root() -> Path:
    # tests/unit/test_*.py → tests → backend
    return Path(__file__).resolve().parent.parent.parent


def _scan_dir(rel_dir: str, allowlist: set[str]) -> list[str]:
    """주어진 dir 의 *.py 파일에서 inline status range 위반 목록 반환.

    Returns:
        list of "{path}: {snippet}" 위반 항목.
    """
    root = _backend_root() / rel_dir
    if not root.exists():
        return []
    violations: list[str] = []
    for py in root.rglob("*.py"):
        rel = py.relative_to(_backend_root()).as_posix()
        if rel in allowlist:
            continue
        text = py.read_text(encoding="utf-8")
        for m in INLINE_STATUS_RANGE.finditer(text):
            snippet = m.group(0)[:120].replace("\n", " ")
            violations.append(f"{rel}: {snippet}")
        for m in PENDING_TO_OPEN_INLINE.finditer(text):
            snippet = m.group(0)[:120].replace("\n", " ")
            violations.append(f"{rel}: PENDING_TO_OPEN inline → {snippet}")
    return violations


class TestStatusSetCentralization:
    """app.core.strategy_status 가 single source — workers/services 에서 재구축 금지."""

    def test_no_inline_status_range_in_workers(self):
        """app/workers/*.py — inline `{f"STAGE{n}_..." for n in range(1, 11)}` 금지."""
        violations = _scan_dir("app/workers", allowlist=set())
        assert not violations, (
            "Inline status set in workers (centralize 위반):\n  "
            + "\n  ".join(violations)
            + "\n\n→ app.core.strategy_status 의 set 을 import 해 사용하세요."
        )

    def test_no_inline_status_range_in_services(self):
        """app/services/*.py — inline status range 금지.

        예외:
        - tp_sl_orchestrator.py: TP level loop (status 가 아닌 TP{n} label index 매핑) 일부 허용
        - risk_service.py: TP level loop 일부 허용
        - execution_service.py: TP_PARTIAL_SET inline (Phase 2 대상)

        이번 Phase 1 의 핵심: zombie_guardian.py 가 깨끗해졌는지만 확인.
        """
        # Phase 1 에서 centralize 한 것: zombie_guardian + reconcile + daily_loss
        # 나머지 services 파일은 Phase 2 에서 확장 예정 (TP_LEVEL 매핑은 별도 차원).
        allowlist = {
            "app/services/tp_sl_orchestrator.py",  # TP level index/label 매핑 (status 아님)
            "app/services/risk_service.py",         # TP level index/label 매핑 (status 아님)
            "app/services/execution_service.py",    # Phase 2 centralize 대상
        }
        violations = _scan_dir("app/services", allowlist=allowlist)
        assert not violations, (
            "Inline status set in services (centralize 위반):\n  "
            + "\n  ".join(violations)
            + "\n\n→ app.core.strategy_status 의 set 을 import 해 사용하세요."
        )

    def test_central_module_exposes_required_sets(self):
        """app.core.strategy_status 가 worker/service 에서 import 하는 모든 set 노출."""
        from app.core import strategy_status as ss

        required = [
            "TERMINAL_STATUSES",
            "DELETABLE_STATUSES",
            "ACTIVE_WITH_POSITION",
            "ACTIVE_WAITING",
            "ACTIVE_LIKE",
            "ACTIVE_FOR_PNL",
            "OPEN_LIKE_FOR_ORPHAN_CHECK",
            "PENDING_TO_OPEN_MAP",
            "STAGES_WITH_NEXT",
            "TOTAL_STAGES_MAX",
            "TOTAL_TP_LEVELS",
        ]
        missing = [name for name in required if not hasattr(ss, name)]
        assert not missing, f"app.core.strategy_status 누락 export: {missing}"

    def test_active_with_position_includes_all_tp_levels(self):
        """ACTIVE_WITH_POSITION 이 TP1~TP10_DONE_PARTIAL 모두 포함하는지 회귀 검증.

        5-06 TP10 확장 시 발생한 재귀 버그 (TP6~10 누락) 의 직접적 회귀 catch.
        """
        from app.core.strategy_status import ACTIVE_WITH_POSITION, TOTAL_TP_LEVELS

        for n in range(1, TOTAL_TP_LEVELS + 1):
            assert f"TP{n}_DONE_PARTIAL" in ACTIVE_WITH_POSITION, (
                f"TP{n}_DONE_PARTIAL 누락 — TOTAL_TP_LEVELS 와 set build 불일치"
            )

    def test_active_with_position_includes_all_stages(self):
        """ACTIVE_WITH_POSITION 이 STAGE1~STAGE10_OPEN 모두 포함하는지 회귀 검증."""
        from app.core.strategy_status import ACTIVE_WITH_POSITION, TOTAL_STAGES_MAX

        for n in range(1, TOTAL_STAGES_MAX + 1):
            assert f"STAGE{n}_OPEN" in ACTIVE_WITH_POSITION, f"STAGE{n}_OPEN 누락"

    def test_active_waiting_includes_all_pending_stages(self):
        """ACTIVE_WAITING 이 STAGE1~STAGE10_OPEN_PENDING 모두 포함."""
        from app.core.strategy_status import ACTIVE_WAITING, TOTAL_STAGES_MAX

        for n in range(1, TOTAL_STAGES_MAX + 1):
            assert f"STAGE{n}_OPEN_PENDING" in ACTIVE_WAITING

    def test_pending_to_open_map_complete(self):
        """PENDING_TO_OPEN_MAP 이 모든 stage 의 PENDING → OPEN 매핑 포함."""
        from app.core.strategy_status import PENDING_TO_OPEN_MAP, TOTAL_STAGES_MAX

        for n in range(1, TOTAL_STAGES_MAX + 1):
            key = f"STAGE{n}_OPEN_PENDING"
            assert key in PENDING_TO_OPEN_MAP, f"{key} → OPEN 매핑 누락"
            target_status, stage_no = PENDING_TO_OPEN_MAP[key]
            assert target_status == f"STAGE{n}_OPEN"
            assert stage_no == n

    def test_open_like_for_orphan_check_completeness(self):
        """OPEN_LIKE_FOR_ORPHAN_CHECK 이 STAGE1~10_OPEN + TP1~10_DONE_PARTIAL 포함."""
        from app.core.strategy_status import (
            OPEN_LIKE_FOR_ORPHAN_CHECK,
            TOTAL_STAGES_MAX,
            TOTAL_TP_LEVELS,
        )

        for n in range(1, TOTAL_STAGES_MAX + 1):
            assert f"STAGE{n}_OPEN" in OPEN_LIKE_FOR_ORPHAN_CHECK
        for n in range(1, TOTAL_TP_LEVELS + 1):
            assert f"TP{n}_DONE_PARTIAL" in OPEN_LIKE_FOR_ORPHAN_CHECK

    def test_stages_with_next_excludes_final_stage(self):
        """STAGES_WITH_NEXT 는 STAGE1~9_OPEN — STAGE10_OPEN 은 마지막이라 제외."""
        from app.core.strategy_status import STAGES_WITH_NEXT, TOTAL_STAGES_MAX

        for n in range(1, TOTAL_STAGES_MAX):
            assert f"STAGE{n}_OPEN" in STAGES_WITH_NEXT, f"STAGE{n}_OPEN 누락"
        # MAX 는 마지막 stage → 제외
        assert f"STAGE{TOTAL_STAGES_MAX}_OPEN" not in STAGES_WITH_NEXT, (
            f"STAGE{TOTAL_STAGES_MAX}_OPEN 은 마지막 stage 라 STAGES_WITH_NEXT 에서 제외돼야"
        )

    def test_terminal_and_active_disjoint(self):
        """TERMINAL 과 ACTIVE 는 절대 겹치면 안 됨 (status 분류 mutually exclusive)."""
        from app.core.strategy_status import (
            ACTIVE_LIKE,
            ACTIVE_WITH_POSITION,
            TERMINAL_STATUSES,
        )

        overlap_active = TERMINAL_STATUSES & ACTIVE_LIKE
        assert not overlap_active, f"TERMINAL ∩ ACTIVE_LIKE 비어야 함: {overlap_active}"
        overlap_pos = TERMINAL_STATUSES & ACTIVE_WITH_POSITION
        assert not overlap_pos, f"TERMINAL ∩ ACTIVE_WITH_POSITION 비어야 함: {overlap_pos}"
