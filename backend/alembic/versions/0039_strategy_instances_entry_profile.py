"""strategy_instances.entry_profile — 「➕ 새 전략 (기존 방식)」 가족 표식 (Fix 367c, 2026-09-11)

사장님 「새전략 기존 방식은 손절없고 단계별 트리거에 다음단계 포지션 진입 … 과거로 돌악가는것과 같아」.
런타임(단계 정리 제외 등)이 템플릿 추정이 아니라 **생성 시 찍힌 표식**만 보게 한다 — 배포 전에 만들어진
인스턴스(#4478 RAYSOL·#4480 KAT 등)는 NULL 이라 옛 동작 그대로다. 값: 'legacy_manual' | NULL.

Revision ID: 0039_strategy_instances_entry_profile
Revises: 0038_managed_symbols_entry_ids
"""
from alembic import op
import sqlalchemy as sa

revision = '0039_strategy_instances_entry_profile'
down_revision = '0038_managed_symbols_entry_ids'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('strategy_instances', sa.Column('entry_profile', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('strategy_instances', 'entry_profile')
