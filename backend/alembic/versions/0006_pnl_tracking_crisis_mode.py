"""크라이시스 복구 모드 + PnL 추적 — strategy_instances 에 5개 컬럼 추가.

추가 컬럼:
- max_loss_pct          : 누적 최대 손실 % (음수, e.g. -32.5)
- max_profit_pct        : 누적 최대 이익 %
- crisis_mode_triggered_at : 크라이시스 모드 진입 시각 (NULL = 미진입)
- crisis_first_tp_done_at  : 크라이시스 모드 첫 TP (+5%) 발동 시각
- peak_pnl_pct_after_first_tp : 첫 TP 발동 후 피크 PnL % (트레일링용)

모두 nullable — 기존 row 는 NULL 로 두고 새 평가 시점부터 추적 시작.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0006_pnl_tracking_crisis"
down_revision = "0005_more_tp_levels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_instances",
        sa.Column("max_loss_pct", sa.Numeric(8, 4), nullable=True),
    )
    op.add_column(
        "strategy_instances",
        sa.Column("max_profit_pct", sa.Numeric(8, 4), nullable=True),
    )
    op.add_column(
        "strategy_instances",
        sa.Column("crisis_mode_triggered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "strategy_instances",
        sa.Column("crisis_first_tp_done_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "strategy_instances",
        sa.Column("peak_pnl_pct_after_first_tp", sa.Numeric(8, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("strategy_instances", "peak_pnl_pct_after_first_tp")
    op.drop_column("strategy_instances", "crisis_first_tp_done_at")
    op.drop_column("strategy_instances", "crisis_mode_triggered_at")
    op.drop_column("strategy_instances", "max_profit_pct")
    op.drop_column("strategy_instances", "max_loss_pct")
