"""재진입 자동화 — strategy_templates 에 delay + offset 컬럼 추가.

reentry_policy 값 의미 (기존 string 컬럼):
  - 'manual_ready' (default): SL 후 status=REENTRY_READY 로 두고 운영자가 수동 재시작
  - 'auto': delay 경과 후 자동으로 새 strategy 생성 + 1단계 주문 발송

추가 컬럼:
  - reentry_delay_seconds : auto 정책 시 SL 후 대기 시간 (초). 기본 600 (10분)
  - reentry_offset_pct    : 새 start_price = 현재가 × (1 ± offset/100)
                              SHORT 면 +offset, LONG 면 -offset (불리한 방향에서 약간 떨어진 곳)
                              기본 1.0 (1%)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0007_auto_reentry"
down_revision = "0006_pnl_tracking_crisis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_templates",
        sa.Column("reentry_delay_seconds", sa.Integer(), nullable=False, server_default="600"),
    )
    op.add_column(
        "strategy_templates",
        sa.Column("reentry_offset_pct", sa.Numeric(8, 4), nullable=False, server_default="1.0"),
    )


def downgrade() -> None:
    op.drop_column("strategy_templates", "reentry_offset_pct")
    op.drop_column("strategy_templates", "reentry_delay_seconds")
