"""enter_stage_at_market 의 additional_margin_usdt 자동 호출 회귀 (사용자 #21 SAGAUSDT 보고).

배경 (2026-05-12 사용자 보고):
사용자가 「수동 ▶ 다음 단계 진입」 으로 4단계 진입했지만 stage_plan 에 설정한
additional_margin_usdt = +50 USDT 가 자동 투입 안 됨.

원인 (이전):
add_position_margin 자동 호출이 두 자동 경로엔 있었지만 수동 경로엔 누락:
- start_stage1 (자동) ✓
- stage_trigger_worker.run_stage_trigger_once (자동 LIMIT) ✓
- enter_stage_at_market (수동 ▶ MARKET) ✗ ← 누락

Fix:
enter_stage_at_market 에 동일 패턴 추가. 실패해도 entry 는 정상, RiskEvent + 알림 기록.
"""
from __future__ import annotations

import inspect

from app.services.execution_service import ExecutionService


class TestEnterStageAtMarketCallsAddMargin:
    def test_source_includes_add_position_margin_call(self):
        """enter_stage_at_market 소스에 add_position_margin 호출 + additional_margin_usdt 참조 검증."""
        src = inspect.getsource(ExecutionService.enter_stage_at_market)
        assert "additional_margin_usdt" in src, (
            "enter_stage_at_market 가 stage_plan.additional_margin_usdt 참조해야 함 (사용자 #21 fix)"
        )
        assert "add_position_margin" in src, (
            "enter_stage_at_market 가 add_position_margin 호출해야 함 (사용자 #21 fix)"
        )

    def test_source_failure_handled_with_notification(self):
        """추가 증거금 실패 시 entry 는 정상 + send_system_alert 호출 (수동 보충 안내)."""
        src = inspect.getsource(ExecutionService.enter_stage_at_market)
        assert "send_system_alert" in src, (
            "추가 증거금 실패 시 사용자 알림 발송 필수"
        )
        assert "수동 보충" in src or "수동 진입" in src or "💡" in src, (
            "알림 본문에 수동 보충 가이드 포함 필수"
        )

    def test_source_calls_add_margin_after_entry_committed(self):
        """add_position_margin 은 db.commit + db.refresh 후에 호출 — entry 가 먼저 확정돼야."""
        src = inspect.getsource(ExecutionService.enter_stage_at_market)
        # 순서 검증: db.commit 먼저, 그 다음 additional_margin_usdt 분기
        commit_idx = src.find("self.db.commit()")
        addm_idx = src.find("additional_margin_usdt")
        assert commit_idx > 0, "db.commit 호출 필수"
        assert addm_idx > commit_idx, (
            "add_position_margin 호출은 entry commit 후에 — 실패해도 entry 는 보존"
        )
