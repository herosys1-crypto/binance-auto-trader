"""paper_trades — 가상 매매 학습 (Fix 361, 2026-09-08)

사장님: "가상으로 포지션 진입해서 성공과 실패를 기록저장 학습해서 다시 실시간 운영시작 하면
        그때 적용할 수 있게 학습해줘 … 롱과숏 포지션 진입하고 익절중에 포지션 추가해서
        수익을 만들 자리를 찾아줘"

실주문 없이(klines/ticker 만 읽음) 규칙별 가상 진입을 기록하고 매 사이클 재계산해 청산까지 저장한다.
(심볼, 규칙, 진입봉) 유일.

Revision ID: 0036_paper_trades
Revises: 0035_chart_learning
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0036_paper_trades'
down_revision = '0035_chart_learning'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'paper_trades',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('source', sa.String(10), nullable=False, server_default='live'),
        sa.Column('symbol', sa.String(30), nullable=False),
        sa.Column('side', sa.String(5), nullable=False),
        sa.Column('rule', sa.String(40), nullable=False),
        sa.Column('entry_bar_ts', sa.BigInteger(), nullable=False),
        sa.Column('entry_price', sa.Numeric(20, 8), nullable=False),
        sa.Column('tp1_pct', sa.Numeric(6, 2), nullable=True),
        sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(8), nullable=False, server_default='OPEN'),
        sa.Column('close_reason', sa.String(60), nullable=True),
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('chg_24h', sa.Numeric(10, 4), nullable=True),
        sa.Column('chg_3d', sa.Numeric(10, 4), nullable=True),
        sa.Column('chg_5d', sa.Numeric(10, 4), nullable=True),
        sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('engines', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('adds', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('bars_seen', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('mfe', sa.Numeric(10, 4), nullable=True),
        sa.Column('mae', sa.Numeric(10, 4), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', 'rule', 'entry_bar_ts', name='uq_paper_trade_entry'),
    )
    op.create_index('ix_paper_trades_source', 'paper_trades', ['source'])
    op.create_index('ix_paper_trades_symbol', 'paper_trades', ['symbol'])
    op.create_index('ix_paper_trades_rule', 'paper_trades', ['rule'])
    op.create_index('ix_paper_trades_status', 'paper_trades', ['status'])
    op.create_index('ix_paper_trades_opened_at', 'paper_trades', ['opened_at'])


def downgrade() -> None:
    op.drop_index('ix_paper_trades_opened_at', table_name='paper_trades')
    op.drop_index('ix_paper_trades_status', table_name='paper_trades')
    op.drop_index('ix_paper_trades_rule', table_name='paper_trades')
    op.drop_index('ix_paper_trades_symbol', table_name='paper_trades')
    op.drop_index('ix_paper_trades_source', table_name='paper_trades')
    op.drop_table('paper_trades')
