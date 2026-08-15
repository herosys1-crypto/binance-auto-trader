"""chart_patterns 테이블 = 4H 차트 패턴 학습 저장! (v152 사장님!)

배경 (사장님 요청 2026-08-16):
"심볼들의 1달 차트를 분석해서 이런 패턴을 학습해서 메모리해줘
 차트분석 에이전트가 없으면 차트분석 에이전트팀을 만들어줘"

= 모든 심볼 4H 캔들 = 1달치 분석!
= v149/v150/v151 패턴 = 과거에도 감지 → DB 저장!
= 실제 outcome (24h/48h/1주 후!) = 자동 tracking!
= 성공률 = 학습 → predictor 개선!

컬럼:
- id, symbol, pattern_type (bounce_failure/bottom_reversal/top_reversal)
- side (SHORT/LONG)
- detected_at (감지 시각!)
- entry_price (감지 시 가격!)
- confidence (0~1)
- pattern_context JSONB (peak/trough/bounce/rsi/macd 등 상세!)
- outcome_price_24h, outcome_price_48h, outcome_price_7d
- outcome_max_favorable_pct (최대 유리 이동 %)
- outcome_max_adverse_pct (최대 불리 이동 %)
- outcome_status (PENDING/SUCCESS/FAIL/EXPIRED)
- outcome_checked_at
- created_at, updated_at

Revision ID: 0031_chart_patterns
Revises: 0030_market_observations
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0031_chart_patterns'
down_revision = '0030_market_observations'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'chart_patterns',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('symbol', sa.String(50), nullable=False, index=True),
        sa.Column('pattern_type', sa.String(50), nullable=False, index=True),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('entry_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('confidence', sa.Numeric(5, 4), nullable=True),
        sa.Column('pattern_context', postgresql.JSONB, nullable=True),
        sa.Column('outcome_price_24h', sa.Numeric(20, 8), nullable=True),
        sa.Column('outcome_price_48h', sa.Numeric(20, 8), nullable=True),
        sa.Column('outcome_price_7d', sa.Numeric(20, 8), nullable=True),
        sa.Column('outcome_max_favorable_pct', sa.Numeric(10, 4), nullable=True),
        sa.Column('outcome_max_adverse_pct', sa.Numeric(10, 4), nullable=True),
        sa.Column('outcome_status', sa.String(20), default='PENDING', index=True),
        sa.Column('outcome_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    # UNIQUE 인덱스 = 같은 심볼 + 같은 시각 + 같은 패턴 = 중복 방지!
    op.create_index(
        'ix_chart_pattern_unique',
        'chart_patterns',
        ['symbol', 'pattern_type', 'detected_at'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_chart_pattern_unique', table_name='chart_patterns')
    op.drop_table('chart_patterns')
