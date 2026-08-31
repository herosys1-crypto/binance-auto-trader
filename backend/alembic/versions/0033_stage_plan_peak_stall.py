"""strategy_stage_plans 정점-주춤 상태 3컬럼 (Fix 260, 2026-09-01)

사장님 verbatim:
"최고점으로 가다가 주춤할때 2단계 진입
 그리고 다시 최고점으로 가면 다시 대기해서 꺾이면 3단계 진입으로 해줘"

「**다시** 최고점으로 가면」을 판정하려면 극값의 재갱신을 **기억**해야 한다.
Redis 가 아니라 DB 인 이유: 스케줄러 재기동 후에도 유지되어야 한다.

- peak_price   : 직전 단계 체결 이후의 **불리방향** 러닝 극값
                 (SHORT=신고점 max / LONG=신저점 min)
- peak_seen_at : 그 극값이 마지막으로 갱신된 시각 (= 「주춤」 지속 측정 기준)
- peak_renewed : 이 단계 대기 중 극값이 의미있게 재갱신되었는가 (3단계 필수 조건)

전부 NULL 허용/기본값 있음 = 롤백해도 무해하다.
기획서: docs/spec/PEAK_STALL_STAGE_ENTRY_SPEC_2026-09-01.md

Revision ID: 0033_stage_peak_stall
Revises: 0032_resistance_price
"""
from alembic import op
import sqlalchemy as sa

revision = '0033_stage_peak_stall'
down_revision = '0032_resistance_price'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('strategy_stage_plans',
        sa.Column('peak_price', sa.Numeric(20, 8), nullable=True,
                  comment='직전 단계 체결 이후 불리방향 러닝 극값 (SHORT=max/LONG=min). Fix 260'))
    op.add_column('strategy_stage_plans',
        sa.Column('peak_seen_at', sa.DateTime(timezone=True), nullable=True,
                  comment='극값이 마지막으로 갱신된 시각 = 「주춤」 지속 측정 기준. Fix 260'))
    op.add_column('strategy_stage_plans',
        sa.Column('peak_renewed', sa.Boolean(), nullable=False, server_default=sa.false(),
                  comment='대기 중 극값 재갱신 여부 =「다시 최고점으로 가면」. Fix 260'))


def downgrade() -> None:
    op.drop_column('strategy_stage_plans', 'peak_renewed')
    op.drop_column('strategy_stage_plans', 'peak_seen_at')
    op.drop_column('strategy_stage_plans', 'peak_price')
