"""market_observations 테이블 = 진입 X 심볼도 관찰 학습! (v136 사장님!)

배경 (사장님 요청 2026-08-13):
"우리가 포지션에 진입하지 않은 심볼들도 그렇게 하면 앞으로 전략진입에 큰도움될것 같아
 운영자인 나는 기록하지 않으면 기억을 할수 없어"

= 매 4시간 = 상위 100 심볼 관찰!
= 진입 여부 무관!
= 시장 흐름 학습!

컬럼:
- id, symbol, side_would_have (LONG/SHORT 어느쪽이 좋았을지)
- observed_at (관찰 시점!)
- price_at_obs (관찰 시점 가격!)
- price_1h_later, price_4h_later, price_24h_later
- change_1h/4h/24h
- rank_by_pump (24h 상승 순위!)
- rank_by_dump (24h 하락 순위!)
- market_context JSONB (RSI, MACD, OBV 등!)

Revision ID: 0030_market_observations
Revises: 0029_suggestion_outcomes
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0030_market_observations'
down_revision = '0029_suggestion_outcomes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'market_observations',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('symbol', sa.String(50), nullable=False, index=True),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('price_at_obs', sa.Numeric(20, 8), nullable=True),
        sa.Column('price_1h_later', sa.Numeric(20, 8), nullable=True),
        sa.Column('price_4h_later', sa.Numeric(20, 8), nullable=True),
        sa.Column('price_24h_later', sa.Numeric(20, 8), nullable=True),
        sa.Column('change_1h', sa.Numeric(10, 4), nullable=True),
        sa.Column('change_4h', sa.Numeric(10, 4), nullable=True),
        sa.Column('change_24h_later', sa.Numeric(10, 4), nullable=True),
        sa.Column('rank_by_pump', sa.Integer(), nullable=True),  # 24h 상승 순위!
        sa.Column('rank_by_dump', sa.Integer(), nullable=True),  # 24h 하락 순위!
        sa.Column('side_would_have', sa.String(10), nullable=True),  # 사후 판단!
        sa.Column('market_context', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        'ix_market_obs_symbol_observed',
        'market_observations',
        ['symbol', 'observed_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_market_obs_symbol_observed', table_name='market_observations')
    op.drop_table('market_observations')
