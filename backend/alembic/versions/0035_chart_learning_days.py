"""chart_learning_days — 차트 학습 일지 (Fix 353, 2026-09-05)

사장님: "상승 50위 하락 50위 심볼을 차트를 우리가 필요한 시스템로직을 위해서 분석학습 …
         한번에 어려우면 할수 있는 만큼씩 매일 매일 나눠서 학습을 해줘"

매일 감시 대상(당일·3·5일 순위)의 차트를 그 시각 기준으로 저장하고 36h 뒤 결과를 라벨링한다.
(날짜, 심볼) 유일. 원시 봉은 45일 뒤 비우고 라벨은 영구.

Revision ID: 0035_chart_learning
Revises: 0034_surge_ladder
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0035_chart_learning'
down_revision = '0034_surge_ladder'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'chart_learning_days',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('snap_date', sa.Date(), nullable=False),
        sa.Column('snapshot_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('symbol', sa.String(30), nullable=False),
        sa.Column('source', sa.String(10), nullable=False, server_default='live'),
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('ranks', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('chg_24h', sa.Numeric(10, 4), nullable=True),
        sa.Column('chg_3d', sa.Numeric(10, 4), nullable=True),
        sa.Column('chg_5d', sa.Numeric(10, 4), nullable=True),
        sa.Column('quote_volume', sa.Numeric(20, 2), nullable=True),
        sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('klines', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('outcome', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('outcome_status', sa.String(12), nullable=False, server_default='PENDING'),
        sa.Column('labeled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('snap_date', 'symbol', name='uq_chart_learning_day_symbol'),
    )
    op.create_index('ix_chart_learning_days_snap_date', 'chart_learning_days', ['snap_date'])
    op.create_index('ix_chart_learning_days_symbol', 'chart_learning_days', ['symbol'])
    op.create_index('ix_chart_learning_days_outcome_status', 'chart_learning_days', ['outcome_status'])


def downgrade() -> None:
    op.drop_index('ix_chart_learning_days_outcome_status', table_name='chart_learning_days')
    op.drop_index('ix_chart_learning_days_symbol', table_name='chart_learning_days')
    op.drop_index('ix_chart_learning_days_snap_date', table_name='chart_learning_days')
    op.drop_table('chart_learning_days')
