"""add account daily risk limits"""
from alembic import op
import sqlalchemy as sa

revision = "0003_daily_risk_limits"
down_revision = "0002_add_account_kill_switches"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "account_daily_risk_limits",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("exchange_account_id", sa.BigInteger(), sa.ForeignKey("exchange_accounts.id"), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("unrealized_pnl_snapshot", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("daily_loss_limit_amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("exchange_account_id", "trading_date", name="uq_account_daily_risk_limits_account_date"),
    )
    op.create_index("ix_account_daily_risk_limits_exchange_account_id", "account_daily_risk_limits", ["exchange_account_id"], unique=False)
    op.create_index("ix_account_daily_risk_limits_trading_date", "account_daily_risk_limits", ["trading_date"], unique=False)

def downgrade() -> None:
    op.drop_index("ix_account_daily_risk_limits_trading_date", table_name="account_daily_risk_limits")
    op.drop_index("ix_account_daily_risk_limits_exchange_account_id", table_name="account_daily_risk_limits")
    op.drop_table("account_daily_risk_limits")
