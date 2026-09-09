"""managed_symbols.entry_ids — 관리 재진입 전용 슬롯 (Fix 365d, 2026-09-09)

사장님 「진행해줘」: 관리 재진입은 자동 워커 동시보유 상한(sajangnim_top_short_daily_limit)과 무관하게
전용 슬롯(managed_symbol_concurrent_slots, 기본 5) 안에서만 나간다. 워커가 낸 인스턴스 id 를 명부 행에 기록해 센다.

Revision ID: 0038_managed_symbols_entry_ids
Revises: 0037_managed_symbols
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0038_managed_symbols_entry_ids'
down_revision = '0037_managed_symbols'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('managed_symbols', sa.Column('entry_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('managed_symbols', 'entry_ids')
