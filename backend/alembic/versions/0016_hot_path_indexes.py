"""Hot-path 인덱스 추가 — Phase 5 conservative perf fix (2026-05-14).

배경:
- 운영 누적 데이터가 늘어나면서 hot-path query 들이 full scan / 비효율 정렬 발생 가능
- 현재는 1 user / testnet 운영 중이라 체감 0 — 하지만 mainnet 진입 + 1주 운영 후엔
  notifications/risk_events/orders 가 수만 row 누적 예상

추가 인덱스 (3개, 보수적):
1. notifications.created_at (DESC)
   - 사용처: recent-activity, get_notifications_by_title (ORDER BY created_at DESC LIMIT N)
   - get_operation_stats (WHERE created_at >= cutoff)
   - 단일 컬럼이라 write overhead 미미.

2. risk_events(severity, created_at) composite + risk_events.created_at
   - 사용처: admin/system-status (WHERE severity='CRITICAL' AND created_at >= cutoff)
   - admin/health/dashboard (WHERE created_at >= since)
   - severity 단독 카디널리티 낮으므로 (CRITICAL/WARNING/INFO 정도) created_at 같이.

3. orders(strategy_instance_id, stage_no, purpose, status) composite
   - 사용처: trigger_next_stage_manually (WHERE strategy_id AND stage AND purpose AND status)
   - risk_service crisis 검사 (ad-hoc ENTRY 탐지)
   - reconcile / zombie_guardian stage queries
   - strategy_instance_id 단독으로는 stage/purpose/status 추가 필터 시 row 많이 fetch.

성능 영향 (PostgreSQL 기준):
- INSERT/UPDATE 약간 느림 (3 인덱스 추가) — 1 user 환경에선 무시 가능
- SELECT 빠름 (특히 notifications/risk_events 누적 후)
- 디스크 사용량 증가 (인덱스 자체 크기) — 작은 운영 규모에선 무시 가능

production 배포: docker compose down + up -d --build 시 자동 적용.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0016_hot_path_indexes"
down_revision = "0015_crisis_threshold"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. notifications.created_at — recent-activity / stats / get_notifications_by_title
    op.create_index(
        "ix_notifications_created_at",
        "notifications",
        ["created_at"],
        unique=False,
    )

    # 2. risk_events 두 인덱스 (composite + 단독)
    op.create_index(
        "ix_risk_events_severity_created_at",
        "risk_events",
        ["severity", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_risk_events_created_at",
        "risk_events",
        ["created_at"],
        unique=False,
    )

    # 3. orders composite — stage/purpose/status 다중 필터
    op.create_index(
        "ix_orders_strategy_stage_purpose_status",
        "orders",
        ["strategy_instance_id", "stage_no", "purpose", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_orders_strategy_stage_purpose_status", table_name="orders")
    op.drop_index("ix_risk_events_created_at", table_name="risk_events")
    op.drop_index("ix_risk_events_severity_created_at", table_name="risk_events")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
