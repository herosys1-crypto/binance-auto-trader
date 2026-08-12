"""trade_learning_records 테이블 = 모든 거래 학습 저장! (v134 사장님!)

배경 (사장님 요청 2026-08-13):
"지금 매매가 성공이든 실패이든 모든 거래를 학습해서 저장하고
 지금 하고 있는 모든 모니터링을 학습해서 실제분석에 도움이 될수 있게 학습해줘
 [...]
 자동화했을때도 항상 진행과정과 종료된거래를 학습해서 다음에 더 잘 활용할수 있게 저장해줘"

= 모든 거래 자동 학습!
= 진입 시 record 생성!
= 종료 시 update + insights!
= 진행 중 스냅샷 (5분 단위 저장 가능!)

컬럼:
- id, strategy_instance_id (FK!)
- symbol, side, status
- entry_price/time, exit_price/time
- pnl_pct/usdt, max_profit/loss_pct
- close_reason (TP/SL/USER/CRISIS 등!)
- entry_config JSONB (진입 시 세팅!)
- entry_context JSONB (진입 시 시장 = RSI/BB/변동!)
- exit_context JSONB (종료 시 시장!)
- progression JSONB (진행 스냅샷 리스트!)
- insights JSONB (자동 인사이트 = 교훈!)
- created_at, updated_at

Revision ID: 0028_trade_learning_records
Revises: 0027_strategy_suggestions
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0028_trade_learning_records'
down_revision = '0027_strategy_suggestions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'trade_learning_records',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('strategy_instance_id', sa.Integer(), nullable=False, index=True),
        sa.Column('symbol', sa.String(50), nullable=False, index=True),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, default='OPEN', index=True),
        # 가격/시간!
        sa.Column('entry_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('exit_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('entry_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('exit_time', sa.DateTime(timezone=True), nullable=True),
        # PnL!
        sa.Column('pnl_pct', sa.Numeric(10, 4), nullable=True),
        sa.Column('pnl_usdt', sa.Numeric(20, 8), nullable=True),
        sa.Column('max_profit_pct', sa.Numeric(10, 4), nullable=True),
        sa.Column('max_loss_pct', sa.Numeric(10, 4), nullable=True),
        # 종료 이유!
        sa.Column('close_reason', sa.String(50), nullable=True, index=True),
        # JSONB!
        sa.Column('entry_config', postgresql.JSONB, nullable=True),
        sa.Column('entry_context', postgresql.JSONB, nullable=True),
        sa.Column('exit_context', postgresql.JSONB, nullable=True),
        sa.Column('progression', postgresql.JSONB, nullable=True),
        sa.Column('insights', postgresql.JSONB, nullable=True),
        # 타임!
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # UNIQUE = strategy_instance_id (한 전략 = 한 학습 레코드!)
    op.create_index(
        'ix_trade_learning_strategy_id_unique',
        'trade_learning_records',
        ['strategy_instance_id'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_trade_learning_strategy_id_unique', table_name='trade_learning_records')
    op.drop_table('trade_learning_records')
