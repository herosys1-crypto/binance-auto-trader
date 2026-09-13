"""strategy_instances.entry_origin — 누가 만들었나 (Fix 371, 2026-09-14)

사장님 「새전략 기본방식과 새전략 obv 자동만 가능하게 수동으로 전략을 만들수 있게 남기고 모든 자동매매 중단」.
자동매매 중단 게이트(app/services/auto_trading_halt.py)가 「사람이 화면 모달로 만든 전략」을 가르는 유일한 값.
entry_profile 은 템플릿이 OBV_REVERSE 면 워커 복제본에도 'obv_auto' 가 찍혀 쓸 수 없다.

값: 'manual_modal' (POST /strategies) | NULL (자동 워커 · 배포 전 인스턴스).
소급: entry_profile = 'legacy_manual' 행만 'manual_modal' — 그 표식은 entry_origin == manual_modal 일 때만 찍혔다(strategy_service.legacy_manual_family).
기존 'obv_auto' 행은 사람/복제를 가를 수 없어 NULL 로 둔다(중단 중 차단 = fail-closed). 사장님이 고른 행만 따로 표시한다.

Revision ID: 0040_si_entry_origin (VARCHAR(32) 안)
Revises: 0039_si_entry_profile
"""
from alembic import op
import sqlalchemy as sa

revision = '0040_si_entry_origin'
down_revision = '0039_si_entry_profile'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('strategy_instances', sa.Column('entry_origin', sa.String(length=20), nullable=True))
    op.execute("UPDATE strategy_instances SET entry_origin = 'manual_modal' WHERE entry_profile = 'legacy_manual'")


def downgrade() -> None:
    op.drop_column('strategy_instances', 'entry_origin')
