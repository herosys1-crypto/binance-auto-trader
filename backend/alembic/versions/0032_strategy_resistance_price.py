"""strategy_instances resistance fields (Fix 29 v228, 2026-08-23)

사장님 verbatim:
"전고점 13354가 최대 저항인데 이것을 돌파했다가 하락시점에 2단계 진입"
"0.013354 아니면 돌파전에 하락하는 시점에 2단계 진입"

컬럼 4개:
- resistance_price: 사장님 지정 저항 (없으면 auto)
- resistance_source: 'user' | 'auto_7d_15m'
- resistance_detected_at: 자동 감지 시각 (24h TTL)
- resistance_reversal_triggered_at: 2단계 발동 시각 (idempotency)

Revision ID: 0032_resistance_price
Revises: 0031_chart_patterns
"""
from alembic import op
import sqlalchemy as sa

revision = '0032_resistance_price'
down_revision = '0031_chart_patterns'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('strategy_instances',
        sa.Column('resistance_price', sa.Numeric(20, 8), nullable=True,
                  comment='사장님 지정 저항가 (없으면 auto 감지). Fix 29 v228'))
    op.add_column('strategy_instances',
        sa.Column('resistance_source', sa.String(20), nullable=True,
                  comment="'user' | 'auto_7d_15m'"))
    op.add_column('strategy_instances',
        sa.Column('resistance_detected_at', sa.DateTime(timezone=True), nullable=True,
                  comment='auto 감지 시각 (24h TTL)'))
    op.add_column('strategy_instances',
        sa.Column('resistance_reversal_triggered_at', sa.DateTime(timezone=True), nullable=True,
                  comment='2단계 발동 시각 (idempotency)'))
    op.create_index('ix_strategy_instances_resistance_active',
                    'strategy_instances', ['status', 'side', 'current_stage'])


def downgrade() -> None:
    op.drop_index('ix_strategy_instances_resistance_active', table_name='strategy_instances')
    op.drop_column('strategy_instances', 'resistance_reversal_triggered_at')
    op.drop_column('strategy_instances', 'resistance_detected_at')
    op.drop_column('strategy_instances', 'resistance_source')
    op.drop_column('strategy_instances', 'resistance_price')
