"""surge_ladder_state — 급등 정점 사다리 심볼별 상태 (Fix 267, 2026-09-01)

사장님 지시: "당일 급등하는 1위 10위까지만 모니터링하고 최고점에 조정 시작할 심볼에
             1단계 500 진입 ... 당연히 첫진입부터 성공해서 포지션 추가를 하고 싶은거야"

🚨 Redis 가 아니라 DB 인 이유: docker-compose 의 redis 에 volume/appendonly 가 없다.
   재기동 한 번이면 시도 카운터가 0 이 되어 이미 크게 잃은 심볼에 다시 자본이 나간다.

기획서: docs/spec/SURGE_TOP10_PEAK_LADDER_SPEC_2026-09-01.md

Revision ID: 0034_surge_ladder
Revises: 0033_stage_peak_stall
"""
from alembic import op
import sqlalchemy as sa

revision = '0034_surge_ladder'
down_revision = '0033_stage_peak_stall'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'surge_ladder_state',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(30), nullable=False),
        sa.Column('side', sa.String(10), nullable=False, server_default='SHORT'),
        sa.Column('status', sa.String(20), nullable=False, server_default='WATCH',
                  comment='WATCH|IN_POSITION|WAITING|COOLDOWN|DONE'),
        sa.Column('attempt_no', sa.Integer(), nullable=False, server_default='0',
                  comment='몇 번째 시도인가 (자본을 좌우하므로 영속화 필수)'),
        sa.Column('adds_done', sa.Integer(), nullable=False, server_default='0',
                  comment='이번 시도의 이익구간 추가 횟수'),
        sa.Column('peak_price', sa.Numeric(20, 8), nullable=True,
                  comment='SHORT 이므로 고가 = 불리방향 극값'),
        sa.Column('peak_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('base_capital', sa.Numeric(20, 8), nullable=True),
        sa.Column('current_capital', sa.Numeric(20, 8), nullable=True),
        sa.Column('cycle_loss_usdt', sa.Numeric(20, 8), nullable=False, server_default='0',
                  comment='이번 사이클 확정 손실 (양수=손실)'),
        sa.Column('last_strategy_id', sa.Integer(), nullable=True),
        sa.Column('last_stop_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cooldown_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cycle_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', 'side', name='uq_surge_ladder_symbol_side'),
    )
    op.create_index('ix_surge_ladder_state_symbol', 'surge_ladder_state', ['symbol'])
    op.create_index('ix_surge_ladder_state_status', 'surge_ladder_state', ['status'])


def downgrade() -> None:
    op.drop_index('ix_surge_ladder_state_status', table_name='surge_ladder_state')
    op.drop_index('ix_surge_ladder_state_symbol', table_name='surge_ladder_state')
    op.drop_table('surge_ladder_state')
