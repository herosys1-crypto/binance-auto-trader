"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # users
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=True),
        sa.Column("role", sa.String(length=30), nullable=False, server_default="admin"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Seoul"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # exchange_accounts
    op.create_table(
        "exchange_accounts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("exchange_name", sa.String(length=30), nullable=False, server_default="binance"),
        sa.Column("market_type", sa.String(length=30), nullable=False, server_default="usds_m_futures"),
        sa.Column("api_key_enc", sa.Text(), nullable=False),
        sa.Column("api_secret_enc", sa.Text(), nullable=False),
        sa.Column("passphrase_enc", sa.Text(), nullable=True),
        sa.Column("hedge_mode_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_testnet", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_exchange_accounts_user_id", "exchange_accounts", ["user_id"], unique=False)

    # symbols
    op.create_table(
        "symbols",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("base_asset", sa.String(length=20), nullable=False),
        sa.Column("quote_asset", sa.String(length=20), nullable=False),
        sa.Column("contract_type", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("price_precision", sa.Integer(), nullable=True),
        sa.Column("quantity_precision", sa.Integer(), nullable=True),
        sa.Column("tick_size", sa.Numeric(30, 12), nullable=True),
        sa.Column("step_size", sa.Numeric(30, 12), nullable=True),
        sa.Column("min_qty", sa.Numeric(30, 12), nullable=True),
        sa.Column("min_notional", sa.Numeric(30, 12), nullable=True),
        sa.Column("raw_exchange_info", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", name="uq_symbols_symbol"),
    )
    op.create_index("ix_symbols_symbol", "symbols", ["symbol"], unique=True)

    # strategy_templates
    op.create_table(
        "strategy_templates",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("strategy_type", sa.String(length=40), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("leverage", sa.Integer(), nullable=False),
        sa.Column("total_capital", sa.Numeric(20, 8), nullable=False),
        sa.Column("stage1_capital", sa.Numeric(20, 8), nullable=False),
        sa.Column("stage2_capital", sa.Numeric(20, 8), nullable=False),
        sa.Column("stage3_capital", sa.Numeric(20, 8), nullable=False),
        sa.Column("stage4_capital", sa.Numeric(20, 8), nullable=False),
        sa.Column("stage2_trigger_percent", sa.Numeric(10, 4), nullable=False),
        sa.Column("stage3_trigger_percent", sa.Numeric(10, 4), nullable=False),
        sa.Column("stage4_trigger_mode", sa.String(length=30), nullable=False),
        sa.Column("stage4_trigger_percent", sa.Numeric(10, 4), nullable=True),
        sa.Column("tp1_percent", sa.Numeric(10, 4), nullable=False),
        sa.Column("tp2_percent", sa.Numeric(10, 4), nullable=False),
        sa.Column("tp3_percent", sa.Numeric(10, 4), nullable=False),
        sa.Column("tp1_qty_ratio", sa.Numeric(10, 4), nullable=False),
        sa.Column("tp2_qty_ratio", sa.Numeric(10, 4), nullable=False),
        sa.Column("tp3_qty_ratio", sa.Numeric(10, 4), nullable=False),
        sa.Column("stop_loss_percent_of_capital", sa.Numeric(10, 4), nullable=False),
        sa.Column("reentry_policy", sa.String(length=30), nullable=False, server_default="manual_ready"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_strategy_templates_name"),
    )

    # strategy_instances
    op.create_table(
        "strategy_instances",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("exchange_account_id", sa.BigInteger(), sa.ForeignKey("exchange_accounts.id"), nullable=False),
        sa.Column("strategy_template_id", sa.BigInteger(), sa.ForeignKey("strategy_templates.id"), nullable=False),
        sa.Column("symbol_id", sa.BigInteger(), sa.ForeignKey("symbols.id"), nullable=False),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("start_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("leverage", sa.Integer(), nullable=False),
        sa.Column("total_capital", sa.Numeric(20, 8), nullable=False),
        sa.Column("current_stage", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_entry_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("current_position_qty", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("invested_capital", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("unrealized_pnl", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("liquidation_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="WAITING"),
        sa.Column("reentry_ready", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_error_code", sa.String(length=60), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_strategy_instances_user_id", "strategy_instances", ["user_id"], unique=False)
    op.create_index("ix_strategy_instances_exchange_account_id", "strategy_instances", ["exchange_account_id"], unique=False)
    op.create_index("ix_strategy_instances_strategy_template_id", "strategy_instances", ["strategy_template_id"], unique=False)
    op.create_index("ix_strategy_instances_symbol_id", "strategy_instances", ["symbol_id"], unique=False)
    op.create_index("ix_strategy_instances_symbol", "strategy_instances", ["symbol"], unique=False)
    op.create_index("ix_strategy_instances_status", "strategy_instances", ["status"], unique=False)

    # strategy_stage_plans
    op.create_table(
        "strategy_stage_plans",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("strategy_instance_id", sa.BigInteger(), sa.ForeignKey("strategy_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage_no", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("trigger_mode", sa.String(length=30), nullable=False),
        sa.Column("trigger_percent", sa.Numeric(10, 4), nullable=True),
        sa.Column("trigger_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("planned_capital", sa.Numeric(20, 8), nullable=False),
        sa.Column("planned_qty", sa.Numeric(20, 8), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_triggered", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("strategy_instance_id", "stage_no", name="uq_strategy_stage"),
    )
    op.create_index("ix_strategy_stage_plans_strategy_instance_id", "strategy_stage_plans", ["strategy_instance_id"], unique=False)

    # orders
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("strategy_instance_id", sa.BigInteger(), sa.ForeignKey("strategy_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage_no", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("position_side", sa.String(length=10), nullable=False),
        sa.Column("order_type", sa.String(length=30), nullable=False),
        sa.Column("time_in_force", sa.String(length=10), nullable=True),
        sa.Column("client_order_id", sa.String(length=50), nullable=False),
        sa.Column("exchange_order_id", sa.BigInteger(), nullable=True),
        sa.Column("trigger_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("price", sa.Numeric(20, 8), nullable=True),
        sa.Column("orig_qty", sa.Numeric(20, 8), nullable=True),
        sa.Column("executed_qty", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("avg_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("raw_request", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("client_order_id", name="uq_orders_client_order_id"),
    )
    op.create_index("ix_orders_strategy_instance_id", "orders", ["strategy_instance_id"], unique=False)
    op.create_index("ix_orders_symbol", "orders", ["symbol"], unique=False)
    op.create_index("ix_orders_status", "orders", ["status"], unique=False)

    # positions
    op.create_table(
        "positions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("strategy_instance_id", sa.BigInteger(), sa.ForeignKey("strategy_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("position_side", sa.String(length=10), nullable=False),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("break_even_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("mark_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("liquidation_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("position_amt", sa.Numeric(20, 8), nullable=True),
        sa.Column("isolated_margin", sa.Numeric(20, 8), nullable=True),
        sa.Column("unrealized_pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column("margin_type", sa.String(length=20), nullable=True),
        sa.Column("leverage", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("snapshot_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_positions_strategy_instance_id", "positions", ["strategy_instance_id"], unique=False)

    # risk_events
    op.create_table(
        "risk_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("strategy_instance_id", sa.BigInteger(), sa.ForeignKey("strategy_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("event_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_risk_events_strategy_instance_id", "risk_events", ["strategy_instance_id"], unique=False)

    # notifications
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("strategy_instance_id", sa.BigInteger(), sa.ForeignKey("strategy_instances.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("send_status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("external_message_id", sa.String(length=120), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notifications_strategy_instance_id", "notifications", ["strategy_instance_id"], unique=False)

    # stream_sessions
    op.create_table(
        "stream_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("exchange_account_id", sa.BigInteger(), sa.ForeignKey("exchange_accounts.id"), nullable=False),
        sa.Column("listen_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_keepalive_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_stream_sessions_exchange_account_id", "stream_sessions", ["exchange_account_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_stream_sessions_exchange_account_id", table_name="stream_sessions")
    op.drop_table("stream_sessions")
    op.drop_index("ix_notifications_strategy_instance_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_risk_events_strategy_instance_id", table_name="risk_events")
    op.drop_table("risk_events")
    op.drop_index("ix_positions_strategy_instance_id", table_name="positions")
    op.drop_table("positions")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_symbol", table_name="orders")
    op.drop_index("ix_orders_strategy_instance_id", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_strategy_stage_plans_strategy_instance_id", table_name="strategy_stage_plans")
    op.drop_table("strategy_stage_plans")
    op.drop_index("ix_strategy_instances_status", table_name="strategy_instances")
    op.drop_index("ix_strategy_instances_symbol", table_name="strategy_instances")
    op.drop_index("ix_strategy_instances_symbol_id", table_name="strategy_instances")
    op.drop_index("ix_strategy_instances_strategy_template_id", table_name="strategy_instances")
    op.drop_index("ix_strategy_instances_exchange_account_id", table_name="strategy_instances")
    op.drop_index("ix_strategy_instances_user_id", table_name="strategy_instances")
    op.drop_table("strategy_instances")
    op.drop_table("strategy_templates")
    op.drop_index("ix_symbols_symbol", table_name="symbols")
    op.drop_table("symbols")
    op.drop_index("ix_exchange_accounts_user_id", table_name="exchange_accounts")
    op.drop_table("exchange_accounts")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
