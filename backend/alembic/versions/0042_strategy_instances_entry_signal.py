"""strategy_instances.entry_signal · entry_signal_meta — 예약 전략 진입 신호 (Fix 466, 2026-10-18)

사장님 「시스템은 개발해 두고 가상매매로 업데이트 지속적으로 하고 시스템을 적용해서 나오는 결과도 검토해야해」.
NULL = 기존 예약 경로 그대로 · 'ichikijun' = 일목 실험실 챔피언 · 'ichikijun:<변형 키>' = 변형 고정.
entry_signal_meta = 진입 때 쓴 변형·신호 봉·진입 봉·손절폭·익절R (적용 결과 검토용). 기존 행은 모두 NULL(동작 변화 없음).

Revision ID: 0042_si_entry_signal
Revises: 0041_ichikijun_lab_trades
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0042_si_entry_signal'
down_revision = '0041_ichikijun_lab_trades'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('strategy_instances', sa.Column('entry_signal', sa.String(length=32), nullable=True))
    op.add_column('strategy_instances', sa.Column('entry_signal_meta', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('strategy_instances', 'entry_signal_meta')
    op.drop_column('strategy_instances', 'entry_signal')
