"""risk_events.strategy_instance_id 를 NULL 허용으로 변경.

배경:
- 기존: NOT NULL + FK to strategy_instances.id
- 문제: listenKeyExpired, 매칭 안 되는 ORDER_TRADE_UPDATE 등
  특정 strategy 에 속하지 않는 시스템 레벨 이벤트도 risk_events 에
  기록되는데, 코드가 strategy_instance_id=0 으로 시도해서 FK 위반 → 워커 크래시.
- 수정: nullable 로 변경. 시스템 이벤트는 NULL 사용.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0008_risk_events_sid_nullable"
down_revision = "0007_auto_reentry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "risk_events",
        "strategy_instance_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    # NULL 행을 0 으로 강제 채워야 NOT NULL 복원 가능 — 단순 다운그레이드는 데이터 손실 위험이 있어 복원 보류.
    op.alter_column(
        "risk_events",
        "strategy_instance_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
