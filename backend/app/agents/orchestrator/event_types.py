"""📡 EventType = 이벤트 상수 (Single Source of Truth!)

헌법 C06: 단일 진실 = 이벤트 이름 = 여기서 한 번만 정의!
모든 팀 = 이 상수 참조!
"""
from __future__ import annotations

from enum import Enum


class EventType(str, Enum):
    """전 팀 이벤트 종류!

    사용:
        from app.agents.orchestrator import EventType
        bus.publish(EventType.STRATEGY_ENTERED, {"strategy_id": 838})
    """

    # ===== Entry Team =====
    STRATEGY_CREATED = "strategy.created"        # 신 전략 생성!
    STRATEGY_ENTERED = "strategy.entered"        # 1단계 진입 완료!
    STAGE_TRIGGERED = "stage.triggered"          # 다음 단계 진입!
    RETRY_REENTRY_TRIGGERED = "retry.triggered"  # 청산 후 재진입!

    # ===== TP Team =====
    TP_ARMED = "tp.armed"                        # TP 감시 시작!
    TP_TRIGGERED = "tp.triggered"                # TP 발동!
    TRAILING_ARMED = "trailing.armed"            # 트레일링 활성!
    TRAILING_TRIGGERED = "trailing.triggered"    # 트레일링 발동!

    # ===== SL Team =====
    SL_TRIGGERED = "sl.triggered"                # SL 발동!
    FORCE_SL_TRIGGERED = "force_sl.triggered"    # 강제 SL 발동!
    LIQUIDATION_IMMINENT = "liquidation.imminent"  # 청산 임박!
    CAPITAL_EXHAUSTED = "capital.exhausted"      # 자본 소진!

    # ===== Monitoring Team =====
    MARK_PRICE_UPDATED = "mark_price.updated"
    POSITION_RECONCILED = "position.reconciled"
    ZOMBIE_DETECTED = "zombie.detected"

    # ===== Alert Team =====
    REENTRY_ALERT_MATCHED = "reentry_alert.matched"    # 재진입 알람!
    PUMP_BB_ALERT_MATCHED = "pump_bb_alert.matched"    # 급등+BB!
    TP_MISS_DETECTED = "tp_miss.detected"              # TP 놓침!

    # ===== Capital Team =====
    CAPITAL_130PCT_EXCEEDED = "capital.130pct_exceeded"  # 130% 초과!
    DAILY_LOSS_LIMIT_REACHED = "daily_loss.limit_reached"
    KILL_SWITCH_TRIGGERED = "kill_switch.triggered"

    # ===== Analysis Team =====
    CHART_ANALYZED = "chart.analyzed"

    # ===== Market Flow Team (v132!) =====
    DAILY_LEARNING_DONE = "learning.daily_done"        # 매일 학습 완료!
    PATTERN_MATCHED = "pattern.matched"                # 유사 패턴!

    # ===== Timezone Pattern Team (v132!) =====
    TIMEZONE_STATS_UPDATED = "timezone.stats_updated"
    TIMEZONE_ALERT = "timezone.alert"

    # ===== Strategy Suggestion Team (v132!) =====
    SUGGESTION_CREATED = "suggestion.created"          # 신 제안 생성!
    SUGGESTION_EXECUTED = "suggestion.executed"        # 사장님 실행!
    SUGGESTION_DISMISSED = "suggestion.dismissed"      # 사장님 삭제!

    # ===== Audit Team =====
    CONSTITUTION_VIOLATED = "constitution.violated"    # 헌법 위반!
    SILENT_BUG_DETECTED = "silent_bug.detected"        # Silent bug!
    SPEC_DRIFT_DETECTED = "spec.drift_detected"        # spec drift!

    # ===== System (최우선!) =====
    SYSTEM_STARTED = "system.started"
    SYSTEM_STOPPING = "system.stopping"
    EMERGENCY_STOP_ALL = "emergency.stop_all"          # 최우선 = 전체 정지!


# 이벤트 → 관련 팀 매핑 (참고용!)
EVENT_TEAM_MAP: dict[EventType, list[str]] = {
    EventType.STRATEGY_ENTERED: ["monitoring", "alert", "capital"],
    EventType.STAGE_TRIGGERED: ["monitoring", "alert"],
    EventType.SL_TRIGGERED: ["alert", "audit"],
    EventType.FORCE_SL_TRIGGERED: ["capital", "alert", "audit"],
    EventType.CAPITAL_EXHAUSTED: ["alert", "audit"],
    EventType.PATTERN_MATCHED: ["alert", "strategy_suggestion"],
    EventType.DAILY_LEARNING_DONE: ["strategy_suggestion"],
    EventType.SUGGESTION_CREATED: ["alert", "ui"],
    EventType.EMERGENCY_STOP_ALL: [
        "entry", "tp", "sl", "monitoring", "alert",
        "capital", "analysis", "maintenance", "ui", "audit",
        "market_flow", "timezone_pattern", "strategy_suggestion",
    ],
}
