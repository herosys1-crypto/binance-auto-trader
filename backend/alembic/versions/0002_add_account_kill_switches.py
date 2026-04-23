"""add account kill switches"""
from alembic import op
import sqlalchemy as sa

revision = "0002_add_account_kill_switches"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "account_kill_switches",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("exchange_account_id", sa.BigInteger(), sa.ForeignKey("exchange_accounts.id"), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reason_code", sa.String(length=60), nullable=True),
        sa.Column("reason_message", sa.Text(), nullable=True),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("exchange_account_id", name="uq_account_kill_switch_exchange_account_id"),
    )
    op.create_index("ix_account_kill_switches_exchange_account_id", "account_kill_switches", ["exchange_account_id"], unique=False)

def downgrade() -> None:
    op.drop_index("ix_account_kill_switches_exchange_account_id", table_name="account_kill_switches")
    op.drop_table("account_kill_switches")
