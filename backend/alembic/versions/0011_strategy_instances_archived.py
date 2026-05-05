"""strategy_instances 에 is_archived + archived_at 컬럼 — soft delete 방어.

배경 (2026-05-06 사용자 보고 / #96 사례):
- DELETE endpoint 가 current_stage > 0 거부하지만, cleanup 스크립트나 운영자
  직접 SQL 실행 시 strategy + cascade orders 모두 사라짐.
- #96 cascade delete 로 +867 USDT realized_pnl 이 운영 통계 합계에서 영구 누락.
- 거래소 (Binance) 의 실제 누적 수익과 DB 합계가 어긋나는 경향.

해결: soft delete — DELETE 시 row 보존 + is_archived=true 마킹.
- /admin/stats 의 SUM(realized_pnl) 이 archived 포함 → 거래소 history 보존
- 신규 query 가 active 만 보고 싶으면 WHERE NOT is_archived 추가 (별도 PR)
- restore endpoint 로 archived 되돌릴 수 있음 (별도 PR)

스키마:
  is_archived BOOLEAN NOT NULL DEFAULT false
  archived_at TIMESTAMP WITH TIME ZONE NULL  (archive 시점 — audit log)

데이터 마이그레이션 불필요 (기본 false = 기존 모든 strategy active).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0011_strategy_archived"
down_revision = "0010_ex_acc_daily_loss_limit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_instances",
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "strategy_instances",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    # 인덱스 — active filter 쿼리가 빠르게 동작하도록 (별도 PR 에서 사용)
    op.create_index(
        "ix_strategy_instances_is_archived",
        "strategy_instances",
        ["is_archived"],
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_instances_is_archived", table_name="strategy_instances")
    op.drop_column("strategy_instances", "archived_at")
    op.drop_column("strategy_instances", "is_archived")
