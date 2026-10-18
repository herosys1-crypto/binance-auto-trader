"""ichikijun_lab_trades — 일목 기준선 변형 실험실 가상 거래 (Fix 465, 2026-10-18)

사장님 「가상매매로 이 전략을 수정해서 승률이 제일 높은 방법을 지속적으로 찾아서 업데이트」.
주문 없음. 변형 72줄 × (신호 + 같은 시각 무작위 짝). 예상 ≈ 하루 30~60행.

Revision ID: 0041_ichikijun_lab_trades
Revises: 0040_si_entry_origin
"""
from alembic import op
import sqlalchemy as sa

revision = '0041_ichikijun_lab_trades'
down_revision = '0040_si_entry_origin'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ichikijun_lab_trades',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('kind', sa.String(length=4), nullable=False),
        sa.Column('variant', sa.String(length=24), nullable=False),
        sa.Column('side', sa.String(length=5), nullable=False),
        sa.Column('interval', sa.String(length=4), nullable=False),
        sa.Column('symbol', sa.String(length=30), nullable=False),
        sa.Column('pair_symbol', sa.String(length=30), nullable=True),
        sa.Column('signal_bar_ts', sa.BigInteger(), nullable=False),
        sa.Column('entry_bar_ts', sa.BigInteger(), nullable=False),
        sa.Column('entry_price', sa.Numeric(20, 8), nullable=False),
        sa.Column('stop_pct', sa.Numeric(8, 4), nullable=False),
        sa.Column('clamped', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('btc_up', sa.Boolean(), nullable=True),
        sa.Column('status', sa.String(length=6), nullable=False, server_default='OPEN'),
        sa.Column('exit_reason', sa.String(length=4), nullable=True),
        sa.Column('r_gross', sa.Numeric(10, 4), nullable=True),
        sa.Column('r_net', sa.Numeric(10, 4), nullable=True),
        sa.Column('bars_held', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('kind', 'variant', 'side', 'symbol', 'entry_bar_ts', name='uq_ichilab_entry'),
    )
    op.create_index('ix_ichikijun_lab_trades_variant', 'ichikijun_lab_trades', ['variant'])
    op.create_index('ix_ichikijun_lab_trades_interval', 'ichikijun_lab_trades', ['interval'])
    op.create_index('ix_ichikijun_lab_trades_symbol', 'ichikijun_lab_trades', ['symbol'])
    op.create_index('ix_ichikijun_lab_trades_status', 'ichikijun_lab_trades', ['status'])
    op.create_index('ix_ichikijun_lab_trades_opened_at', 'ichikijun_lab_trades', ['opened_at'])


def downgrade() -> None:
    op.drop_table('ichikijun_lab_trades')
