"""managed_symbols — 심볼 관리 재진입 명부 (Fix 365, 2026-09-09)

사장님: "첫 진입에 실패하면 청산하고 재진입 모니터링으로 특별 관리해서 … 다시 10usdt로 진입해서 성공하면 포지션추가 …
        10번까지 반복 … 한번 선택한 종목을 지속적으로 분석하면서 관리 재진입"

한 행 = 심볼 하나(유일). 워커가 종료된 OBV 자동 인스턴스를 집계(실패/성공)하고 1분마다 롱·숏 신호를 본다.

Revision ID: 0037_managed_symbols
Revises: 0036_paper_trades
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0037_managed_symbols'
down_revision = '0036_paper_trades'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'managed_symbols',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(30), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('exchange_account_id', sa.Integer(), nullable=True),
        sa.Column('strategy_template_id', sa.Integer(), nullable=True),
        sa.Column('templates', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(12), nullable=False, server_default='WATCHING'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('successes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_entries', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('origin_instance_id', sa.BigInteger(), nullable=True),
        sa.Column('last_instance_id', sa.BigInteger(), nullable=True),
        sa.Column('last_side', sa.String(5), nullable=True),
        sa.Column('last_pnl', sa.Numeric(20, 8), nullable=True),
        sa.Column('last_exit_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_entry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_signal_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_check_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('counted_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('note', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', name='uq_managed_symbol'),
    )
    op.create_index('ix_managed_symbols_status', 'managed_symbols', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_managed_symbols_status', table_name='managed_symbols')
    op.drop_table('managed_symbols')
